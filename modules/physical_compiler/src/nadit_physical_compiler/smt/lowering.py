"""Lower a solved finite-domain schedule without making scheduling choices."""

from collections import defaultdict
from dataclasses import replace
from math import hypot

from ..atom_ir import (
    AtomAction,
    AtomProgram,
    AtomStep,
    CZPulse,
    Load,
    LocalU,
    Measure,
    Move,
    Reset,
    Rotation,
    Store,
)
from ..compiler import CompilationResult, CompiledOperation, MeasurementRecord
from ..compilers.contracts import ProgramContext
from ..contracts import GateLayer
from ..coverage import RegionSet
from ..emission.actions import emit_layer
from ..execution import MeasurementBackend
from ..replay import apply_step
from ..state import AODGrid, AODHolder, AODLine, AtomLayout, SLMHolder
from .contracts import Plan, Snapshot


def lower_plan(
    context: ProgramContext, plan: Plan, case: MeasurementBackend
) -> CompilationResult:
    """Translate solved steps, preserving line identities and measurement IDs.

    Args:
        context: Native circuit, Device, and explicit initial atom layout.
        plan: Validated endpoint states and parallel native operation groups.
        case: Measurement values, queried once per emitted measurement identity.

    Returns:
        Timed Atom IR with records and replayed final layout. Timing uses Device
        functions directly; integer solver time bounds are not pulse durations.
    """
    layout = context.entry_state
    lines = _GridLines(layout.grid(context.aod_id))
    steps: list[AtomStep] = []
    records: dict[int, CompiledOperation] = {}
    measurements: list[MeasurementRecord] = []
    layers: list[GateLayer] = []
    time_us = 0.0
    phase = context.dag.global_phase
    for index, (transition, operations) in enumerate(
        zip(plan.transitions, plan.operations, strict=True)
    ):
        following = plan.states[index + 1]
        actions: list[AtomAction] = []
        if transition != "none":
            actions.append(_transport(context, layout, following, transition, lines))
        native = tuple(
            source
            for source in operations
            if context.dag.nodes[source].name not in ("barrier", "global_phase")
        )
        actions.extend(_native_actions(context, layout, native))
        for action in actions:
            for source in action.source_ids:
                records[source] = CompiledOperation(
                    source, "emitted", time_us, time_us + action.duration_us
                )
            if isinstance(action, Measure):
                assert context.device.readout is not None
                available = (
                    time_us + action.duration_us + context.device.readout.latency_us
                )
                for _, reference in action.results:
                    value = case.measure(reference)
                    if value not in (0, 1):
                        raise ValueError(f"Measurement {reference} returned a non-bit.")
                    measurements.append(MeasurementRecord(reference, value, available))
        for source in operations:
            node = context.dag.nodes[source]
            if node.name in ("barrier", "global_phase"):
                records[source] = CompiledOperation(
                    source, "metadata", time_us, time_us
                )
                if node.name == "global_phase":
                    phase += node.params[0]
        if native:
            layers.append(GateLayer(native))
        step = AtomStep(tuple(actions))
        steps.append(step)
        layout = apply_step(layout, step, context.device)
        time_us += step.duration_us
    return CompilationResult(
        AtomProgram(tuple(steps), phase),
        layout,
        tuple(records[source] for source in sorted(records)),
        tuple(measurements),
        tuple(layers),
    )


class _GridLines:
    """Maintain stable active line IDs, including unoccupied lines."""

    def __init__(self, grid: AODGrid) -> None:
        self.grid = grid
        self.next_row = max((line.id for line in grid.rows), default=-1) + 1
        self.next_column = max((line.id for line in grid.columns), default=-1) + 1

    def advance(self, target: Snapshot, transition: str) -> AODGrid:
        """Move by spatial rank; add on load and remove on store by coordinate."""
        rows, self.next_row = _axis_lines(
            self.grid.rows, target.rows, transition, self.next_row
        )
        columns, self.next_column = _axis_lines(
            self.grid.columns, target.columns, transition, self.next_column
        )
        self.grid = AODGrid(self.grid.aod_id, rows, columns)
        return self.grid


