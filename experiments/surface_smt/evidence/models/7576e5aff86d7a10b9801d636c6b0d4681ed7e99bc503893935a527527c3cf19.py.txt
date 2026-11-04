"""Compact QF_BV encoding of two-dimensional Cartesian AOD moves.

Every endpoint is an SLM site. Transfers have zero objective weight, so storing
all carriers and loading the next closed group preserves attainable MOVE depth.
This normal form is not a time optimization or a claim for continuous geometry.
"""

from dataclasses import dataclass
from itertools import combinations
from time import perf_counter
from typing import Any, Literal

import z3


@dataclass(frozen=True)
class Problem:
    """Finite double-trap cells, fixed matchings and an initially idle layout."""

    atoms: int
    layers: tuple[tuple[tuple[int, int], ...], ...]
    columns: int = 5
    rows: int = 5
    motion: Literal["flexible", "rigid"] = "flexible"
    initially_idle: bool = True
    cyclic: bool = False


@dataclass(frozen=True)
class Witness:
    """Endpoint trap indices, complete carried groups and gate-state indices."""

    positions: tuple[tuple[tuple[int, int], ...], ...]
    carriers: tuple[tuple[int, ...], ...]
    gate_states: tuple[int, ...]


def _bits(limit: int) -> int:
    return max(1, limit.bit_length())


