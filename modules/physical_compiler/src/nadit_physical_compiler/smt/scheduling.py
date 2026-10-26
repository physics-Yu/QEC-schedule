"""Native dependencies, exact CZ illumination, readout and synchronous timing."""

from collections import defaultdict
from itertools import combinations

import z3

from ..compilers.contracts import ProgramContext
from .expressions import (
    distance_table,
    inside,
    maximum,
    segment_tables,
    squared_differences,
    ticks,
)
from .transport import TransportModel


class ScheduleModel:
    """Assign each native operation once and combine it with transport steps."""

    def __init__(
        self, solver: z3.Solver, context: ProgramContext, transport: TransportModel
    ) -> None:
        self.solver, self.context, self.transport = solver, context, transport
        self.domain, self.device = transport.domain, context.device
        self.when = [z3.Int(f"op_{node.id}") for node in context.dag.nodes]
        self.step_ticks = [z3.Int(f"duration_{t}") for t in range(self.domain.horizon)]
        self.total_ticks = z3.Sum(self.step_ticks)
        self.atom_index = {
            atom.id: i for i, atom in enumerate(context.entry_state.atoms)
        }
        self.node_atoms = [
            tuple(
                self.atom_index[context.entry_state.qubit_to_atom[q]]
                for q in node.qubits
            )
            for node in context.dag.nodes
        ]
        self._distances: dict[tuple[int, int, int, int], z3.ArithRef] = {}
        self._coverage: dict[tuple[int, int], z3.BoolRef] = {}
        self._cz_nodes = tuple(node for node in context.dag.nodes if node.name == "cz")
        self._cz_by_pair: dict[tuple[int, ...], list[int]] = defaultdict(list)
        self._cz_by_atom: dict[int, list[int]] = defaultdict(list)
        for node in self._cz_nodes:
            atoms = self.node_atoms[node.id]
            self._cz_by_pair[tuple(sorted(atoms))].append(node.id)
            for atom in atoms:
                self._cz_by_atom[atom].append(node.id)
        self._measurements = tuple(
            node.id for node in context.dag.nodes if node.name == "measure"
        )
        self._scheduled = [
            [value == t for value in self.when] for t in range(self.domain.horizon)
        ]
        self.x2 = squared_differences(self.domain.xs)
        self.y2 = squared_differences(self.domain.ys)
        self.move_table = distance_table(
            self.domain.xs,
            self.domain.ys,
            self.device.timing,
            self.domain.time_quantum_us,
        )
        self.cz_regions = tuple(
            zone.bounds for zone in self.device.zones if "cz" in zone.operations
        )
        self.slabs = [
            (
                segment_tables(self.domain.xs, r.x_min, r.x_max),
                segment_tables(self.domain.ys, r.y_min, r.y_max),
            )
            for r in self.cz_regions
        ]
        self.durations = [self._duration(node.name) for node in context.dag.nodes]
        self._dependencies()
        self._idle_suffix()
        for t in range(self.domain.horizon):
            self._step(t)
        self.total_ticks = self._completion_ticks()

    def _completion_ticks(self) -> z3.ArithRef:
        """Include final readout availability in the result completion time."""
        elapsed = z3.Sum(self.step_ticks)
        if not self._measurements:
            return elapsed
        assert self.device.readout is not None
        starts = [z3.IntVal(0)]
        for duration in self.step_ticks[:-1]:
            starts.append(starts[-1] + duration)
        quantum = self.domain.time_quantum_us
        readout_ticks = ticks(self.device.readout.duration_us, quantum)
        latency_ticks = ticks(self.device.readout.latency_us, quantum)
        available = []
        for source in self._measurements:
            start = starts[-1]
            for t in range(len(starts) - 2, -1, -1):
                start = z3.If(self.when[source] == t, starts[t], start)
            available.append(start + readout_ticks + latency_ticks)
        return maximum([elapsed, *available])

    def _dependencies(self) -> None:
        earliest = [0] * len(self.when)
        tail = [0] * len(self.when)
        # PhysicalDAG guarantees forward, source-sorted edges.
        for source, target in self.context.dag.edges:
            earliest[target] = max(earliest[target], earliest[source] + 1)
        for source, target in reversed(self.context.dag.edges):
            tail[source] = max(tail[source], tail[target] + 1)
        for index, value in enumerate(self.when):
            self.solver.add(
                value >= earliest[index],
                value < self.domain.horizon - tail[index],
            )
        for source, target in self.context.dag.edges:
            # Metadata still provides a barrier boundary, without a pulse.
            self.solver.add(self.when[source] < self.when[target])
        for a, b in combinations(range(len(self.when)), 2):
            if set(self.node_atoms[a]) & set(self.node_atoms[b]):
                self.solver.add(self.when[a] != self.when[b])

    def _idle_suffix(self) -> None:
        """Move empty identity steps to the suffix without changing elapsed time.

        Metadata counts as an operation. A no-transport step with no operation
        changes no state and consumes zero time, so shifting it past later steps
        preserves dependencies, geometry, and every action duration.
        """
        empty = [
            z3.And(self.transport.kind[t] == 0, z3.Not(z3.Or(scheduled)))
            for t, scheduled in enumerate(self._scheduled)
        ]
        for current, following in zip(empty, empty[1:], strict=False):
            self.solver.add(z3.Implies(current, following))

    def _duration(self, name: str) -> float:
        if name == "cz":
            assert self.device.cz is not None
            return self.device.cz.duration_us
        if name == "measure":
            assert self.device.readout is not None
            return self.device.readout.duration_us
        if name in ("barrier", "global_phase"):
            return 0
        assert self.device.local is not None
        return (
            self.device.local.reset_us
            if name == "reset"
            else self.device.local.rotation_us
        )

    def _distance2(self, t: int, q: int, other_t: int, other_q: int) -> z3.ArithRef:
        if (other_t, other_q) < (t, q):
            t, q, other_t, other_q = other_t, other_q, t, q
        key = (t, q, other_t, other_q)
        if key in self._distances:
            return self._distances[key]
        tm = self.transport
        value = z3.Select(
            self.x2, tm.x[t][q] * len(self.domain.xs) + tm.x[other_t][other_q]
        ) + z3.Select(
            self.y2, tm.y[t][q] * len(self.domain.ys) + tm.y[other_t][other_q]
        )
        self._distances[key] = value
        return value

    def _covered(self, t: int, q: int) -> z3.BoolRef:
        key = (t, q)
        if key not in self._coverage:
            tm = self.transport
            self._coverage[key] = z3.Or(
                [inside(tm.px[t][q], tm.py[t][q], r) for r in self.cz_regions]
            )
        return self._coverage[key]

    def _step(self, t: int) -> None:
        tm, domain = self.transport, self.domain
        scheduled = self._scheduled[t]
        for node in self.context.dag.nodes:
            if node.name in ("barrier", "global_phase"):
                continue
            for atom in self.node_atoms[node.id]:
                self.solver.add(
                    z3.Implies(scheduled[node.id], z3.Not(tm.touched(t, atom)))
                )
            if node.name != "cz":
                self._addressed(t, node.id, scheduled[node.id])
        self._cz(t, scheduled)
        self._measure(t, scheduled)
        d2 = maximum(
            [
                z3.If(tm.carried[t][q], self._distance2(t, q, t + 1, q), 0)
                for q in range(len(tm.entry.atoms))
            ]
        )
        move_ticks = z3.Select(self.move_table, d2)
        transport_ticks = z3.If(
            tm.kind[t] == 1,
            ticks(self.device.timing.load_us, domain.time_quantum_us),
            z3.If(
                tm.kind[t] == 3,
                ticks(self.device.timing.store_us, domain.time_quantum_us),
                z3.If(tm.kind[t] == 2, move_ticks, 0),
            ),
        )
        gate_ticks = [
            z3.If(scheduled[i], ticks(value, domain.time_quantum_us), 0)
            for i, value in enumerate(self.durations)
        ]
        self.solver.add(self.step_ticks[t] == maximum([transport_ticks, *gate_ticks]))

    def _addressed(self, t: int, index: int, active: z3.BoolRef) -> None:
        node = self.context.dag.nodes[index]
        name = (
            "measure"
            if node.name == "measure"
            else "reset"
            if node.name == "reset"
            else "rotate"
        )
        capability = self.device.readout if name == "measure" else self.device.local
        assert capability is not None
        tm = self.transport
        for q in self.node_atoms[index]:
            permitted = z3.Or(
                [
                    inside(tm.px[t][q], tm.py[t][q], zone.bounds)
                    for zone in self.device.zones
                    if name in zone.operations
                ]
            )
            holders = z3.Or(
                [
                    tm.carried[t][q] if h == "aod" else z3.Not(tm.carried[t][q])
                    for h in capability.holders
                ]
            )
            self.solver.add(z3.Implies(active, z3.And(permitted, holders)))

    def _measure(self, t: int, scheduled: list[z3.BoolRef]) -> None:
        cap = self.device.readout
        measurements = self._measurements
        if cap is None:
            return
        if cap.max_atoms is not None:
            self.solver.add(
                z3.Sum([z3.If(scheduled[i], 1, 0) for i in measurements])
                <= cap.max_atoms
            )
        for a, b in combinations(measurements, 2):
            qa, qb = self.node_atoms[a][0], self.node_atoms[b][0]
            self.solver.add(
                z3.Implies(
                    z3.And(scheduled[a], scheduled[b]),
                    self._distance2(t, qa, t, qb) >= cap.min_spacing_um**2,
                )
            )

    def _cz(self, t: int, scheduled: list[z3.BoolRef]) -> None:
        nodes = self._cz_nodes
        if not nodes:
            return
        cap, tm = self.device.cz, self.transport
        assert cap is not None
        pulse = z3.Or([scheduled[node.id] for node in nodes])
        for a, b in combinations(range(len(tm.entry.atoms)), 2):
            wanted = z3.Or(
                [scheduled[index] for index in self._cz_by_pair.get((a, b), ())]
            )
            actual = z3.And(
                self._covered(t, a),
                self._covered(t, b),
                self._distance2(t, a, t, b) <= cap.radius_um**2,
            )
            self.solver.add(z3.Implies(pulse, actual == wanted))
        for node in nodes:
            a, b = self.node_atoms[node.id]
            regions = z3.Or(
                [
                    z3.And(
                        inside(tm.px[t][a], tm.py[t][a], region),
                        inside(tm.px[t][b], tm.py[t][b], region),
                    )
                    for region in self.cz_regions
                ]
            )
            holders = []
            for h1, h2 in cap.holder_pairs:
                for left, right in ((h1, h2), (h2, h1)):
                    holders.append(
                        z3.And(
                            tm.carried[t][a] == (left == "aod"),
                            tm.carried[t][b] == (right == "aod"),
                        )
                    )
            self.solver.add(
                z3.Implies(scheduled[node.id], z3.And(regions, z3.Or(holders)))
            )
        for q in range(len(tm.entry.atoms)):
            if not cap.allow_spectators:
                participant = z3.Or(
                    [scheduled[index] for index in self._cz_by_atom.get(q, ())]
                )
                self.solver.add(
                    z3.Implies(z3.And(pulse, self._covered(t, q)), participant)
                )
            crossings = []
            for (xlo, xhi), (ylo, yhi) in self.slabs:
                xi = tm.x[t][q] * len(self.domain.xs) + tm.x[t + 1][q]
                yi = tm.y[t][q] * len(self.domain.ys) + tm.y[t + 1][q]
                xl, xh, yl, yh = (
                    z3.Select(xlo, xi),
                    z3.Select(xhi, xi),
                    z3.Select(ylo, yi),
                    z3.Select(yhi, yi),
                )
                crossings.append(z3.And(xl <= xh, yl <= yh, xl <= yh, yl <= xh))
            self.solver.add(
                z3.Implies(
                    z3.And(pulse, tm.kind[t] == 2, tm.carried[t][q]),
                    z3.Not(z3.Or(crossings)),
                )
            )

    def extract(self, model: z3.ModelRef) -> tuple[tuple[int, ...], ...]:
        """Read parallel native operation IDs from a SAT model."""
        groups: list[list[int]] = [[] for _ in range(self.domain.horizon)]
        for index, value in enumerate(self.when):
            groups[model.eval(value).as_long()].append(index)
        return tuple(tuple(group) for group in groups)
