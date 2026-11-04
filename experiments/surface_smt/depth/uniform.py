"""Uniform rigid arrays with per-MOVE pitch and atom-wise cyclic return."""

from dataclasses import dataclass, replace
from itertools import pairwise
from typing import Any

import z3

from .model import DepthModel, Problem, Witness
from .validation import physical, validate


@dataclass(frozen=True)
class UniformWitness(Witness):
    """Full source grid lines, including lines without any carried atom."""

    grids: tuple[tuple[tuple[int, ...], tuple[int, ...]], ...]


class UniformModel(DepthModel):
    """Add independently chosen uniform pitches and exact final-home equality."""

    def __init__(self, problem: Problem, depth: int, seed: int = 0) -> None:
        if problem.motion != "rigid":
            raise ValueError("Uniform translation requires rigid motion.")
        super().__init__(replace(problem, cyclic=True), depth, seed)
        self.pitches = []
        for t in range(depth):
            covered = []
            destination_covered = []
            pitches = []
            for axis in range(2):
                pitch = z3.Int(f"pitch_{t}_{axis}")
                pitches.append(pitch)
                values = [
                    (z3.BV2Int(self.x[t][q]) / 2) * 10
                    + (z3.BV2Int(self.x[t][q]) % 2) * 2
                    if axis == 0
                    else z3.BV2Int(self.y[t][q]) * 10
                    for q in range(problem.atoms)
                ]
                limit = 10 * max(problem.columns, problem.rows) + 2
                lo, hi = z3.IntVal(limit), z3.IntVal(-1)
                for q, value in enumerate(values):
                    lo = z3.If(z3.And(self.carried[t][q], value < lo), value, lo)
                    hi = z3.If(z3.And(self.carried[t][q], value > hi), value, hi)
                self.solver.add(pitch >= 1, pitch <= limit)
                on_lines = [
                    z3.And(v >= lo, v <= hi, (v - lo) % pitch == 0) for v in values
                ]
                for q in range(problem.atoms):
                    self.solver.add(z3.Implies(self.carried[t][q], on_lines[q]))
                covered.append(on_lines)
                targets = [
                    (z3.BV2Int(self.x[t + 1][q]) / 2) * 10
                    + (z3.BV2Int(self.x[t + 1][q]) % 2) * 2
                    if axis == 0
                    else z3.BV2Int(self.y[t + 1][q]) * 10
                    for q in range(problem.atoms)
                ]
                delta = z3.Int(f"translation_{t}_{axis}")
                for q in range(problem.atoms):
                    self.solver.add(
                        z3.Implies(self.carried[t][q], targets[q] - values[q] == delta)
                    )
                destination_covered.append(
                    [
                        z3.And(
                            v >= lo + delta,
                            v <= hi + delta,
                            (v - lo - delta) % pitch == 0,
                        )
                        for v in targets
                    ]
                )
            for q in range(problem.atoms):
                self.solver.add(
                    z3.Implies(z3.And(covered[0][q], covered[1][q]), self.carried[t][q])
                )
                self.solver.add(
                    z3.Implies(
                        z3.And(destination_covered[0][q], destination_covered[1][q]),
                        self.carried[t][q],
                    )
                )
            self.pitches.append(pitches)
        # Uniform spacing uses integer arithmetic; do not retain a QF_BV-only solver.
        assertions = self.solver.assertions()
        self.solver = z3.Solver()
        self.solver.set(random_seed=seed)
        self.solver.add(assertions)

    def check(self, timeout_s: float) -> tuple[dict[str, Any], UniformWitness | None]:
        report, witness = super().check(timeout_s)
        if witness is None:
            return report, None
        model = self.solver.model()
        grids = []
        for t, carriers in enumerate(witness.carriers):
            lines = []
            for axis in range(2):
                values = [physical(witness.positions[t][q])[axis] for q in carriers]
                pitch = model.eval(self.pitches[t][axis]).as_long()
                lines.append(tuple(range(min(values), max(values) + 1, pitch)))
            grids.append(tuple(lines))
        return report, UniformWitness(
            witness.positions, witness.carriers, witness.gate_states, tuple(grids)
        )


def validate_uniform(problem: Problem, witness: UniformWitness) -> list[str]:
    """Check complete arrays with integer geometry, independent of SMT pitches."""
    if problem.motion != "rigid":
        return ["uniform_motion_requires_rigid"]
    errors = validate(replace(problem, cyclic=True), witness)
    if errors:
        return errors
    if len(witness.grids) != len(witness.carriers):
        return errors + ["grid_count"]
    for t, (columns, rows) in enumerate(witness.grids):
        carriers = set(witness.carriers[t])
        for axis, lines in enumerate((columns, rows)):
            gaps = {b - a for a, b in pairwise(lines)}
            if (
                not lines
                or any(not isinstance(value, int) for value in lines)
                or len(gaps) > 1
                or any(g <= 0 for g in gaps)
            ):
                errors.append(f"move {t}: uniform_spacing")
                continue
            coords = [physical(witness.positions[t][q])[axis] for q in carriers]
            if (lines[0], lines[-1]) != (min(coords), max(coords)):
                errors.append(f"move {t}: grid_extent")
        q = next(iter(carriers))
        start, end = (
            physical(witness.positions[t][q]),
            physical(witness.positions[t + 1][q]),
        )
        for boundary, dx, dy in (
            (t, 0, 0),
            (t + 1, end[0] - start[0], end[1] - start[1]),
        ):
            xs, ys = {x + dx for x in columns}, {y + dy for y in rows}
            picked = {
                q
                for q, p in enumerate(witness.positions[boundary])
                if physical(p)[0] in xs and physical(p)[1] in ys
            }
            if picked != carriers:
                errors.append(f"move {t}: full_grid_pickup")
    return errors
