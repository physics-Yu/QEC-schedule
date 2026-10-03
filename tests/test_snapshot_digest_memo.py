"""Exact full-preimage hash reuse, with an independent canonical JSON oracle."""
from hashlib import sha256
from sys import getsizeof
from types import MethodType

import pytest

from neutral_atom_env.replay import snapshot_encoding as encoding
from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_env.replay.snapshot_encoding import SnapshotDigestMemo, TraceEncodingCache
from neutral_atom_env.domain.models import PhysicalGate
from test_quantum_readout import state_for


def oracle(payload):
    return sha256(canonical_json(payload).encode('utf-8')).hexdigest()


def checked(payload, memo):
    expected = oracle(payload)
    assert encoding.snapshot_digest(payload, memo=memo) == expected
    assert encoding.encode_snapshot(payload) == canonical_json(payload)
    return expected


def test_real_snapshot_same_preimage_reuses_digest_without_changing_bytes():
    state = state_for([PhysicalGate('m', 'MEASURE', ('q0',))])
    memo = SnapshotDigestMemo()
    first = checked(state.snapshot_data(), memo)
    assert checked(state.snapshot_data(), memo) == first
    assert memo.stats()['entries'] == 1
    assert memo.stats()['hits'] == 1
    assert memo.stats()['misses'] == 1
    assert state.snapshot() == canonical_json(state.snapshot_data())


def test_unicode_numeric_and_key_order_match_independent_full_snapshot_hash():
    memo = SnapshotDigestMemo()
    trace = ('量子😀\\\"\n\r\t', 'false', '{"trace":["sentinel"]}')
    payload = {'z': -0.0, 'trace': trace, 'a': {'nested': ('é', 1, 1.0, False, None)}}
    first = checked(payload, memo)
    assert checked({'a': payload['a'], 'trace': trace, 'z': -0.0}, memo) == first
    assert memo.stats()['hits'] == 1


def test_same_version_nested_mutation_and_shared_alias_are_not_reused():
    memo = SnapshotDigestMemo()
    alias = {'values': [1]}
    payload = {'trace': ('fixed',), 'version': 17, 'left': alias, 'right': alias}
    first = checked(payload, memo)
    assert checked(payload, memo) == first
    alias['values'].append(2)
    second = checked(payload, memo)
    assert second != first
    assert payload['version'] == 17
    alias['values'][0] = {'nested': ['changed']}
    assert checked(payload, memo) != second
    assert memo.stats()['misses'] == 3
    assert memo.stats()['hits'] == 1


def test_added_removed_and_modified_nontrace_fields_invalidate_certificate():
    memo = SnapshotDigestMemo()
    payload = {'trace': ('fixed',), 'version': 3, 'world': {'geometry': [0, 1]}}
    before = checked(payload, memo)
    payload['extra'] = None
    assert checked(payload, memo) != before
    del payload['extra']
    assert checked(payload, memo) == before
    payload['world']['geometry'][1] = 2
    assert checked(payload, memo) != before
    assert memo.stats()['misses'] == 4


def test_complete_history_comparison_detects_first_last_and_middle_edits():
    memo = SnapshotDigestMemo()
    original = ('first', 'middle', 'last')
    payload = {'trace': original, 'version': 3}
    first = checked(payload, memo)
    for trace in (('edited', *original[1:]), (*original[:-1], 'edited'),
                  ('first', 'edited', 'last'), original + ('next',), original[:1], original):
        payload['trace'] = trace
        result = checked(payload, memo)
        assert (result == first) == (trace == original)
    # A distinct tuple with the same complete values is also a valid preimage.
    payload['trace'] = tuple(list(original))
    assert payload['trace'] is not original
    assert checked(payload, memo) == first
    assert memo.stats()['hits'] == 1
    assert memo.stats()['entries'] == 1


def test_divergent_histories_replace_the_single_entry_and_clear_resets_it():
    memo = SnapshotDigestMemo()
    for trace in (('a', 'b'), ('a', 'c'), (), ('different',), ('a', 'b')):
        checked({'trace': trace, 'value': 0}, memo)
        assert memo.stats()['entries'] == 1
    assert memo.stats()['misses'] == 5
    memo.clear()
    assert memo.stats() == dict(entries=0, retained_bytes=0, max_bytes=memo.max_bytes,
                               hits=0, misses=0, bypasses=0)


@pytest.mark.parametrize('budget', [0, 1, 600])
def test_over_budget_preserves_original_hash_and_retains_no_trace(budget):
    memo = SnapshotDigestMemo(max_bytes=budget)
    payload = {'trace': ('large' * 1000,), 'nested': [1, 2]}
    checked(payload, memo)
    checked(payload, memo)
    assert memo.stats()['entries'] == memo.stats()['retained_bytes'] == 0
    assert memo.stats()['bypasses'] == 2
    assert memo.stats()['hits'] == 0


def test_conservative_exact_byte_boundary_and_large_miss_drop_old_entry():
    payload = {'trace': ('a', 'b'), 'value': {'mutable': [1]}}
    probe = SnapshotDigestMemo()
    checked(payload, probe)
    charged = probe.stats()['retained_bytes']
    assert charged > getsizeof(payload['trace']) + sum(getsizeof(r) for r in payload['trace'])
    fits = SnapshotDigestMemo(max_bytes=charged)
    checked(payload, fits)
    checked(payload, fits)
    assert fits.stats()['retained_bytes'] == charged
    assert fits.stats()['hits'] == 1
    cannot_fit = SnapshotDigestMemo(max_bytes=charged - 1)
    checked(payload, cannot_fit)
    assert cannot_fit.stats()['entries'] == 0
    payload['trace'] = ('large' * 10000,)
    checked(payload, fits)
    assert fits.stats()['entries'] == fits.stats()['retained_bytes'] == 0


