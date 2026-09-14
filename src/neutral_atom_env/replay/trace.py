from dataclasses import dataclass
from pathlib import Path
from neutral_atom_env.replay.serializer import canonical_json
from functools import lru_cache
from types import MappingProxyType
import json


# Bounded four-patch policy: its trace can exceed the former 4096/8192-entry limits.
# Sequential full-history audits must fit to avoid cyclic LRU thrashing. This
# remains an entry bound, not a universal byte-bounded history-cache solution.
@lru_cache(maxsize=16384)
def _event_data(record):
    """Decode exact trace bytes once; callers cannot mutate cached evidence."""
    def freeze(value):
        if isinstance(value, dict):
            return MappingProxyType({k: freeze(v) for k, v in value.items()})
        if isinstance(value, list):
            return tuple(freeze(v) for v in value)
        return value
    return freeze(json.loads(record)['event'])


@dataclass(frozen=True)
class Trace:
    records: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, 'records', tuple(self.records))

    def appended(self, record) -> 'Trace':
        return Trace(self.records + (canonical_json(record),))

    def write(self, path):
        Path(path).write_text(''.join(r + '\n' for r in self.records), encoding='utf-8')
