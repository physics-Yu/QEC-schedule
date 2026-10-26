"""Solver-independent states and plans at Atom IR step boundaries."""

from dataclasses import dataclass
from typing import Any

from ..compiler import CompilationResult
from ..device import Position


@dataclass(frozen=True, slots=True)
class Domain:
    """Finite coordinate alphabet and step horizon; neither is AOD capacity."""

    xs: tuple[float, ...]
    ys: tuple[float, ...]
    horizon: int
    timeout_s: float = 60
    time_quantum_us: float = 0.001


@dataclass(frozen=True, slots=True)
class Snapshot:
    """Positions in entry atom order, holder flags and all active AOD lines."""

    positions: tuple[Position, ...]
    carried: tuple[bool, ...]
    columns: tuple[float, ...] = ()
    rows: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class Plan:
    """H transitions and operation groups between H+1 physical snapshots."""

    states: tuple[Snapshot, ...]
    transitions: tuple[str, ...]
    operations: tuple[tuple[int, ...], ...]


@dataclass(frozen=True, slots=True)
class SolveResult:
    """An independently validated feasible result and bounded-search evidence."""

    result: CompilationResult | None
    plan: Plan | None
    evidence: dict[str, Any]