class DepthModel:
    """Solve exactly K nonempty parallel MOVE transitions in a finite bank."""

    def __init__(self, problem: Problem, depth: int, seed: int = 0) -> None:
        if depth < 0 or problem.atoms < 1 or min(problem.columns, problem.rows) < 1:
            raise ValueError("Invalid finite depth problem dimensions.")
        if problem.motion not in ("flexible", "rigid"):
            raise ValueError("Unknown AOD motion.")
        self.problem, self.depth = problem, depth
        self.solver = z3.SolverFor("QF_BV")
        self.solver.set(random_seed=seed)
        bx, by, bt = _bits(2 * problem.columns), _bits(problem.rows), _bits(depth + 1)
        self.x = [
            [z3.BitVec(f"x_{t}_{q}", bx) for q in range(problem.atoms)]
            for t in range(depth + 1)
        ]
        self.y = [
            [z3.BitVec(f"y_{t}_{q}", by) for q in range(problem.atoms)]
            for t in range(depth + 1)
        ]
        self.carried = [
            [z3.Bool(f"a_{t}_{q}") for q in range(problem.atoms)] for t in range(depth)
        ]
        self.gates = [z3.BitVec(f"gate_{k}", bt) for k in range(len(problem.layers))]
        pairs = tuple(combinations(range(problem.atoms), 2))
        if problem.cyclic:
            for q in range(problem.atoms):
                self.solver.add(
                    self.x[-1][q] == self.x[0][q], self.y[-1][q] == self.y[0][q]
                )
        for t in range(depth + 1):
            for q in range(problem.atoms):
                self.solver.add(
                    z3.ULT(self.x[t][q], 2 * problem.columns),
                    z3.ULT(self.y[t][q], problem.rows),
                )
            for a, b in pairs:
                self.solver.add(
                    z3.Or(self.x[t][a] != self.x[t][b], self.y[t][a] != self.y[t][b])
                )
                if t == 0 and problem.initially_idle:
                    self.solver.add(z3.Not(self.same_cell(t, a, b)))
        for t in range(depth):
            self._move(t, pairs)
        for k, gates in enumerate(problem.layers):
            self.solver.add(z3.ULE(self.gates[k], depth))
            if problem.initially_idle:
                self.solver.add(z3.UGT(self.gates[k], 0))
            if k:
                self.solver.add(z3.ULT(self.gates[k - 1], self.gates[k]))
            expected = {tuple(sorted(pair)) for pair in gates}
            for t in range(depth + 1):
                for a, b in pairs:
                    self.solver.add(
                        z3.Implies(
                            self.gates[k] == t,
                            self.same_cell(t, a, b) == ((a, b) in expected),
                        )
                    )

    def same_cell(self, t: int, a: int, b: int) -> z3.BoolRef:
        """Only the two traps within a cell lie inside the interaction radius."""
        return z3.And(
            z3.LShR(self.x[t][a], 1) == z3.LShR(self.x[t][b], 1),
            self.y[t][a] == self.y[t][b],
        )

    def _move(self, t: int, pairs: tuple[tuple[int, int], ...]) -> None:
        active = self.carried[t]
        n = self.problem.atoms
        changed = [
            z3.Or(self.x[t][q] != self.x[t + 1][q], self.y[t][q] != self.y[t + 1][q])
            for q in range(n)
        ]
        self.solver.add(z3.Or(changed))
        for q in range(n):
            self.solver.add(z3.Implies(changed[q], active[q]))
            for boundary in (t, t + 1):
                # Includes EMPTY Cartesian intersections: row and column may
                # be supplied by two different carriers.
                on_column = z3.Or(
                    [
                        z3.And(active[p], self.x[boundary][q] == self.x[boundary][p])
                        for p in range(n)
                    ]
                )
                on_row = z3.Or(
                    [
                        z3.And(active[p], self.y[boundary][q] == self.y[boundary][p])
                        for p in range(n)
                    ]
                )
                self.solver.add(z3.Implies(z3.And(on_column, on_row), active[q]))
        for a, b in pairs:
            for axis in (self.x, self.y):
                self.solver.add(
                    z3.Implies(
                        z3.And(active[a], active[b]),
                        z3.And(
                            (axis[t][a] == axis[t][b])
                            == (axis[t + 1][a] == axis[t + 1][b]),
                            z3.ULT(axis[t][a], axis[t][b])
                            == z3.ULT(axis[t + 1][a], axis[t + 1][b]),
                        ),
                    )
                )
            if self.problem.motion == "rigid":
                # Wide signed differences avoid modular wrap; x trap spacing
                # is alternating 2/8 um, not a uniform index displacement.
                def physical_x(t_: int, q_: int):
                    x = z3.ZeroExt(12, self.x[t_][q_])
                    return z3.LShR(x, 1) * 10 + (x & 1) * 2

                self.solver.add(
                    z3.Implies(
                        z3.And(active[a], active[b]),
                        z3.And(
                            physical_x(t + 1, a) - physical_x(t, a)
                            == physical_x(t + 1, b) - physical_x(t, b),
                            z3.ZeroExt(12, self.y[t + 1][a])
                            - z3.ZeroExt(12, self.y[t][a])
                            == z3.ZeroExt(12, self.y[t + 1][b])
                            - z3.ZeroExt(12, self.y[t][b]),
                        ),
                    )
                )

    def check(self, timeout_s: float) -> tuple[dict[str, Any], Witness | None]:
        """Return SAT/UNSAT/UNKNOWN; an external worker enforces hard wall time."""
        self.solver.set(timeout=max(1, int(timeout_s * 1000)))
        started = perf_counter()
        answer = self.solver.check()
        report = {
            "status": str(answer),
            "depth": self.depth,
            "solve_s": perf_counter() - started,
            "solver": z3.get_version_string(),
        }
        if answer != z3.sat:
            if answer == z3.unknown:
                report["reason"] = self.solver.reason_unknown()
            return report, None
        model = self.solver.model()
        witness = Witness(
            tuple(
                tuple(
                    (
                        model.eval(self.x[t][q]).as_long(),
                        model.eval(self.y[t][q]).as_long(),
                    )
                    for q in range(self.problem.atoms)
                )
                for t in range(self.depth + 1)
            ),
            tuple(
                tuple(
                    q
                    for q in range(self.problem.atoms)
                    if z3.is_true(model.eval(self.carried[t][q]))
                )
                for t in range(self.depth)
            ),
            tuple(model.eval(value).as_long() for value in self.gates),
        )
        return report, witness
