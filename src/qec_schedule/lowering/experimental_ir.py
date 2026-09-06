"""Unscheduled experiment requests and resource lifetimes, not an execution trace."""
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType

from ..hardware.geometry import Position, finite_number


class ActionType(str, Enum):
    PICKUP = "PICKUP"
    MOVE = "MOVE"
    DROPOFF = "DROPOFF"
    SINGLE_QUBIT = "SINGLE_QUBIT"
    ENTANGLE = "ENTANGLE"
    MEASURE = "MEASURE"
    PREPARE = "PREPARE"
    RESET = "RESET"


@dataclass(frozen=True)
class SiteRef:
    zone: str
    site: str
    position: Position

    def __post_init__(self):
        if not isinstance(self.zone, str) or not self.zone or not isinstance(self.site, str) or not self.site or not isinstance(self.position, Position):
            raise ValueError("SiteRef requires a zone, site and Position")

    def to_dict(self):
        return {"zone": self.zone, "site": self.site, "position": self.position.to_list()}


@dataclass(frozen=True)
class ResourceRequirement:
    resource: str
    units: int = 1

    def __post_init__(self):
        if not isinstance(self.resource, str) or not self.resource or type(self.units) is not int or self.units < 1:
            raise ValueError("Resource requirement needs a name and positive integer units")

    def to_dict(self):
        return {"resource": self.resource, "units": self.units}


