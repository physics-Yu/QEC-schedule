"""Arithmetic witness checks independent of the symbolic transport encoding."""

from collections import Counter
from itertools import combinations, pairwise
from math import hypot, isclose

from ..compiler import CompilationResult
from ..compilers.contracts import ProgramContext
from ..replay import apply_step
from ..state import COORDINATE_TOLERANCE, AODHolder, AtomLayout
from .contracts import Plan, Snapshot


def check_plan(context: ProgramContext, plan: Plan) -> list[str]:
    """Check decoded states, transport rules, coverage, and dependency timing.

    This checker does not import Z3 or symbolic constraint builders. Pulse,
    holder, addressing, and readout rules are additionally checked on Atom IR by
    the common semantic validator after lowering.
    """
    horizon = len(plan.transitions)
    if len(plan.states) != horizon + 1 or len(plan.operations) != horizon:
        return ["plan_shape: expected H transitions, H operation groups, H+1 states"]
    if any(
        len(state.positions) != len(context.entry_state.atoms)
        or len(state.carried) != len(context.entry_state.atoms)
        for state in plan.states
    ):
        return ["snapshot_shape: atom tuples must follow the complete entry order"]
    errors: list[str] = []
    if plan.states[0] != _snapshot(context.entry_state, context.aod_id):
        errors.append("initial_state: snapshot differs from the explicit entry")
    final = plan.states[-1]
    if (
        final.positions != tuple(atom.position for atom in context.entry_state.atoms)
        or any(final.carried)
        or final.rows
        or final.columns
    ):
        errors.append("final_home: every atom must return to its SLM home with AOD off")
    for index, state in enumerate(plan.states):
        errors.extend(f"state {index}: {message}" for message in _state(context, state))
    for index, transition in enumerate(plan.transitions):
        errors.extend(
            f"step {index}: {message}"
            for message in _transition(
                context, plan.states[index], plan.states[index + 1], transition
            )
        )
    errors.extend(_schedule(context, plan))
    return errors


def check_lowering(
    context: ProgramContext, plan: Plan, result: CompilationResult
) -> list[str]:
    """Compare every replayed Atom IR boundary with the decoded witness.

    Empty active lines are compared explicitly. This detects a lowerer dropping
    lines, misbinding atom identities, or emitting a different endpoint schedule.
    """
    if len(result.program.steps) != len(plan.transitions):
        return ["step_count: Atom IR and plan have different step counts"]
    errors: list[str] = []
    layout = context.entry_state
    for index, step in enumerate(result.program.steps):
        try:
            layout = apply_step(layout, step, context.device)
        except (KeyError, ValueError, NotImplementedError) as error:
            errors.append(f"replay at step {index}: {error}")
            return errors
        if _snapshot(layout, context.aod_id) != plan.states[index + 1]:
            errors.append(f"snapshot_mismatch at state {index + 1}")
        if any(grid.aod_id != context.aod_id for grid in layout.aod_grids):
            errors.append(f"unmodeled_aod at state {index + 1}")
    if layout != result.exit_state:
        errors.append("exit_state: result differs from replay")
    return errors


def _snapshot(layout: AtomLayout, aod_id: str) -> Snapshot:
    grid = layout.grid(aod_id)
    return Snapshot(
        tuple(atom.position for atom in layout.atoms),
        tuple(isinstance(atom.holder, AODHolder) for atom in layout.atoms),
        tuple(sorted(line.coordinate for line in grid.columns)),
        tuple(sorted(line.coordinate for line in grid.rows)),
    )


def _state(context: ProgramContext, state: Snapshot) -> list[str]:
    errors: list[str] = []
    aod = context.device.aod(context.aod_id)
    for name, values, capacity, lower, upper in (
        (
            "columns",
            state.columns,
            aod.max_columns,
            aod.workspace.x_min,
            aod.workspace.x_max,
        ),
        ("rows", state.rows, aod.max_rows, aod.workspace.y_min, aod.workspace.y_max),
    ):
        if tuple(sorted(set(values))) != values:
            errors.append(f"line_order: {name} must be sorted and distinct")
        if capacity is not None and len(values) > capacity:
            errors.append(f"capacity: too many {name}")
        if any(
            value < lower - COORDINATE_TOLERANCE or value > upper + COORDINATE_TOLERANCE
            for value in values
        ):
            errors.append(f"workspace: {name} outside the AOD workspace")
        if any(
            right - left < aod.min_spacing - COORDINATE_TOLERANCE
            for left, right in pairwise(values)
        ):
            errors.append(f"spacing: adjacent {name} are too close")
    sites = {site.position for site in context.device.slm_sites}
    for index, (position, carried) in enumerate(
        zip(state.positions, state.carried, strict=True)
    ):
        intersection = position.x in state.columns and position.y in state.rows
        if carried != intersection:
            errors.append(
                f"intersection: atom {index} holder disagrees with "
                "active Cartesian grid"
            )
        if not carried and position not in sites:
            errors.append(f"slm_site: atom {index} has no fixed trap")
    if any(
        hypot(a.x - b.x, a.y - b.y) <= COORDINATE_TOLERANCE
        for a, b in combinations(state.positions, 2)
    ):
        errors.append("occupied_position: two atoms share an endpoint")
    return errors


