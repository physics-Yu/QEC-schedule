"""Exact LOAD/MOVE/STORE transitions on a declared finite coordinate alphabet."""

from collections.abc import Sequence
from itertools import combinations

import z3

from ..device import Device, Position
from ..state import COORDINATE_TOLERANCE, AODHolder, AtomLayout
from .contracts import Domain, Snapshot

_NAMES = ("none", "load", "move", "store")


def _lookup(index: z3.ArithRef, values: Sequence[z3.ExprRef]) -> z3.ExprRef:
    """Select an entry; callers constrain the index to the sequence bounds."""
    result = values[-1]
    for i in range(len(values) - 2, -1, -1):
        result = z3.If(index == i, values[i], result)
    return result


def _count(flags: Sequence[z3.BoolRef]) -> z3.ArithRef:
    return z3.Sum([z3.If(flag, 1, 0) for flag in flags])


def _ranks(flags: Sequence[z3.BoolRef]) -> list[z3.ArithRef]:
    values = [z3.IntVal(0)]
    for flag in flags[:-1]:
        values.append(values[-1] + z3.If(flag, 1, 0))
    return values


class TransportModel:
    """Add a bounded shared-AOD transport problem to a Z3 solver.

    Atom indices follow ``entry.atoms``. States include all active lines,
    including empty lines. MOVE maps their spatial ranks, so line identities
    remain stable without allocating artificial line capacity. The final state
    stores every atom at its entry position and deactivates every line.

    Args:
        solver: Solver receiving constraints; optimization is owned by the caller.
        device: SLM geometry and AOD capability.
        aod_id: The single shared AOD controlled by this model.
        entry: Initial atom state and optional active lines for this AOD.
        domain: Sorted finite coordinate alphabets and number of transitions.

    Raises:
        ValueError: For invalid alphabets, a negative horizon, out-of-domain
            entry coordinates, or entry atoms/lines using another AOD.
        KeyError: If the AOD is absent from the device.
    """

    def __init__(
        self,
        solver: z3.Solver | z3.Optimize,
        device: Device,
        aod_id: str,
        entry: AtomLayout,
        domain: Domain,
    ) -> None:
        for values in (domain.xs, domain.ys):
            if not values or tuple(sorted(set(values))) != values:
                raise ValueError(
                    "Transport coordinate alphabets must be sorted and unique."
                )
        if domain.horizon < 0:
            raise ValueError("Transport horizon must be nonnegative.")
        if any(grid.aod_id != aod_id for grid in entry.aod_grids) or any(
            isinstance(atom.holder, AODHolder) and atom.holder.aod_id != aod_id
            for atom in entry.atoms
        ):
            raise ValueError("Transport entry uses an AOD outside the selected model.")
        self.solver = solver
        self.device = device
        self.aod_id = aod_id
        self.entry = entry
        self.domain = domain
        self.aod = device.aod(aod_id)
        self._xs = tuple(z3.RealVal(str(value)) for value in domain.xs)
        self._ys = tuple(z3.RealVal(str(value)) for value in domain.ys)
        states = range(domain.horizon + 1)
        atoms = range(len(entry.atoms))
        self.x = [[z3.Int(f"tx_{t}_{q}") for q in atoms] for t in states]
        self.y = [[z3.Int(f"ty_{t}_{q}") for q in atoms] for t in states]
        self.carried = [[z3.Bool(f"ta_{t}_{q}") for q in atoms] for t in states]
        self.columns = [
            [z3.Bool(f"tc_{t}_{i}") for i in range(len(domain.xs))] for t in states
        ]
        self.rows = [
            [z3.Bool(f"tr_{t}_{i}") for i in range(len(domain.ys))] for t in states
        ]
        self.px = [[_lookup(index, self._xs) for index in row] for row in self.x]
        self.py = [[_lookup(index, self._ys) for index in row] for row in self.y]
        self.kind = [z3.Int(f"tk_{t}") for t in range(domain.horizon)]
        self._column_ranks = [_ranks(flags) for flags in self.columns]
        self._row_ranks = [_ranks(flags) for flags in self.rows]
        self._boundary()
        for t in states:
            self._state(t)
        for t in range(domain.horizon):
            self._transition(t)

    def _boundary(self) -> None:
        grid = self.entry.grid(self.aod_id)
        initial_columns = {line.coordinate for line in grid.columns}
        initial_rows = {line.coordinate for line in grid.rows}
        if not initial_columns <= set(self.domain.xs) or not initial_rows <= set(
            self.domain.ys
        ):
            raise ValueError(
                "Initial AOD lines must be in the transport coordinate domain."
            )
        for q, atom in enumerate(self.entry.atoms):
            try:
                x = self.domain.xs.index(atom.position.x)
                y = self.domain.ys.index(atom.position.y)
            except ValueError as error:
                raise ValueError(
                    f"Atom {atom.id} entry position is outside the transport domain."
                ) from error
            self.solver.add(
                self.x[0][q] == x,
                self.y[0][q] == y,
                self.carried[0][q] == isinstance(atom.holder, AODHolder),
                self.x[-1][q] == x,
                self.y[-1][q] == y,
                z3.Not(self.carried[-1][q]),
            )
        for flags, values, active in (
            (self.columns, self.domain.xs, initial_columns),
            (self.rows, self.domain.ys, initial_rows),
        ):
            self.solver.add(
                *[
                    flag == (value in active)
                    for flag, value in zip(flags[0], values, strict=True)
                ],
                *[z3.Not(flag) for flag in flags[-1]],
            )

    def _state(self, t: int) -> None:
        self._axis_state(
            self.columns[t],
            self.domain.xs,
            self.aod.max_columns,
            self.aod.workspace.x_min,
            self.aod.workspace.x_max,
        )
        self._axis_state(
            self.rows[t],
            self.domain.ys,
            self.aod.max_rows,
            self.aod.workspace.y_min,
            self.aod.workspace.y_max,
        )
        sites = tuple(
            (
                self.domain.xs.index(site.position.x),
                self.domain.ys.index(site.position.y),
            )
            for site in self.device.slm_sites
            if site.position.x in self.domain.xs and site.position.y in self.domain.ys
        )
        for q in range(len(self.entry.atoms)):
            x, y = self.x[t][q], self.y[t][q]
            intersection = z3.And(_lookup(x, self.columns[t]), _lookup(y, self.rows[t]))
            self.solver.add(
                x >= 0,
                x < len(self.domain.xs),
                y >= 0,
                y < len(self.domain.ys),
                # Every atom at an active Cartesian intersection is carried.
                # This includes LOAD closure and empty-trap ghosts after MOVE.
                self.carried[t][q] == intersection,
                z3.Implies(
                    z3.Not(self.carried[t][q]),
                    z3.Or([z3.And(x == sx, y == sy) for sx, sy in sites]),
                ),
            )
        for p, q in combinations(range(len(self.entry.atoms)), 2):
            self.solver.add(
                z3.Or(self.x[t][p] != self.x[t][q], self.y[t][p] != self.y[t][q])
            )

    def _axis_state(
        self,
        flags: Sequence[z3.BoolRef],
        values: tuple[float, ...],
        capacity: int | None,
        lower: float,
        upper: float,
    ) -> None:
        if capacity is not None:
            self.solver.add(_count(flags) <= capacity)
        for i, value in enumerate(values):
            if (
                value < lower - COORDINATE_TOLERANCE
                or value > upper + COORDINATE_TOLERANCE
            ):
                self.solver.add(z3.Not(flags[i]))
            for j in range(i + 1, len(values)):
                if values[j] - value >= self.aod.min_spacing - COORDINATE_TOLERANCE:
                    break
                self.solver.add(z3.Not(z3.And(flags[i], flags[j])))

    def _transition(self, t: int) -> None:
        kind = self.kind[t]
        self.solver.add(kind >= 0, kind <= 3)
        for before, after in (
            (self.columns[t], self.columns[t + 1]),
            (self.rows[t], self.rows[t + 1]),
        ):
            self.solver.add(
                z3.Implies(
                    kind == 0,
                    z3.And([a == b for a, b in zip(before, after, strict=True)]),
                ),
                z3.Implies(
                    kind == 1,
                    z3.And(
                        [z3.Implies(a, b) for a, b in zip(before, after, strict=True)]
                    ),
                ),
                z3.Implies(kind == 2, _count(before) == _count(after)),
                z3.Implies(
                    kind == 3,
                    z3.And(
                        [z3.Implies(b, a) for a, b in zip(before, after, strict=True)]
                    ),
                ),
            )
        for q in range(len(self.entry.atoms)):
            before, after = self.carried[t][q], self.carried[t + 1][q]
            same_position = z3.And(
                self.x[t][q] == self.x[t + 1][q], self.y[t][q] == self.y[t + 1][q]
            )
            self.solver.add(
                z3.Implies(kind == 0, before == after),
                z3.Implies(kind == 1, z3.Implies(before, after)),
                z3.Implies(kind == 2, before == after),
                z3.Implies(kind == 3, z3.Implies(after, before)),
                z3.Implies(z3.Or(kind != 2, z3.Not(before)), same_position),
            )
            for positions, ranks in (
                (self.x, self._column_ranks),
                (self.y, self._row_ranks),
            ):
                self.solver.add(
                    z3.Implies(
                        z3.And(kind == 2, before),
                        _lookup(positions[t][q], ranks[t])
                        == _lookup(positions[t + 1][q], ranks[t + 1]),
                    )
                )
        if self.aod.motion == "rigid":
            self._rigid(t)

    def _rigid(self, t: int) -> None:
        loaded = z3.Or(self.carried[t])
        for label, masks, values in (
            ("x", self.columns, self._xs),
            ("y", self.rows, self._ys),
        ):
            before, after = masks[t], masks[t + 1]
            self.solver.add(
                z3.Implies(
                    z3.And(self.kind[t] == 1, loaded),
                    z3.And([a == b for a, b in zip(before, after, strict=True)]),
                )
            )
            delta = z3.Real(f"td{label}_{t}")
            for i, flag in enumerate(before):
                self.solver.add(
                    z3.Implies(
                        z3.And(self.kind[t] == 2, flag),
                        z3.Or(
                            [
                                z3.And(target, values[j] == values[i] + delta)
                                for j, target in enumerate(after)
                            ]
                        ),
                    )
                )

    def touched(self, t: int, q: int) -> z3.BoolRef:
        """Return whether transition t reserves atom q against concurrent gates."""
        return z3.Or(
            z3.And(
                self.kind[t] == 1, z3.Not(self.carried[t][q]), self.carried[t + 1][q]
            ),
            z3.And(self.kind[t] == 2, self.carried[t][q]),
            z3.And(
                self.kind[t] == 3, self.carried[t][q], z3.Not(self.carried[t + 1][q])
            ),
        )

    def snapshot(self, model: z3.ModelRef, t: int) -> Snapshot:
        """Decode a satisfying assignment at state t without running transport."""
        return Snapshot(
            tuple(
                Position(
                    self.domain.xs[model.eval(self.x[t][q]).as_long()],
                    self.domain.ys[model.eval(self.y[t][q]).as_long()],
                )
                for q in range(len(self.entry.atoms))
            ),
            tuple(z3.is_true(model.eval(flag)) for flag in self.carried[t]),
            tuple(
                value
                for value, flag in zip(self.domain.xs, self.columns[t], strict=True)
                if z3.is_true(model.eval(flag))
            ),
            tuple(
                value
                for value, flag in zip(self.domain.ys, self.rows[t], strict=True)
                if z3.is_true(model.eval(flag))
            ),
        )

    def transition_names(self, model: z3.ModelRef) -> tuple[str, ...]:
        """Decode transport kinds in order, including explicit no-transport steps."""
        return tuple(_NAMES[model.eval(kind).as_long()] for kind in self.kind)
