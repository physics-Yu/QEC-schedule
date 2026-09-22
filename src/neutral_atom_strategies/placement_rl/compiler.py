"""Fast discrete compiler inspired by reuse, conflict graphs, and bounded IDS.

This is an original research abstraction, not the ZAC/QMAP implementations.
Fixed paired EZ traps define the interaction relation. Transport groups preserve
strict row/column identities and order, and validate every source/target Cartesian
intersection. Continuous paths, clearance, empty-AOD positioning, trap switching,
and optical interactions beyond the explicit EZ pairs are outside this model.
Consequently success and model microseconds are not physical validation or timing.
"""

from __future__ import annotations

from heapq import heappop, heappush, nsmallest
from itertools import combinations
from math import hypot, isclose, isfinite, sqrt
from typing import Any, Sequence

from .model import Circuit, CompileResult, CompilerConfig, Hardware, Point, Scenario

TRANSFER_US = 5.0
PULSE_US = 1.0
MOVE_US_PER_SQRT_UM = 2.0


def _sign(value: float) -> int:
    return (value > 0) - (value < 0)


def _pair_conflicts(a: Point, b: Point, ta: Point, tb: Point) -> bool:
    # Equality must be preserved both ways: neither split nor merge is allowed.
    return any(_sign(a[axis] - b[axis]) != _sign(ta[axis] - tb[axis]) for axis in (0, 1))


def conflict_graph(positions: Sequence[Point], targets: dict[int, Point]) -> dict[int, frozenset[int]]:
    """Pairwise row/column motion conflicts only; closure/capacity are separate."""
    graph: dict[int, set[int]] = {q: set() for q in targets}
    for a, b in combinations(targets, 2):
        if _pair_conflicts(positions[a], positions[b], targets[a], targets[b]):
            graph[a].add(b)
            graph[b].add(a)
    return {q: frozenset(neighbors) for q, neighbors in graph.items()}


def group_violation(hardware: Hardware, positions: Sequence[Point], targets: dict[int, Point]) -> str | None:
    """Return a discrete violation; a graph independent set alone is insufficient."""
    if not targets:
        return "EMPTY_GROUP"
    if any(isinstance(q, bool) or not isinstance(q, int) or not 0 <= q < len(positions) for q in targets):
        return "INVALID_QUBIT"
    if any(len(p) != 2 or not all(isinstance(x, (int, float)) and isfinite(x) for x in p)
           for p in targets.values()):
        return "INVALID_TARGET"
    allowed = set(hardware.storage) | {p for pair in hardware.entangling for p in pair}
    if any(tuple(p) not in allowed for p in targets.values()):
        return "TARGET_NOT_SLM"
    if len(set(tuple(p) for p in targets.values())) != len(targets):
        return "DUPLICATE_TARGET"
    rows = {positions[q][1] for q in targets}
    cols = {positions[q][0] for q in targets}
    target_rows = {targets[q][1] for q in targets}
    target_cols = {targets[q][0] for q in targets}
    if max(len(rows), len(target_rows)) > hardware.aod_rows or max(len(cols), len(target_cols)) > hardware.aod_cols:
        return "AOD_CAPACITY"
    for a, b in combinations(targets, 2):
        if _pair_conflicts(positions[a], positions[b], targets[a], targets[b]):
            return "AXIS_SPLIT_MERGE_OR_CROSSING"
    for axis_values in (rows, cols, target_rows, target_cols):
        ordered = sorted(axis_values)
        if any(b - a < hardware.min_axis_separation_um for a, b in zip(ordered, ordered[1:])):
            return "AOD_AXIS_MINIMUM_SEPARATION"
    for q, point in enumerate(positions):
        if q in targets:
            continue
        if point[0] in cols and point[1] in rows:
            return "SOURCE_CAPTURE_CLOSURE"
        if point[0] in target_cols and point[1] in target_rows:
            return "TARGET_STATIONARY_INTERSECTION"
    return None


def _initial(circuit: Circuit, hardware: Hardware, mapping: Sequence[int]) -> list[Point]:
    if len(hardware.storage) < circuit.n_qubits:
        raise ValueError("storage capacity is smaller than the number of qubits")
    if len(mapping) != circuit.n_qubits or any(isinstance(i, bool) or not isinstance(i, int)
                                               or not 0 <= i < len(hardware.storage) for i in mapping):
        raise ValueError("mapping must contain one valid storage-site integer per qubit")
    if len(set(mapping)) != len(mapping):
        raise ValueError("mapping must be injective")
    return [hardware.storage[i] for i in mapping]


