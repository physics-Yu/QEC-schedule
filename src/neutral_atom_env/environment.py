"""Experimental platform interface. No planning policy or application imports.

The Executor remains the only live-state writer. Planners may inspect the frozen
state for backward-compatible physical prediction; public observations deliberately
omit the quantum state, RNG, and trace. This is not an RL/Gym environment.
"""
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Mapping

from .simulation.executor import Executor
from .simulation.state import SimulationState


@dataclass(frozen=True)
class Observation:
    version: int
    time_us: float
    positions: Mapping
    holders: Mapping
    ready_gates: tuple
    completed: bool
    pending_events: int
    measurement_results: Mapping
    slm_enabled: Mapping
    aod_configuration: object
    enabled_rows: tuple
    enabled_columns: tuple


class NeutralAtomEnv:
    """Own execution; accept supplied physical plans without choosing an algorithm.

    ``state`` is the privileged immutable planning/verification view retained for
    existing compilers. Only submit/step/run modify the live episode. A fork owns
    a separate top-level runtime and shares persistent immutable children.
    """

    def __init__(self, state: SimulationState):
        if not isinstance(state, SimulationState):
            raise TypeError('NeutralAtomEnv requires a SimulationState')
        self._executor = Executor(state)

    @classmethod
    def create(cls, circuit, platform, placement, *, seed=0):
        from .platform import initialize
        return cls(initialize(circuit, platform, placement, seed=seed))

    @classmethod
    def restore(cls, checkpoint: str):
        return cls(SimulationState.restore(checkpoint))

    @property
    def state(self):
        return self._executor.state

    @property
    def pending(self):
        return bool(self.state.event_queue)

    def observe(self):
        state = self.state
        return Observation(
            state.version, state.time_us,
            MappingProxyType({q: state.placement.position(q, state.world, state.aod)
                              for q in state.atoms}),
            MappingProxyType(dict(state.placement.atom_to_holder)),
            tuple(state.dag.ready_gates()), state.dag.completed,
            len(state.event_queue.entries),
            MappingProxyType(dict(state.measurement_results)),
            MappingProxyType(dict(state.slm_enabled)), state.aod.configuration(),
            tuple(state.aod.enabled_rows), tuple(state.aod.enabled_columns))

    def validate(self, plan):
        from .program.binding import exact_validate
        exact_validate(plan, self.state)

    def submit(self, plan):
        """Validate against the current state and enqueue; never search a route."""
        return self._executor.submit(plan)

    def step(self):
        """Commit the next physical event. An empty queue raises as Executor does."""
        return self._executor.step()

    def run(self, on_event=None):
        """Drain supplied operations, not the remaining circuit."""
        if on_event is None:
            return self._executor.run()
        from .simulation.runtime_validation import validate_runtime
        validate_runtime(self.state)
        while self.pending:
            event = self.step()
            on_event(self.state, event)

    def fork(self):
        return type(self)(replace(self.state))

    def snapshot(self):
        return self.state.snapshot()


def as_environment(value):
    """Legacy runner adapter; new control programs pass NeutralAtomEnv directly."""
    return value if isinstance(value, NeutralAtomEnv) else NeutralAtomEnv(value)
