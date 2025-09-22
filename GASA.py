import random, math, time, json
from simulator import Simulator
from planners import Planner
from problems import HealthcareProblem, ResourceType
from reporter import EventLogReporter, ResourceScheduleReporter
from scipy.stats import norm


case_ids = [f"case_{i:03}" for i in range(1, 101)]
with open("pm_params.json") as f:
    _pm = json.load(f)

class CalibratedProblem(HealthcareProblem):
    def __init__(self):
        super().__init__()
        self._pm_params = _pm
    def processing_time_sample(self, resource, task, sim_time):
        act = task.label
        if act in self._pm_params["mean_sec"]:
            m = self._pm_params["mean_sec"][act]/3600
            s = self._pm_params["std_sec"][act]/3600
            return max(0.0, norm.rvs(loc=m, scale=s))
        return super().processing_time_sample(resource, task, sim_time)

def evaluate(adm_schedule, calibrated=False):
    """
    Run a one-week simulation and return total waiting_time_for_admission.
    If `calibrated` is True, use CalibratedProblem; otherwise use the base HealthcareProblem.
    """
    class FixedPlanner(Planner):
        def __init__(self, sched):
            super().__init__("./temp/event_log.csv", ["diagnosis"], {})
            self.adm_schedule = sched

        def plan(self, to_plan, to_replan, now):
            # Admit each case at its scheduled time (or 24h from now if missing)
            return [(cid, self.adm_schedule.get(cid, now + 24))
                    for cid in to_plan]

        def schedule(self, now):
            # No resource changes
            return []

    # Choose problem class based on calibration flag
    problem_cls = CalibratedProblem if calibrated else HealthcareProblem
    sim = Simulator(FixedPlanner(adm_schedule), problem_cls())
    result = sim.run(24 * 7)
    return result["waiting_time_for_admission"]


def run_ga(case_ids):
    # Dummy implementation; replace with your actual GA logic
    # Returns (best_schedule_dict, score)
    best_schedule = {cid: random.randint(0, 24*7) for cid in case_ids}
    score = random.uniform(100, 200)
    return best_schedule, score

def run_sa_seed(case_ids, initial_schedule):
    # Dummy implementation; replace with your actual SA logic
    # Returns (refined_schedule_dict, score)
    refined_schedule = {cid: t + random.randint(-2, 2) for cid, t in initial_schedule.items()}
    score = random.uniform(80, 150)
    return refined_schedule, score

class OfflinePlanner(Planner):
    def __init__(self, adm_schedule):
        super().__init__("./temp/event_log.csv", ["diagnosis"], {})
        self.adm_schedule = adm_schedule

    def plan(self, to_plan, to_replan, now):
        return [(cid, self.adm_schedule.get(cid, now + 24))
                for cid in to_plan]

    def schedule(self, now):
        return []

def run_ga_sa(case_ids, calibrated=False):
    """
    Run GA→SA on the given case IDs.
    Returns (GA_initial_score, SA_refined_score, full_year_performance_dict).
    """
    # 1) Genetic Algorithm search
    ga_best, ga_score = run_ga(case_ids)
    # 2) Simulated Annealing refinement starting from GA result
    sa_best, sa_score = run_sa_seed(case_ids, ga_best)
    # 3) Full-year discrete-event simulation of the final plan
    problem_cls = CalibratedProblem if calibrated else HealthcareProblem
    full_perf = Simulator(OfflinePlanner(sa_best), problem_cls()).run(365 * 24)
    return ga_score, sa_score, full_perf


if __name__ == "__main__":
    label, use_calib = "with-PM", True
    start = time.perf_counter()
    ga_s, sa_s, perf = run_ga_sa(case_ids, calibrated=use_calib)
    end = time.perf_counter()
    print(f"[GA→SA {label}] Full-year performance: {perf}\n")
    
    start = time.perf_counter()
    ga_best, ga_score = run_ga(case_ids)
    sa_best, sa_score = run_sa_seed(case_ids, ga_best)
    end = time.perf_counter()
    
    # Create the final planner using the optimized schedule
    planner = OfflinePlanner(sa_best)
    
    problem = HealthcareProblem()
    simulator = Simulator(planner, problem)
    result = simulator.run(365 * 24)