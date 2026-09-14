"""Warm runtime caches cannot authorize a changed trace, environment or state."""
from dataclasses import replace
import json

import pytest

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import GateStatus, Position2D
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_env.replay.trace import Trace, _event_data
from neutral_atom_env.simulation.event_queue import EventQueue
from neutral_atom_env.simulation import operation_program as program
from neutral_atom_env.simulation.runtime_validation import validate_runtime
from neutral_atom_env.world import PlacementState
from test_search_state_fork import physical_boundaries


@pytest.fixture(autouse=True)
def fresh_expected_cache():
    program._runtime_prefixes.clear()
    yield
    program._runtime_prefixes.clear()


def trace_edit(state, index, edit):
    records = list(state.trace.records)
    record = json.loads(records[index])
    edit(record)
    records[index] = canonical_json(record)
    return replace(state, trace=Trace(tuple(records)))


def mutate(state, kind):
    if kind == 'holders':
        holders = dict(state.placement.atom_to_holder)
        holders['Q002'], holders['Q003'] = holders['Q003'], holders['Q002']
        return replace(state, placement=PlacementState(holders))
    if kind == 'masks':
        masks = dict(state.slm_enabled)
        site = next(k for k, enabled in masks.items() if k.startswith('EZ') and not enabled)
        masks[site] = True
        return replace(state, slm_enabled=masks)
    if kind == 'aod':
        return replace(state, aod=replace(state.aod, pose=Position2D(state.aod.pose.x_um+.01, state.aod.pose.y_um)))
    if kind == 'metrics':
        return replace(state, physical_metrics=replace(state.physical_metrics,
                       total_aod_distance_um=state.physical_metrics.total_aod_distance_um+1))
    if kind == 'runtime':
        return replace(state, active_plan=replace(state.active_plan,
                       operation_started_us=state.active_plan.operation_started_us+.01))
    if kind == 'reservations':
        return replace(state, reservations=())
    if kind == 'time':
        return replace(state, time_us=state.time_us+.01)
    if kind == 'dag':
        return replace(state, dag=state.dag.transitioned('G001', GateStatus.COMPLETED))
    if kind == 'transfer':
        return replace(state, transfer=None)
    if kind == 'trace_time':
        return trace_edit(state, -1, lambda record: record['event'].update(time_us=record['event']['time_us']+.01))
    if kind == 'trace_plan':
        return trace_edit(state, 0, lambda record: record['event']['plan'].update(estimated_duration_us=999999))
    if kind == 'pending_missing':
        return replace(state, event_queue=EventQueue(state.event_queue.entries[1:], state.event_queue.next_sequence))
    if kind == 'pending_duplicate':
        return replace(state, event_queue=state.event_queue.push(state.event_queue.peek()))
    raise AssertionError(kind)


@pytest.mark.parametrize('kind', ['holders', 'masks', 'aod', 'metrics', 'runtime', 'reservations',
                                  'time', 'dag', 'transfer', 'trace_time', 'trace_plan',
                                  'pending_missing', 'pending_duplicate'])
def test_warm_cache_still_rejects_tampered_runtime(physical_boundaries, kind):
    states, _, _ = physical_boundaries
    state = states['moving' if kind == 'aod' else 'load' if kind == 'transfer' else 'parallel']
    before = state.snapshot()
    validate_runtime(state)
    assert program._runtime_prefixes
    damaged = mutate(state, kind)
    with pytest.raises(ValidationError):
        validate_runtime(damaged)
    assert state.snapshot() == before
    # The same corruption must also fail without any expected-state cache.
    program._runtime_prefixes.clear()
    with pytest.raises(ValidationError):
        validate_runtime(damaged)


