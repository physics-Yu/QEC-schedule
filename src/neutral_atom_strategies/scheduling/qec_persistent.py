"""Conservative QEC baseline order with same-cohort transport reuse.

Reference candidates are validated in a purely predicted offloaded state.
Only plans compiled against the actual live state are ever submitted. This
does not optimize gate ordering or change the classical measurement policy.
"""
from neutral_atom_env.environment import as_environment
from dataclasses import replace
from time import perf_counter

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderType as H, GateStatus
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget, OperationType as K
from neutral_atom_strategies.motion.qec_persistent import PersistentCohortCompiler
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_env.program.scheduled import scheduled_program
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_env.replay.serializer import primitive
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from neutral_atom_strategies.scheduling.m4 import M4Result
from neutral_atom_strategies.scheduling.qec import qec_cz_groups, readout_groups, readout_service
from neutral_atom_strategies.scheduling.patch_greedy import patch_assignment, preflight_group, batch_service


def run_qec_persistent(state,*,on_event=None,terminal=None,max_decisions=10000,
                       candidate_budget=4096,route_expansions=100000):
    env = as_environment(state)
    state = env.state
    terminal=terminal or initial_terminal(state)
    compiler=PersistentCohortCompiler(route_expansions);executor=env
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
    def reject(error,entry):rejected.append(entry|{'violation':primitive(error.violation)})
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
            'flush_count':sum(e.get('kind')=='cohort_release' for e in log)}
        return M4Result(status,diagnostics,tuple(rejected),decisions,tuple(log)+(summary,))
    try:
        if state.quantum_state is None:raise ValidationError('QEC_QUANTUM_STATE_REQUIRED','Enable quantum tracking before QEC')
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
            rotations=[g for g in ready if g.u_parameters is not None]
            if rotations:
                gate=rotations[0];same=[g for g in rotations if g.gate_type==gate.gate_type]
                # Existing core reserves AOD_0 exclusively for each mobile
                # Raman operation. Respect it: at most one mobile target per
                # optical interval; static targets can still join that pulse.
                mobile=[g for g in same if state.placement.atom_to_holder[g.qubit_ids[0]].holder_type==H.MOBILE]
                if len(mobile)>1:
                    keep=mobile[0].id;same=[g for g in same if g not in mobile or g.id==keep]
                gate=same[0]
                p=ProgramBuilder(state,TaskIntent(f'qec-raman/{state.version}/{gate.id}',TaskTarget(),
                    frozenset(gate.qubit_ids),gate.id,'effect',gate.id))
                p.add(K.RAMAN_ROTATION,'Same-type addressed control on stable supports',gate_id=gate.id)
                plan=p.finish('qec-raman-retained-v1')
                if len(same)>1:plan=scheduled_program(plan,state,tuple((g.id,0.) for g in same[1:]))
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
                        plan,count=readout_service(state,compiler,group);chosen=(plan,group,count);break
                    except ValidationError as error:reject(error,{'kind':'readout','gates':[g.id for g in group]})
                if chosen:break
            if chosen:
                submit(chosen[0],{'kind':'readout','batch_size':len(chosen[1]),'reset_count':chosen[2],
                    'selected':','.join(g.id for g in chosen[1])},started)
                continue
            raise ValidationError('QEC_FRONTIER_EXHAUSTED','No ready quantum or readout group passed physical validation')
        phase='terminal';release('explicit_terminal');started=perf_counter()
        p=ProgramBuilder(state,TaskIntent(f'qec-return/{state.version}',terminal,frozenset(state.atoms),phase='cleanup'))
        compiler.restore(p,terminal)
        if p.operations:submit(p.finish('qec-terminal-v1'),{'kind':'terminal'},started)
        validate_target(terminal,state)
        return result('completed')
    except ValidationError as error:return result('stalled',error)
