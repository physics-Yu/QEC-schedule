"""Recognize the constructive M3 family; this is not a general routing oracle.

Other layouts may still produce individually validated finite candidates.
See docs/milestone3.md for the corridor and spare-capacity argument.
"""
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderType, Position2D, ZoneType
from .single_trap import in_zone


def validate_family(state):
    def check(condition,message):
        if not condition:raise ValidationError('OUTSIDE_M3_FAMILY',message)
    h=state.hardware;world=state.world
    check(h.backend=='rigid' and (state.aod.rows,state.aod.columns)==(1,1),'One rigid trap required')
    check(1<=len(state.atoms)<=256,'Declared atom range is 1–256')
    check((h.minimum_clearance_um,h.slm_clearance_um,h.interaction_distance_um,h.interaction_offset)==(1,1,2,Position2D(-2,0)),
          'Declared family uses unchanged 1 um clearance and 2 um interaction geometry')
    check(world.grid_spacing_um==5 and world.grid_origin==Position2D(0,0),'Declared routing grid is 5 um')
    storage=[];ez=[]
    for trap in world.traps.values():
        p=trap.position
        if in_zone(state,p,ZoneType.STORAGE):
            check(p.x_um>=0 and p.y_um>=0 and p.x_um%10==0 and p.y_um%10==0,'SZ sites must be on the 10 um lattice')
            storage.append(p)
        else:
            check(in_zone(state,p,ZoneType.ENTANGLEMENT) and p.y_um==-35 and p.x_um%10==5,'EZ sites must use the separated parking row')
            ez.append(p)
        check(all(world.bounds.contains(Position2D(p.x_um+dx,p.y_um+dy)) for dx in (-5,5) for dy in (-5,5)),
              'Five um boundary margin required for clear corridors')
    check(len(storage)>=len(state.atoms) and len(ez)>=2,'Storage capacity for every atom and two EZ spares required')
    check(all(h.holder_type in {HolderType.STATIC,HolderType.MOBILE} for h in state.placement.atom_to_holder.values()),'Lost atoms outside constructive family')
    return {'id':'m3-grid-10um-v1','atom_count':len(state.atoms),'storage_sites':len(storage),'ez_sites':len(ez),
            'clearance_um':1,'routing_grid_um':5,'arbitrary_layout_complete':False}
