"""Recovery-local primitive hash buckets retain the original full key proof."""
from collections import OrderedDict
from dataclasses import FrozenInstanceError, replace

import pytest

from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import Position2D
from neutral_atom_env.domain.operations import CompiledPlan
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_env.simulation import operation_program as program
from neutral_atom_env.simulation.runtime_validation import validate_runtime
from neutral_atom_experiments.qec_pbc.encoded_export_recovery import (
    _ExactReplayKey, exclusive_recovery_prefix_cache)
from test_runtime_prefix_cache import mutate
from test_search_state_fork import physical_boundaries
from test_qec_encoded_export_recovery import real_short_run


def test_adapter_calls_no_plan_or_circuit_dataclass_hash(physical_boundaries, monkeypatch):
    state = physical_boundaries[0]['parallel']
    def poisoned(_):
        raise AssertionError('Deep dataclass hash must not be called in recovery')
    monkeypatch.setattr(CompiledPlan, '__hash__', poisoned)
    monkeypatch.setattr(PhysicalCircuit, '__hash__', poisoned)
    with exclusive_recovery_prefix_cache():
        validate_runtime(state)
        validate_runtime(state)
        assert program._runtime_prefixes


@pytest.mark.parametrize('field', range(13))
def test_every_complete_original_key_field_still_guards_forced_hash_collision(physical_boundaries, monkeypatch, field):
    state = physical_boundaries[0]['parallel']
    parts = program._replay_key(state.active_plan.plan, state)
    alternatives = [replace(parts[0],estimated_duration_us=parts[0].estimated_duration_us+1),
        replace(parts[1],upper=Position2D(parts[1].upper.x_um+5,parts[1].upper.y_um)),
        parts[2][1:], parts[3][::-1], parts[4]+1,
        Position2D(parts[5].x_um+1,parts[5].y_um), parts[6][1:],
        replace(parts[7],raman_minimum_separation_um=parts[7].raman_minimum_separation_um+1),
        tuple((key,replace(value,measured=not value.measured)) for key,value in parts[8]),
        replace(parts[9],gates=tuple(replace(g,id='changed.'+g.id) for g in parts[9].gates)),
        parts[10]+1,parts[11]+1,parts[12]+1]
    assert alternatives[field] != parts[field]
    changed = tuple(alternatives[field] if i == field else value for i,value in enumerate(parts))
    assert changed[0].id == parts[0].id
    monkeypatch.setattr(_ExactReplayKey, '__hash__', lambda _:0)
    left, same, right = _ExactReplayKey(parts), _ExactReplayKey(tuple(parts)), _ExactReplayKey(changed)
    cache = OrderedDict(((left,'old'),))
    assert hash(left) == hash(right) == 0
    assert cache[same] == 'old' and cache.get(right) is None
    cache[right] = 'changed'
    assert len(cache) == 2 and cache[left] == 'old'


def test_warm_cold_original_reconstruction_and_older_fork_have_identical_results(physical_boundaries, monkeypatch):
    states = physical_boundaries[0]
    original_cache = program._runtime_prefixes
    calls, original_transition = [], program.transition
    def counted(state,event):
        calls.append(event)
        return original_transition(state,event)
    monkeypatch.setattr(program,'transition',counted)
    original_cache.clear()
    validate_runtime(states['parallel'])
    oracle = next(iter(original_cache.values()))[1]
    with exclusive_recovery_prefix_cache():
        validate_runtime(states['completed'])
        calls.clear()
        validate_runtime(states['completed'])
        assert not calls
        validate_runtime(states['parallel'])
        assert calls, 'Earlier prefix must reconstruct its own origin and transitions'
        warm = next(iter(program._runtime_prefixes.values()))[1]
        assert canonical_json(warm.snapshot_data()) == canonical_json(oracle.snapshot_data())
        program._runtime_prefixes.clear()
        validate_runtime(states['parallel'])
        cold = next(iter(program._runtime_prefixes.values()))[1]
        assert canonical_json(cold.snapshot_data()) == canonical_json(oracle.snapshot_data())
    assert program._runtime_prefixes is original_cache


@pytest.mark.parametrize('kind', ['holders','masks','aod','metrics','runtime','reservations','time',
                                  'dag','transfer','trace_time','trace_plan','pending_missing','pending_duplicate'])
