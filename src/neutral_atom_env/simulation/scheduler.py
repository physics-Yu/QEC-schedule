"""Continuous serial eager scheduling. Executor remains the only state writer."""
from dataclasses import dataclass
from neutral_atom_env.planning.eager_baseline import EagerBaseline
from neutral_atom_env.replay.serializer import primitive
from .executor import Executor
from .runtime_validation import validate_runtime


@dataclass(frozen=True)
class ScheduleResult:
    status: str
    diagnostics: dict


class EagerScheduler:
    def __init__(self,state,*,policy=None):
        self.state=state
        self.executor=Executor(state)
        self.policy=policy or EagerBaseline()

    def step(self):
        state=self.state
        validate_runtime(state)
        if state.event_queue:
            return self.executor.step()
        if state.dag.completed and not state.placement.mobile_occupancy and not state.reservations:
            return ScheduleResult('completed',{})
        plan,failures=self.policy.compile_first(state)
        if plan is not None:
            self.executor.submit(plan)
            return self.executor.step()
        return ScheduleResult('stalled',{
            'reason':'candidate_scope_exhausted' if failures else 'no_ready_gate_or_cleanup_unsupported',
            'message':'No executable plan in the supported eager routing family; this is not proof of physical impossibility.',
            'pending_event_count':len(state.event_queue.entries),
            'holders':primitive(state.placement.atom_to_holder),
            'gate_statuses':{key:node.status.value for key,node in state.dag.nodes.items()},
            'candidate_failures':[{'gate_id':gate,'violation':primitive(error)} for gate,error in failures]})

    def run(self,on_event=None):
        while True:
            result=self.step()
            if isinstance(result,ScheduleResult):
                return result
            if on_event is not None:
                on_event(self.state,result)
