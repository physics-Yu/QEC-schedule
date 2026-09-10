"""Single layout definition shared by state creation and scene rendering."""
from dataclasses import dataclass
import json
from pathlib import Path
from math import isfinite
from neutral_atom_env.domain.models import Position2D, GridCoord, Rectangle, Zone, ZoneType, StaticTrap
from neutral_atom_env.domain.errors import ValidationError
from .world import WorldState


@dataclass(frozen=True)
class LayoutConfig:
    columns: int = 21
    rows: int = 3
    spacing_um: float = 5
    zone_height_um: float = 20
    isolation_gap_um: float = 20
    disabled_traps: tuple[int, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, 'disabled_traps', tuple(self.disabled_traps))
        if (type(self.columns) is not int or type(self.rows) is not int or min(self.columns,self.rows) < 1 or
            any(not isfinite(v) or v <= 0 for v in (self.spacing_um,self.zone_height_um,self.isolation_gap_um)) or
            (self.rows-1)*self.spacing_um > self.zone_height_um or
            len(set(self.disabled_traps)) != len(self.disabled_traps) or
            any(type(i) is not int or i < 0 or i >= self.columns*self.rows for i in self.disabled_traps)):
            raise ValidationError('INVALID_LAYOUT_CONFIG', 'Invalid lattice dimensions, isolation gap or disabled trap IDs')

    @classmethod
    def load(cls, path):
        return cls(**json.loads(Path(path).read_text(encoding='utf-8')))

    def build(self) -> WorldState:
        s = self.spacing_um
        width = (self.columns+1)*s
        stride = self.zone_height_um+self.isolation_gap_um
        zones = tuple(Zone(kind.value, kind, Rectangle(Position2D(-s,-self.zone_height_um-i*stride),
                            Position2D(width, -i*stride))) for i,kind in enumerate(ZoneType))
        traps = {f'S{i:03d}': StaticTrap(f'S{i:03d}', GridCoord(i % self.columns, -(i // self.columns)),
                    Position2D((i % self.columns)*s, -(i // self.columns)*s), i not in self.disabled_traps)
                 for i in range(self.columns*self.rows)}
        return WorldState(Rectangle(Position2D(-2*s,-2*stride-self.zone_height_um-s), Position2D(width+s,s)),
                          traps,zones,s)
