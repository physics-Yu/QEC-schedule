"""Regression for exact immutable event caching past the former 4096 and 8192 cliffs."""
import json
import pytest

from neutral_atom_env.replay.trace import _event_data
from neutral_atom_env.replay.snapshot_encoding import TraceEncodingCache


@pytest.fixture(autouse=True)
def clean_event_cache():
    _event_data.cache_clear()
    yield
    _event_data.cache_clear()


@pytest.mark.parametrize("count", [4097, 8193])
def test_distinct_records_survive_repeated_full_sequential_scans(count):
    records = tuple(json.dumps({'event': {'event_type': 'wait_completed', 'time_us': i}, 'sequence': i})
                    for i in range(count))
    for i, raw in enumerate(records):
        assert _event_data(raw)['time_us'] == i
    cold = _event_data.cache_info()
    assert cold.maxsize == 16384 and cold.currsize == cold.misses == count and cold.hits == 0
    for _ in range(3):
        for i, raw in enumerate(records):
            assert _event_data(raw)['time_us'] == i
    warm = _event_data.cache_info()
    assert warm.misses == count and warm.hits == 3 * count


def test_cached_event_is_deeply_immutable_and_raw_record_is_exact_key():
    event = {'event_type': 'plan_started', 'plan': {'intent': {'task_id': '閲忓瓙'}, 'items': [{'x': 1}]}}
    first = json.dumps({'event': event, 'audit': 1}, ensure_ascii=False)
    changed_audit = json.dumps({'event': event, 'audit': 2}, ensure_ascii=False)
    changed_encoding = json.dumps({'event': event, 'audit': 1}, ensure_ascii=True)
    a = _event_data(first)
    assert _event_data(first) is a
    b, c = _event_data(changed_audit), _event_data(changed_encoding)
    assert a == b == c and a is not b and a is not c
    assert _event_data.cache_info().misses == 3
    with pytest.raises(TypeError):
        a['plan']['intent']['task_id'] = 'mutated'
    with pytest.raises(TypeError):
        a['plan']['items'][0]['x'] = 2
    assert isinstance(a['plan']['items'], tuple)
    assert _event_data(first)['plan']['items'][0]['x'] == 1


def test_larger_encoding_budget_is_lazy_and_can_still_be_explicitly_lowered():
    cache = TraceEncodingCache()
    assert cache.stats()['max_bytes'] == 1536 * 1024 * 1024
    assert cache.stats()['retained_bytes'] == cache.stats()['records'] == 0
    limited = TraceEncodingCache(max_bytes=0)
    assert ''.join(limited.encode(('test',))) == '["test"]'
    assert limited.stats()['retained_bytes'] == limited.stats()['records'] == 0
