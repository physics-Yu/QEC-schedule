"""Small, independent scheduling IR; this module has no environment dependency."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite, ulp
from types import MappingProxyType
from typing import Any, Mapping


def _id(value: str, label: str = "id") -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _ids(values: tuple[str, ...], label: str) -> tuple[str, ...]:
    result = tuple(_id(value, label) for value in values)
    if len(set(result)) != len(result):
        raise ValueError(f"duplicate {label}")
    return result


def freeze(value: Any) -> Any:
    """Freeze JSON-shaped metadata without retaining caller-owned containers."""
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("metadata keys must be strings")
        return MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (tuple, list)):
        return tuple(freeze(item) for item in value)
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and isfinite(value):
        return value
    raise ValueError("metadata must contain finite JSON values")


def thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [thaw(item) for item in value]
    return value


def gate_kind(kind: str) -> str:
    kind = _id(kind, "kind").upper()
    return {"M": "MEASURE", "MZ": "MEASURE", "MEASUREMENT": "MEASURE"}.get(kind, kind)


@dataclass(frozen=True, slots=True)
class GateSpec:
    id: str
    kind: str
    atoms: tuple[str, ...]
    depends_on: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _id(self.id)
        object.__setattr__(self, "kind", gate_kind(self.kind))
        object.__setattr__(self, "atoms", _ids(self.atoms, "atom id"))
        object.__setattr__(self, "depends_on", _ids(self.depends_on, "dependency id"))
        if not self.atoms:
            raise ValueError("a gate requires atoms")
        if self.id in self.depends_on:
            raise ValueError("a gate cannot depend on itself")


@dataclass(frozen=True, slots=True)
class Operation:
    id: str
    kind: str
    atoms: tuple[str, ...] = ()
    duration_us: float = 0.0
    positions: tuple[tuple[str, tuple[float, float]], ...] = ()
    gate_ids: tuple[str, ...] = ()
    report_ids: tuple[str, ...] = ()
    aod_id: str = "AOD_0"
    metadata: Mapping[str, Any] = field(default_factory=dict)
    start_us: float | None = None
    depends_on: tuple[str, ...] = ()
    resources: tuple[str, ...] = ()
    motion_profile: str = "row_column"
    end_us: float | None = None

    def __post_init__(self) -> None:
        _id(self.id)
        kind = gate_kind(self.kind)
        object.__setattr__(self, "kind", {"OFFLOAD": "STORE"}.get(kind, kind))
        object.__setattr__(self, "atoms", _ids(self.atoms, "atom id"))
        object.__setattr__(self, "gate_ids", _ids(self.gate_ids, "gate id"))
        object.__setattr__(self, "report_ids", _ids(self.report_ids, "report id"))
        duration = float(self.duration_us)
        if not isfinite(duration) or duration < 0:
            raise ValueError("duration_us must be finite and nonnegative")
        object.__setattr__(self, "duration_us", duration)
        _id(self.aod_id, "aod id")
        points = []
        for atom, point in self.positions:
            _id(atom, "position atom id")
            if len(point) != 2:
                raise ValueError("positions require two coordinates")
            x, y = float(point[0]), float(point[1])
            if not isfinite(x) or not isfinite(y):
                raise ValueError("positions must be finite")
            points.append((atom, (x, y)))
        if len({atom for atom, _ in points}) != len(points):
            raise ValueError("duplicate position atom id")
        object.__setattr__(self, "positions", tuple(points))
        object.__setattr__(self, "metadata", freeze(self.metadata))
        if self.start_us is not None:
            start = float(self.start_us)
            if not isfinite(start) or start < 0:
                raise ValueError("start_us must be a finite nonnegative block offset")
            object.__setattr__(self, "start_us", start)
        object.__setattr__(self, "depends_on", _ids(self.depends_on, "operation dependency id"))
        object.__setattr__(self, "resources", _ids(self.resources, "resource id"))
        if self.id in self.depends_on:
            raise ValueError("an operation cannot depend on itself")
        if self.motion_profile not in ("row_column", "rigid"):
            raise ValueError("motion_profile must be row_column or rigid")
        if self.end_us is not None:
            end = float(self.end_us)
            if self.start_us is None or not isfinite(end) or end < self.start_us:
                raise ValueError("end_us requires a finite end at or after explicit start_us")
            tolerance = 4*(ulp(self.start_us)+ulp(end)+ulp(duration))
            if (duration == 0 and end != self.start_us) or abs((end-self.start_us)-duration) > tolerance:
                raise ValueError("explicit end-start must equal duration within floating-point representation")
            object.__setattr__(self, "end_us", end)


@dataclass(frozen=True, slots=True)
class Block:
    id: str
    operations: tuple[Operation, ...]
    expected_version: int
    starting_state_hash: str
    native_provenance: Mapping[str, Any] = field(default_factory=dict)
    execution_mode: str = "serial"

    def __post_init__(self) -> None:
        _id(self.id)
        operations = tuple(self.operations)
        if any(not isinstance(operation, Operation) for operation in operations):
            raise ValueError("blocks contain Operation values")
        if len({operation.id for operation in operations}) != len(operations):
            raise ValueError("duplicate operation id in block")
        if isinstance(self.expected_version, bool) or not isinstance(self.expected_version, int) or self.expected_version < 0:
            raise ValueError("expected_version must be a nonnegative integer")
        _id(self.starting_state_hash, "starting state hash")
        object.__setattr__(self, "operations", operations)
        object.__setattr__(self, "native_provenance", freeze(self.native_provenance))
        if self.execution_mode not in ("serial", "scheduled"):
            raise ValueError("execution_mode must be serial or scheduled")
        if self.execution_mode == "scheduled" and any(operation.start_us is None for operation in operations):
            raise ValueError("scheduled operations require explicit start_us")


@dataclass(frozen=True, slots=True)
class Observation:
    time_us: float
    version: int
    measurement_results: Mapping[str, int]
    completed_gate_ids: tuple[str, ...]
    activated_fragments: tuple[str, ...]
    completed: bool
    pending_events: int
    holders: Mapping[str, str]
    positions: Mapping[str, tuple[float, float]]
    measurement_completion_times_us: Mapping[str, float]
    fragment_remaining: Mapping[str, int]
    completed_fragment_ids: tuple[str, ...]
    report_source_cursor: int | None
    aod_axes: Mapping[str, Mapping[str, tuple[float, ...]]]
    inflight_operations: tuple[str, ...] = ()
    completed_operation_ids: tuple[str, ...] = ()
    resource_owners: Mapping[str, str] = field(default_factory=dict)
    committed_positions: Mapping[str, tuple[float, float]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TrajectoryEvaluation:
    time_us: float
    committed_version: int
    positions: Mapping[str, tuple[float, float]]
    aod_axes: Mapping[str, Mapping[str, tuple[float, ...]]]

