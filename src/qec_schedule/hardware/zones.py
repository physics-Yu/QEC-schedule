"""Hardware zones and their geometric capabilities.

Storage and reservoir zones keep discrete trap sites.  Entangling and
measurement zones additionally expose dynamic working geometry; their legacy
``pair_slots``/``sites`` fields are retained only for migration compatibility.
"""
from dataclasses import dataclass
from enum import Enum

from .geometry import Bounds, Position, finite_number


class ZoneKind(str, Enum):
    STORAGE = "STORAGE"
    ENTANGLING = "ENTANGLING"
    MEASUREMENT = "MEASUREMENT"
    RESERVOIR = "RESERVOIR"


class HardwareOperation(str, Enum):
    PREPARE = "PREPARE"
    RESET = "RESET"
    LOCAL_1Q = "LOCAL_1Q"
    ENTANGLE = "ENTANGLE"
    MEASURE = "MEASURE"
    REFILL = "REFILL"


@dataclass(frozen=True)
class TrapSite:
    id: str
    position: Position

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("Trap site needs a nonempty ID")


@dataclass(frozen=True)
class PairSlot:
    id: str
    sites: tuple[str, str]

    def __post_init__(self):
        object.__setattr__(self, "sites", tuple(self.sites))
        if not isinstance(self.id, str) or not self.id.strip() or len(self.sites) != 2 or len(set(self.sites)) != 2:
            raise ValueError("Pair slot needs an ID and two distinct site IDs")


def _optional_positive_int(value, name: str):
    if value is not None and (type(value) is not int or value <= 0):
        raise ValueError(f"{name} must be a positive integer or None")


def _contains_bounds(outer: Bounds, inner: Bounds) -> bool:
    return (outer.xmin <= inner.xmin <= inner.xmax <= outer.xmax
            and outer.ymin <= inner.ymin <= inner.ymax <= outer.ymax)


@dataclass(frozen=True)
class EntanglingGeometry:
    """Dynamic placement capability for an entangling working region."""

    bounds: Bounds
    interaction_lanes: tuple[float, ...] | None = None
    preferred_axis: str = "x"
    pair_distance: float = 1.0
    pair_distance_tolerance: float = 0.0
    inter_pair_guard_distance: float = 0.0
    min_atom_spacing: float = 1.0
    max_parallel_pairs: int | None = None
    max_atoms: int | None = None

    def __post_init__(self):
        if not isinstance(self.bounds, Bounds):
            raise ValueError("Entangling bounds must be Bounds")
        if self.preferred_axis not in ("x", "y"):
            raise ValueError("preferred_axis must be x or y")
        lanes = None if self.interaction_lanes is None else tuple(self.interaction_lanes)
        if lanes is not None:
            if not lanes:
                raise ValueError("interaction_lanes cannot be empty")
            for lane in lanes:
                lane = finite_number(lane, "interaction lane")
                low, high = ((self.bounds.ymin, self.bounds.ymax)
                             if self.preferred_axis == "x"
                             else (self.bounds.xmin, self.bounds.xmax))
                if not low <= lane <= high:
                    raise ValueError("Interaction lane must be inside entangling bounds")
        object.__setattr__(self, "interaction_lanes", lanes)
        pair_distance = finite_number(self.pair_distance, "pair_distance")
        tolerance = finite_number(self.pair_distance_tolerance, "pair_distance_tolerance")
        guard = finite_number(self.inter_pair_guard_distance, "inter_pair_guard_distance")
        spacing = finite_number(self.min_atom_spacing, "min_atom_spacing")
        if pair_distance <= 0 or tolerance < 0 or guard < 0 or spacing <= 0:
            raise ValueError("Invalid entangling distance constraint")
        if pair_distance - tolerance <= 0:
            raise ValueError("pair_distance_tolerance is too large")
        object.__setattr__(self, "pair_distance", pair_distance)
        object.__setattr__(self, "pair_distance_tolerance", tolerance)
        object.__setattr__(self, "inter_pair_guard_distance", guard)
        object.__setattr__(self, "min_atom_spacing", spacing)
        _optional_positive_int(self.max_parallel_pairs, "max_parallel_pairs")
        _optional_positive_int(self.max_atoms, "max_atoms")
        if self.max_parallel_pairs is not None and self.max_atoms is not None and 2 * self.max_parallel_pairs > self.max_atoms:
            raise ValueError("max_parallel_pairs exceeds max_atoms")

    def to_dict(self):
        return {
            "bounds": self.bounds.to_list(),
            "interaction_lanes": None if self.interaction_lanes is None else list(self.interaction_lanes),
            "preferred_axis": self.preferred_axis,
            "pair_distance": self.pair_distance,
            "pair_distance_tolerance": self.pair_distance_tolerance,
            "inter_pair_guard_distance": self.inter_pair_guard_distance,
            "min_atom_spacing": self.min_atom_spacing,
            "max_parallel_pairs": self.max_parallel_pairs,
            "max_atoms": self.max_atoms,
        }


