from collections import defaultdict
from datetime import datetime, timedelta
import argparse
import random

from planners import Planner
from problems import ResourceType, HealthcareProblem
from simulator import Simulator

# ===== Baseline (naive) KPIs =====
BASELINE = {
    "waiting_time_for_admission": 281013.6992142152,
    "waiting_time_in_hospital":   4997561.385304505,
    "nervousness":                2932427.0,
    "personnel_cost":             733449.0,
}

# ---- score helpers ----
def _nz(x: float) -> float:
    return x if x != 0 else 1e-9

def _normalized(yours, base):
    return {
        "WTA%": 100.0 * (yours["waiting_time_for_admission"] - base["waiting_time_for_admission"]) / _nz(base["waiting_time_for_admission"]),
        "WTH%": 100.0 * (yours["waiting_time_in_hospital"]   - base["waiting_time_in_hospital"])   / _nz(base["waiting_time_in_hospital"]),
        "NERV%":100.0 * (yours["nervousness"]                - base["nervousness"])                / _nz(base["nervousness"]),
        "COST%":100.0 * (yours["personnel_cost"]             - base["personnel_cost"])             / _nz(base["personnel_cost"]),
    }

def _final_score(norm):
    return (norm["WTA%"] + norm["WTH%"] + norm["NERV%"] + 3.0 * norm["COST%"]) / 6.0