@dataclass(frozen=True)
class ExperimentalAction:
    id: str
    gate_id: str
    action_type: ActionType
    atoms: tuple[str, ...]
    duration: float
    sources: tuple[SiteRef, ...]
    targets: tuple[SiteRef, ...]
    dependencies: tuple[str, ...] = ()
    required_resources: tuple[ResourceRequirement, ...] = ()
    metadata: Mapping[str, str | int] = field(default_factory=dict)
    start_time: None = None

    def __post_init__(self):
        object.__setattr__(self, "action_type", ActionType(self.action_type))
        for name in ("atoms", "sources", "targets", "dependencies", "required_resources"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        object.__setattr__(self, "duration", finite_number(self.duration, "duration"))
        arity = 2 if self.action_type == ActionType.ENTANGLE else 1
        if not self.id or not self.gate_id or len(self.atoms) != arity or len(set(self.atoms)) != arity or any(not a for a in self.atoms):
            raise ValueError("Action requires IDs and distinct atoms of correct arity")
        if len(self.sources) != arity or len(self.targets) != arity:
            raise ValueError("Sources and targets must correspond to the atoms in order")
        if any(not isinstance(p, SiteRef) for p in self.sources + self.targets):
            raise ValueError("Action endpoints must be SiteRef values")
        if any(not isinstance(k, str) or type(v) not in (str, int) for k, v in self.metadata.items()):
            raise ValueError("Action metadata needs string keys and string/integer values")
        if self.action_type == ActionType.ENTANGLE and (self.sources[0].zone != self.sources[1].zone or self.sources[0].site == self.sources[1].site):
            raise ValueError("Entangling atoms must occupy distinct sites in the same zone")
        if self.duration <= 0 or self.start_time is not None:
            raise ValueError("Requests need positive duration and start_time=None")
        if self.action_type != ActionType.MOVE and self.sources != self.targets:
            raise ValueError("Only MOVE can change an atom position")
        if self.action_type == ActionType.MOVE and self.sources[0].position == self.targets[0].position:
            raise ValueError("Zero-distance moves must be omitted")
        if len(set(self.dependencies)) != len(self.dependencies) or self.id in self.dependencies:
            raise ValueError("Invalid action dependencies")
        if len({r.resource for r in self.required_resources}) != len(self.required_resources):
            raise ValueError("Duplicate action resource requirement")

    @property
    def source_zone(self) -> str:
        return self.sources[0].zone

    @property
    def target_zone(self) -> str:
        return self.targets[0].zone

    def to_dict(self):
        return {"id": self.id, "gate_id": self.gate_id, "type": self.action_type.value,
                "atoms": list(self.atoms), "start_time": None, "duration": self.duration,
                "source_zone": self.source_zone, "target_zone": self.target_zone,
                "sources": [p.to_dict() for p in self.sources], "targets": [p.to_dict() for p in self.targets],
                "dependencies": list(self.dependencies), "required_resources": [r.to_dict() for r in self.required_resources],
                "metadata": dict(self.metadata)}


@dataclass(frozen=True)
class Reservation:
    """Acquire all resources before ANY entry; release after ALL exits finish.

    An empty release_after means hold through the end of this plan. Site/zone
    leases and transport custody are separate from action requirements. Actions
    inside an active lease borrow its resources instead of counting them twice.
    """
    id: str
    required_resources: tuple[ResourceRequirement, ...]
    acquire_before: tuple[str, ...]
    release_after: tuple[str, ...] = ()

    def __post_init__(self):
        for name in ("required_resources", "acquire_before", "release_after"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if not self.id or not self.required_resources or not self.acquire_before:
            raise ValueError("Reservation requires ID, resources and entry actions")
        if len({r.resource for r in self.required_resources}) != len(self.required_resources):
            raise ValueError("Duplicate reservation resource")
        if len(set(self.acquire_before)) != len(self.acquire_before) or len(set(self.release_after)) != len(self.release_after):
            raise ValueError("Duplicate reservation boundaries")

    def to_dict(self):
        return {"id": self.id, "required_resources": [r.to_dict() for r in self.required_resources],
                "acquire_before": list(self.acquire_before), "release_after": list(self.release_after)}


@dataclass(frozen=True)
class ExperimentalPlan:
    actions: tuple[ExperimentalAction, ...]
    gate_completion: Mapping[str, tuple[str, ...]]
    reservations: tuple[Reservation, ...]
    home_sites: Mapping[str, SiteRef]
    planned_final_sites: Mapping[str, SiteRef]

    def __post_init__(self):
        object.__setattr__(self, "actions", tuple(self.actions))
        object.__setattr__(self, "reservations", tuple(self.reservations))
        object.__setattr__(self, "gate_completion", MappingProxyType({k: tuple(v) for k, v in self.gate_completion.items()}))
        for name in ("home_sites", "planned_final_sites"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))
        seen = {}
        for action in self.actions:
            if action.id in seen or not set(action.dependencies) <= seen.keys():
                raise ValueError("Action IDs must be unique and dependencies refer to earlier actions")
            if not set(action.atoms) <= self.home_sites.keys():
                raise ValueError("Action references an unmapped atom")
            seen[action.id] = action
        if {a.gate_id for a in self.actions} != set(self.gate_completion):
            raise ValueError("Gate completion map must cover all lowered gates")
        for gate_id, terminals in self.gate_completion.items():
            if not terminals or any(t not in seen or seen[t].gate_id != gate_id for t in terminals):
                raise ValueError("Gate terminals must reference actions of that gate")
        internal_parents = {parent for a in self.actions for parent in a.dependencies if seen[parent].gate_id == a.gate_id}
        sinks = {gate_id: set() for gate_id in self.gate_completion}
        for action in self.actions:
            if action.id not in internal_parents:
                sinks[action.gate_id].add(action.id)
        for gate_id, terminals in self.gate_completion.items():
            if len(set(terminals)) != len(terminals) or set(terminals) != sinks[gate_id]:
                raise ValueError("Gate completion must wait for exactly its terminal actions")
        if set(self.home_sites) != set(self.planned_final_sites):
            raise ValueError("Final site map must cover every mapped atom")
        if len({r.id for r in self.reservations}) != len(self.reservations):
            raise ValueError("Duplicate reservation ID")
        for reservation in self.reservations:
            if not set(reservation.acquire_before + reservation.release_after) <= seen.keys():
                raise ValueError("Unknown reservation boundary action")

    def actions_for_gate(self, gate_id: str) -> tuple[ExperimentalAction, ...]:
        self.gate_completion[gate_id]
        return tuple(a for a in self.actions if a.gate_id == gate_id)

    def to_dict(self):
        return {"schema_version": 1, "kind": "experimental_requests", "scheduled": False,
                "units": {"length": "um", "time": "us"},
                "actions": [a.to_dict() for a in self.actions],
                "gate_completion": {k: list(v) for k, v in self.gate_completion.items()},
                "reservations": [r.to_dict() for r in self.reservations],
                "home_sites": {k: v.to_dict() for k, v in self.home_sites.items()},
                "planned_final_sites": {k: v.to_dict() for k, v in self.planned_final_sites.items()}}
