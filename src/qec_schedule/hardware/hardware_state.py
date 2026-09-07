"""Validated immutable hardware snapshot; future event engines create new states."""
from dataclasses import dataclass
from itertools import combinations
from types import MappingProxyType

from .atom import Atom, AtomState
from .geometry import finite_number
from .zones import HardwareOperation, Zone, ZoneKind


@dataclass(frozen=True)
class HardwareState:
    atoms: tuple[Atom, ...]
    zones: tuple[Zone, ...]
    current_time: float = 0.0  # microseconds
    min_atom_separation: float = 1.0  # micrometres

    def __post_init__(self):
        object.__setattr__(self, "atoms", tuple(self.atoms))
        object.__setattr__(self, "zones", tuple(self.zones))
        object.__setattr__(self, "current_time", finite_number(self.current_time, "current_time"))
        object.__setattr__(self, "min_atom_separation", finite_number(self.min_atom_separation, "min_atom_separation"))
        if self.current_time < 0 or self.min_atom_separation <= 0:
            raise ValueError("Time must be nonnegative and minimum separation positive")
        self.validate()

    @property
    def atoms_by_id(self):
        return MappingProxyType({a.atom_id: a for a in self.atoms})

    @property
    def zones_by_id(self):
        return MappingProxyType({z.id: z for z in self.zones})

    @property
    def qubit_to_atom(self):
        return MappingProxyType({a.assigned_qubit: a.atom_id for a in self.atoms if a.assigned_qubit is not None})

    def atom_for_qubit(self, qubit: str) -> Atom:
        return self.atoms_by_id[self.qubit_to_atom[qubit]]

    def atoms_in_zone(self, zone_id: str) -> tuple[Atom, ...]:
        self.zones_by_id[zone_id]  # Unknown zone should not silently look empty.
        return tuple(a for a in self.atoms if a.zone == zone_id)

    def validate(self) -> None:
        zones = self.zones_by_id
        if len(zones) != len(self.zones) or len(self.atoms_by_id) != len(self.atoms):
            raise ValueError("Duplicate zone or atom IDs")
        assigned = [a.assigned_qubit for a in self.atoms if a.assigned_qubit is not None]
        if len(set(assigned)) != len(assigned):
            raise ValueError("Each qubit can be assigned to only one atom")
        sites = {}
        for zone in self.zones:
            for site in zone.sites:
                if site.id in sites:
                    raise ValueError("Trap site IDs must be globally unique")
                sites[site.id] = (zone.id, site.position)
        for left, right in combinations(self.zones, 2):
            if left.bounds.overlaps(right.bounds):
                raise ValueError(f"Zones overlap: {left.id}, {right.id}")
        for left, right in combinations(sites.values(), 2):
            if left[1].distance_to(right[1]) < self.min_atom_separation:
                raise ValueError("Trap sites violate minimum separation")
        occupied = set()
        for atom in self.atoms:
            if atom.state in (AtomState.MOVING, AtomState.LOST):
                continue
            if atom.zone not in zones:
                raise ValueError(f"Unknown zone for atom {atom.atom_id}")
            zone = zones[atom.zone]
            dynamic_state = atom.state in (AtomState.AOD_CAPTURED, AtomState.IN_ENTANGLING_REGION,
                                           AtomState.IN_MEASUREMENT_REGION, AtomState.MEASURED)
            if dynamic_state:
                if atom.site_id is not None:
                    raise ValueError(f"Dynamic atom {atom.atom_id} cannot claim a fixed trap site")
                if not zone.bounds.contains(atom.position):
                    raise ValueError(f"Atom {atom.atom_id} is outside its dynamic zone")
            else:
                if atom.site_id not in sites or sites[atom.site_id] != (atom.zone, atom.position):
                    raise ValueError(f"Atom {atom.atom_id} position must match its declared trap site and zone")
                if atom.site_id in occupied:
                    raise ValueError("Two atoms occupy the same site")
                occupied.add(atom.site_id)
            if atom.state == AtomState.MEASURING and not zone.allows(HardwareOperation.MEASURE):
                raise ValueError("Measuring atom must be in a measurement-enabled zone")
            if atom.state in (AtomState.GATING, AtomState.IN_ENTANGLING_REGION) and not (
                    zone.allows(HardwareOperation.LOCAL_1Q) or zone.allows(HardwareOperation.ENTANGLE)):
                raise ValueError("Gating atom must be in a gate-enabled zone")
            if atom.state in (AtomState.MEASURED, AtomState.IN_MEASUREMENT_REGION) and not zone.allows(HardwareOperation.MEASURE):
                raise ValueError("Measured atom must be in a measurement-enabled zone")
        for zone in self.zones:
            if len(self.atoms_in_zone(zone.id)) > zone.capacity:
                raise ValueError(f"Zone capacity exceeded: {zone.id}")
        live = [a for a in self.atoms if a.state != AtomState.LOST]
        for left, right in combinations(live, 2):
            if left.position.distance_to(right.position) < self.min_atom_separation:
                raise ValueError(f"Atoms too close: {left.atom_id}, {right.atom_id}")

    def to_dict(self):
        return {"schema_version": 1, "kind": "hardware_state", "units": {"length": "um", "time": "us"},
                "current_time": self.current_time, "min_atom_separation": self.min_atom_separation,
                "atoms": [a.to_dict() for a in self.atoms], "zones": [z.to_dict() for z in self.zones],
                "qubit_to_atom": dict(self.qubit_to_atom)}
