"""Explicit ideal addressed handoff; rigid motion never implies this capability."""
from dataclasses import replace
from neutral_atom_env.domain.models import HolderType, HolderRef, ZoneType
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.world import PlacementState
from .rigid_aod import distance


def transfer(backend,state,bindings,*,recapture=False):
    if backend.name!='rigid' or not state.hardware.selective_transfer_enabled:
        raise ValidationError('SELECTIVE_TRANSFER_UNSUPPORTED','Partial transfer requires explicit rigid selective-transfer capability')
    if state.aod.is_moving:
        raise ValidationError('AOD_MOVING','Transfer requires stationary traps')
    if (not bindings or len({b.atom_id for b in bindings})!=len(bindings)
        or len({b.cell for b in bindings})!=len(bindings)
        or len({b.static_trap_id for b in bindings})!=len(bindings)):
        raise ValidationError('INVALID_TRANSFER_SET','Transfer bindings must be nonempty and unique')
    holders=dict(state.placement.atom_to_holder)
    for b in bindings:
        trap=state.world.traps.get(b.static_trap_id)
        if not trap or not trap.enabled:
            raise ValidationError('TRANSFER_TRAP_UNAVAILABLE','Transfer requires an enabled SLM trap',holder_id=b.static_trap_id)
        if not any(z.zone_type==ZoneType.ENTANGLEMENT and z.bounds.contains(trap.position) for z in state.world.zones):
            raise ValidationError('TRANSFER_OUTSIDE_EZ','Temporary parking uses configured EZ traps',holder_id=trap.id)
        expected=HolderRef(HolderType.STATIC,trap.id) if recapture else HolderRef(HolderType.MOBILE,b.cell)
        if holders.get(b.atom_id)!=expected:
            raise ValidationError('TRANSFER_SOURCE_MISMATCH','Atom is not held by the declared source',atom_ids=(b.atom_id,))
        occupied=state.placement.mobile_occupancy.get(b.cell) if recapture else state.placement.static_occupancy.get(trap.id)
        if occupied is not None:
            raise ValidationError('TRANSFER_DESTINATION_OCCUPIED','Transfer destination is occupied',atom_ids=(b.atom_id,occupied))
        if distance(state.aod.position(b.cell),trap.position)>state.hardware.alignment_tolerance_um:
            raise ValidationError('TRANSFER_MISALIGNMENT','AOD cell and SLM trap must align',atom_ids=(b.atom_id,),holder_id=trap.id)
        holders[b.atom_id]=HolderRef(HolderType.MOBILE,b.cell) if recapture else HolderRef(HolderType.STATIC,trap.id)
    result=replace(state,placement=PlacementState(holders))
    backend.validate_geometry_move(result,result.aod.pose)
    return result
