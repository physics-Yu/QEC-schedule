from dataclasses import dataclass
from types import MappingProxyType
from math import isfinite
from collections.abc import Mapping
from neutral_atom_env.domain.models import HolderType, Position2D, MobileCellIndex, Rectangle, StaticTrap, Zone, ZoneType, HolderRef, Atom
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.aod import AODConfiguration


@dataclass(frozen=True)
class AODRuntimeState:
    is_moving: bool = False
    pose: Position2D = Position2D(0, 0)
    rows: int = 2
    columns: int = 2
    spacing_um: float = 5.0
    column_offsets_um: tuple[float, ...] | None = None
    row_offsets_um: tuple[float, ...] | None = None

    def __post_init__(self):
        if type(self.rows) is not int or type(self.columns) is not int or self.rows < 1 or self.columns < 1 or not isfinite(self.spacing_um) or self.spacing_um <= 0:
            raise ValidationError('INVALID_AOD', 'Invalid AOD geometry')
        for name, count in (('column_offsets_um', self.columns), ('row_offsets_um', self.rows)):
            values = getattr(self, name)
            if values is not None:
                values = tuple(values)
                object.__setattr__(self, name, values)
                if len(values) != count or values[0] != 0:
                    raise ValidationError('INVALID_AOD_AXES', 'Offsets must match axis counts and start at zero')
        self.configuration()

    def configuration(self):
        xs = self.column_offsets_um if self.column_offsets_um is not None else tuple(i*self.spacing_um for i in range(self.columns))
        ys = self.row_offsets_um if self.row_offsets_um is not None else tuple(i*self.spacing_um for i in range(self.rows))
        return AODConfiguration(tuple(self.pose.x_um+x for x in xs), tuple(self.pose.y_um+y for y in ys))

    def configured(self, configuration):
        from dataclasses import replace
        if len(configuration.x_um) != self.columns or len(configuration.y_um) != self.rows:
            raise ValidationError('AOD_AXIS_COUNT', 'Changing active row/column counts during a move is unsupported')
        x, y = configuration.x_um[0], configuration.y_um[0]
        # Canonicalize uniform axes so a round trip recovers the original state exactly.
        xs, ys = tuple(v-x for v in configuration.x_um), tuple(v-y for v in configuration.y_um)
        return replace(self, pose=Position2D(x,y),
            column_offsets_um=None if xs==tuple(i*self.spacing_um for i in range(self.columns)) else xs,
            row_offsets_um=None if ys==tuple(i*self.spacing_um for i in range(self.rows)) else ys)

    def position(self, cell):
        if not isinstance(cell, MobileCellIndex) or cell.row >= self.rows or cell.column >= self.columns:
            raise ValidationError('UNKNOWN_MOBILE_CELL', 'Unknown AOD cell', holder_id=cell)
        return self.configuration().position(cell)


@dataclass(frozen=True)
class WorldState:
    bounds: Rectangle
    traps: Mapping[str, StaticTrap]
    zones: tuple[Zone, ...] = ()
    grid_spacing_um: float = 5.0
    grid_origin: Position2D = Position2D(0, 0)
    static_zone_types: tuple[ZoneType, ...] = tuple(ZoneType)

    def __post_init__(self):
        object.__setattr__(self, "traps", MappingProxyType(dict(self.traps)))
        object.__setattr__(self, "zones", tuple(self.zones))
        object.__setattr__(self, 'static_zone_types', tuple(self.static_zone_types))
        if not isfinite(self.grid_spacing_um) or self.grid_spacing_um <= 0:
            raise ValidationError('INVALID_GRID', 'Grid spacing must be finite and positive')
        if len({t.position for t in self.traps.values()}) != len(self.traps):
            raise ValidationError('DUPLICATE_TRAP_POSITION', 'Duplicate trap position')
        for key, trap in self.traps.items():
            if key != trap.id or not self.bounds.contains(trap.position):
                raise ValidationError('INVALID_TRAP', 'Invalid trap identity or position', holder_id=key, position=trap.position)
            if not self.is_candidate_site(trap.position):
                raise ValidationError('INVALID_STATIC_SITE', 'Trap must lie on grid in an allowed zone', holder_id=key, position=trap.position)
        if len({z.id for z in self.zones}) != len(self.zones):
            raise ValidationError('DUPLICATE_ZONE', 'Duplicate zone')
        for zone in self.zones:
            if not self.bounds.contains(zone.bounds.lower) or not self.bounds.contains(zone.bounds.upper):
                raise ValidationError('ZONE_OUTSIDE_WORLD', 'Zone outside world', holder_id=zone.id)
        for i, left in enumerate(self.zones):
            for right in self.zones[i+1:]:
                if (max(left.bounds.lower.x_um,right.bounds.lower.x_um) < min(left.bounds.upper.x_um,right.bounds.upper.x_um)
                    and max(left.bounds.lower.y_um,right.bounds.lower.y_um) < min(left.bounds.upper.y_um,right.bounds.upper.y_um)):
                    raise ValidationError('OVERLAPPING_ZONES', f'Zones {left.id} and {right.id} overlap')

    def is_candidate_site(self, position: Position2D) -> bool:
        coordinates = ((position.x_um-self.grid_origin.x_um)/self.grid_spacing_um,
                       (position.y_um-self.grid_origin.y_um)/self.grid_spacing_um)
        return (self.bounds.contains(position) and all(abs(v-round(v)) < 1e-9 for v in coordinates)
                and any(z.zone_type in self.static_zone_types and z.bounds.contains(position) for z in self.zones))


