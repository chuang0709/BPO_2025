# BPO Challenge 2025  
My solution builds admission schedules using a randomized search with local refinement, combined with Process Mining calibration to make the simulation more realistic. The approach was designed to minimize the four KPIs defined in the project:  
* Waiting time for admission (WTA)  
* Waiting time in hospital (WTH)  
* Nervousness (NERV)  
* Personnel cost (COST)  

---

### Simplified Genetic Algorithm (Initial Scheduling)  
Instead of a full evolutionary loop, the GA stage generates randomized admission schedules as starting points. Each schedule is evaluated in the simulator against the KPIs, serving as initial candidates for refinement.  

### Local Refinement via Simulated Annealing  
The refinement stage applies small random adjustments to admission times, inspired by simulated annealing principles. This allows the schedule to improve incrementally by exploring local variations while avoiding rigid local optima.  

### Process Mining Calibration  
Task durations in the simulator were calibrated using event log data. For each activity, mean and variance were extracted and used to replace default values with fitted distributions, making outcomes more representative of real hospital operations.  

---

### OR Planner (Custom Scheduling Heuristic)  
My OR planner that maximizes admission throughput while avoiding bottlenecks. It fixes high capacities for operating rooms, intake staff, Emergency Room (ER) practitioners, and beds, and admits patients in six fixed waves starting at 08:00.  
Daily admission quotas are based on intake, ER, and bed availability, adjusted for backlog and early warm-up. Quotas are bounded between 48 and 72 patients/day and split across waves by fixed proportions. Patients are scheduled once (no replanning) to keep nervousness low.  

*This approach drains backlogs and reduces admission waiting time, but can increase in-hospital waiting due to aggressive intake.*  

---

### Simplified Reinforcement Learning Planner (Daily Operating Room Capacity Control)  
This simplified RL policy that adjusts next day OR capacity once per day at 18:00. The policy observes weekday, backlog level, and overtime, then selects an OR level between 2 and 5 using an ε-greedy rule. The reward balances shorter waiting times against a heavy penalty on personnel cost. Rules enforce ≥24h admissions, ≥14h decisions, increase only near-term changes, and capping at 5 ORs.  

*This adapts OR capacity day by day, but results were unstable and often produced higher personnel costs compared to heuristic planners.*  


## Conclusion  
I compared multiple approaches for hospital admission scheduling:  
* Simplified GA → SA provided randomized schedules with local refinement.  
* GA → SA + Process Mining improved realism and gave the most balanced results.  
* OR Planner reduced admission waiting via fixed quotas and waves, but increased in-hospital waiting.  
* RL Planner adapted OR capacity dynamically, but outcomes were unstable and costly.  

### Overall, the combination of randomized GA initialization, local refinement, and process mining calibration delivered the most effective and balanced results.
