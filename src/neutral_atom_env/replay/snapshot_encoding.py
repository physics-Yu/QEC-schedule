"""Exact canonical snapshot encoding and bounded exact-preimage hash reuse.

No state/version cache: callers build the current payload on every invocation.
The single active prefix retains at most 1536 MiB (conservative Python object
sizes, including original strings) and 16384 records. Divergent histories trim
the cached suffix. A separate one-entry digest memo compares fresh canonical
nontrace bytes and the complete immutable trace values. Its retained objects
are conservatively charged against a separate 1536 MiB limit. No cache content
or counter enters a checkpoint; schema, encoded bytes and SHA remain unchanged.
"""
from hashlib import sha256
from sys import getsizeof
from threading import RLock
from types import MethodType

from neutral_atom_env.replay.serializer import canonical_json


class TraceEncodingCache:
    def __init__(self, max_bytes=1536 * 1024 * 1024, max_records=16384):
        self.max_bytes = max_bytes
        self.max_records = max_records
        self._entries = []
        self._bytes = 0
        self._hits = self._misses = 0
        self._lock = RLock()

    def clear(self):
        with self._lock:
            self._entries.clear()
            self._bytes = self._hits = self._misses = 0

    def stats(self):
        with self._lock:
            return dict(records=len(self._entries), retained_bytes=self._bytes,
                        max_bytes=self.max_bytes, max_records=self.max_records,
                        hits=self._hits, misses=self._misses)

    def encode(self, records):
        # Exact str excludes objects with caller-defined equality/serialization.
        if type(records) is not tuple or any(type(r) is not str for r in records):
            return (canonical_json(records),)
        with self._lock:
            common = 0
            for original, _, _ in self._entries:
                if common >= len(records) or original != records[common]:
                    break
                common += 1
            for _, _, size in self._entries[common:]:
                self._bytes -= size
            del self._entries[common:]
            self._hits += common
            encoded = [entry[1] for entry in self._entries]
            for record in records[common:]:
                fragment = canonical_json(record)
                self._misses += 1
                # Include entry tuple and a conservative list allocation share.
                size = getsizeof(record) + getsizeof(fragment) + getsizeof((record, fragment, 0)) + 64
                if len(self._entries) == len(encoded) and len(self._entries) < self.max_records and self._bytes + size <= self.max_bytes:
                    self._entries.append((record, fragment, size))
                    self._bytes += size
                encoded.append(fragment)
            return ('[', *interleaved_chunks(encoded), ']')


def interleaved_chunks(values):
    """Interleave separators without joining or escaping history again."""
    for index, value in enumerate(values):
        if index:
            yield ','
        yield value


TRACE_CACHE = TraceEncodingCache()
_DEFAULT_TRACE_ENCODE = TraceEncodingCache.encode


class SnapshotDigestMemo:
    """At most one digest, keyed by its complete exact serialized preimage.

    Callers must freshly serialize every nontrace value before lookup. Raw
    trace strings are immutable and compared in full; no state identity,
    version number or digest authorizes reuse. Referenced strings are charged
    even when another cache or the live state already retains them.
    """
    def __init__(self, max_bytes=1536 * 1024 * 1024):
        if type(max_bytes) is not int or max_bytes < 0:
            raise ValueError('Digest memo byte budget must be a nonnegative integer')
        self.max_bytes = max_bytes
        self._entry = None
        self._bytes = 0
        self._hits = self._misses = self._bypasses = 0
        self._lock = RLock()

    def clear(self):
        with self._lock:
            self._entry = None
            self._bytes = self._hits = self._misses = self._bypasses = 0

    def stats(self):
        with self._lock:
            return dict(entries=int(self._entry is not None), retained_bytes=self._bytes,
                        max_bytes=self.max_bytes, hits=self._hits, misses=self._misses,
                        bypasses=self._bypasses)

    def _get_or_compute(self, fields, records, compute):
        # Includes duplicates and references to conservatively account for all
        # retained Python objects before admitting an entry. No joined trace or
        # encoded whole snapshot is allocated to construct this certificate.
        size = (getsizeof((fields, records, '')) + getsizeof(fields)
                + getsizeof(records) + sum(getsizeof(record) for record in records)
                + getsizeof('0' * 64) + 128)
        size += sum(getsizeof(field) + sum(getsizeof(value) for value in field)
                    for field in fields)
        with self._lock:
            if size > self.max_bytes:
                self._entry, self._bytes = None, 0
                self._bypasses += 1
                return compute()
            if self._entry is not None:
                old_fields, old_records, result = self._entry
                if fields == old_fields and (records is old_records or records == old_records):
                    self._hits += 1
                    return result
            # Do not retain a divergent old prefix during the new computation.
            self._entry, self._bytes = None, 0
            self._misses += 1
            result = compute()
            self._entry, self._bytes = (fields, records, result), size
            return result


DIGEST_MEMO = SnapshotDigestMemo()


def snapshot_chunks(payload, *, cache=TRACE_CACHE):
    # State snapshot keys are exact strings. A defensive fallback preserves the
    # general serializer's key conversion/collision semantics for other callers.
    if any(type(key) is not str for key in payload):
        yield canonical_json(payload)
        return
    yield '{'
    for index, key in enumerate(sorted(payload)):
        if index:
            yield ','
        yield canonical_json(key)
        yield ':'
        if key == 'trace':
            yield from cache.encode(payload[key])
        else:
            yield canonical_json(payload[key])
    yield '}'


def encode_snapshot(payload, *, cache=TRACE_CACHE):
    return ''.join(snapshot_chunks(payload, cache=cache))


def _digest_chunks(chunks):
    digest = sha256()
    for fragment in chunks:
        digest.update(fragment.encode('utf-8'))
    return digest.hexdigest()


def _certificate_chunks(fields, records):
    """Use the same freshly captured nontrace bytes for lookup and hashing."""
    yield '{'
    for index, (key, encoded_key, value) in enumerate(fields):
        if index:
            yield ','
        yield encoded_key
        yield ':'
        if key == 'trace':
            yield from TRACE_CACHE.encode(records)
        else:
            yield value
    yield '}'


def snapshot_digest(payload, *, cache=TRACE_CACHE, memo=DIGEST_MEMO):
    # A caller-defined encoder may change output or have observable side
    # effects, so it always retains the original path. Exact built-in types
    # exclude equality/iteration overrides from the reuse certificate.
    records = payload.get('trace') if type(payload) is dict else None
    encoder = (cache.encode if cache is TRACE_CACHE and type(cache) is TraceEncodingCache
               and TraceEncodingCache.__dict__.get('encode') is _DEFAULT_TRACE_ENCODE else None)
    if (memo is None or type(memo) is not SnapshotDigestMemo or cache is not TRACE_CACHE
            or type(encoder) is not MethodType or encoder.__self__ is not cache
            or encoder.__func__ is not _DEFAULT_TRACE_ENCODE
            or type(payload) is not dict or any(type(key) is not str for key in payload)
            or type(records) is not tuple or any(type(record) is not str for record in records)):
        return _digest_chunks(snapshot_chunks(payload, cache=cache))
    fields = tuple((key, canonical_json(key),
                    None if key == 'trace' else canonical_json(payload[key]))
                   for key in sorted(payload))
    return memo._get_or_compute(fields, records,
                                lambda: _digest_chunks(_certificate_chunks(fields, records)))
