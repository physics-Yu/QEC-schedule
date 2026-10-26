"""Fuse declared synchronous grid writes without changing member trajectories.

This is lowering after admission. It does not infer parallelism, pad durations,
change row identities, or move an atom to make incompatible actions fit.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from nadit_physical_compiler.atom_ir import (
    AtomAction,
    AtomStep,
    Load,
    Measure,
    Move,
    Store,
)
from nadit_physical_compiler.device import Device
from nadit_physical_compiler.state import AODGrid, AODHolder, AtomLayout

from modules.codes.contracts.parallel import SharedAODClaim


@dataclass(frozen=True)
class SharedGridMapping:
    """Stable local-to-batch column identities for one member and one AOD."""

    aod_id: str
    column_id_map: tuple[tuple[int, int], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "aod_id": self.aod_id,
            "row_ids_unchanged": True,
            "column_id_map": [list(pair) for pair in self.column_id_map],
        }


def check_device_claim(
    claim: SharedAODClaim, device: Device, entry: AtomLayout
) -> None:
    """Reject forged hardware limits and unsupported nonempty shared entry grids."""
    aod, readout = device.aod(claim.aod_id), device.readout
    if (
        claim.max_rows != aod.max_rows
        or claim.max_columns != aod.max_columns
        or claim.min_spacing != aod.min_spacing
        or readout is None
        or claim.readout_channel != readout.channel
        or claim.max_readout_atoms != readout.max_atoms
    ):
        raise ValueError("SHARED_AOD_DEVICE_CLAIM_MISMATCH")
    grid = entry.grid(aod.id)
    if grid.rows or grid.columns:
        raise ValueError("SHARED_AOD_NONEMPTY_ENTRY_GRID_UNSUPPORTED")


def make_mappings(
    lanes: tuple[tuple[AtomStep, ...], ...],
    claims: tuple[SharedAODClaim, ...],
    entry: AtomLayout,
) -> tuple[SharedGridMapping, ...]:
    """Verify emitted demands, then allocate disjoint columns without a stride."""
    occupied = {
        claim.aod_id: {line.id for line in entry.grid(claim.aod_id).columns}
        for claim in claims
    }
    mappings = []
    for lane, claim in zip(lanes, claims, strict=True):
        columns: set[int] = set()
        for step in lane:
            demand = 0
            for action in step.actions:
                if isinstance(action, Load | Move | Store):
                    if action.grid.aod_id != claim.aod_id:
                        raise ValueError("BATCH_ACTION_EXCEEDS_AOD_CLAIM")
                    if (
                        len(action.grid.rows) > claim.peak_rows
                        or len(action.grid.columns) > claim.peak_columns
                        or any(
                            not claim.column_min <= line.coordinate <= claim.column_max
                            for line in action.grid.columns
                        )
                    ):
                        raise ValueError("SHARED_AOD_ACTION_EXCEEDS_DECLARED_DEMAND")
                    columns.update(line.id for line in action.grid.columns)
                if isinstance(action, Measure):
                    if action.channel != claim.readout_channel:
                        raise ValueError("SHARED_AOD_READOUT_CHANNEL_MISMATCH")
                    demand += len(action.results)
            if demand > claim.peak_readout_atoms:
                raise ValueError("SHARED_AOD_READOUT_EXCEEDS_DECLARED_DEMAND")
        assigned = []
        used = occupied[claim.aod_id]
        next_id = 0
        for local_id in sorted(columns):
            while next_id in used:
                next_id += 1
            assigned.append((local_id, next_id))
            used.add(next_id)
        mappings.append(SharedGridMapping(claim.aod_id, tuple(assigned)))
    return tuple(mappings)


def project_member(
    world: AtomLayout, atoms: frozenset[int], mapping: SharedGridMapping
) -> dict[str, Any]:
    """Project actual shared lines/holders back to the source's local identities."""
    inverse = {global_id: local_id for local_id, global_id in mapping.column_id_map}
    projected = []
    for atom_id in sorted(atoms):
        atom = world.atom(atom_id)
        holder = atom.holder
        if isinstance(holder, AODHolder) and holder.aod_id == mapping.aod_id:
            if holder.column not in inverse:
                raise ValueError("SHARED_AOD_PARTICIPANT_USES_FOREIGN_COLUMN")
            atom = replace(atom, holder=replace(holder, column=inverse[holder.column]))
        projected.append(asdict(atom))
    grid = world.grid(mapping.aod_id)
    local = replace(
        grid,
        columns=tuple(
            replace(line, id=inverse[line.id])
            for line in grid.columns
            if line.id in inverse
        ),
    )
    return {"atoms": projected, "aod_grids": [asdict(local)]}


