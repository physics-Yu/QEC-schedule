"""Pure transitions for binary supports, safe axis switching and timed handoff.

Transfer timing includes ramp/settling. At start both supports exist, the source
still owns the atom; completion commits holder and source extinction together.
"""
from dataclasses import replace
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderType as H, HolderRef, MobileCellIndex
from neutral_atom_env.domain.operations import OperationType as K, TrapState, TransferRuntime
from neutral_atom_env.world import PlacementState
from neutral_atom_env.hardware.rigid_aod import distance, segment_clearance


LOADS = {K.AOD_LOAD, K.AOD_RECAPTURE}
TRANSFERS = LOADS | {K.AOD_OFFLOAD, K.AOD_PARK}


def trap_state(state):
    return TrapState(state.aod.enabled_rows, state.aod.enabled_columns, tuple(sorted(state.slm_enabled.items())))


def with_traps(state, traps, **changes):
    if not isinstance(traps, TrapState):
        raise ValidationError('INVALID_TRAP_STATE', 'Explicit trap state required')
    return replace(state, aod=replace(state.aod, enabled_rows=traps.rows, enabled_columns=traps.columns),
                   slm_enabled=dict(traps.slm), **changes)


def validate_support(state):
    for q, h in state.placement.atom_to_holder.items():
        enabled = state.slm_enabled.get(h.holder_id, False) if h.holder_type == H.STATIC else (
            state.aod.is_enabled(h.holder_id) if h.holder_type == H.MOBILE else True)
        if not enabled:
            raise ValidationError('HOLDER_SUPPORT_DISABLED', 'A committed holder must remain enabled', atom_ids=(q,), holder_id=h.holder_id)
    transfer = state.transfer
    if transfer is not None:
        if (not isinstance(transfer, TransferRuntime) or transfer.kind not in TRANSFERS
                or transfer.stage != 'target_supported' or state.aod.is_moving or not transfer.bindings):
            raise ValidationError('INVALID_TRANSFER_STATE', 'Invalid supported handoff boundary')
        for b in transfer.bindings:
            expected = HolderRef(H.STATIC, b.static_trap_id) if transfer.kind in LOADS else HolderRef(H.MOBILE, b.cell)
            trap = state.world.traps.get(b.static_trap_id)
            if (state.placement.atom_to_holder.get(b.atom_id) != expected or trap is None
                    or not state.slm_enabled[trap.id] or not state.aod.is_enabled(b.cell)
                    or distance(state.aod.position(b.cell), trap.position) > state.hardware.alignment_tolerance_um):
                raise ValidationError('TRANSFER_SUPPORT_LOST', 'Handoff must retain aligned source and destination supports', atom_ids=(b.atom_id,))


def validate_active_sweep(state, end, *, allowed=(), cells=None):
    """All active cells against live static atoms, including empty Cartesian cells.

    No transport exemption is accepted here. `allowed` is private to the aligned,
    zero-length target-support establishment used by begin_transfer.
    """
    exemptions = {(b.cell, b.atom_id) for b in allowed}
    for cell in state.aod.active_cells if cells is None else cells:
        start, finish = state.aod.position(cell), end.position(cell)
        for trap_id, q in state.placement.static_occupancy.items():
            p = state.world.traps[trap_id].position
            if ((cell, q) in exemptions and start == finish
                    and distance(start, p) <= state.hardware.alignment_tolerance_um):
                continue
            d, closest = segment_clearance(p, start, finish)
            if d + 1e-9 < state.hardware.minimum_clearance_um:
                raise ValidationError('ACTIVE_TRAP_SWEEP', 'Active AOD trap sweeps a static atom', atom_ids=(q,), holder_id=cell, position=closest)


def switch_traps(state, target):
    if state.aod.is_moving or state.transfer is not None:
        raise ValidationError('TRAP_SWITCH_BUSY', 'Switch requires stationary geometry outside a handoff')
    result = with_traps(state, target)  # Checks every holder before any commit.
    from neutral_atom_env.hardware import get_backend
    backend = get_backend(state.hardware)
    backend.validate_pose(result, result.aod.pose)
    validate_active_sweep(result, result.aod)
    # Turning on an SLM beneath an unrelated mobile atom is also a handoff.
    for trap_id, enabled in result.slm_enabled.items():
        if enabled and not state.slm_enabled[trap_id]:
            for cell, q in state.placement.mobile_occupancy.items():
                if distance(state.aod.position(cell), state.world.traps[trap_id].position) < state.hardware.slm_clearance_um:
                    raise ValidationError('SLM_ENABLE_OVERLAP', 'Establish support beneath a mobile atom through a bound handoff', atom_ids=(q,))
    return result


