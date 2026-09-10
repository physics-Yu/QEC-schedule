"""Conservative geometric exclusion around enabled SLM traps, including empty ones."""
from math import hypot
from neutral_atom_env.domain.errors import ValidationError
from .rigid_aod import distance, segment_clearance


def validate_slm_clearance(state,end,phase=None,bindings=()):
    if phase not in {None,'depart','approach'}:
        raise ValidationError('INVALID_TRANSFER_PHASE','Unknown transfer phase')
    bound={b.atom_id:b for b in bindings}
    radius=state.hardware.slm_clearance_um;tol=state.hardware.alignment_tolerance_um
    for cell,atom in state.placement.mobile_occupancy.items():
        start,finish=state.aod.position(cell),end.position(cell)
        binding=bound.get(atom)
        if phase and binding is not None and binding.cell!=cell:
            raise ValidationError('INVALID_TRANSFER_BINDING','Transfer requires the actual atom/cell binding',atom_ids=(atom,))
        for trap in state.world.traps.values():
            if not trap.enabled:continue
            p=trap.position
            if phase and binding is not None and trap.id==binding.static_trap_id:
                near,far=(start,finish) if phase=='depart' else (finish,start)
                # Moving away from an aligned endpoint along a straight segment is monotone.
                dx,dy=far.x_um-near.x_um,far.y_um-near.y_um
                outward=(near.x_um-p.x_um)*dx+(near.y_um-p.y_um)*dy
                if distance(near,p)>tol or distance(far,p)+1e-9<radius or outward < -tol*max(1,hypot(dx,dy)):
                    raise ValidationError('INVALID_TRANSFER_PATH','Transfer must align at its own trap and clear its exclusion region monotonically',atom_ids=(atom,),holder_id=trap.id)
                continue
            d,closest=segment_clearance(p,start,finish)
            if d+1e-9<radius:
                raise ValidationError('SLM_PATH_BLOCKED',f'Path passes within {d:g} um of enabled SLM trap',atom_ids=(atom,),holder_id=trap.id,position=closest)