def _remap(
    action: Load | Move | Store, mapping: SharedGridMapping
) -> Load | Move | Store:
    columns = dict(mapping.column_id_map)
    grid = replace(
        action.grid,
        columns=tuple(
            replace(line, id=columns[line.id]) for line in action.grid.columns
        ),
    )
    if isinstance(action, Load):
        return replace(
            action,
            grid=grid,
            bindings=tuple(
                (atom, row, columns[col]) for atom, row, col in action.bindings
            ),
        )
    return replace(action, grid=grid)


def _combine(actions: tuple[Load | Move | Store, ...]) -> Load | Move | Store:
    first = actions[0]
    if any(
        type(action) is not type(first) or action.duration_us != first.duration_us
        for action in actions
    ):
        raise ValueError("SHARED_AOD_TRANSPORT_PHASE_MISMATCH")
    if any(action.grid.rows != first.grid.rows for action in actions):
        raise ValueError("SHARED_AOD_ROW_TRAJECTORY_MISMATCH")
    grid = AODGrid(
        first.grid.aod_id,
        first.grid.rows,
        tuple(line for action in actions for line in action.grid.columns),
    )
    source_ids = tuple(source for action in actions for source in action.source_ids)
    if isinstance(first, Load):
        return replace(
            first,
            grid=grid,
            source_ids=source_ids,
            bindings=tuple(
                binding
                for action in actions
                if isinstance(action, Load)
                for binding in action.bindings
            ),
        )
    if isinstance(first, Move):
        return replace(
            first,
            grid=grid,
            source_ids=source_ids,
            targets=tuple(
                target
                for action in actions
                if isinstance(action, Move)
                for target in action.targets
            ),
        )
    return replace(
        first,
        grid=grid,
        source_ids=source_ids,
        bindings=tuple(
            binding
            for action in actions
            if isinstance(action, Store)
            for binding in action.bindings
        ),
    )


def fuse_step(
    lane_steps: tuple[AtomStep, ...], mappings: tuple[SharedGridMapping, ...]
) -> tuple[AtomStep, tuple[tuple[int, ...], ...]]:
    """Merge one transport write per AOD and return every original action's slot."""
    groups: dict[str, list[Load | Move | Store]] = {}
    for step, mapping in zip(lane_steps, mappings, strict=True):
        seen: set[str] = set()
        for action in step.actions:
            if isinstance(action, Load | Move | Store):
                if action.grid.aod_id != mapping.aod_id or action.grid.aod_id in seen:
                    raise ValueError("SHARED_AOD_MULTIPLE_OR_UNDECLARED_MEMBER_WRITES")
                seen.add(action.grid.aod_id)
                groups.setdefault(mapping.aod_id, []).append(_remap(action, mapping))
    combined = {aod: _combine(tuple(actions)) for aod, actions in groups.items()}
    actions: list[AtomAction] = []
    emitted: dict[str, int] = {}
    indices = []
    for step in lane_steps:
        member_indices = []
        for action in step.actions:
            if isinstance(action, Load | Move | Store):
                aod_id = action.grid.aod_id
                if aod_id not in emitted:
                    emitted[aod_id] = len(actions)
                    actions.append(combined[aod_id])
                member_indices.append(emitted[aod_id])
            else:
                member_indices.append(len(actions))
                actions.append(action)
        indices.append(tuple(member_indices))
    return AtomStep(tuple(actions)), tuple(indices)
