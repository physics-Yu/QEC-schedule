"""Two bounded readout service families, preserving reference effect order.

The reference SLM service chooses the group and first legal destination. The
alternative uses that exact destination with stationary, loaded AOD atoms.
No additional destination search, measurement reorder or changed permissions.
"""
from dataclasses import replace
from time import perf_counter

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderType as H,Position2D,ZoneType,GateStatus
from neutral_atom_env.domain.operations import TaskIntent,TaskTarget,OperationType as K
from neutral_atom_env.replay.serializer import primitive
from neutral_atom_env.hardware.dynamic_traps import trap_state
from .program import ProgramBuilder
from .single_trap import in_zone


INTERNAL_FAILURES=frozenset({'PLAN_TAMPERED','OUTDATED_STATE','INVALID_RUNTIME','INVALID_CHECKPOINT'})


def reject_internal(error):
    """Programming/state-consistency failures are never a geometric fallback."""
    if error.violation.code in INTERNAL_FAILURES or 'runtime mismatch' in error.violation.message.lower():raise error


def _reference_service(state,compiler,gates):
    """Same baseline destination/effect order, with transparent strict errors."""
    from neutral_atom_env.simulation.qec import measurement_destinations
    atoms=tuple(g.qubit_ids[0] for g in gates)
    source={q:state.placement.atom_to_holder[q].holder_id for q in atoms}
    resets=[]
    for gate in gates:
        for key in state.dag.nodes[gate.id].successors:
            candidate=state.dag.nodes[key].gate
            parents={p for p,n in state.dag.nodes.items() if key in n.successors}
            available={g.id for g in gates}|{g for g,n in state.dag.nodes.items() if n.status==GateStatus.COMPLETED}
            if candidate.gate_type=='RESET' and candidate.qubit_ids==gate.qubit_ids and parents<=available:resets.append(candidate)
    ids=tuple(g.id for g in gates)+tuple(g.id for g in resets)
    destinations=[source] if all(in_zone(state,state.placement.position(q,state.world,state.aod),ZoneType.MEASUREMENT)
        for q in atoms) else measurement_destinations(state,atoms)
    errors=[];last=None
    for index,destination in enumerate(destinations):
        try:
            p=ProgramBuilder(state,TaskIntent(f'qec-readout/{state.version}/{gates[0].id}',TaskTarget(),
                frozenset(atoms),phase='program',gate_effects=frozenset(ids)))
            compiler.transfer_group(p,destination,'Move readout atoms to MZ')
            p.add(K.MEASUREMENT if gates[0].gate_type=='MEASURE' else K.RESET,
                f'{gates[0].gate_type}: {len(gates)} atoms in MZ',gate_ids=tuple(g.id for g in gates))
            if resets:p.add(K.RESET,'Reset measured ancillas for reuse',gate_ids=tuple(g.id for g in resets))
            compiler.transfer_group(p,source,'Return readout atoms to their working sites')
            p.intent=replace(p.intent,target=TaskTarget(tuple(sorted(p.state.placement.atom_to_holder.items())),
                p.state.aod.configuration(),trap_state(p.state)))
            plan=p.finish('qec-measure-reset-return-v1')
            return plan,len(resets),{'destination_candidates_total':len(destinations),'destinations_attempted':index+1,
                'destination_rejections':errors,'selected_destination':destination}
        except ValidationError as error:
            reject_internal(error);last=error
            errors.append({'destination':destination,'violation':primitive(error.violation)})
    raise last