def _transition(
    context: ProgramContext, before: Snapshot, after: Snapshot, kind: str
) -> list[str]:
    errors: list[str] = []
    if kind not in ("none", "load", "move", "store"):
        return [f"transition_kind: unknown transition {kind!r}"]
    if kind == "none":
        return (
            []
            if before == after
            else ["none_changed_state: idle transport altered a snapshot"]
        )
    axes = ((before.columns, after.columns), (before.rows, after.rows))
    if kind in ("load", "store"):
        if before.positions != after.positions:
            errors.append("transfer_motion: transfer changed atom positions")
        for old, new in axes:
            keeps_lines = (
                set(old) <= set(new) if kind == "load" else set(new) <= set(old)
            )
            if not keeps_lines:
                errors.append("line_activation: LOAD adds lines; STORE removes lines")
        for held_before, held_after in zip(before.carried, after.carried, strict=True):
            if (kind == "load" and held_before and not held_after) or (
                kind == "store" and held_after and not held_before
            ):
                errors.append(
                    "transfer_holder: transfer changed ownership in the wrong direction"
                )
        if (
            context.device.aod(context.aod_id).motion == "rigid"
            and kind == "load"
            and any(before.carried)
            and any(old != new for old, new in axes)
        ):
            errors.append("rigid_loading: carrying atoms forbids activating new lines")
        return errors
    if before.carried != after.carried:
        errors.append("move_holder: MOVE changed atom ownership")
    if any(len(old) != len(new) for old, new in axes):
        return [*errors, "line_count: MOVE must preserve every active line"]
    maps = tuple(dict(zip(old, new, strict=True)) for old, new in axes)
    for index, (old_position, new_position, carried) in enumerate(
        zip(before.positions, after.positions, before.carried, strict=True)
    ):
        if not carried:
            if old_position != new_position:
                errors.append(f"stationary_slm: MOVE displaced SLM atom {index}")
        elif (
            old_position.x not in maps[0]
            or old_position.y not in maps[1]
            or (new_position.x, new_position.y)
            != (maps[0][old_position.x], maps[1][old_position.y])
        ):
            errors.append(f"line_rank: atom {index} switched or lost an active line")
    if context.device.aod(context.aod_id).motion == "rigid":
        for old, new in axes:
            if old and any(
                not isclose(
                    target - source,
                    new[0] - old[0],
                    rel_tol=0,
                    abs_tol=COORDINATE_TOLERANCE,
                )
                for source, target in zip(old, new, strict=True)
            ):
                errors.append(
                    "rigid_translation: all lines on each axis must "
                    "share a displacement"
                )
    return errors


def _duration(context: ProgramContext, source: int) -> float:
    name = context.dag.nodes[source].name
    if name in ("barrier", "global_phase"):
        return 0
    if name == "cz" and context.device.cz is not None:
        return context.device.cz.duration_us
    if name == "measure" and context.device.readout is not None:
        return context.device.readout.duration_us
    if name in ("rx", "ry", "rz", "u", "reset") and context.device.local is not None:
        return (
            context.device.local.reset_us
            if name == "reset"
            else context.device.local.rotation_us
        )
    raise ValueError(f"unsupported native operation or capability {name!r}")


def _schedule(context: ProgramContext, plan: Plan) -> list[str]:
    counts = Counter(source for group in plan.operations for source in group)
    if counts != Counter(range(len(context.dag.nodes))):
        return [
            "operation_coverage: each native operation must be scheduled exactly once"
        ]
    errors: list[str] = []
    intervals = {}
    time = 0.0
    for step, group in enumerate(plan.operations):
        durations = []
        for source in group:
            try:
                duration = _duration(context, source)
            except ValueError as error:
                errors.append(str(error))
                continue
            intervals[source] = (time, time + duration)
            durations.append(duration)
        kind = plan.transitions[step]
        if kind == "load":
            durations.append(context.device.timing.load_us)
        elif kind == "store":
            durations.append(context.device.timing.store_us)
        elif kind == "move":
            before_state, after_state = plan.states[step : step + 2]
            distance = max(
                (
                    hypot(a.x - b.x, a.y - b.y)
                    for a, b, carried in zip(
                        before_state.positions,
                        after_state.positions,
                        before_state.carried,
                        strict=True,
                    )
                    if carried
                ),
                default=0.0,
            )
            durations.append(context.device.timing.move_duration(distance))
        time += max(durations, default=0.0)
    for before, after in context.dag.edges:
        if (
            before in intervals
            and after in intervals
            and intervals[before][1] > intervals[after][0] + COORDINATE_TOLERANCE
        ):
            errors.append(f"dependency_order: {after} starts before {before} completes")
    return errors