@pytest.mark.parametrize('budget', [-1, True, 1.5])
def test_invalid_byte_budget_is_rejected(budget):
    with pytest.raises(ValueError, match='nonnegative integer'):
        SnapshotDigestMemo(max_bytes=budget)


def test_trace_and_key_subclasses_and_mutable_trace_take_original_path():
    class String(str):
        pass
    class Tuple(tuple):
        def __eq__(self, other):
            return True
    class Dictionary(dict):
        pass
    for payload in ({'trace': (String('different'),), 'value': 0},
                    {'trace': Tuple(('a', 'b')), 'value': 0},
                    {String('trace'): ('a',), 'value': 0},
                    {'trace': ['a'], 'value': 0},
                    {1: 'nonstring key', 'trace': ('a',)},
                    {1: 'first', '1': 'collision', 'trace': ('a',)},
                    {'value': 0}, Dictionary(trace=('a',), value=0)):
        memo = SnapshotDigestMemo()
        checked(payload, memo)
        checked(payload, memo)
        assert memo.stats()['entries'] == memo.stats()['hits'] == memo.stats()['misses'] == 0


def test_custom_encoding_cache_is_called_every_time_without_reuse():
    class Encoder:
        def __init__(self):
            self.calls = 0
        def encode(self, records):
            self.calls += 1
            return (f'[{self.calls}]',)
    memo = SnapshotDigestMemo()
    cache = Encoder()
    payload = {'other': 1, 'trace': ('unchanged',)}
    for call in (1, 2, 3):
        expected = sha256(f'{{"other":1,"trace":[{call}]}}'.encode()).hexdigest()
        assert encoding.snapshot_digest(payload, cache=cache, memo=memo) == expected
    assert cache.calls == 3
    assert memo.stats()['entries'] == memo.stats()['hits'] == 0
    # Even a normal caller-owned encoding cache uses its original path.
    cache = TraceEncodingCache()
    assert encoding.snapshot_digest(payload, cache=cache, memo=memo) == oracle(payload)
    assert memo.stats()['entries'] == 0


def test_overridden_default_encoder_cannot_return_a_previous_cached_digest(monkeypatch):
    memo = SnapshotDigestMemo()
    payload = {'trace': ('original',), 'other': 1}
    checked(payload, memo)
    monkeypatch.setattr(encoding.TRACE_CACHE, 'encode', lambda records: ('["custom"]',))
    expected = sha256(b'{"other":1,"trace":["custom"]}').hexdigest()
    assert encoding.snapshot_digest(payload, memo=memo) == expected
    assert memo.stats()['hits'] == 0


@pytest.mark.parametrize('warm', [False, True])
def test_callable_spoofing_default_encoder_func_always_uses_custom_path(monkeypatch, warm):
    memo = SnapshotDigestMemo()
    payload = {'trace': ('original',), 'other': 1}
    if warm:
        checked(payload, memo)
    def custom(records):
        return ('["custom"]',)
    custom.__func__ = encoding._DEFAULT_TRACE_ENCODE
    custom.__self__ = encoding.TRACE_CACHE
    monkeypatch.setattr(encoding.TRACE_CACHE, 'encode', custom)
    expected = sha256(b'{"other":1,"trace":["custom"]}').hexdigest()
    assert encoding.snapshot_digest(payload, memo=memo) == expected
    assert memo.stats()['hits'] == 0
    assert memo.stats()['misses'] == int(warm)


def test_method_bound_to_different_encoder_cannot_use_default_memo(monkeypatch):
    memo = SnapshotDigestMemo()
    payload = {'trace': ('original',), 'other': 1}
    checked(payload, memo)
    other = TraceEncodingCache()
    monkeypatch.setattr(encoding.TRACE_CACHE, 'encode', MethodType(encoding._DEFAULT_TRACE_ENCODE, other))
    assert encoding.snapshot_digest(payload, memo=memo) == oracle(payload)
    assert memo.stats()['hits'] == 0
    assert other.stats()['misses'] == 1


def test_every_nontrace_value_is_freshly_serialized_even_when_digest_is_reused(monkeypatch):
    memo = SnapshotDigestMemo()
    value = {'values': [1]}
    payload = {'trace': ('fixed',), 'value': value}
    native = encoding.canonical_json
    reads = []
    def observed(item):
        if item is value:
            reads.append(tuple(value['values']))
        return native(item)
    monkeypatch.setattr(encoding, 'canonical_json', observed)
    assert encoding.snapshot_digest(payload, memo=memo) == oracle(payload)
    assert encoding.snapshot_digest(payload, memo=memo) == oracle(payload)
    assert reads == [(1,), (1,)]
    value['values'].append(2)
    assert encoding.snapshot_digest(payload, memo=memo) == oracle(payload)
    assert reads == [(1,), (1,), (1, 2)]
    assert memo.stats()['hits'] == 1
    assert memo.stats()['misses'] == 2


def test_explicitly_disabled_memo_and_utf8_failure_match_reference():
    payload = {'trace': ('same',), 'nested': {'a': [1]}}
    assert encoding.snapshot_digest(payload, memo=None) == oracle(payload)
    payload['nested']['a'].append(2)
    assert encoding.snapshot_digest(payload, memo=None) == oracle(payload)
    surrogate = {'trace': ('\ud800',)}
    memo = SnapshotDigestMemo()
    assert encoding.encode_snapshot(surrogate) == canonical_json(surrogate)
    with pytest.raises(UnicodeEncodeError):
        oracle(surrogate)
    with pytest.raises(UnicodeEncodeError):
        encoding.snapshot_digest(surrogate, memo=memo)
    assert memo.stats()['entries'] == 0
