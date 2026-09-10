"""Bounded eager planner for a co-captured pair sharing an AOD row or column."""
from neutral_atom_env.domain.aod import AODConfiguration
from neutral_atom_env.domain.models import HolderType
from neutral_atom_env.domain.operations import CompiledPlan, Operation, OperationType
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware import get_backend


def compile_mobile_pair(intent,state,fingerprint,planner,target_configuration=None):
    backend=get_backend(state.hardware)
    gate_id=next(iter(intent.gate_ids));requested=frozenset(state.dag.nodes[gate_id].gate.qubit_ids)
    if any(state.placement.atom_to_holder[a].holder_type!=HolderType.STATIC for a in requested):
        raise ValidationError('STATIC_SOURCE_REQUIRED','Eager source operands must be static')
    initial=state.aod.configuration()
    bindings=backend.capture_closure(state,initial)
    by_atom={b.atom_id:b.cell for b in bindings};captured=frozenset(by_atom)
    if not requested<=captured:
        raise ValidationError('PAIR_CAPTURE_REQUIRED','Mobile-pair planner requires both operands in the initial aligned capture set',atom_ids=tuple(sorted(requested)))
    a,b=(by_atom[q] for q in sorted(requested))
    center=state.hardware.mobile_pair_center
    gap=state.hardware.interaction_distance_um
    from neutral_atom_env.hardware.trap_spacing import minimum_trap_spacing
    intervals=abs(a.column-b.column) if a.row==b.row else abs(a.row-b.row) if a.column==b.column else None
    if intervals is not None and gap<=intervals*minimum_trap_spacing(state.hardware):
        raise ValidationError('AOD_PAIR_SPACING_INFEASIBLE',
            f'Targets span {intervals} live AOD intervals: their separation must exceed '
            f'{intervals*minimum_trap_spacing(state.hardware):g} um, but the gate radius is {gap:g} um; '
            'intervening empty traps cannot be ignored',atom_ids=tuple(sorted(requested)))
    if a.row==b.row:
        midpoint=(initial.x_um[a.column]+initial.x_um[b.column])/2
        dx,dy=center.x_um-midpoint,center.y_um-initial.y_um[a.row]
        ratio=gap/abs(initial.x_um[a.column]-initial.x_um[b.column])
        target=AODConfiguration(tuple(center.x_um+(x-midpoint)*ratio for x in initial.x_um),tuple(y+dy for y in initial.y_um))
    elif a.column==b.column:
        midpoint=(initial.y_um[a.row]+initial.y_um[b.row])/2
        dx,dy=center.x_um-initial.x_um[a.column],center.y_um-midpoint
        ratio=gap/abs(initial.y_um[a.row]-initial.y_um[b.row])
        target=AODConfiguration(tuple(x+dx for x in initial.x_um),tuple(center.y_um+(y-midpoint)*ratio for y in initial.y_um))
    else:
        raise ValidationError('PAIR_ROUTE_UNSUPPORTED','This planner supports same-row or same-column pairs; backend supports general ordered axes')
    target=target_configuration or target
    operations=[];work=state;travel=0.0
    def add(kind,label,duration,configuration=None):
        operations.append(Operation(f'op{len(operations):02d}',kind,label,duration,target_configuration=configuration))
    add(OperationType.AOD_LOAD,'Load',state.hardware.load_duration_us)
    work=backend.load(work,bindings)
    from .routing import plan_transport
    work,moves,travel=plan_transport(planner,work,target,bindings,gate_id,len(operations))
    operations.extend(moves)
    work=backend.offload(work,bindings)
    add(OperationType.AOD_OFFLOAD,'Offload',state.hardware.offload_duration_us)
    resources=('AOD_0','ENTANGLING_LASER_0',state.hardware.interaction_slot_id)+tuple('atom:'+a for a in sorted(captured))+tuple('trap:'+b.static_trap_id for b in bindings)
    plan=CompiledPlan('plan_'+fingerprint[:12],state.version,fingerprint,intent,bindings,requested,captured-requested,
        tuple(operations),resources,sum(o.duration_us for o in operations),travel,
        tuple(sorted(work.placement.atom_to_holder.items())),initial,planner.id)
    from .compiler import exact_validate
    exact_validate(plan,state)
    return plan
