from dataclasses import dataclass, field
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
    parameters: tuple[float, ...] = ()
    condition: tuple[tuple[str, int], ...] = ()
    depends_on: tuple[str, ...] = ()
    readout_flip: bool = field(default=False, metadata={'omit_if_false': True})

    def __post_init__(self):
        object.__setattr__(self, "qubit_ids", tuple(self.qubit_ids))
        object.__setattr__(self, "parameters", tuple(self.parameters))
        object.__setattr__(self, 'condition', tuple(tuple(c) for c in self.condition))
        object.__setattr__(self, 'depends_on', tuple(self.depends_on))
        if type(self.readout_flip) is not bool:
            raise ValueError('readout_flip must be a boolean')
        if self.readout_flip and self.gate_type not in {'MEASURE','MZ'}:
            raise ValueError('readout_flip is only valid for MEASURE/MZ')
        if (len(set(self.depends_on))!=len(self.depends_on) or
                any(not isinstance(g,str) or not g for g in self.depends_on)):
            raise ValueError('Explicit dependencies require unique gate IDs')
        if self.condition and (self.gate_type not in {'X','Z'} or
                any(len(c)!=2 or not isinstance(c[0],str) or not c[0] or type(c[1]) is not int or c[1] not in (0,1) for c in self.condition)
                or len({c[0] for c in self.condition})!=len(self.condition)):
            raise ValueError('Only X/Z corrections support distinct measurement-bit equality conditions')
        arity = 2 if self.gate_type in {"CZ", "CPHASE"} else 1
        if self.gate_type not in {"U", "U3", "I", "X", "Y", "Z", "H", "S", "Sdg", "T", "Tdg", "RX", "RY", "RZ", "CZ", "CPHASE", "MEASURE", "MZ", "RESET"}:
            raise ValueError("Unsupported gate type")
        if not self.id or len(self.qubit_ids) != arity or len(set(self.qubit_ids)) != arity:
            raise ValueError("Invalid gate identity or qubits")
        count = 3 if self.gate_type in {'U', 'U3'} else 1 if self.gate_type in {'RX', 'RY', 'RZ', 'CPHASE'} else 0
        if len(self.parameters) != count or any(type(p) not in (int, float) or not isfinite(p) for p in self.parameters):
            raise ValueError(f'{self.gate_type} requires {count} finite real parameters in radians')

    @property
    def u_parameters(self):
        """Canonical U(theta, phi, lambda), up to global phase for aliases."""
        from math import pi
        if self.gate_type in {'U', 'U3'}:
            return self.parameters
        aliases = {'I': (0, 0, 0), 'X': (pi, 0, pi), 'Y': (pi, pi/2, pi/2),
                   'Z': (0, 0, pi), 'H': (pi/2, 0, pi), 'S': (0, 0, pi/2),
                   'Sdg': (0, 0, -pi/2), 'T': (0, 0, pi/4), 'Tdg': (0, 0, -pi/4)}
        if self.gate_type in aliases:
            return aliases[self.gate_type]
        if self.gate_type in {'RX', 'RY', 'RZ'}:
            angle = self.parameters[0]
            return {'RX': (angle, -pi/2, pi/2), 'RY': (angle, 0, 0), 'RZ': (0, 0, angle)}[self.gate_type]
        return None

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