class _Builder:
    def __init__(self, hardware: Hardware, scenario: Scenario, positions: list[Point]) -> None:
        self.hardware = hardware
        self.scenario = scenario
        self.positions = positions
        self.trace: list[dict[str, Any]] = []
        self.duration = 0.0
        self.groups = 0
        self.reused = 0
        self.distance = 0.0

    def clone(self) -> _Builder:
        other = _Builder(self.hardware, self.scenario, self.positions.copy())
        other.trace = self.trace.copy()
        other.duration, other.groups = self.duration, self.groups
        other.reused, other.distance = self.reused, self.distance
        return other

    def event(self, kind: str, duration: float, **kwargs: Any) -> None:
        self.trace.append(dict(kind=kind, start_us=self.duration, duration_us=duration, **kwargs))
        self.duration += duration

    def transport(self, targets: dict[int, Point], phase: str) -> None:
        pending = {q: p for q, p in targets.items() if self.positions[q] != p}
        while pending:
            graph = conflict_graph(self.positions, pending)
            order = sorted(pending)
            if self.scenario.grouping_order == "reverse":
                order.reverse()
            elif self.scenario.grouping_order in {"longest", "shortest"}:
                order.sort(key=lambda q: (hypot(self.positions[q][0] - pending[q][0],
                                               self.positions[q][1] - pending[q][1]), q),
                           reverse=self.scenario.grouping_order == "longest")
            group: dict[int, Point] = {}
            for q in order:
                if any(neighbor in group for neighbor in graph[q]):
                    continue
                proposal = {**group, q: pending[q]}
                if group_violation(self.hardware, self.positions, proposal) is None:
                    group = proposal
            if not group:
                raise RuntimeError("NO_LEGAL_TRANSPORT_GROUP")
            qubits = list(group)
            sources = [self.positions[q] for q in qubits]
            destinations = [group[q] for q in qubits]
            distances = [hypot(s[0] - t[0], s[1] - t[1]) for s, t in zip(sources, destinations)]
            # The longest active trap can be an EMPTY Cartesian intersection.
            # Its x and y displacements may originate from different atoms.
            grid_distance = hypot(max(abs(s[0] - t[0]) for s, t in zip(sources, destinations)),
                                  max(abs(s[1] - t[1]) for s, t in zip(sources, destinations)))
            move_duration = MOVE_US_PER_SQRT_UM * sqrt(grid_distance) * self.scenario.move_scale
            transfer_duration = TRANSFER_US * self.scenario.transfer_scale
            common = dict(group=self.groups, qubits=qubits, phase=phase)
            self.event("load", transfer_duration, positions=sources, **common)
            self.event("move", move_duration, sources=sources, positions=destinations, **common)
            self.event("unload", transfer_duration, positions=destinations, **common)
            self.groups += 1
            self.distance += sum(distances)
            for q, p in group.items():
                self.positions[q] = p
                del pending[q]

    def park(self, qubits: list[int]) -> None:
        occupied = set(self.positions)
        free = set(self.hardware.storage) - occupied
        if len(free) < len(qubits):
            raise RuntimeError("STORAGE_CAPACITY")
        targets = {}
        for q in sorted(qubits):
            source = self.positions[q]
            target = min(free, key=lambda p: (hypot(source[0] - p[0], source[1] - p[1]), p))
            targets[q] = target
            free.remove(target)
        self.transport(targets, "parking")


def _service(builder: _Builder, gates: tuple[tuple[int, int], ...], layer: int,
             gate_indices: tuple[int, ...], assignments: tuple[tuple[int, bool], ...],
             config: CompilerConfig) -> _Builder:
    out = builder.clone()
    desired: dict[int, Point] = {}
    for gate, (site, reverse) in zip(gates, assignments):
        pair = out.hardware.entangling[site]
        for q, p in zip(gate, pair[::-1] if reverse else pair):
            desired[q] = p
    ez = {p for pair in out.hardware.entangling for p in pair}
    retained = {q for q, p in desired.items() if config.reuse and out.positions[q] == p}
    out.reused += len(retained)
    out.park([q for q, p in enumerate(out.positions) if p in ez and q not in retained])
    out.transport({q: p for q, p in desired.items() if q not in retained}, "inbound")
    out.event("pulse", PULSE_US, layer=layer, gate_indices=list(gate_indices), pairs=list(gates))
    return out