def test_original_and_adapter_warm_and_cold_reject_the_same_tampered_runtime(physical_boundaries, kind):
    from neutral_atom_env.domain.errors import ValidationError
    states = physical_boundaries[0]
    state = states['moving' if kind == 'aod' else 'load' if kind == 'transfer' else 'parallel']
    bad = mutate(state,kind)
    program._runtime_prefixes.clear()
    with pytest.raises(ValidationError):
        validate_runtime(bad)
    with exclusive_recovery_prefix_cache():
        validate_runtime(state)
        with pytest.raises(ValidationError):
            validate_runtime(bad)
        program._runtime_prefixes.clear()
        with pytest.raises(ValidationError):
            validate_runtime(bad)


def test_adapter_keeps_original_32_entry_lru_limit(physical_boundaries):
    state = physical_boundaries[0]['parallel']
    with exclusive_recovery_prefix_cache():
        first = program._replay_key(state.active_plan.plan,state)
        for i in range(33):
            upper = replace(state.world.bounds.upper,x_um=state.world.bounds.upper.x_um+5*i)
            changed = replace(state,world=replace(state.world,bounds=replace(state.world.bounds,upper=upper)))
            validate_runtime(changed)
        assert len(program._runtime_prefixes) == 32 and first not in program._runtime_prefixes


@pytest.mark.parametrize('raise_error', [False,True])
def test_context_restores_original_function_and_cache_objects_even_on_exception(raise_error):
    original_key,original_cache = program._replay_key,program._runtime_prefixes
    try:
        with exclusive_recovery_prefix_cache():
            assert program._replay_key is not original_key and program._runtime_prefixes is not original_cache
            if raise_error:
                raise RuntimeError('Injected context failure')
    except RuntimeError:
        assert raise_error
    assert program._replay_key is original_key and program._runtime_prefixes is original_cache


def test_nested_context_is_rejected_without_corrupting_outer_context():
    original_key,original_cache = program._replay_key,program._runtime_prefixes
    with exclusive_recovery_prefix_cache():
        outer_key,outer_cache = program._replay_key,program._runtime_prefixes
        with pytest.raises(RuntimeError,match='exclusive and non-reentrant'):
            with exclusive_recovery_prefix_cache():
                pytest.fail('Nested adapter must not enter')
        assert program._replay_key is outer_key and program._runtime_prefixes is outer_cache
    assert program._replay_key is original_key and program._runtime_prefixes is original_cache


def test_nonexact_plan_id_cannot_invoke_custom_hash(physical_boundaries):
    class CustomString(str):
        def __hash__(self):
            raise AssertionError('Custom string hash was invoked')
    state = physical_boundaries[0]['parallel']
    parts = program._replay_key(state.active_plan.plan,state)
    with pytest.raises(TypeError,match='exact string plan ID'):
        _ExactReplayKey((replace(parts[0],id=CustomString(parts[0].id)),*parts[1:]))


def test_cache_certificate_rebinding_is_rejected(physical_boundaries):
    state = physical_boundaries[0]['parallel']
    key = _ExactReplayKey(program._replay_key(state.active_plan.plan,state))
    cache = {key:'original'}
    with pytest.raises(FrozenInstanceError):
        key.parts = (replace(key.parts[0],estimated_duration_us=99),*key.parts[1:])
    assert cache[key] == 'original'


def test_real_recovery_has_full_replay_with_poisoned_plan_and_circuit_hash(real_short_run, monkeypatch):
    from neutral_atom_experiments.qec_pbc import encoded_export_recovery as recovery
    protocol,parent,crashed,manifest,root,baseline = real_short_run
    def poisoned(_):
        raise AssertionError('Recovery must avoid the observed deep dataclass hash path')
    monkeypatch.setattr(CompiledPlan,'__hash__',poisoned)
    monkeypatch.setattr(PhysicalCircuit,'__hash__',poisoned)
    result = recovery.recover_encoded_export(protocol,crashed,parent,root/'poison-hash-recovered',
        seed=7,crash_manifest=manifest)
    assert result['status'] == 'completed' and result['metrics'] == baseline['metrics']
    assert result['audit']['independent_plan_replay_equal']
    assert result['recovery']['runtime_prefix_cache_adapter']['enabled']
    assert result['recovery']['forward_gates_executed'] == 0
