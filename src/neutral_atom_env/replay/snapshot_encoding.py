"""Exact canonical snapshot encoding; only immutable trace strings are cached.

No state/version cache: callers build the current payload on every invocation.
The single active prefix retains at most 1536 MiB (conservative Python object
sizes, including original strings) and 16384 records. Divergent histories trim
the cached suffix. Neither cache contents nor counters enter a checkpoint.
"""
from hashlib import sha256
from sys import getsizeof
from threading import RLock

from .serializer import canonical_json


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


def snapshot_digest(payload, *, cache=TRACE_CACHE):
    digest = sha256()
    for fragment in snapshot_chunks(payload, cache=cache):
        digest.update(fragment.encode('utf-8'))
    return digest.hexdigest()
