"""Shared ordered-axis matching and physical-program helpers; no search policy."""
from dataclasses import dataclass, replace
from math import hypot
from time import perf_counter

from neutral_atom_env.domain.aod import AODConfiguration
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderType, MobileCellIndex, Position2D
from neutral_atom_env.domain.operations import CaptureBinding, OperationType as K, TaskIntent, TaskTarget
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_env.hardware.trap_spacing import minimum_trap_spacing
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_strategies.motion.ordered_routes import discrete_corridor_routes,OccupiedSLMGrid
from neutral_atom_strategies.motion.axis_hold_routes import axis_hold_routes,transfer_annotation


@dataclass(frozen=True)
class AxisBatch:
    # gate id, stationary operand, moving operand, destination x, destination y
    assignments: tuple
    pickup: AODConfiguration
    target: AODConfiguration
    bindings: tuple

    @property
    def gate_ids(self):
        return tuple(a[0] for a in self.assignments)


def build_batch(state, assignments, *, translation_only=False, check_closure=True, check_interactions=True, bounded_spares=False):
    """Solve shared-axis equality/order constraints for a partial matching.

    Source coordinate order fixes axis identity; spare axes normally extend to
    the right and above. Optional bounded padding keeps the full capacity inside
    the existing world. Disabled axes remain present and physically validated.
    """
    positions={q:state.placement.position(q,state.world,state.aod) for q in state.atoms}
    used=set(); xm={};ym={}; shifts=set()
    for gid,anchor,mobile,x,y in assignments:
        if {anchor,mobile}&used:raise ValidationError('AXIS_OPERAND_CONFLICT','Batch operands must be disjoint')
        used.update((anchor,mobile));p=positions[mobile]
        for mapping,s,t in ((xm,p.x_um,x),(ym,p.y_um,y)):
            if s in mapping and abs(mapping[s]-t)>1e-7:
                raise ValidationError('AXIS_SHARED_COORDINATE','Atoms sharing an axis need the same target coordinate')
            mapping[s]=t
        shifts.add((round(x-p.x_um,7),round(y-p.y_um,7)))
    if translation_only and len(shifts)>1:
        raise ValidationError('AXIS_TRANSLATION_ONLY','Ablation requires one common displacement')
    gap=minimum_trap_spacing(state.hardware)
    def axes(mapping,count,lower,upper):
        start=tuple(sorted(mapping));end=tuple(mapping[v] for v in start)
        if len(start)>count:raise ValidationError('AXIS_CAPACITY','Too many distinct source axes')
        if any(b-a<=gap+1e-9 for values in (start,end) for a,b in zip(values,values[1:])):
            raise ValidationError('AXIS_ORDER','Axis order or minimum spacing would be violated')
        spare=count-len(start)
        padded=(start+tuple(start[-1]+10*i for i in range(1,spare+1)),
                end+tuple(end[-1]+10*i for i in range(1,spare+1)))
        if bounded_spares and any(v[0]<lower or v[-1]>upper for v in padded):
            from neutral_atom_strategies.motion.bounded_spare_axes import bounded_spare_axes
            return bounded_spare_axes(start,end,count,lower,upper,gap)
        return padded
    bounds=state.world.bounds
    sx,tx=axes(xm,state.aod.columns,bounds.lower.x_um,bounds.upper.x_um)
    sy,ty=axes(ym,state.aod.rows,bounds.lower.y_um,bounds.upper.y_um)
    pickup=AODConfiguration(sx,sy);target=AODConfiguration(tx,ty)
    if any(not state.world.bounds.contains(Position2D(x,y)) for c in (pickup,target)
           for x in (c.x_um[0],c.x_um[-1]) for y in (c.y_um[0],c.y_um[-1])):
        raise ValidationError('AXIS_BOUNDS','Full capacity axes leave world bounds')
    mobile={a[2] for a in assignments}
    if check_closure:
        captured={q for q,p in positions.items() if p.x_um in xm and p.y_um in ym}
        if captured!=mobile:
            raise ValidationError('AXIS_CAPTURE_CLOSURE','Enabled row × column would capture an unrequested atom')
        ends={q:Position2D(x,y) for _,_,q,x,y in assignments}
        ids=sorted(positions);actual=set()
        for i,a in enumerate(ids):
            p=ends.get(a,positions[a])
            for b in ids[i+1:]:
                q=ends.get(b,positions[b])
                if hypot(p.x_um-q.x_um,p.y_um-q.y_um)<=state.hardware.interaction_distance_um+1e-9:
                    actual.add(frozenset((a,b)))
        if check_interactions and actual!={frozenset((a,b)) for _,a,b,_,_ in assignments}:
            raise ValidationError('AXIS_EXTRA_PAIR','Endpoint interaction pairs differ from requested gates')
    bindings=tuple(sorted((CaptureBinding(q,MobileCellIndex(sy.index(positions[q].y_um),sx.index(positions[q].x_um)),
                       state.placement.atom_to_holder[q].holder_id) for q in mobile),key=lambda b:b.atom_id))
    return AxisBatch(tuple(assignments),pickup,target,bindings)


def new_builder(state,ids=()):
    return ProgramBuilder(state,TaskIntent(f'ordered-axis/{state.version}/{"-".join(ids)}',TaskTarget(),
                           frozenset(state.atoms),phase='program',gate_effects=frozenset(ids)))


def finish(p,terminal=None,*,compiler='ordered-axis-greedy-v1'):
    p.intent=replace(p.intent,target=terminal or TaskTarget(tuple(sorted(p.state.placement.atom_to_holder.items())),
                     p.state.aod.configuration(),trap_state(p.state)))
    return p.finish(compiler)


def empty_reconfigure(p,target):
    if p.state.placement.mobile_occupancy:raise ValidationError('AXIS_EMPTY_REQUIRED','Empty positioning requires no payload')
    masks=replace(trap_state(p.state),rows=(False,)*p.state.aod.rows,columns=(False,)*p.state.aod.columns)
    if masks!=trap_state(p.state):p.add(K.TRAP_SWITCH,'Disable empty array for axis positioning',switch_state=masks)
    # Coordinate-wise moves preserve orthogonality for every trap.
    for c in (AODConfiguration(target.x_um,p.state.aod.configuration().y_um),target):
        if c!=p.state.aod.configuration():p.add(K.AOD_MOVE,'Position ordered empty axes',configuration=c)


def corridor_routes(start,target,motion_router='axis_hold'):
    if motion_router=='axis_hold':return axis_hold_routes(start,target)
    if motion_router=='legacy_corridor':return discrete_corridor_routes(start,target)
    raise ValueError('Unknown motion router: '+motion_router)


def restore(state,terminal,*,compiler='ordered-axis-greedy-v1'):
    p=new_builder(state);empty_reconfigure(p,terminal.aod_configuration)
    if trap_state(p.state)!=terminal.traps:p.add(K.TRAP_SWITCH,'Restore original trap switches',switch_state=terminal.traps)
    return finish(p,terminal,compiler=compiler) if p.operations else None