def begin_transfer(backend, state, bindings, kind):
    bindings = tuple(bindings)
    if kind not in TRANSFERS or state.transfer is not None or state.aod.is_moving:
        raise ValidationError('TRANSFER_BUSY', 'Transfer requires an idle, stationary handoff channel')
    if (not bindings or any(len({getattr(b, key) for b in bindings}) != len(bindings)
                            for key in ('atom_id', 'cell', 'static_trap_id'))):
        raise ValidationError('INVALID_TRANSFER_SET', 'Transfer bindings must be nonempty and unique')
    loading = kind in LOADS
    if kind in {K.AOD_PARK, K.AOD_RECAPTURE} and (backend.name != 'rigid' or not state.hardware.selective_transfer_enabled):
        raise ValidationError('SELECTIVE_TRANSFER_UNSUPPORTED', 'Partial transfer requires explicit rigid capability')
    if kind == K.AOD_LOAD and state.placement.mobile_occupancy:
        raise ValidationError('AOD_BUSY', 'LOAD requires empty AOD; use an explicit partial recapture')
    if kind == K.AOD_OFFLOAD and set(state.placement.mobile_occupancy.values()) != {b.atom_id for b in bindings}:
        raise ValidationError('OFFLOAD_SET_MISMATCH', 'OFFLOAD must account for all loaded atoms')
    backend.validate_pose(state, state.aod.pose)
    before = trap_state(state)
    rows, cols, slm = list(before.rows), list(before.columns), dict(before.slm)
    for b in bindings:
        trap = state.world.traps.get(b.static_trap_id)
        if trap is None:
            raise ValidationError('TRANSFER_TRAP_UNAVAILABLE', 'Unknown SLM destination/source')
        expected = HolderRef(H.STATIC, trap.id) if loading else HolderRef(H.MOBILE, b.cell)
        if state.placement.atom_to_holder.get(b.atom_id) != expected:
            raise ValidationError('TRANSFER_SOURCE_MISMATCH', 'Declared source does not own the atom', atom_ids=(b.atom_id,))
        occupied = state.placement.mobile_occupancy.get(b.cell) if loading else state.placement.static_occupancy.get(trap.id)
        if occupied is not None:
            raise ValidationError('TRANSFER_DESTINATION_OCCUPIED', 'Destination is occupied', atom_ids=(b.atom_id, occupied))
        if distance(state.aod.position(b.cell), trap.position) > state.hardware.alignment_tolerance_um:
            raise ValidationError('TRANSFER_MISALIGNMENT', 'Handoff must align at a legal SLM site', atom_ids=(b.atom_id,))
        if loading:
            rows[b.cell.row] = cols[b.cell.column] = True
        else:
            slm[trap.id] = True
    overlap = TrapState(tuple(rows), tuple(cols), tuple(sorted(slm.items())))
    # Full capture closure includes incidental atoms; inactive aligned cells do not capture.
    if kind == K.AOD_LOAD:
        candidate = with_traps(state, overlap)
        options={'active_only':True} if backend.name=='rigid' else {}
        actual = tuple(b for b in backend.capture_closure(candidate, candidate.aod.pose,**options) if candidate.aod.is_enabled(b.cell))
        if actual != bindings:
            raise ValidationError('CAPTURE_CHANGED', 'Bindings must cover the full active capture set')
    if loading:
        for b in bindings:
            slm[b.static_trap_id] = False
    else:
        remaining = set(state.placement.mobile_occupancy) - {b.cell for b in bindings}
        for b in bindings:
            # Either axis may be removed only when all its carried atoms transfer.
            if not any(c.row == b.cell.row for c in remaining):
                rows[b.cell.row] = False
            elif not any(c.column == b.cell.column for c in remaining):
                cols[b.cell.column] = False
            else:
                raise ValidationError('SHARED_AXIS_SUPPORT', 'Neither axis can close without dropping another carried atom', atom_ids=(b.atom_id,))
        if not remaining:
            rows, cols = [False] * state.aod.rows, [False] * state.aod.columns
    target = TrapState(tuple(rows), tuple(cols), tuple(sorted(slm.items())))
    transfer = TransferRuntime(kind, bindings, before, target)
    result = with_traps(state, overlap, transfer=transfer)
    validate_active_sweep(result, result.aod, allowed=bindings if loading else ())
    # Audit the final geometry too, before starting a timed operation.
    finish_transfer(backend, result, bindings, kind)
    return result


def finish_transfer(backend, state, bindings, kind):
    transfer = state.transfer
    if transfer is None or transfer.bindings != tuple(bindings) or transfer.kind != kind:
        raise ValidationError('TRANSFER_STATE_MISMATCH', 'Completion requires the matching established target support')
    validate_support(state)
    holders = dict(state.placement.atom_to_holder)
    for b in bindings:
        holders[b.atom_id] = HolderRef(H.MOBILE, b.cell) if kind in LOADS else HolderRef(H.STATIC, b.static_trap_id)
    result = with_traps(state, transfer.target_traps, placement=PlacementState(holders), transfer=None)
    backend.validate_geometry_move(result, result.aod.pose)
    validate_active_sweep(result, result.aod)
    return result


def transfer(backend, state, bindings, kind):
    """Read-only prediction of a complete handoff; executor persists its midpoint."""
    work = begin_transfer(backend, state, bindings, kind)
    return finish_transfer(backend, work, bindings, kind)
