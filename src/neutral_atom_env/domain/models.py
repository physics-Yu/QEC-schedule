from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .operations import CompiledPlan


@dataclass(frozen=True)
class Position2D:
    x_um: float
    y_um: float

    def __post_init__(self):
        if not all(isfinite(v) for v in (self.x_um, self.y_um)):
            raise ValueError("Coordinates must be finite")


@dataclass(frozen=True)
class GridCoord:
    x: int
    y: int


class ZoneType(str, Enum):
    STORAGE = "storage"
    ENTANGLEMENT = "entanglement"
    MEASUREMENT = "measurement"


@dataclass(frozen=True)
class Rectangle:
    lower: Position2D
    upper: Position2D

    def __post_init__(self):
        if self.lower.x_um >= self.upper.x_um or self.lower.y_um >= self.upper.y_um:
            raise ValueError("Rectangle must have positive area")

    def contains(self, p):
        return (self.lower.x_um <= p.x_um <= self.upper.x_um
                and self.lower.y_um <= p.y_um <= self.upper.y_um)


@dataclass(frozen=True)
class Zone:
    id: str
    zone_type: ZoneType
    bounds: Rectangle


@dataclass(frozen=True)
class StaticTrap:
    id: str
    grid: GridCoord
    position: Position2D
    enabled: bool = True


@dataclass(frozen=True)
class Atom:
    """One atom is one physical qubit; id is the shared circuit/placement ID."""
    id: str
    alive: bool = True
    measured: bool = False
    quantum_state_ref: str | None = None

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id:
            raise ValueError('Physical qubit ID must be a nonempty string')


class HolderType(str, Enum):
    STATIC = "static"
    MOBILE = "mobile"
    LOST = "lost"


@dataclass(frozen=True, order=True)
class MobileCellIndex:
    row: int
    column: int

    def __post_init__(self):
        if self.row < 0 or self.column < 0:
            raise ValueError("Negative mobile cell")


@dataclass(frozen=True)
class HolderRef:
    holder_type: HolderType
    holder_id: str | MobileCellIndex | None


class GateStatus(str, Enum):
    BLOCKED = "blocked"
    READY = "ready"
    RESERVED = "reserved"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class PhysicalGate:
    id: str
    gate_type: str
    qubit_ids: tuple[str, ...]

    def __post_init__(self):
        object.__setattr__(self, "qubit_ids", tuple(self.qubit_ids))
        arity = 2 if self.gate_type in {"CZ", "CPHASE"} else 1
        if self.gate_type not in {"X", "Y", "Z", "H", "RX", "RY", "RZ", "CZ", "CPHASE", "MEASURE"}:
            raise ValueError("Unsupported gate type")
        if not self.id or len(self.qubit_ids) != arity or len(set(self.qubit_ids)) != arity:
            raise ValueError("Invalid gate identity or qubits")

    @property
    def is_two_qubit(self):
        return len(self.qubit_ids) == 2


class EventType(str, Enum):
    GATE_RESERVED = "gate_reserved"
    GATE_STARTED = "gate_started"
    GATE_COMPLETED = "gate_completed"
    GATE_FAILED = "gate_failed"
    WAIT_COMPLETED = "wait_completed"
    RNG_DRAW = "rng_draw"
    PLAN_STARTED = 'plan_started'
    OPERATION_STARTED = 'operation_started'
    OPERATION_COMPLETED = 'operation_completed'
    PLAN_COMPLETED = 'plan_completed'


@dataclass(frozen=True)
class SimulationEvent:
    time_us: float
    event_type: EventType
    gate_id: str | None = None
    plan_id: str | None = None
    operation_id: str | None = None
    plan: 'CompiledPlan | None' = None

    def __post_init__(self):
        if not isfinite(self.time_us) or self.time_us < 0:
            raise ValueError("Event time must be finite and nonnegative")
        if not isinstance(self.event_type, EventType):
            raise ValueError('Unknown event type')
        if self.event_type.value.startswith('gate_') != bool(self.gate_id):
            raise ValueError('Gate events require a gate ID; other events must not have one')
        physical = self.event_type.value.startswith(('plan_', 'operation_'))
        if physical != bool(self.plan_id):
            raise ValueError('Physical events require a plan ID')
        if self.event_type.value.startswith('operation_') != bool(self.operation_id):
            raise ValueError('Operation events require an operation ID')
        if (self.event_type == EventType.PLAN_STARTED) != (self.plan is not None):
            raise ValueError('Only PLAN_STARTED carries a compiled plan')