# ---- time helpers ----
START_DT = datetime(2018, 1, 1)
def hours_to_dt(h): return START_DT + timedelta(hours=h)
def is_weekend(h): return hours_to_dt(h).weekday() >= 5  # Mon=0..Sun=6
def next_day_0800(h, days_ahead=1):
    dt = hours_to_dt(h).replace(minute=0, second=0, microsecond=0)
    target = (dt + timedelta(days=days_ahead)).replace(hour=8)
    return max(h + 1, int((target - START_DT).total_seconds() // 3600))

class RLSubmissionPlanner(Planner):
    """
    Contextual-bandit RL for daily OR staffing.
      - State: (weekday, backlog_bin, overtime_flag)
      - Actions: tomorrow's OR level in {2,3,4,5}
      - Reward (updated nightly 18:00): - (admit_wait + in_hosp_wait + nerv + 3*cost)
    Enforces submission rules (≥24h admissions, ≥14h scheduling, increase-only < 1 week, caps).
    """
    def __init__(self, epsilon=0.1):
        super().__init__("temp/event_log.csv", ["case_id", "element", "timestamp"], "timestamp")
        self.epsilon = epsilon
        self.Q = defaultdict(lambda: {2:0.0, 3:0.0, 4:0.0, 5:0.0})
        self.N = defaultdict(lambda: {2:0, 3:0, 4:0, 5:0})
        self.last_state = None
        self.last_action = None

        self.metrics = {"admit_wait":0.0, "in_hosp_wait":0.0, "nerv":0.0, "cost":0.0, "overtime":0}
        self.ready_or = 0
        self.last_level = {ResourceType.OR: 5}  # Start with max to avoid decrease violations
        self.max_resources = {ResourceType.OR: 5}
        self._scheduled = {}  # (resource, time) -> level

    # --- submission API ---
    def plan(self, cases_to_plan, cases_to_replan, simulation_time):
        out = []
        slot1 = next_day_0800(simulation_time, 1)
        if slot1 < simulation_time + 24:
            slot1 = next_day_0800(simulation_time, 2)
        slot2 = next_day_0800(simulation_time, 2)

        cap1 = 6 if not is_weekend(simulation_time) else 2
        cap2 = max(1, cap1 // 2)
        for cid in cases_to_plan:
            if cap1 > 0: out.append((cid, slot1)); cap1 -= 1
            elif cap2 > 0: out.append((cid, slot2)); cap2 -= 1
            else: break
        return out

    def schedule(self, simulation_time):
        if hours_to_dt(simulation_time).hour != 18:
            return []

        # state
        weekday = hours_to_dt(simulation_time).weekday()
        backlog_bin = min(3, self.ready_or // 5)  # 0..3
        overtime_flag = 1 if self.metrics["overtime"] else 0
        s = (weekday, backlog_bin, overtime_flag)

        # update last (s,a)
        if self.last_state is not None and self.last_action is not None:
            r = - ( self.metrics["admit_wait"]
                  + self.metrics["in_hosp_wait"]
                  + self.metrics["nerv"]
                  + 3.0 * self.metrics["cost"] )
            a_prev = self.last_action
            self.N[self.last_state][a_prev] += 1
            n = self.N[self.last_state][a_prev]
            q_old = self.Q[self.last_state][a_prev]
            self.Q[self.last_state][a_prev] = q_old + (r - q_old) / n

        # epsilon-greedy action
        if random.random() < self.epsilon:
            a = random.choice([2,3,4,5])
        else:
            q = self.Q[s]
            a = max(q, key=q.get)

        # reset metrics for next day
        for k in self.metrics: self.metrics[k] = 0.0
        self.metrics["overtime"] = 0

        # emit schedule ≥ t+14h (tomorrow 08:00), increase-only, cap
        start_t = max(simulation_time + 14, next_day_0800(simulation_time, 1))
        chosen = min(self.max_resources[ResourceType.OR], max(2, int(a)))
        
        # protect increase-only in near term: never schedule less than what we've done before
        existing = self._scheduled.get((ResourceType.OR, start_t), self.last_level[ResourceType.OR])
        near = max(existing, self.last_level[ResourceType.OR], chosen)
        self.last_level[ResourceType.OR] = near

        # Only schedule if it's actually different to avoid redundant calls
        schedule = []
        if (ResourceType.OR, start_t) not in self._scheduled or self._scheduled[(ResourceType.OR, start_t)] != near:
            schedule.append((ResourceType.OR, start_t, near))
            self._scheduled[(ResourceType.OR, start_t)] = near
        
        # Week-ahead anchor (more flexible scheduling)
        week_ahead_t = start_t + 168
        if (ResourceType.OR, week_ahead_t) not in self._scheduled or self._scheduled[(ResourceType.OR, week_ahead_t)] != chosen:
            schedule.append((ResourceType.OR, week_ahead_t, chosen))
            self._scheduled[(ResourceType.OR, week_ahead_t)] = chosen

        self.last_state = s
        self.last_action = a
        return schedule

    def report(self, case_id, element, timestamp, resource, lifecycle_state, data=None):
        lbl = (element.label if element else "").upper()
        if "ADMISSION" in lbl or "INTAKE" in lbl or "REGISTER" in lbl:
            if lifecycle_state in ("ACTIVATE_EVENT", "WAITING"):
                self.metrics["admit_wait"] += 1.0

        if lifecycle_state == "ACTIVATE_TASK":
            self.metrics["in_hosp_wait"] += 0.2

        if lifecycle_state in ("REPLAN", "RESCHEDULE"):
            self.metrics["nerv"] += 1.0

        if lifecycle_state == "OVERTIME":
            self.metrics["cost"] += 3.0
            self.metrics["overtime"] = 1

        if lifecycle_state == "PLANNED_STAFF_LT_1W":
            self.metrics["cost"] += 2.0
        elif lifecycle_state == "PLANNED_STAFF_GE_1W":
            self.metrics["cost"] += 1.0

        if resource == ResourceType.OR:
            if lifecycle_state == "ACTIVATE_TASK":
                self.ready_or += 1
            elif lifecycle_state == "START_TASK":
                self.ready_or = max(0, self.ready_or - 1)

# ---- runnable tail: run + auto-compare ----
if __name__ == "__main__":
    problem = HealthcareProblem()
    simulator = Simulator(RLSubmissionPlanner(), problem)
    result = simulator.run(365*24)
    print(result)