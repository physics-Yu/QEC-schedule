"""A bounded decode cache must never turn a warm audit into an accepted proof."""
from collections import Counter
from dataclasses import replace
import json

import pytest

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_env.replay.trace import Trace, TraceEventCache, _event_data
from neutral_atom_env.simulation import operation_program, runtime_validation
from neutral_atom_env.simulation.state import SimulationState
from test_search_state_fork import physical_boundaries


def record(index, **event_fields):
    return canonical_json({'event': {'event_type': 'wait_completed', 'time_us': index,
                                     'gate_id': None, 'plan_id': None, 'operation_id': None,
                                     'plan': None, **event_fields},
                           'sequence': index, 'state_version': index + 1})


@pytest.fixture(autouse=True)
def clean_caches():
    _event_data.cache_clear()
    operation_program._runtime_prefixes.clear()
    yield
    _event_data.cache_clear()
    operation_program._runtime_prefixes.clear()


def test_full_scan_past_entry_limit_retains_prefix_without_cyclic_eviction(monkeypatch):
    count = 16385
    cache = TraceEventCache(max_records=16384)
    records = tuple(record(i) for i in range(count))
    calls = []
    original = json.loads

    def counted(raw):
        calls.append(raw)
        return original(raw)

    monkeypatch.setattr('neutral_atom_env.replay.trace.json.loads', counted)
    cache.activate_history(records)
    first = [cache.decode(raw) for raw in records]
    assert len(calls) == count
    assert cache.cache_info().currsize == 16384
    for _ in range(3):
        cache.activate_history(records)
        for i, raw in enumerate(records):
            assert cache.decode(raw) == first[i]
    assert len(calls) == count + 3
    assert cache.cache_info().hits == 3 * 16384
    assert calls[-3:] == [records[-1]] * 3
    assert cache.stats()['retained_bytes'] <= cache.max_bytes


def test_default_cache_keeps_twenty_thousand_records_warm_for_complete_audits(monkeypatch):
    records = tuple(record(i) for i in range(20000))
    calls = []
    original = json.loads

    def counted(raw):
        calls.append(raw)
        return original(raw)

    monkeypatch.setattr('neutral_atom_env.replay.trace.json.loads', counted)
    _event_data.activate_history(records)
    first = [_event_data(raw) for raw in records]
    assert len(calls) == len(records)
    retained = _event_data.stats()
    assert retained['records'] == len(records) <= retained['max_records']
    assert retained['max_bytes'] == 3 * 1024 * 1024 * 1024
    assert 0 < retained['retained_bytes'] <= retained['max_bytes']
    calls.clear()
    for _ in range(3):
        _event_data.activate_history(records)
        for i, raw in enumerate(records):
            assert _event_data(raw) is first[i]
            assert first[i]['time_us'] == i
    assert calls == []
    assert _event_data.cache_info().hits == 3 * len(records)
    assert _event_data.cache_info().misses == len(records)
    assert _event_data.stats()['retained_bytes'] == retained['retained_bytes']


def test_byte_limit_keeps_earlier_admissions_and_all_suffixes_are_still_decoded():
    records = tuple(record(i, payload='x' * 1000) for i in range(10))
    cache = TraceEventCache(max_records=100, max_bytes=10000)
    cache.activate_history(records)
    first = [cache.decode(raw) for raw in records]
    retained = cache.cache_info().currsize
    assert 0 < retained < len(records)
    byte_count = cache.stats()['retained_bytes']
    assert 0 < byte_count <= cache.max_bytes
    for raw in records:
        cache.decode(raw)
    assert cache.cache_info().hits == retained
    assert cache.cache_info().misses == 2 * len(records) - retained
    assert cache.stats()['retained_bytes'] == byte_count
    assert cache.decode(records[0]) is first[0]


