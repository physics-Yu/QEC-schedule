"""A private shallow state fork must isolate every Executor-owned mutation.

This covers trusted states produced by repository constructors and Executor;
it does not replace checkpoint decoding or validation of untrusted objects.
"""
from dataclasses import fields, is_dataclass, replace
from enum import Enum
import json
import random
from types import MappingProxyType

import pytest

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import EventType, SimulationEvent
from neutral_atom_env.domain.operations import OperationType as K, TaskIntent
from neutral_atom_strategies.motion.greedy import GreedyCompiler
from neutral_atom_env.simulation import Executor
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from neutral_atom_strategies.scheduling.m4 import fill_raman
from neutral_atom_env.platform import initialize
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_app.visualization.workbench import build_inputs


def make(gates):
    value = {'compiler': 'greedy', 'atom_count': 4, 'layout': 'row', 'seed': 7,
             'ez_policy': 'adaptive', 'gates': [
                 {'id': f'G{i:03d}', 'gate_type': kind, 'qubit_ids': [f'Q{q:03d}' for q in qs],
                  'parameters': [], 'column': i} for i, (kind, qs) in enumerate(gates)]}
    value, circuit, platform, placement = build_inputs(value)
    return initialize(circuit, platform, placement, seed=value['seed'])


def assert_persistent_tree(value, seen=None):
    """Guard the actual reachable containers, including in-flight plan metadata."""
    seen = set() if seen is None else seen
    if id(value) in seen:
        return
    seen.add(id(value))
    if value is None or isinstance(value, (str, int, float, bool, Enum)):
        return
    if isinstance(value, MappingProxyType):
        for key, item in value.items():
            assert_persistent_tree(key, seen)
            assert_persistent_tree(item, seen)
    elif isinstance(value, (tuple, frozenset)):
        for item in value:
            assert_persistent_tree(item, seen)
    elif is_dataclass(value):
        assert value.__dataclass_params__.frozen, type(value)
        for field in fields(value):
            assert_persistent_tree(getattr(value, field.name), seen)
    else:
        pytest.fail(f'Mutable or unaudited reachable object: {type(value).__name__}')


@pytest.fixture(scope='module')
def physical_boundaries():
    state = make([('CZ', (0, 1)), ('H', (2,)), ('H', (3,)), ('X', (2,))])
    terminal = initial_terminal(state)
    compiler = GreedyCompiler(adaptive_sites=True)
    base = min(compiler.alternatives('G000', state, site_limit=1)[0], key=lambda c: c.cost).plan
    plan, slots = fill_raman(base, state)
    assert len(slots) == 3
    states = {'idle': replace(state)}
    executor = Executor(state)
    executor.submit(plan)
    states['submitted'] = replace(state)
    while state.event_queue:
        executor.step()
        if state.transfer:
            name = 'load' if state.transfer.kind == K.AOD_LOAD else 'offload'
            states.setdefault(name, replace(state))
        if state.aod.is_moving:
            states.setdefault('moving', replace(state))
        if state.active_plan:
            active = {key for key, _ in state.active_plan.running_operations}
            pulses = [o for o in state.active_plan.plan.operations if o.id in active and o.operation_type == K.RAMAN_ROTATION]
            if len(pulses) == 2:
                states.setdefault('parallel', replace(state))
    states['completed'] = replace(state)
    assert set(states) == {'idle', 'submitted', 'load', 'offload', 'moving', 'parallel', 'completed'}
    assert state.metrics()['completed_gate_count'] == 4
    exit_plan = compiler.compile(TaskIntent('fork-final-return', terminal), state)
    return states, plan, exit_plan


@pytest.mark.parametrize('boundary', ['idle', 'submitted', 'load', 'offload', 'moving', 'parallel', 'completed'])
def test_private_executor_fork_preserves_live_and_matches_checkpoint_restore(physical_boundaries, boundary):
    states, initial_plan, exit_plan = physical_boundaries
    live = states[boundary]
    before = live.snapshot()
    references = {name: getattr(live, name) for name in ('event_queue', 'trace', 'dag', 'placement',
                                                         'aod', 'active_plan', 'transfer', 'physical_metrics')}
    assert_persistent_tree(live)
    private, sibling = replace(live), replace(live)
    restored = SimulationState.restore(before)
    assert private is not live and private.event_queue is live.event_queue
    assert private.dag is live.dag and private.trace is live.trace
    if boundary in {'idle', 'completed'}:
        plan = initial_plan if boundary == 'idle' else exit_plan
        Executor(private).submit(plan)
        Executor(restored).submit(plan)
    executor = Executor(private)
    while private.event_queue:
        executor.step()
        assert live.snapshot() == sibling.snapshot() == before
        assert all(getattr(live, name) is original for name, original in references.items())
    Executor(restored).run()
    assert private.snapshot() == restored.snapshot()
    assert private.event_queue.entries == () and private.active_plan is None
    assert private.metrics()['completed_gate_count'] == 4


def test_rng_queue_and_trace_are_private_even_with_pending_events():
    live = make([])
    executor = Executor(live)
    executor.schedule(SimulationEvent(1, EventType.RNG_DRAW))
    executor.schedule(SimulationEvent(1, EventType.WAIT_COMPLETED))
    executor.schedule(SimulationEvent(2, EventType.RNG_DRAW))
    before = live.snapshot()
    private = replace(live)
    Executor(private).run()
    assert live.snapshot() == before and len(live.event_queue.entries) == 3
    restored = SimulationState.restore(before)
    Executor(restored).run()
    assert private.snapshot() == restored.snapshot()
    rng = random.Random(7)
    values = [record['random_value'] for text in private.trace.records
              if 'random_value' in (record := json.loads(text))]
    assert values == [rng.random(), rng.random()]


def test_rejected_private_submission_does_not_mutate_either_state(physical_boundaries):
    states, plan, _ = physical_boundaries
    live = states['idle']
    before = live.snapshot()
    private = replace(live)
    malformed = replace(plan, estimated_duration_us=plan.estimated_duration_us + 1)
    with pytest.raises(ValidationError):
        Executor(private).submit(malformed)
    assert private.snapshot() == live.snapshot() == before
