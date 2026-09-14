"""Exact schema19 compatibility, independent canonical oracle and live mutations."""
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import random

import pytest

from neutral_atom_env.domain.models import EventType, SimulationEvent, PhysicalGate, StaticTrap, GridCoord, Position2D
from neutral_atom_env.program.binding import fingerprint
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_env.replay.snapshot_encoding import TraceEncodingCache, encode_snapshot, snapshot_digest
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from test_quantum_readout import state_for


def check(payload, cache):
    expected = canonical_json(payload)
    assert encode_snapshot(payload, cache=cache) == expected
    assert snapshot_digest(payload, cache=cache) == sha256(expected.encode('utf-8')).hexdigest()


def test_unicode_escape_numeric_and_nonstring_trace_fallback():
    cache = TraceEncodingCache()
    for trace in [('量子😀\\\"\n\r\t', 'false', '{"trace":["sentinel"]}'), (),
                  ['list', {'mutable': [1, 2]}], (1, {'mixed': True})]:
        check({'trace': trace, 'z': -0.0, 'a': {'nested': ('é', 1, 1.0, False, None)}}, cache)
    # Canonical JSON can contain lone surrogates even though UTF-8 hashing cannot.
    payload = {'trace': ('\ud800',)}
    assert encode_snapshot(payload, cache=cache) == canonical_json(payload)


def test_append_fork_replace_truncate_and_return_to_old_branch():
    cache = TraceEncodingCache()
    original = ('first', 'second', 'third')
    for records in (original, original, original + ('fourth',),
                    original[:1] + ('other branch',), original, (), ('replacement',), original):
        check({'trace': records, 'other': len(records)}, cache)
    assert cache.stats()['hits'] > 0


def test_byte_and_record_budgets_do_not_change_encoding():
    for cache in (TraceEncodingCache(max_bytes=700), TraceEncodingCache(max_records=2),
                  TraceEncodingCache(max_bytes=0)):
        for records in (('a', 'b', 'c', 'd'), ('a', 'b' * 2000, 'c'), ('a',)):
            check({'trace': records}, cache)
            stats = cache.stats()
            assert stats['retained_bytes'] <= stats['max_bytes']
            assert stats['records'] <= stats['max_records']
        cache.clear()
        assert cache.stats()['records'] == cache.stats()['retained_bytes'] == 0


def test_nontrace_mutable_values_are_always_fresh():
    cache = TraceEncodingCache()
    payload = {'trace': ('same',), 'nested': {'mutable': [1]}}
    before = encode_snapshot(payload, cache=cache)
    payload['nested']['mutable'].append(2)
    check(payload, cache)
    assert encode_snapshot(payload, cache=cache) != before


def test_live_schedule_same_version_and_rng_measurement_slm_changes():
    state = state_for([PhysicalGate('m', 'MEASURE', ('q0',))])
    spare = StaticTrap('spare', GridCoord(4, 0), Position2D(20, 0))
    state = replace(state, world=replace(state.world, traps={**state.world.traps, 'spare': spare}), slm_enabled=None)
    initial_version = state.version
    initial = fingerprint(state)
    Executor(state).schedule(SimulationEvent(1.0, EventType.RNG_DRAW))
    assert state.version == initial_version and fingerprint(state) != initial
    assert state.snapshot() == canonical_json(state.snapshot_data())
    assert fingerprint(state) == sha256(state.snapshot().encode('utf-8')).hexdigest()
    previous = fingerprint(state)
    Executor(state).step()
    assert fingerprint(state) != previous
    variants = [replace(state, rng_state=random.Random(999).getstate()),
                replace(state, measurement_results={'m': 1}),
                replace(state, slm_enabled={**state.slm_enabled, 'spare': False})]
    for variant in variants:
        assert variant.version == state.version
        assert variant.snapshot() == canonical_json(variant.snapshot_data())
        assert fingerprint(variant) != fingerprint(state)
    restored = SimulationState.restore(state.snapshot())
    assert restored.snapshot() == state.snapshot()


@pytest.mark.parametrize('relative', [
    'artifacts/surface-qec-ghz2/browser/checkpoint.json',
    'artifacts/qec-roadmap/step4B-attempt1/checkpoint.json',
])
def test_saved_schema19_checkpoint_exact_string_and_hash(relative):
    path = Path(__file__).resolve().parents[1] / relative
    if not path.exists():
        pytest.skip('Saved acceptance artifact not available in this checkout')
    original = path.read_text(encoding='utf-8')
    state = SimulationState.restore(original)
    assert canonical_json(state.snapshot_data()) == original
    assert state.snapshot() == original
    assert fingerprint(state) == sha256(original.encode('utf-8')).hexdigest()