def test_cache_is_lazy_zero_budget_and_oversized_records_do_not_retain_evidence():
    for kwargs in ({'max_records': 0}, {'max_bytes': 0}, {'max_bytes': 40}):
        cache = TraceEventCache(**kwargs)
        records = (record(0, payload='x' * 100),)
        for _ in range(2):
            cache.activate_history(records)
            assert cache.decode(records[0])['time_us'] == 0
        assert cache.cache_info().hits == cache.cache_info().currsize == 0
        assert cache.stats()['retained_bytes'] <= cache.max_bytes


@pytest.mark.parametrize('kwargs', [dict(max_records=-1), dict(max_bytes=-1),
                                   dict(max_records=True), dict(max_bytes=1.1)])
def test_invalid_cache_budgets_rejected(kwargs):
    with pytest.raises(ValueError):
        TraceEventCache(**kwargs)


def test_history_switch_selects_a_new_working_set_but_edits_are_exact_new_evidence():
    cache = TraceEventCache(max_records=3)
    first = tuple(record(i) for i in range(5))
    second = tuple(record(i + 10) for i in range(5))
    cache.activate_history(first)
    original = [cache.decode(raw) for raw in first]
    cache.activate_history(second)
    assert cache.cache_info().currsize == 0
    for raw in second:
        cache.decode(raw)
    assert cache.cache_info().currsize == 3
    cache.activate_history(second)
    assert cache.decode(second[0])['time_us'] == 10
    edited = (second[0], record(11, payload={'signed': [1, {'value': -1}]}), *second[2:])
    cache.activate_history(edited)
    assert cache.decode(edited[1])['payload']['signed'][1]['value'] == -1
    assert cache.decode(first[0]) == original[0]


def test_only_exact_strings_are_retained_and_nested_evidence_is_immutable():
    class StringSubclass(str):
        pass

    cache = TraceEventCache()
    raw = record(0, nested={'items': [{'x': 1}]})
    immutable = cache.decode(raw)
    assert cache.decode(raw) is immutable
    assert cache.decode(raw.encode()) == immutable
    assert cache.decode(StringSubclass(raw)) == immutable
    assert cache.cache_info().currsize == 1
    assert cache.cache_info().hits == 1 and cache.cache_info().misses == 3
    with pytest.raises(TypeError):
        immutable['nested']['items'][0]['x'] = 2
    assert type(immutable['nested']['items']) is tuple


def test_each_warm_runtime_audit_still_reads_every_record(physical_boundaries, monkeypatch):
    state = physical_boundaries[0]['parallel']
    before = state.snapshot()
    calls = []

    def observed(raw):
        calls.append(raw)
        return _event_data(raw)

    observed.activate_history = _event_data.activate_history
    monkeypatch.setattr(runtime_validation, '_event_data', observed)
    monkeypatch.setattr(operation_program, '_event_data', observed)
    for _ in range(2):
        calls.clear()
        runtime_validation.validate_runtime(state)
        frequencies = Counter(calls)
        assert all(frequencies[raw] >= 2 for raw in state.trace.records)
    assert state.snapshot() == before


@pytest.mark.parametrize('index,field', [(0, 'plan'), (-1, 'time')])
def test_warm_history_tamper_and_checkpoint_restore_fail_closed(physical_boundaries, index, field):
    state = physical_boundaries[0]['parallel']
    before = state.snapshot()
    runtime_validation.validate_runtime(state)
    assert SimulationState.restore(before).snapshot() == before
    records = list(state.trace.records)
    changed = json.loads(records[index])
    if field == 'plan':
        changed['event']['plan']['estimated_duration_us'] += 1
    else:
        changed['event']['time_us'] += .01
    records[index] = canonical_json(changed)
    damaged = replace(state, trace=Trace(tuple(records)))
    with pytest.raises(ValidationError):
        runtime_validation.validate_runtime(damaged)
    with pytest.raises(ValidationError):
        SimulationState.restore(damaged.snapshot())
    assert state.snapshot() == before
    assert SimulationState.restore(before).snapshot() == before