@dataclass(frozen=True)
class MeasurementGeometry:
    """Dynamic placement and field-of-view capability for imaging."""

    bounds: Bounds
    imaging_bounds: Bounds
    min_atom_spacing: float = 1.0
    max_parallel_atoms: int | None = None
    field_of_view: Bounds | None = None

    def __post_init__(self):
        if not isinstance(self.bounds, Bounds) or not isinstance(self.imaging_bounds, Bounds):
            raise ValueError("Measurement geometry bounds must be Bounds")
        if not _contains_bounds(self.bounds, self.imaging_bounds):
            raise ValueError("imaging_bounds must be inside measurement bounds")
        field = self.imaging_bounds if self.field_of_view is None else self.field_of_view
        if not isinstance(field, Bounds) or not _contains_bounds(self.bounds, field):
            raise ValueError("field_of_view must be inside measurement bounds")
        spacing = finite_number(self.min_atom_spacing, "min_atom_spacing")
        if spacing <= 0:
            raise ValueError("Measurement minimum atom spacing must be positive")
        object.__setattr__(self, "min_atom_spacing", spacing)
        object.__setattr__(self, "field_of_view", field)
        _optional_positive_int(self.max_parallel_atoms, "max_parallel_atoms")

    def to_dict(self):
        return {
            "bounds": self.bounds.to_list(),
            "imaging_bounds": self.imaging_bounds.to_list(),
            "min_atom_spacing": self.min_atom_spacing,
            "max_parallel_atoms": self.max_parallel_atoms,
            "field_of_view": self.field_of_view.to_list(),
        }


@dataclass(frozen=True)
class Zone:
    id: str
    kind: ZoneKind
    bounds: Bounds
    capacity: int  # Number of atoms, NOT number of entangling pairs.
    allowed_operations: frozenset[HardwareOperation]
    sites: tuple[TrapSite, ...]
    pair_slots: tuple[PairSlot, ...] = ()
    entangling_geometry: EntanglingGeometry | None = None
    measurement_geometry: MeasurementGeometry | None = None

    def __post_init__(self):
        object.__setattr__(self, "kind", ZoneKind(self.kind))
        object.__setattr__(self, "allowed_operations", frozenset(HardwareOperation(op) for op in self.allowed_operations))
        object.__setattr__(self, "sites", tuple(self.sites))
        object.__setattr__(self, "pair_slots", tuple(self.pair_slots))
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("Zone ID must be nonempty")
        if type(self.capacity) is not int or self.capacity < 0:
            raise ValueError("Zone capacity must be a nonnegative integer")
        if self.kind in (ZoneKind.STORAGE, ZoneKind.RESERVOIR) and self.capacity > len(self.sites):
            raise ValueError("Storage/reservoir capacity cannot exceed the number of sites")
        site_ids = {site.id for site in self.sites}
        if len(site_ids) != len(self.sites) or len({s.position for s in self.sites}) != len(self.sites):
            raise ValueError("Zone trap IDs and positions must be unique")
        if any(not self.bounds.contains(site.position) for site in self.sites):
            raise ValueError(f"Trap site outside zone {self.id}")
        if len({pair.id for pair in self.pair_slots}) != len(self.pair_slots):
            raise ValueError("Duplicate pair-slot ID")
        used = set()
        for pair in self.pair_slots:
            if not set(pair.sites) <= site_ids or used & set(pair.sites):
                raise ValueError("Pair slots must reference disjoint, known trap sites")
            used.update(pair.sites)
        if self.pair_slots and self.kind != ZoneKind.ENTANGLING:
            raise ValueError("Pair slots only belong in entangling zones")
        if self.kind == ZoneKind.ENTANGLING:
            geometry = self.entangling_geometry
            if geometry is None:
                geometry = EntanglingGeometry(
                    self.bounds,
                    max_parallel_pairs=(self.capacity // 2 or None),
                    max_atoms=(self.capacity or None),
                )
            if not isinstance(geometry, EntanglingGeometry) or geometry.bounds != self.bounds:
                raise ValueError("Entangling zones require matching EntanglingGeometry")
            object.__setattr__(self, "entangling_geometry", geometry)
            if self.measurement_geometry is not None:
                raise ValueError("Only measurement zones may define MeasurementGeometry")
        elif self.entangling_geometry is not None:
            raise ValueError("EntanglingGeometry only belongs to entangling zones")
        if self.kind == ZoneKind.MEASUREMENT:
            geometry = self.measurement_geometry
            if geometry is None:
                geometry = MeasurementGeometry(self.bounds, self.bounds, max_parallel_atoms=(self.capacity or None))
            if not isinstance(geometry, MeasurementGeometry) or geometry.bounds != self.bounds:
                raise ValueError("Measurement zones require matching MeasurementGeometry")
            object.__setattr__(self, "measurement_geometry", geometry)
        elif self.measurement_geometry is not None:
            raise ValueError("MeasurementGeometry only belongs to measurement zones")
        if HardwareOperation.ENTANGLE in self.allowed_operations and self.kind != ZoneKind.ENTANGLING:
            raise ValueError("ENTANGLE requires an entangling zone")
        if HardwareOperation.MEASURE in self.allowed_operations and self.kind != ZoneKind.MEASUREMENT:
            raise ValueError("MEASURE requires a measurement zone")
        if HardwareOperation.REFILL in self.allowed_operations and self.kind != ZoneKind.RESERVOIR:
            raise ValueError("REFILL requires a reservoir zone")

    def allows(self, operation: HardwareOperation | str) -> bool:
        return HardwareOperation(operation) in self.allowed_operations

    def to_dict(self):
        return {"id": self.id, "kind": self.kind.value, "bounds": self.bounds.to_list(),
                "capacity": self.capacity, "allowed_operations": sorted(op.value for op in self.allowed_operations),
                "sites": [{"id": s.id, "position": s.position.to_list()} for s in self.sites],
                "pair_slots": [{"id": p.id, "sites": list(p.sites)} for p in self.pair_slots],
                "entangling_geometry": (self.entangling_geometry.to_dict()
                                         if self.entangling_geometry is not None else None),
                "measurement_geometry": (self.measurement_geometry.to_dict()
                                          if self.measurement_geometry is not None else None)}
