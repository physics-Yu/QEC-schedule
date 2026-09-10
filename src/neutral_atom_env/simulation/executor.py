from neutral_atom_env.domain.models import EventType, GateStatus, SimulationEvent
from dataclasses import replace, fields
import random
from .state import SimulationState
from .physical_executor import reduce_physical, PHYSICAL_EVENTS
from neutral_atom_env.domain.errors import ValidationError


class Executor:
    """Only live-state writer; validate a complete next state before committing it."""
    def __init__(self, state: SimulationState):
        self.state = state

    def _logical_transition(self, state, event, target):
        raise ValidationError('PHYSICAL_PLAN_REQUIRED', 'Gate transitions require Executor.submit(plan)')

    def schedule(self, event):
        if event.event_type.value.startswith('gate_'):
            self._check_logical_event()
        if self.state.active_plan or any(e.event_type in PHYSICAL_EVENTS for _,_,e in self.state.event_queue.entries):
            raise ValidationError('RESOURCE_BUSY','Cannot externally schedule events during a reserved physical cycle')
        if event.time_us < self.state.time_us:
            raise ValueError('Cannot schedule in the past')
        object.__setattr__(self.state, 'event_queue', self.state.event_queue.push(event))

    def _check_logical_event(self):
        raise ValidationError('PHYSICAL_PLAN_REQUIRED', 'Gate transitions require Executor.submit(plan)')

    def submit(self, plan):
        from neutral_atom_env.motion.compiler import exact_validate
        exact_validate(plan,self.state)
        self.schedule(SimulationEvent(self.state.time_us,EventType.PLAN_STARTED,plan_id=plan.id,plan=plan))

    def step(self):
        from .runtime_validation import validate_runtime
        validate_runtime(self.state)
        state = self.state
        event = state.event_queue.peek()
        transitions = {EventType.GATE_RESERVED: GateStatus.RESERVED,
                       EventType.GATE_STARTED: GateStatus.RUNNING,
                       EventType.GATE_COMPLETED: GateStatus.COMPLETED,
                       EventType.GATE_FAILED: GateStatus.FAILED}
        if event.time_us < state.time_us:
            raise ValueError('Event time regression')
        dag, atoms, rng_state = state.dag, state.atoms, state.rng_state
        record = {'sequence': state.committed_events, 'event': event, 'state_version': state.version+1}
        _, queue = state.event_queue.pop()
        work=state
        if event.event_type in PHYSICAL_EVENTS:
            work,queue,extra=reduce_physical(state,event,queue)
            dag,atoms,rng_state=work.dag,work.atoms,work.rng_state
            record.update(extra)
        elif state.active_plan:
            raise ValidationError('RESOURCE_BUSY','Logical events cannot bypass an active physical cycle')
        elif event.event_type in transitions:
            dag, atoms = self._logical_transition(state, event, transitions[event.event_type])
        elif event.event_type == EventType.RNG_DRAW:
            rng = random.Random()
            rng.setstate(rng_state)
            record['random_value'] = rng.random()
            rng_state = rng.getstate()
        elif event.event_type != EventType.WAIT_COMPLETED:
            raise ValueError('Unsupported event')
        # Constructing/serializing can fail. Nothing has been installed yet.
        next_state = replace(work, dag=dag, atoms=atoms, rng_state=rng_state,
            event_queue=queue, time_us=event.time_us, version=state.version+1,
            committed_events=state.committed_events+1, trace=state.trace.appended(record))
        validate_runtime(next_state)
        for field in fields(state):
            object.__setattr__(state, field.name, getattr(next_state, field.name))
        return event

    def run(self):
        from .runtime_validation import validate_runtime
        validate_runtime(self.state)
        while self.state.event_queue:
            self.step()