def _search_service(builder: _Builder, gates: tuple[tuple[int, int], ...], layer: int,
                    gate_indices: tuple[int, ...], config: CompilerConfig) -> tuple[_Builder, int, int]:
    """Bounded iterative diving: greedily finish a node, retain bounded alternatives.

    Scores order partial alternatives; only full, discretely routed leaves compete.
    The budget is completed leaves, and truncation never implies infeasibility.
    """
    serial = 0
    frontier: list[tuple[float, int, tuple[tuple[int, bool], ...]]] = [(0.0, serial, ())]
    best: _Builder | None = None
    leaves = nodes = 0
    while frontier and leaves < config.trials:
        prefix_cost, _, assignments = heappop(frontier)
        while len(assignments) < len(gates):
            nodes += 1
            used = {site for site, _ in assignments}
            a, b = gates[len(assignments)]
            options = []
            for site, pair in enumerate(builder.hardware.entangling):
                if site in used:
                    continue
                for reverse in (False, True):
                    points = pair[::-1] if reverse else pair
                    cost = 0.0
                    moves: dict[int, Point] = {}
                    for q, p in zip((a, b), points):
                        source = builder.positions[q]
                        if config.reuse and source == p:
                            continue
                        cost += 2.0 * TRANSFER_US * builder.scenario.transfer_scale
                        cost += MOVE_US_PER_SQRT_UM * sqrt(hypot(source[0] - p[0], source[1] - p[1])) * builder.scenario.move_scale
                        moves[q] = p
                    # A compatible pair saves one transfer pair and one move slot.
                    if len(moves) == 2 and not _pair_conflicts(builder.positions[a], builder.positions[b], moves[a], moves[b]):
                        cost -= 2.0 * TRANSFER_US * builder.scenario.transfer_scale
                    options.append((cost, site, reverse))
            options.sort()
            eligible_sites = []
            for _, site, _ in options:
                if site not in eligible_sites:
                    eligible_sites.append(site)
            allowed_sites = set(eligible_sites[:config.site_limit])
            options = [item for item in options if item[1] in allowed_sites]
            if not options:
                break
            for cost, site, reverse in options[1:]:
                serial += 1
                heappush(frontier, (prefix_cost + cost, serial, assignments + ((site, reverse),)))
            if len(frontier) > config.queue_capacity:
                frontier = nsmallest(config.queue_capacity, frontier)
                # nsmallest returns a sorted list, which is also a valid min-heap.
            cost, site, reverse = options[0]
            prefix_cost += cost
            assignments += ((site, reverse),)
        if len(assignments) != len(gates):
            continue
        leaves += 1
        try:
            candidate = _service(builder, gates, layer, gate_indices, assignments, config)
        except RuntimeError:
            continue
        if best is None or candidate.duration < best.duration:
            best = candidate
    if best is None:
        raise RuntimeError("BOUNDED_PLACEMENT_SEARCH_EXHAUSTED")
    return best, leaves, nodes


def _finish(builder: _Builder, circuit: Circuit, config: CompilerConfig) -> None:
    storage = set(builder.hardware.storage)
    if config.terminal == "storage":
        builder.park([q for q, p in enumerate(builder.positions) if p not in storage])
        return
    # Canonical absolute terminal supports full storage occupancy via an explicit
    # vacant EZ trap as temporary buffer. Cycles do not become free permutations.
    goal = builder.hardware.storage[:circuit.n_qubits]
    for _ in range(3 * circuit.n_qubits + 1):
        wrong = [q for q, p in enumerate(builder.positions) if p != goal[q]]
        if not wrong:
            return
        occupied = set(builder.positions)
        targets = {q: goal[q] for q in wrong if goal[q] not in occupied}
        if targets:
            builder.transport(targets, "terminal")
            continue
        free = [p for pair in builder.hardware.entangling for p in pair if p not in occupied]
        movable = [q for q in wrong if builder.positions[q] in storage]
        if not free or not movable:
            raise RuntimeError("CANONICAL_TERMINAL_BUFFER_UNAVAILABLE")
        builder.transport({movable[0]: free[0]}, "terminal_buffer")
    raise RuntimeError("CANONICAL_TERMINAL_LIMIT")


def compile_layout(circuit: Circuit, hardware: Hardware, mapping: tuple[int, ...],
                   scenario: Scenario = Scenario("nominal"),
                   config: CompilerConfig = CompilerConfig()) -> CompileResult:
    """Compile fixed ordered CZ layers in the stated discrete research model."""
    builder = _Builder(hardware, scenario, _initial(circuit, hardware, mapping))
    search_leaves = search_nodes = 0
    error = None
    try:
        width = len(hardware.entangling)
        for layer_index, layer in enumerate(circuit.layers):
            for start in range(0, len(layer), width):
                gates = layer[start:start + width]
                builder, leaves, nodes = _search_service(builder, gates, layer_index,
                                                         tuple(range(start, start + len(gates))), config)
                search_leaves += leaves
                search_nodes += nodes
        _finish(builder, circuit, config)
    except RuntimeError as exc:
        error = str(exc)
    metrics = dict(transport_groups=builder.groups,
                   pulse_count=sum(event["kind"] == "pulse" for event in builder.trace),
                   reused_atoms=builder.reused, search_leaves=search_leaves,
                   search_nodes=search_nodes, atom_distance_um=builder.distance,
                   model_only=True, continuous_safety_checked=False,
                   timing_model="5us transfer; 2sqrt(longest_active_trap_distance_um)us move; 1us pulse",
                   omitted_timing=["empty_aod_reposition", "trap_switching"],
                   terminal=config.terminal)
    return CompileResult("failed" if error else "completed", builder.duration, metrics,
                         tuple(builder.trace), tuple(builder.positions), error)