def _axis_lines(
    previous: tuple[AODLine, ...],
    coordinates: tuple[float, ...],
    transition: str,
    next_id: int,
) -> tuple[tuple[AODLine, ...], int]:
    if transition == "move":
        ordered = sorted(previous, key=lambda line: line.coordinate)
        return tuple(
            AODLine(line.id, coordinate)
            for line, coordinate in zip(ordered, coordinates, strict=True)
        ), next_id
    old = {line.coordinate: line for line in previous}
    result = []
    for coordinate in coordinates:
        if coordinate in old:
            result.append(old[coordinate])
        elif transition == "load":
            result.append(AODLine(next_id, coordinate))
            next_id += 1
        else:
            raise ValueError("A store cannot introduce an active AOD line.")
    return tuple(result), next_id


def _transport(
    context: ProgramContext,
    layout: AtomLayout,
    target: Snapshot,
    transition: str,
    lines: _GridLines,
) -> Load | Move | Store:
    grid = lines.advance(target, transition)
    timing = context.device.timing
    if transition == "load":
        rows = {line.coordinate: line.id for line in grid.rows}
        columns = {line.coordinate: line.id for line in grid.columns}
        load_bindings = tuple(
            (atom.id, rows[atom.position.y], columns[atom.position.x])
            for atom, carried in zip(layout.atoms, target.carried, strict=True)
            if carried and isinstance(atom.holder, SLMHolder)
        )
        return Load(grid, load_bindings, duration_us=timing.load_us)
    if transition == "move":
        targets = tuple(
            (atom.id, position)
            for atom, position, carried in zip(
                layout.atoms, target.positions, target.carried, strict=True
            )
            if carried
        )
        positions = {atom.id: atom.position for atom in layout.atoms}
        distance = max(
            (
                hypot(
                    position.x - positions[atom].x,
                    position.y - positions[atom].y,
                )
                for atom, position in targets
            ),
            default=0.0,
        )
        return Move(grid, targets, duration_us=timing.move_duration(distance))
    if transition == "store":
        sites = {site.position: site.id for site in context.device.slm_sites}
        store_bindings = tuple(
            (atom.id, sites[position])
            for atom, position, carried in zip(
                layout.atoms, target.positions, target.carried, strict=True
            )
            if not carried and isinstance(atom.holder, AODHolder)
        )
        return Store(grid, store_bindings, duration_us=timing.store_us)
    raise ValueError(f"Unknown SMT transport transition {transition!r}.")


def _native_actions(
    context: ProgramContext, layout: AtomLayout, sources: tuple[int, ...]
) -> tuple[AtomAction, ...]:
    groups: dict[tuple[str, tuple[float, ...]], list[int]] = defaultdict(list)
    for source in sources:
        node = context.dag.nodes[source]
        groups[node.name, node.params].append(source)
    actions: list[AtomAction] = []
    for (name, _), group in groups.items():
        ids = tuple(group)
        if name == "cz":
            assert context.device.cz is not None
            actions.append(
                CZPulse(
                    context.device.cz.channel,
                    RegionSet(
                        tuple(
                            zone.bounds
                            for zone in context.device.zones
                            if "cz" in zone.operations
                        )
                    ),
                    duration_us=context.device.cz.duration_us,
                    source_ids=ids,
                )
            )
            continue
        emitted = emit_layer(context.dag, GateLayer((ids[0],)), layout, context.device)
        first = emitted.steps[0].actions[0]
        if isinstance(first, Measure):
            results = []
            for source in ids:
                node = context.dag.nodes[source]
                assert node.result is not None
                results.append((layout.qubit_to_atom[node.qubits[0]], node.result))
            actions.append(
                replace(
                    first,
                    results=tuple(results),
                    source_ids=ids,
                )
            )
        elif isinstance(first, Rotation | LocalU | Reset):
            actions.append(
                replace(
                    first,
                    atoms=tuple(
                        layout.qubit_to_atom[qubit]
                        for source in ids
                        for qubit in context.dag.nodes[source].qubits
                    ),
                    source_ids=ids,
                )
            )
        else:
            raise ValueError(f"Unsupported SMT native operation {name!r}.")
    return tuple(actions)
