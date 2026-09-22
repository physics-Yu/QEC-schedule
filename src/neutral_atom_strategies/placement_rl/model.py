"""Immutable inputs for the isolated, discrete placement-learning research model.

Coordinates are micrometres; reported durations are illustrative model microseconds.
This model is deliberately not the production environment or a physical validator.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil, isfinite, sqrt
from typing import Any

Point = tuple[float, float]
Gate = tuple[int, int]


def _positive_integer(value: int, name: str, *, zero: bool = False) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < (0 if zero else 1):
        raise ValueError(f"{name} must be an integer >= {0 if zero else 1}")


def _point(value: Any) -> Point:
    if len(value) != 2 or not all(isinstance(v, (int, float)) and not isinstance(v, bool)
                                  and isfinite(v) for v in value):
        raise ValueError("coordinates must contain two finite numbers")
    return (float(value[0]), float(value[1]))


@dataclass(frozen=True)
class Circuit:
    n_qubits: int
    layers: tuple[tuple[Gate, ...], ...]

    def __post_init__(self) -> None:
        _positive_integer(self.n_qubits, "n_qubits")
        layers = tuple(tuple(tuple(g) for g in layer) for layer in self.layers)
        for layer in layers:
            seen: set[int] = set()
            for gate in layer:
                if len(gate) != 2 or any(isinstance(q, bool) or not isinstance(q, int)
                                         or not 0 <= q < self.n_qubits for q in gate):
                    raise ValueError("CZ gate must contain two in-range qubit integers")
                if gate[0] == gate[1] or any(q in seen for q in gate):
                    raise ValueError("CZ layers must be disjoint matchings")
                seen.update(gate)
        object.__setattr__(self, "layers", layers)


@dataclass(frozen=True)
class Hardware:
    storage: tuple[Point, ...]
    entangling: tuple[tuple[Point, Point], ...]
    aod_rows: int = 4
    aod_cols: int = 4
    min_axis_separation_um: float = 1.0

    def __post_init__(self) -> None:
        _positive_integer(self.aod_rows, "aod_rows")
        _positive_integer(self.aod_cols, "aod_cols")
        gap = self.min_axis_separation_um
        if isinstance(gap, bool) or not isinstance(gap, (int, float)) or not isfinite(gap) or gap <= 0:
            raise ValueError("min_axis_separation_um must be finite and positive")
        storage = tuple(_point(p) for p in self.storage)
        if any(len(pair) != 2 for pair in self.entangling):
            raise ValueError("each entangling site must contain exactly two traps")
        entangling = tuple(tuple(_point(p) for p in pair) for pair in self.entangling)
        points = storage + tuple(p for pair in entangling for p in pair)
        if not storage or not entangling or len(set(points)) != len(points):
            raise ValueError("nonempty, disjoint storage and entangling traps are required")
        object.__setattr__(self, "storage", storage)
        object.__setattr__(self, "entangling", entangling)


@dataclass(frozen=True)
class Scenario:
    name: str
    move_scale: float = 1.0
    transfer_scale: float = 1.0
    grouping_order: str = "forward"

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("scenario name must be nonempty")
        for name in ("move_scale", "transfer_scale"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.grouping_order not in {"forward", "reverse", "longest", "shortest"}:
            raise ValueError("unknown grouping_order")


@dataclass(frozen=True)
class CompilerConfig:
    trials: int = 2
    queue_capacity: int = 24
    site_limit: int = 4
    reuse: bool = True
    terminal: str = "storage"

    def __post_init__(self) -> None:
        for name in ("trials", "queue_capacity", "site_limit"):
            _positive_integer(getattr(self, name), name)
        if not isinstance(self.reuse, bool):
            raise ValueError("reuse must be boolean")
        if self.terminal not in {"storage", "canonical"}:
            raise ValueError("terminal must be storage or canonical")


@dataclass(frozen=True)
class CompileResult:
    status: str
    duration_us: float
    metrics: dict[str, Any]
    trace: tuple[dict[str, Any], ...]
    final_positions: tuple[Point, ...]
    error: str | None = None


def standard_hardware(n_qubits: int, vacancies: int = 0) -> Hardware:
    """An explicitly synthetic paired-SLM geometry, not a paper's device."""
    _positive_integer(n_qubits, "n_qubits")
    _positive_integer(vacancies, "vacancies", zero=True)
    count = n_qubits + vacancies
    width = ceil(sqrt(count))
    storage = tuple((10.0 * (i % width), 10.0 * (i // width)) for i in range(count))
    pairs = max(1, n_qubits // 2)
    ez_width = ceil(sqrt(pairs))
    offset = max(p[1] for p in storage) + 40.0
    entangling = tuple(((24.0 * (i % ez_width), offset + 16.0 * (i // ez_width)),
                       (24.0 * (i % ez_width) + 2.0, offset + 16.0 * (i // ez_width)))
                      for i in range(pairs))
    return Hardware(storage, entangling)
