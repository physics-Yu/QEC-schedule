from dataclasses import dataclass
from pathlib import Path
from neutral_atom_env.replay.serializer import canonical_json
from collections import namedtuple
from sys import getsizeof
from threading import RLock
from types import MappingProxyType
import json


_CacheInfo = namedtuple('CacheInfo', 'hits misses maxsize currsize')


def _freeze_event(value):
    """Return recursively immutable evidence and a conservative retained size."""
    if isinstance(value, dict):
        frozen, size = {}, 0
        for key, child in value.items():
            item, retained = _freeze_event(child)
            frozen[key] = item
            size += getsizeof(key) + retained
        proxy = MappingProxyType(frozen)
        return proxy, size + getsizeof(frozen) + getsizeof(proxy)
    if isinstance(value, list):
        items = tuple(_freeze_event(child) for child in value)
        frozen = tuple(item for item, _ in items)
        return frozen, getsizeof(frozen) + sum(size for _, size in items)
    return value, getsizeof(value)


class TraceEventCache:
    """Byte/entry-bounded immutable decode cache with stable prefix admission.

    A miss never evicts a previously admitted entry. A sequential audit whose
    history exceeds the budget therefore reparses only the uncached suffix,
    instead of cyclically evicting and reparsing every record as an LRU does.
    Switching the exact first record starts a new working history. Cache hits
    authorize only decoding that exact string, never acceptance of a state.
    """
    def __init__(self, max_records=32768, max_bytes=3 * 1024 * 1024 * 1024):
        if type(max_records) is not int or max_records < 0 or type(max_bytes) is not int or max_bytes < 0:
            raise ValueError('Trace cache budgets must be nonnegative integers')
        self.max_records, self.max_bytes = max_records, max_bytes
        self._entries = {}
        self._retained_bytes = self._hits = self._misses = 0
        self._history_anchor = None
        self._lock = RLock()

    def activate_history(self, records):
        # Cache selection only. Every runtime call still traverses/compares all
        # records and all state evidence, including changed historical entries.
        if type(records) is not tuple or (records and type(records[0]) is not str):
            return
        anchor = records[0] if records else None
        with self._lock:
            if anchor != self._history_anchor:
                self._entries.clear()
                self._retained_bytes = 0
                # The anchor is retained only when it individually fits. Its
                # bytes are charged even if it is also an admitted exact key.
                self._history_anchor = anchor if self.max_records and (anchor is None or getsizeof(anchor) <= self.max_bytes) else None
                self._retained_bytes = getsizeof(anchor) if self._history_anchor is not None else 0

    def decode(self, record):
        with self._lock:
            if type(record) is str and record in self._entries:
                self._hits += 1
                return self._entries[record]
            self._misses += 1
            decoded, size = _freeze_event(json.loads(record)['event'])
            # Exact immutable string keys only; string subclasses and
            # accepted JSON bytes use the normal decode path without retention.
            size += getsizeof(record) + 256  # dict slot/value reference allowance
            if (type(record) is str and len(self._entries) < self.max_records and
                    self._retained_bytes + size <= self.max_bytes):
                self._entries[record] = decoded
                self._retained_bytes += size
            return decoded

    def cache_clear(self):
        with self._lock:
            self._entries.clear()
            self._history_anchor = None
            self._retained_bytes = self._hits = self._misses = 0

    def cache_info(self):
        with self._lock:
            return _CacheInfo(self._hits, self._misses, self.max_records, len(self._entries))

    def stats(self):
        with self._lock:
            return {'records': len(self._entries), 'retained_bytes': self._retained_bytes,
                    'max_records': self.max_records, 'max_bytes': self.max_bytes,
                    'hits': self._hits, 'misses': self._misses}


_EVENT_CACHE = TraceEventCache()


def _event_data(record):
    """Decode exact trace bytes once; callers cannot mutate cached evidence."""
    return _EVENT_CACHE.decode(record)


_event_data.cache_clear = _EVENT_CACHE.cache_clear
_event_data.cache_info = _EVENT_CACHE.cache_info
_event_data.activate_history = _EVENT_CACHE.activate_history
_event_data.stats = _EVENT_CACHE.stats


@dataclass(frozen=True)
class Trace:
    records: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, 'records', tuple(self.records))

    def appended(self, record) -> 'Trace':
        return Trace(self.records + (canonical_json(record),))

    def write(self, path):
        Path(path).write_text(''.join(r + '\n' for r in self.records), encoding='utf-8')
