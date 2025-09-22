# or.py — OR-only planner tuned to lower WTA/WTH without exploding COST/NERV
from planners import Planner
from simulator import Simulator
from problems import ResourceType, HealthcareProblem

# Max-out the “flow” resources; beds at max to avoid downstream bottlenecks.
WEEKLY_CAP = {d: {
    ResourceType.OR: 5,               # full OR
    ResourceType.A_BED: 30,           # max beds
    ResourceType.B_BED: 40,           # max beds
    ResourceType.INTAKE: 4,           # max intake
    ResourceType.ER_PRACTITIONER: 9   # max ER
} for d in range(1, 8)}

def next_8am_at_or_after(t: float) -> int:
    hod = int(t % 24); base = int(t - hod)
    return base + 8 if hod <= 8 else base + 32

def dow_1_to_7(t: int) -> int:
    return ((t // 24) % 7) + 1

class ORPlanner(Planner):
    def __init__(self, cap_schedule=None):
        super().__init__("./temp/event_log.csv", ["diagnosis"], {})
        # Build a tuple-keyed capacity schedule: {(ResourceType, day 1..7) -> int}
        if cap_schedule is None:
            # Convert WEEKLY_CAP (day -> {ResourceType: count}) to tuple-keyed
            cap_schedule = {}
            for d in range(1, 8):
                for r, v in WEEKLY_CAP[d].items():
                    cap_schedule[(r, d)] = v
        else:
            # If user passed a day->dict mapping, convert it
            # Detect by checking a sample key
            sample_key = next(iter(cap_schedule.keys()))
            if not isinstance(sample_key, tuple):
                converted = {}
                for d in cap_schedule:
                    for r, v in cap_schedule[d].items():
                        converted[(r, d)] = v
                cap_schedule = converted
        self.cap = cap_schedule
        self._used = {}  # (week, day, hour) -> admits

    def report(self, *args, **kwargs):
        return  # no logging for speed

    def _daily_quota(self, d):
        i   = self.cap[(ResourceType.INTAKE, d)]
        er  = self.cap[(ResourceType.ER_PRACTITIONER, d)]
        beds= self.cap[(ResourceType.A_BED, d)] + self.cap[(ResourceType.B_BED, d)]
        # Don’t cap by OR. Push admission throughput.
        q = min(14 * i, 6 * er, beds)     # with max caps → ~54/day typically
        return max(48, min(q, 64))        # raise floor to drain backlog

    @staticmethod
    def _split_quota(total: int, fractions):
        """Turn total day quota into integer sub‑quotas per wave, preserving total."""
        raw = [f * total for f in fractions]
        ints = [int(x) for x in raw]
        # distribute leftovers due to rounding to the biggest fractional parts
        leftover = total - sum(ints)
        if leftover > 0:
            order = sorted(range(len(raw)), key=lambda i: raw[i] - ints[i], reverse=True)
            for i in order[:leftover]:
                ints[i] += 1
        return ints

    def plan(self, cases_to_plan, cases_to_replan, simulation_time):
        out = []
        earliest = simulation_time + 24
        base8 = next_8am_at_or_after(earliest)

        # Six admission waves in a day
        waves = [0, 2, 4, 6, 8, 12]  # hours after 08:00
        wave_frac = [0.36, 0.22, 0.16, 0.12, 0.08, 0.06]
        assert len(waves) == len(wave_frac)

        pending = list(cases_to_plan)   # intentionally ignore replans to keep NERV low
        if not pending:
            return out

        # Precompute two‑day horizon: fully use Day 1 before spilling to Day 2.
        day_slots = []
        for day_offset in (0, 1):
            day_start = base8 + 24 * day_offset
            d = dow_1_to_7(day_start)          # 1..7 for that calendar day
            w = day_start // 168               # week index
            quota_day = self._daily_quota(d)

            # backlog-aware & warm-start adjustments
            backlog = len(pending) + len(cases_to_replan)
            # stronger boost to drain large queues quickly
            boost = min(quota_day // 2, backlog // 6)

            # warm-start for roughly first two weeks of simulation
            days_since_epoch = (base8 // 24)
            warm = days_since_epoch < 14

            # dynamic floor/ceiling to avoid starving Day 1 capacity
            floor = 56 if warm else 50
            cap_max = 72 if (warm or backlog > 150) else 64

            quota_day = min(cap_max, max(floor, quota_day + boost))

            # Split today's quota into wave sub‑quotas
            subqs = self._split_quota(quota_day, wave_frac)

            # For each wave today, generate (absolute_time, capacity_remaining, key_for_used)
            slots = []
            for idx, h_after in enumerate(waves):
                tslot = day_start + h_after
                key = (w, d, tslot % 24)  # reuse used-bucket scheme
                # respect anything already placed in this exact hour
                already = self._used.get(key, 0)
                cap = max(0, subqs[idx] - already)
                slots.append([tslot, cap, key])
            day_slots.append(slots)

        # Fill Day 1 completely before touching Day 2
        for slots in day_slots:
            for idx in range(len(slots)):
                if not pending:
                    break
                tslot, cap, key = slots[idx]
                # place up to 'cap' patients in this wave
                k = min(cap, len(pending))
                if k <= 0:
                    continue
                # append k cases at this tslot
                for _ in range(k):
                    out.append((pending.pop(), tslot))
                # update used counter
                self._used[key] = self._used.get(key, 0) + k
            if not pending:
                break

        # If still pending after two days, keep pushing by whole days reusing the same wave pattern
        day_offset = 2
        while pending:
            day_start = base8 + 24 * day_offset
            d = dow_1_to_7(day_start)
            w = day_start // 168
            quota_day = self._daily_quota(d)
            backlog = len(pending) + len(cases_to_replan)
            boost = min(quota_day // 2, backlog // 6)
            days_since_epoch = (base8 // 24) + day_offset
            warm = days_since_epoch < 14
            floor = 56 if warm else 50
            cap_max = 72 if (warm or backlog > 150) else 64
            quota_day = min(cap_max, max(floor, quota_day + boost))
            subqs = self._split_quota(quota_day, wave_frac)
            for i, h_after in enumerate(waves):
                if not pending:
                    break
                tslot = day_start + h_after
                key = (w, d, tslot % 24)
                already = self._used.get(key, 0)
                cap = max(0, subqs[i] - already)
                k = min(cap, len(pending))
                for _ in range(k):
                    out.append((pending.pop(), tslot))
                self._used[key] = self._used.get(key, 0) + k
            day_offset += 1

        return out

    def schedule(self, simulation_time: float):
        t = int(simulation_time)
        t_morning = t + 158   # next week's same weekday 08:00
        t_evening = t + 168   # next day's 18:00
        d = dow_1_to_7(t_morning)

        # Morning: full capacity from CP
        out = []
        for r in [ResourceType.OR, ResourceType.A_BED, ResourceType.B_BED,
                  ResourceType.INTAKE, ResourceType.ER_PRACTITIONER]:
            out.append((r, t_morning, self.cap[(r, d)]))

        # Evening: keep INTAKE/ER/Beds at morning level; OR slightly trimmed
        out += [
            (ResourceType.INTAKE,           t_evening, self.cap[(ResourceType.INTAKE, d)]),
            (ResourceType.ER_PRACTITIONER,  t_evening, self.cap[(ResourceType.ER_PRACTITIONER, d)]),
            (ResourceType.A_BED,            t_evening, self.cap[(ResourceType.A_BED, d)]),
            (ResourceType.B_BED,            t_evening, self.cap[(ResourceType.B_BED, d)]),
            (ResourceType.OR,               t_evening, max(4, self.cap[(ResourceType.OR, d)] - 1)),
        ]
        return out
    
    
if __name__ == "__main__":
    planner = ORPlanner()
    problem = HealthcareProblem()
    sim = Simulator(planner, problem)
    res = sim.run(365*24)
    print("[OR-Tools] Annual performance:", res)