def audit_result(circuit: Circuit, hardware: Hardware, mapping: tuple[int, ...],
                 result: CompileResult, scenario: Scenario = Scenario("nominal"),
                 config: CompilerConfig = CompilerConfig()) -> dict[str, Any]:
    """Independent discrete trace replay; does not call compiler/group validators.

    Checks source and holder provenance, strict axis maps, all active intersections,
    exact CZ layer coverage, model timing, final state, and declared terminal mode.
    """
    positions = _initial(circuit, hardware, mapping)
    errors: list[str] = []
    completed: set[tuple[int, int]] = set()
    expected = {(li, gi) for li, layer in enumerate(circuit.layers) for gi in range(len(layer))}
    elapsed = 0.0
    stage = "idle"
    loaded: list[int] = []
    sources: list[Point] = []
    group_id = -1
    groups = pulses = 0
    atom_distance = 0.0
    slm = set(hardware.storage) | {p for pair in hardware.entangling for p in pair}
    ez = {p for pair in hardware.entangling for p in pair}
    try:
        for index, event in enumerate(result.trace):
            def require(condition: bool, message: str) -> None:
                if not condition:
                    raise ValueError(f"event {index}: {message}")

            start, duration = event["start_us"], event["duration_us"]
            require(isfinite(start) and isfinite(duration) and duration >= 0, "invalid timing")
            require(isclose(start, elapsed, abs_tol=1e-8), "nonserial event start")
            kind = event["kind"]
            if kind in {"load", "move", "unload"}:
                qubits = event["qubits"]
                points = [tuple(p) for p in event["positions"]]
                require(bool(qubits) and len(qubits) == len(set(qubits)), "empty or duplicate transport qubits")
                require(all(isinstance(q, int) and not isinstance(q, bool) and 0 <= q < circuit.n_qubits for q in qubits), "invalid transport qubit")
                require(len(points) == len(qubits) and all(len(p) == 2 and all(isfinite(v) for v in p) for p in points), "invalid transport points")
                require(len(points) == len(set(points)), "duplicate transport position")
                if kind == "load":
                    require(stage == "idle", "load while AOD occupied")
                    require(all(positions[q] == p and p in slm for q, p in zip(qubits, points)), "load source/support mismatch")
                    require(event["group"] == group_id + 1, "nonsequential group id")
                    group_id = event["group"]
                    loaded, sources = list(qubits), points
                    xs, ys = {p[0] for p in points}, {p[1] for p in points}
                    require(len(xs) <= hardware.aod_cols and len(ys) <= hardware.aod_rows, "source AOD capacity")
                    for values in (sorted(xs), sorted(ys)):
                        require(all(b - a >= hardware.min_axis_separation_um for a, b in zip(values, values[1:])), "source minimum axis separation")
                    actual = {q for q, p in enumerate(positions) if p[0] in xs and p[1] in ys}
                    require(actual == set(loaded), "source Cartesian capture closure")
                    stage = "loaded"
                    target_duration = TRANSFER_US * scenario.transfer_scale
                else:
                    require(qubits == loaded and event["group"] == group_id, "group identity mismatch")
                    if kind == "move":
                        require(stage == "loaded", "move requires loaded AOD")
                        require([tuple(p) for p in event["sources"]] == sources, "move source mismatch")
                        require(all(p in slm for p in points), "unknown target SLM")
                        # Validate each axis as a strictly increasing, injective map.
                        for axis, limit in ((0, hardware.aod_cols), (1, hardware.aod_rows)):
                            axis_map: dict[float, float] = {}
                            for source, target in zip(sources, points):
                                require(source[axis] not in axis_map or axis_map[source[axis]] == target[axis], "axis split")
                                axis_map[source[axis]] = target[axis]
                            ordered = [axis_map[x] for x in sorted(axis_map)]
                            require(len(ordered) <= limit and all(a < b for a, b in zip(ordered, ordered[1:])), "axis merge/crossing/capacity")
                            require(all(b - a >= hardware.min_axis_separation_um for a, b in zip(ordered, ordered[1:])), "target minimum axis separation")
                        xs, ys = {p[0] for p in points}, {p[1] for p in points}
                        require(all(q in loaded or p[0] not in xs or p[1] not in ys for q, p in enumerate(positions)), "target Cartesian stationary intersection")
                        distances = [hypot(source[0] - target[0], source[1] - target[1]) for source, target in zip(sources, points)]
                        atom_distance += sum(distances)
                        x_displacements = [abs(target[0] - source[0]) for source, target in zip(sources, points)]
                        y_displacements = [abs(target[1] - source[1]) for source, target in zip(sources, points)]
                        full_grid_distance = hypot(max(x_displacements), max(y_displacements))
                        target_duration = MOVE_US_PER_SQRT_UM * sqrt(full_grid_distance) * scenario.move_scale
                        for q, p in zip(loaded, points):
                            positions[q] = p
                        stage = "moved"
                    else:
                        require(stage == "moved", "unload requires completed move")
                        require(all(positions[q] == p and p in slm for q, p in zip(qubits, points)), "unload support mismatch")
                        loaded, sources, stage = [], [], "idle"
                        groups += 1
                        target_duration = TRANSFER_US * scenario.transfer_scale
                require(isclose(duration, target_duration, abs_tol=1e-8), "transport duration mismatch")
            elif kind == "pulse":
                require(stage == "idle", "pulse requires empty AOD")
                layer, ids = event["layer"], event["gate_indices"]
                require(isinstance(layer, int) and 0 <= layer < len(circuit.layers), "invalid layer")
                require(bool(ids) and len(ids) == len(set(ids)), "empty/duplicate pulse gate ids")
                require(all(isinstance(gi, int) and 0 <= gi < len(circuit.layers[layer]) for gi in ids), "invalid gate id")
                keys = {(layer, gi) for gi in ids}
                require(not keys & completed, "repeated gate")
                require(all(key in completed for key in expected if key[0] < layer), "layer dependency violation")
                intended = {tuple(sorted(circuit.layers[layer][gi])) for gi in ids}
                require([tuple(g) for g in event["pairs"]] == [circuit.layers[layer][gi] for gi in ids], "declared gate mismatch")
                occupancy = {p: q for q, p in enumerate(positions)}
                actual = {tuple(sorted((occupancy[pair[0]], occupancy[pair[1]])))
                          for pair in hardware.entangling if pair[0] in occupancy and pair[1] in occupancy}
                require(actual == intended, "actual CZ pairs differ from intended pairs")
                active = {q for pair in intended for q in pair}
                require({q for q, p in enumerate(positions) if p in ez} == active, "unexpected EZ residents at pulse")
                require(isclose(duration, PULSE_US, abs_tol=1e-8), "pulse duration mismatch")
                completed.update(keys)
                pulses += 1
            else:
                raise ValueError(f"event {index}: unknown event kind {kind!r}")
            elapsed += duration
        if result.status != "completed" or result.error is not None:
            errors.append("compiler did not report completed")
        if stage != "idle" or loaded:
            errors.append("AOD remains loaded or operation incomplete")
        if completed != expected:
            errors.append("gate coverage differs from circuit")
        if tuple(positions) != tuple(tuple(p) for p in result.final_positions):
            errors.append("reported final positions disagree with trace")
        if len(set(positions)) != circuit.n_qubits:
            errors.append("duplicate final occupancy")
        if config.terminal == "canonical":
            if tuple(positions) != hardware.storage[:circuit.n_qubits]:
                errors.append("canonical absolute terminal mismatch")
        elif any(p not in hardware.storage for p in positions):
            errors.append("storage terminal mismatch")
        if not isfinite(result.duration_us) or not isclose(elapsed, result.duration_us, abs_tol=1e-8):
            errors.append("reported duration differs from trace")
        for key, expected_value in (("transport_groups", groups), ("pulse_count", pulses)):
            if result.metrics.get(key) != expected_value:
                errors.append(f"reported {key} differs from trace")
        if not isclose(result.metrics.get("atom_distance_um", -1.0), atom_distance, abs_tol=1e-8):
            errors.append("reported atom distance differs from trace")
    except (KeyError, TypeError, ValueError, IndexError, OverflowError) as exc:
        errors.append(str(exc))
    return dict(status="failed" if errors else "passed", ok=not errors, errors=errors, duration_us=elapsed, gates_checked=len(completed),
                transport_groups=groups, model_only=True, continuous_safety_checked=False)
