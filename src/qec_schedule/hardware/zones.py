"""Zone capabilities and predefined trap/pair sites, independent of QEC codes."""
from dataclasses import dataclass
from enum import Enum

from .geometry import Bounds, Position


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


@dataclass(frozen=True)
class Zone:
    id: str
    kind: ZoneKind
    bounds: Bounds
    capacity: int  # Number of atoms, NOT number of entangling pairs.
    allowed_operations: frozenset[HardwareOperation]
    sites: tuple[TrapSite, ...]
    pair_slots: tuple[PairSlot, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "kind", ZoneKind(self.kind))
        object.__setattr__(self, "allowed_operations", frozenset(HardwareOperation(op) for op in self.allowed_operations))
        object.__setattr__(self, "sites", tuple(self.sites))
        object.__setattr__(self, "pair_slots", tuple(self.pair_slots))
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("Zone ID must be nonempty")
        if type(self.capacity) is not int or not 0 <= self.capacity <= len(self.sites):
            raise ValueError("Zone capacity must be an integer between 0 and the number of sites")
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
        if HardwareOperation.ENTANGLE in self.allowed_operations and (self.kind != ZoneKind.ENTANGLING or not self.pair_slots):
            raise ValueError("ENTANGLE requires an entangling zone with pair slots")
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
                "pair_slots": [{"id": p.id, "sites": list(p.sites)} for p in self.pair_slots]}
