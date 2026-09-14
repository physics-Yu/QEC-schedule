"""Baseline QEC order with retained CZ cohorts, batch Raman and MZ choices.

Reference candidates are validated in a purely predicted offloaded state.
Only plans compiled against the actual live state are ever submitted. This
does not optimize gate ordering or change the classical measurement policy.
"""
from dataclasses import replace
from time import perf_counter

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderType as H,GateStatus
from neutral_atom_env.domain.operations import TaskIntent,TaskTarget,OperationType as K
from neutral_atom_env.motion.qec_persistent import PersistentCohortCompiler
from neutral_atom_env.motion.program import ProgramBuilder
from neutral_atom_env.motion.qec_readout import choose_readout_service,reject_internal
from neutral_atom_env.motion.task_validation import validate_target
from neutral_atom_env.replay.serializer import primitive
from .executor import Executor
from .m3 import initial_terminal
from .m4 import M4Result
from .qec import qec_cz_groups,readout_groups
from .patch_greedy import patch_assignment,preflight_group,batch_service


def _resume_context(state, terminal, compiler):
    """Read-only reconstruction at an audited complete QEC-plan boundary."""
    import json
    from neutral_atom_env.domain.models import ZoneType
    from neutral_atom_env.domain.operations import CaptureBinding
    from neutral_atom_env.hardware.dynamic_traps import trap_state
    from neutral_atom_env.hardware.rigid_aod import distance
    from neutral_atom_env.motion.qec_persistent import RetainedCohort
    from neutral_atom_env.motion.single_trap import in_zone
    from neutral_atom_env.replay.operation_codec import plan_from_dict
    from .runtime_validation import validate_runtime

    def require(condition, code, message):
        if not condition:raise ValidationError(code,message)
    require(isinstance(terminal,TaskTarget),'QEC_RESUME_TERMINAL',
            'Resume requires the explicit original full terminal target')
    require(not(state.event_queue or state.active_plan or state.transfer or state.reservations)
            and not state.aod.is_moving,'QEC_RESUME_BOUNDARY',
            'Resume requires an idle completed plan; no queued or partial operations may be drained')
    require(bool(state.trace.records),'QEC_RESUME_BOUNDARY','Resume needs a committed QEC plan prefix')
    last=json.loads(state.trace.records[-1])['event']
    require(last['event_type']=='plan_completed' and last['time_us']==state.time_us,
            'QEC_RESUME_BOUNDARY','The last committed event must be PLAN_COMPLETED at the current time')
    require(all(n.status not in {GateStatus.RESERVED,GateStatus.RUNNING,GateStatus.FAILED}
                for n in state.dag.nodes.values()),'QEC_RESUME_BOUNDARY','No unfinished or failed gate runtime may remain')
    require(all(a.alive for a in state.atoms.values()),'QEC_RESUME_WORKING_LAYOUT','All original atoms must remain alive')
    validate_runtime(state)
    stage=None;stage_completed=False
    for raw in state.trace.records:
        event=json.loads(raw)['event']
        if stage is None and event['event_type']=='plan_started':
            raw_plan=event['plan']
            if raw_plan['planner_id']=='qec-stage-v1' and raw_plan['intent'].get('task_id','').startswith('qec-stage/'):
                stage=plan_from_dict(raw_plan)
        elif stage is not None and event['event_type']=='plan_completed' and event['plan_id']==stage.id:
            stage_completed=True;break
    require(stage is not None and stage_completed,'QEC_RESUME_ORIGIN','No completed original QEC stage is recorded')
    require(stage.initial_placement is not None and stage.initial_aod_configuration is not None
            and stage.initial_traps is not None,'QEC_RESUME_ORIGIN','Original stage lacks full terminal provenance')
    original=TaskTarget(stage.initial_placement,stage.initial_aod_configuration,stage.initial_traps)
    require(terminal==original and {q for q,_ in terminal.holders}==set(state.atoms),
            'QEC_RESUME_TERMINAL','Explicit terminal must exactly match the original stage origin')
    if (state.dag.completed and tuple(sorted(state.placement.atom_to_holder.items()))==terminal.holders
            and state.aod.configuration()==terminal.aod_configuration and trap_state(state)==terminal.traps):
        validate_target(terminal,state)
        return None,True
    working=dict(stage.predicted_placement)
    require(set(working)==set(state.atoms) and all(h.holder_type==H.STATIC for h in working.values()),
            'QEC_RESUME_ORIGIN','Original completed stage must identify every working SLM')
    bindings=[]
    for q in sorted(state.atoms):
        expected=working[q];site=state.world.traps.get(expected.holder_id)
        require(site is not None and in_zone(state,site.position,ZoneType.ENTANGLEMENT),
                'QEC_RESUME_WORKING_LAYOUT','Original working supports must lie in EZ')
        holder=state.placement.atom_to_holder[q]
        if holder.holder_type==H.STATIC:
            require(holder==expected,'QEC_RESUME_WORKING_LAYOUT','Static atom has left its original EZ working support')
        else:
            require(holder.holder_type==H.MOBILE,'QEC_RESUME_COHORT','Unexpected non-static/non-mobile holder')
            point=state.aod.position(holder.holder_id)
            matches=[t.id for t in state.world.traps.values()
                     if distance(point,t.position)<=state.hardware.alignment_tolerance_um]
            require(matches==[site.id] and not state.slm_enabled[site.id]
                    and site.id not in state.placement.static_occupancy,'QEC_RESUME_COHORT',
                    'Each carried atom must align with its unique unoccupied, switched-off original working SLM')
            bindings.append(CaptureBinding(q,holder.holder_id,site.id))
    cohort=RetainedCohort(tuple(bindings),state.aod.pose) if bindings else None
    if cohort is not None:compiler.validate_cohort(state,cohort)
    return cohort,False