def test_warm_cache_rejects_reordered_equal_time_events(physical_boundaries):
    state = physical_boundaries[0]['parallel']
    validate_runtime(state)
    entries = list(state.event_queue.entries)
    pair = next((i, j) for i, left in enumerate(entries) for j, right in enumerate(entries)
                if i < j and left[0] == right[0])
    i, j = pair
    entries[i], entries[j] = (*entries[i][:2], entries[j][2]), (*entries[j][:2], entries[i][2])
    with pytest.raises(ValidationError):
        validate_runtime(replace(state, event_queue=EventQueue(tuple(entries), state.event_queue.next_sequence)))


@pytest.mark.parametrize('change', ['neighbor_rule', 'atom_measured'])
def test_physical_environment_change_cannot_reuse_old_proof(physical_boundaries, change):
    state = physical_boundaries[0]['parallel']
    validate_runtime(state)
    if change == 'neighbor_rule':
        changed = replace(state, hardware=replace(state.hardware, raman_minimum_separation_um=11))
    else:
        atoms = dict(state.atoms)
        atoms['Q002'] = replace(atoms['Q002'], measured=True)
        changed = replace(state, atoms=atoms)
    assert program._replay_key(state.active_plan.plan, state) != program._replay_key(changed.active_plan.plan, changed)
    with pytest.raises(ValidationError):
        validate_runtime(changed)
    program._runtime_prefixes.clear()
    with pytest.raises(ValidationError):
        validate_runtime(changed)


def test_warm_and_cold_reconstruction_match_and_older_fork_is_rebuilt(physical_boundaries, monkeypatch):
    states, _, _ = physical_boundaries
    calls = []
    original = program.transition

    def observed(state, event):
        calls.append(event)
        return original(state, event)

    monkeypatch.setattr(program, 'transition', observed)
    validate_runtime(states['completed'])
    assert calls
    calls.clear()
    validate_runtime(states['completed'])
    assert calls == [], 'A second identical completed prefix should reuse its independent proof'
    validate_runtime(states['parallel'])
    assert calls, 'An older branch must reconstruct instead of reusing the later physical state'
    warm = next(iter(program._runtime_prefixes.values()))[1]
    program._runtime_prefixes.clear()
    validate_runtime(states['parallel'])
    cold = next(iter(program._runtime_prefixes.values()))[1]
    for name in ('placement', 'aod', 'slm_enabled', 'transfer', 'active_plan', 'reservations', 'physical_metrics', 'time_us'):
        assert getattr(warm, name) == getattr(cold, name)
    assert canonical_json(warm.dag.nodes) == canonical_json(cold.dag.nodes)


def test_world_and_aod_shape_are_keyed_and_expected_cache_is_bounded(physical_boundaries):
    state = physical_boundaries[0]['parallel']
    validate_runtime(state)
    original_key = program._replay_key(state.active_plan.plan, state)
    reshaped = replace(state, aod=replace(state.aod, spacing_um=7))
    assert program._replay_key(reshaped.active_plan.plan, reshaped) != original_key
    validate_runtime(reshaped)
    for i in range(33):
        upper = replace(state.world.bounds.upper, x_um=state.world.bounds.upper.x_um+5*(i+1))
        changed = replace(state, world=replace(state.world, bounds=replace(state.world.bounds, upper=upper)))
        validate_runtime(changed)
    assert len(program._runtime_prefixes) == 32
    assert original_key not in program._runtime_prefixes


def test_decoded_trace_cache_is_recursive_readonly_and_exact_text_keyed(physical_boundaries):
    state = physical_boundaries[0]['parallel']
    record = state.trace.records[0]
    decoded = _event_data(record)
    assert _event_data(record) is decoded
    with pytest.raises(TypeError):
        decoded['time_us'] = 99
    with pytest.raises(TypeError):
        decoded['plan']['operations'][0]['duration_us'] = 99
    changed = json.loads(record)
    changed['event']['plan']['operations'][0]['duration_us'] += 1
    alternative = _event_data(canonical_json(changed))
    assert alternative is not decoded
    assert alternative['plan']['operations'][0]['duration_us'] != decoded['plan']['operations'][0]['duration_us']
