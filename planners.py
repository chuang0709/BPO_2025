from abc import ABC, abstractmethod
from reporter import EventLogReporter, ResourceScheduleReporter
from problems import ResourceType

class Planner(ABC):
    """
    The class that must be implemented to create a planner.
    The class must implement the plan method.
    The class must not use the simulator or the problem directly. Information from those classes is not available to it.
    Note that once an event is planned, it can still show up as possible event to (re)plan.
    """
    def __init__(self, eventlog_file, data_columns, case_priority):
        self.eventlog_reporter = EventLogReporter(eventlog_file, data_columns)
        self.resource_reporter = ResourceScheduleReporter()
        self.replanned_patients = set()
        self.case_priority = case_priority

    def report(self, case_id, element, timestamp, resource, lifecycle_state, data=None):
        self.eventlog_reporter.callback(case_id, element, timestamp, resource, lifecycle_state)
        self.resource_reporter.callback(case_id, element, timestamp, resource, lifecycle_state, data)

    def plan(self, cases_to_plan, cases_to_replan, simulation_time):
        raise NotImplementedError

    def schedule(self, simulation_time):
        raise NotImplementedError
        
    # @abstractmethod
    # def plan(self, plannable_elements, simulation_time):
    #     '''
    #     The method that must be implemented for planning.
    #     :param plannable_elements: A dictionary with case_id as key and a list of element_labels that can be planned or re-planned.
    #     :param simulation_time: The current simulation time.
    #     :return: A list of tuples of how the elements are planned. Each tuple must have the following format: (case_id, element_label, timestamp).
    #     '''
        
    #     pass


    # def report(self, case_id, element, timestamp, resource, lifecycle_state):
    #     '''
    #     The method that can be implemented for reporting.
    #     It is called by the simulator upon each simulation event.
    #     '''
    #     pass
    
class ImprovedPlanner(Planner):
    def __init__(self, eventlog_file, data_columns, case_priority):
        super().__init__(eventlog_file, data_columns, case_priority)

    def estimate_batch_size(self, simulation_time):
        
        return 5

    def plan(self, cases_to_plan, cases_to_replan, simulation_time):
        planned_cases = []

        base_admission_time = simulation_time + 24
        sorted_cases = sorted(cases_to_plan, key=lambda c: self.case_priority.get(c, 0), reverse=True)

        batch_size = self.estimate_batch_size(simulation_time)
        interval = 1 

        for i, case_id in enumerate(sorted_cases):
            if i < batch_size:
                admission_time = base_admission_time + i * interval
                planned_cases.append((case_id, admission_time))

        for case_id in cases_to_replan:
            if case_id not in self.replanned_patients:
                admission_time = simulation_time + 24
                planned_cases.append((case_id, admission_time))
                self.replanned_patients.add(case_id)

        return planned_cases

    def schedule(self, simulation_time):
        hour_of_week = simulation_time % 168
        day_of_week = hour_of_week // 24
        is_weekday = day_of_week < 5

        if is_weekday:
            return [
                (ResourceType.OR, simulation_time + 158, 5),
                (ResourceType.A_BED, simulation_time + 158, 30),
                (ResourceType.B_BED, simulation_time + 158, 40),
                (ResourceType.INTAKE, simulation_time + 158, 4),
                (ResourceType.ER_PRACTITIONER, simulation_time + 158, 9),
                (ResourceType.OR, simulation_time + 168, 1),
                (ResourceType.INTAKE, simulation_time + 168, 1)
            ]
        else:
            return []