def retained_readout_service(state,compiler,reference):
    effects=tuple(o for o in reference.operations if o.operation_type in {K.MEASUREMENT,K.RESET})
    if not effects:raise ValidationError('QEC_READOUT_KEEP_NOT_APPLICABLE','Reference contains no readout effect')
    first_index=reference.operations.index(effects[0])
    arrivals=[o for o in reference.operations[:first_index] if o.operation_type==K.AOD_OFFLOAD]
    if not arrivals:
        raise ValidationError('QEC_READOUT_KEEP_NOT_APPLICABLE','Reference already begins on MZ SLM; no transport pair to remove')
    unload=arrivals[-1].transfer_bindings
    atoms=tuple(b.atom_id for b in unload)
    if state.placement.mobile_occupancy or any(state.placement.atom_to_holder[q].holder_type!=H.STATIC for q in atoms):
        raise ValidationError('QEC_READOUT_KEEP_NOT_APPLICABLE','Readout retention begins with all selected atoms on SLM and an empty AOD')
    if any(not in_zone(state,state.world.traps[b.static_trap_id].position,ZoneType.MEASUREMENT) for b in unload):
        raise ValidationError('QEC_READOUT_KEEP_NOT_APPLICABLE','Reference arrival is not in MZ')
    # Do not silently disable a trap or use a fictitious approach exception to
    # occupy an illuminated SLM. This family is explicitly unavailable there.
    if any(state.slm_enabled[b.static_trap_id] for b in unload):
        raise ValidationError('QEC_READOUT_ACTIVE_MZ_SLM','Loaded readout candidate requires its MZ SLM destinations to be OFF')
    origin,bindings=compiler.bindings(state,atoms)
    destination={b.atom_id:state.world.traps[b.static_trap_id].position for b in unload}
    shifts={(destination[b.atom_id].x_um-state.world.traps[b.static_trap_id].position.x_um,
             destination[b.atom_id].y_um-state.world.traps[b.static_trap_id].position.y_um) for b in bindings}
    if len(shifts)!=1:raise ValidationError('QEC_READOUT_KEEP_NOT_APPLICABLE','Reference MZ arrival is not a rigid translation')
    dx,dy=next(iter(shifts));target=Position2D(origin.x_um+dx,origin.y_um+dy)
    ids=frozenset(g for o in effects for g in o.effect_gate_ids)
    p=ProgramBuilder(state,TaskIntent(f'qec-readout-keep/{state.version}/{effects[0].effect_gate_ids[0]}',
        reference.intent.target,frozenset(atoms),phase='program',gate_effects=ids))
    compiler.route(p,origin)
    p.add(K.AOD_LOAD,'Load readout cohort for one uninterrupted MZ visit',bindings=bindings)
    compiler.route(p,target,depart=bindings,label='Move loaded readout cohort into MZ')
    for effect in effects:
        p.add(effect.operation_type,effect.label,gate_ids=effect.effect_gate_ids)
    # Sources have been OFF since LOAD. The return is ordinary checked motion;
    # the aligned OFFLOAD immediately following is a real final handoff.
    compiler.route(p,origin,label='Return measured and reset cohort to working sites')
    p.add(K.AOD_OFFLOAD,'Offload readout cohort after the complete MZ visit',bindings=bindings)
    return p.finish('qec-readout-loaded-v1')


def choose_readout_service(state,compiler,gates):
    """Return (plan, reset_count, report) after at most two service classes.

    Baseline destination enumeration is unchanged. There is exactly one extra
    retained candidate, at that first valid reference destination.
    """
    from neutral_atom_env.simulation.operation_program import audit
    started=perf_counter()
    reference,count,destination_report=_reference_service(state,compiler,gates)
    entries=[{'family':'slm_return','status':'valid','duration_us':reference.estimated_duration_us,
              'compile_wall_time_s':perf_counter()-started}]
    chosen=reference;family='slm_return';started=perf_counter()
    try:
        retained=retained_readout_service(state,compiler,reference)
        # All clock/metrics differences are expected cost differences. The
        # physical target and exact quantum/RNG branch must nevertheless agree.
        left=audit(reference,state)[0];right=audit(retained,state)[0]
        for name in ('placement','aod','slm_enabled','transfer','atoms','quantum_state','measurement_results','rng_state','dag'):
            if getattr(left,name)!=getattr(right,name):
                raise ValidationError('PLAN_TAMPERED','Readout candidates have different semantic terminal field: '+name)
        if tuple((o.operation_type,o.effect_gate_ids) for o in reference.operations if o.effect_gate_ids)!=tuple(
                (o.operation_type,o.effect_gate_ids) for o in retained.operations if o.effect_gate_ids):
            raise ValidationError('PLAN_TAMPERED','Readout candidates changed the ordered effect stream')
        entries.append({'family':'loaded_return','status':'valid','duration_us':retained.estimated_duration_us,
                        'compile_wall_time_s':perf_counter()-started})
        if retained.estimated_duration_us<reference.estimated_duration_us:chosen=retained;family='loaded_return'
    except ValidationError as error:
        reject_internal(error)
        entries.append({'family':'loaded_return','status':'rejected','violation':primitive(error.violation),
                        'compile_wall_time_s':perf_counter()-started})
    return chosen,count,{'service_class_budget':2,'destination_policy':'baseline_first_valid',
        'reference_destination_search':destination_report,'loaded_destination_candidates':1,
        'candidates':entries,'selected_family':family,'selected_duration_us':chosen.estimated_duration_us,
        'reference_duration_us':reference.estimated_duration_us,
        'saved_us':reference.estimated_duration_us-chosen.estimated_duration_us}