@dataclass(frozen=True)
class PlacementState:
    atom_to_holder: Mapping[str, HolderRef]

    def __post_init__(self):
        object.__setattr__(self, "atom_to_holder", MappingProxyType(dict(self.atom_to_holder)))

    @property
    def static_occupancy(self):
        return MappingProxyType({h.holder_id: a for a, h in self.atom_to_holder.items() if h.holder_type == HolderType.STATIC})

    @property
    def mobile_occupancy(self):
        return MappingProxyType({h.holder_id: a for a, h in self.atom_to_holder.items() if h.holder_type == HolderType.MOBILE})

    def position(self, atom_id, world, aod):
        h = self.atom_to_holder[atom_id]
        if h.holder_type == HolderType.STATIC:
            return world.traps[h.holder_id].position
        if h.holder_type == HolderType.MOBILE:
            return aod.position(h.holder_id)
        return None

    def validate(self, atoms: Mapping[str, Atom], world: WorldState, aod: AODRuntimeState):
        if set(atoms) != set(self.atom_to_holder):
            raise ValidationError('HOLDER_SET_MISMATCH', 'Every atom must have exactly one holder entry', atom_ids=sorted(set(atoms)^set(self.atom_to_holder)))
        occupied = {}
        for atom_id, holder in self.atom_to_holder.items():
            atom = atoms[atom_id]
            if not isinstance(holder.holder_type, HolderType):
                raise ValidationError('UNKNOWN_HOLDER_TYPE', 'Unknown holder type', atom_ids=(atom_id,))
            if holder.holder_type == HolderType.LOST:
                if atom.alive or holder.holder_id is not None:
                    raise ValidationError('INVALID_LOST_ATOM', 'Lost atom cannot be alive or occupy a holder', atom_ids=(atom_id,))
                continue
            if not atom.alive:
                raise ValidationError('DEAD_ATOM_OCCUPIED', 'Dead atom has a holder', atom_ids=(atom_id,), holder_id=holder.holder_id)
            if holder in occupied:
                raise ValidationError('DUPLICATE_HOLDER', 'Duplicate holder occupancy', atom_ids=(occupied[holder], atom_id), holder_id=holder.holder_id, position=self.position(atom_id, world, aod))
            occupied[holder] = atom_id
            if holder.holder_type == HolderType.STATIC:
                if holder.holder_id not in world.traps or not world.traps[holder.holder_id].enabled:
                    raise ValidationError('UNAVAILABLE_STATIC_TRAP', 'Unknown or disabled static trap', atom_ids=(atom_id,), holder_id=holder.holder_id,
                        position=world.traps[holder.holder_id].position if holder.holder_id in world.traps else None)
            try:
                position = self.position(atom_id, world, aod)
            except ValidationError as error:
                raise ValidationError(error.violation.code, error.violation.message, atom_ids=(atom_id,), holder_id=holder.holder_id) from error
            if not world.bounds.contains(position):
                raise ValidationError('ATOM_OUTSIDE_WORLD', 'Atom outside world', atom_ids=(atom_id,), holder_id=holder.holder_id, position=position)