def run_qec_joint(state,*,on_event=None,terminal=None,max_decisions=10000,
                       candidate_budget=4096,route_expansions=100000,frontier_validator=None,
                       compiler_type=PersistentCohortCompiler,resume=False):
    terminal=terminal if resume else terminal or initial_terminal(state)
    compiler=compiler_type(route_expansions);executor=Executor(state)
    rejected=[];log=[];decisions=0;phase='initialization';cohort=None
    def drain():
        while state.event_queue:
            event=executor.step()
            if on_event:on_event(state,event)
    def submit(plan,entry,started):
        nonlocal decisions
        if decisions>=max_decisions:raise ValidationError('DECISION_BUDGET_EXHAUSTED','Persistent QEC decision budget exhausted')
        entry.update(decision=decisions,start_us=state.time_us,duration_us=plan.estimated_duration_us,
            compile_wall_time_s=perf_counter()-started)
        executor.submit(plan);log.append(entry);decisions+=1;drain()
    def reject(error,entry):
        reject_internal(error)
        rejected.append(entry|{'violation':primitive(error.violation)})
    def release(reason,prepared=None):
        nonlocal cohort
        if cohort is None:return
        started=perf_counter();plan,_=prepared or compiler.release(state,cohort)
        submit(plan,{'kind':'cohort_release','reason':reason,'atoms':sorted(cohort.atoms)},started)
        cohort=None
    def result(status,error=None):
        diagnostics=() if error is None else ({'code':error.violation.code,'message':error.violation.message,
            'phase':phase,'decisions_completed':decisions,'unfinished_gates':[
                g.id for g in state.dag.circuit.gates if state.dag.nodes[g.id].status!=GateStatus.COMPLETED]},)
        summary={'kind':'reuse_summary','retained_count':sum(e.get('kind')=='cz_batch' and bool(e.get('retained_atoms')) and not e.get('cohort_reused') for e in log),
            'reuse_count':sum(bool(e.get('cohort_reused')) for e in log),
            'flush_count':sum(e.get('kind')=='cohort_release' for e in log),
            'loaded_readout_visits':sum(e.get('readout_search',{}).get('selected_family')=='loaded_return' for e in log),
            'readout_saved_us':sum(e.get('readout_search',{}).get('saved_us',0.) for e in log)}
        return M4Result(status,diagnostics,tuple(rejected),decisions,tuple(log)+(summary,))
    try:
        if type(resume) is not bool:raise ValidationError('QEC_RESUME_OPTION','resume must be a boolean')
        if state.quantum_state is None:raise ValidationError('QEC_QUANTUM_STATE_REQUIRED','Enable quantum tracking before QEC')
        if resume:
            phase='resume_boundary';cohort,at_terminal=_resume_context(state,terminal,compiler)
            if at_terminal:return result('completed')
        else:
            if state.placement.mobile_occupancy:raise ValidationError('QEC_REUSE_INITIAL_STATE','This runner starts from an empty AOD; checkpoints remain replayable by Executor')
            drain()
            if state.dag.completed:validate_target(terminal,state);return result('completed')
            phase='joint_preparation';started=perf_counter();destinations=patch_assignment(state)
            p=ProgramBuilder(state,TaskIntent(f'qec-stage/{state.version}',TaskTarget(),frozenset(state.atoms),phase='prepare'))
            compiler.transfer_group(p,destinations,'Stage data and stabilizer ancillas in EZ')
            p.intent=replace(p.intent,target=TaskTarget(tuple(sorted(p.state.placement.atom_to_holder.items()))))
            if p.operations:submit(p.finish('qec-stage-v1'),{'kind':'stage','atoms':len(destinations)},started)
        while not state.dag.completed:
            if decisions>=max_decisions:raise ValidationError('DECISION_BUDGET_EXHAUSTED','Persistent QEC decision budget exhausted')
            ready=list(state.dag.ready_gates());started=perf_counter();phase='frontier'
            if frontier_validator is not None:
                frontier_validator(state,ready)
            rotations=[g for g in ready if g.u_parameters is not None]
            if rotations:
                gate=rotations[0];same=[g for g in rotations if g.gate_type==gate.gate_type]
                p=ProgramBuilder(state,TaskIntent(f'qec-raman/{state.version}/{gate.id}',TaskTarget(),
                    frozenset(q for g in same for q in g.qubit_ids),phase='program',gate_effects=frozenset(g.id for g in same)))
                p.add(K.RAMAN_ROTATION,'One simultaneous same-type pulse on stable supports',gate_ids=tuple(g.id for g in same))
                plan=p.finish('qec-joint-raman-v1')
                submit(plan,{'kind':'raman','gate_type':gate.gate_type,'batch_size':len(same),
                    'selected':','.join(g.id for g in same),'retained_atoms':sorted(cohort.atoms) if cohort else []},started)
                continue
            phase='cz_search';cz=[g for g in ready if g.gate_type=='CZ'];chosen=None
            prepared=compiler.release(state,cohort) if cohort else None
            reference=prepared[1] if prepared else state
            # Same candidate order and full first-valid reference service as
            # the immutable baseline. Reuse cannot promote another cohort.
            for attempt,(shift,members) in enumerate(qec_cz_groups(reference,cz)):
                if attempt>=candidate_budget:break
                try:
                    preflight_group(reference,compiler,shift,members)
                    batch_service(reference,compiler,shift,members)
                    chosen=(shift,members);break
                except ValidationError as error:reject(error,{'kind':'cz_reference','members':members,'shift':shift})
            if chosen:
                shift,members=chosen
                if cohort and frozenset(m for _,_,m in members)!=cohort.atoms:
                    release('baseline_selected_different_cohort',prepared)
                reused=cohort is not None
                try:plan,new_cohort=compiler.pulse(state,members,shift,cohort)
                except ValidationError as error:
                    # Declared candidate fallback: retain/reuse can be more
                    # constrained than the validated restoring service.
                    reject(error,{'kind':'persistent_candidate','members':members,'shift':shift})
                    release('persistent_candidate_rejected')
                    plan=batch_service(state,compiler,shift,members);new_cohort=None;reused=False
                submit(plan,{'kind':'cz_batch','batch_size':len(members),'selected':','.join(g for g,_,_ in members),
                    'cohort_reused':reused,'retained_atoms':sorted(new_cohort.atoms) if new_cohort else []},started)
                cohort=new_cohort
                continue
            if cohort:release('readout_or_other_frontier',prepared)
            phase='readout_search'
            for kind in ('MEASURE','RESET'):
                pending=[g for g in ready if g.gate_type==kind]
                for group in readout_groups(state,pending) if pending else ():
                    try:
                        plan,count,report=choose_readout_service(state,compiler,group);chosen=(plan,group,count,report);break
                    except ValidationError as error:reject(error,{'kind':'readout','gates':[g.id for g in group]})
                if chosen:break
            if chosen:
                submit(chosen[0],{'kind':'readout','batch_size':len(chosen[1]),'reset_count':chosen[2],
                    'selected':','.join(g.id for g in chosen[1]),'readout_search':chosen[3]},started)
                continue
            raise ValidationError('QEC_FRONTIER_EXHAUSTED','No ready quantum or readout group passed physical validation')
        phase='terminal';release('explicit_terminal');started=perf_counter()
        p=ProgramBuilder(state,TaskIntent(f'qec-return/{state.version}',terminal,frozenset(state.atoms),phase='cleanup'))
        compiler.restore(p,terminal)
        if p.operations:submit(p.finish('qec-terminal-v1'),{'kind':'terminal'},started)
        validate_target(terminal,state)
        return result('completed')
    except ValidationError as error:return result('stalled',error)
