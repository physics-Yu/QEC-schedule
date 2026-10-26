"""Align already admitted local correction lanes without changing their pulses.

No software Pauli frame is implemented here. Original addressed rotations and
unitaries retain their targets, angles, source IDs and exact start/end times.
The caller still validates declarations, worlds, DAG semantics and hardware.
"""

from dataclasses import dataclass
from math import isfinite

from nadit_physical_compiler.atom_ir import AtomStep, LocalU, Rotation, Wait


@dataclass(frozen=True)
class LocalAlignment:
    """Merged steps and a total map from each original step/action to its slot.

    Shorter lanes finish at their own original end. Their remaining hold interval
    is not an invented operation or a longer correction. Consecutive zero-time
    no-op steps can map to the same merged step without delaying a later pulse.
    """

    steps: tuple[AtomStep, ...]
    member_step_indices: tuple[tuple[int, ...], ...]
    member_action_indices: tuple[tuple[tuple[int, ...], ...], ...]
    member_action_end_us: tuple[float, ...]
    action_end_us: float


def align_local_lanes(
    lanes: tuple[tuple[AtomStep, ...], ...], *, start_us: float
) -> LocalAlignment:
    """Combine disjoint local lanes on their existing ordered physical clock.

    Only Rotation, LocalU and existing zero-duration Wait actions are accepted.
    Nonzero concurrent step durations must match exactly. Incompatible pulse
    boundaries raise ValueError; no pulse is split, padded, moved or substituted.
    An empty lane contributes no actions and finishes at start_us. Immutable
    containers are required so the returned mapping binds an unchanging source.
    """
    if type(start_us) not in (int, float) or not isfinite(start_us) or start_us < 0:
        raise ValueError("INVALID_LOCAL_BATCH_START")
    if (
        not isinstance(lanes, tuple)
        or not lanes
        or any(not isinstance(lane, tuple) for lane in lanes)
        or any(not isinstance(step, AtomStep) for lane in lanes for step in lane)
    ):
        raise TypeError("INVALID_LOCAL_BATCH_LANES: immutable AtomStep lanes required")
    events: dict[float, list[tuple[int, int, AtomStep]]] = {}
    member_ends: list[float] = []
    all_atoms: set[int] = set()
    for member_index, lane in enumerate(lanes):
        clock = float(start_us)
        atoms: set[int] = set()
        for source_index, step in enumerate(lane):
            for action in step.actions:
                if isinstance(action, Rotation | LocalU):
                    atoms.update(action.atoms)
                elif not isinstance(action, Wait) or action.duration_us != 0:
                    raise ValueError("LOCAL_BATCH_UNSUPPORTED_ACTION")
            events.setdefault(clock, []).append((member_index, source_index, step))
            clock += step.duration_us
            if not isfinite(clock):
                raise ValueError("LOCAL_BATCH_NONFINITE_END")
        if atoms & all_atoms:
            raise ValueError("LOCAL_BATCH_OVERLAPPING_MEMBER_ATOMS")
        all_atoms.update(atoms)
        member_ends.append(clock)

    merged_steps: list[AtomStep] = []
    step_indices: list[list[int]] = [[] for _ in lanes]
    action_indices: list[list[tuple[int, ...]]] = [[] for _ in lanes]
    clock = float(start_us)
    for event_start, sources in sorted(events.items()):
        if event_start != clock:
            raise ValueError(
                "LOCAL_BATCH_BOUNDARY_MISMATCH: pulses cannot overlap another step"
            )
        durations = {step.duration_us for _, _, step in sources if step.duration_us > 0}
        if len(durations) > 1:
            raise ValueError("LOCAL_BATCH_DURATION_MISMATCH: no padding or splitting")
        actions = tuple(action for _, _, step in sources for action in step.actions)
        touched: set[int] = set()
        for action in actions:
            if isinstance(action, Rotation | LocalU):
                if touched.intersection(action.atoms):
                    raise ValueError("LOCAL_BATCH_CONCURRENT_TARGET_OVERLAP")
                touched.update(action.atoms)
        slot, action_offset = len(merged_steps), 0
        for member, source, step in sources:
            if source != len(step_indices[member]):
                raise ValueError("LOCAL_BATCH_SOURCE_ORDER_CHANGED")
            step_indices[member].append(slot)
            action_indices[member].append(
                tuple(range(action_offset, action_offset + len(step.actions)))
            )
            action_offset += len(step.actions)
        merged = AtomStep(actions)
        merged_steps.append(merged)
        clock += merged.duration_us
    if clock != max(member_ends):
        raise ValueError("LOCAL_BATCH_END_MISMATCH")
    return LocalAlignment(
        tuple(merged_steps),
        tuple(tuple(indices) for indices in step_indices),
        tuple(tuple(indices) for indices in action_indices),
        tuple(member_ends),
        clock,
    )
