from dataclasses import dataclass
from pathlib import Path
from .serializer import canonical_json


@dataclass(frozen=True)
class Trace:
    records: tuple[str, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, 'records', tuple(self.records))

    def appended(self, record) -> 'Trace':
        return Trace(self.records + (canonical_json(record),))

    def write(self, path):
        Path(path).write_text(''.join(r + '\n' for r in self.records), encoding='utf-8')
