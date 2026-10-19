"""Real small-window continuation and adversarial public-context probes.

Mutated guards/contexts are explicit negative fixtures; successful execution of
such a mutant is a failure finding, never production acceptance.
"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import gzip,json,time,traceback

from na_pipeline.device import preinitialized_device
from na_pipeline.backend import place_patches,compile_physical_dag
from na_pipeline.qec import build_patch_operation_spec
from na_pipeline.runtime import EventSession,bind_physical_plan,make_scenario

root=Path(__file__).resolve().parents[2]; out=root/'knowledge/roles/R6/evidence/T605'; out.mkdir(parents=True,exist_ok=True)


def main():
    began=time.perf_counter(); results=[]; artifacts={}
    source_paths=[root/'src/na_pipeline/runtime/session.py',root/'src/na_pipeline/runtime/window_binding.py',root/'src/na_pipeline/backend/physical_dag.py',root/'src/na_pipeline/backend/execution_context.py']
    source_before={str(p.relative_to(root)):sha256(p.read_bytes()).hexdigest() for p in source_paths}
    try:
        device=preinitialized_device(); placement=place_patches({'block':{'aod_group':'data','basis':'Z','value':0}},[],device)
        session=EventSession(device,placement['initial_state'],run_id='R6-D05')
        se=build_patch_operation_spec('SE')['physical_dag']; context=session.compilation_context(se)
        first=compile_physical_dag(se,device,session.snapshot()['world_state'],execution_context=context)
        bound=bind_physical_plan(first,context); scenario=make_scenario(bound,value=0)
        session.submit(bound,scenario,expected_revision=context['revision']); session.advance()
        checkpoint=session.checkpoint(); snapshot=session.snapshot(); bit=next(iter(snapshot['published_results']))
        artifacts.update(device=device,initial_state=placement['initial_state'],first_plan=first,first_bound=bound,first_trace=session.export_trace(),first_snapshot=snapshot)
        x=build_patch_operation_spec('X')['physical_dag']; x['execution_guard']={'bit':bit,'equals':0}; x['external_reads']=[bit]
        context=session.compilation_context(x); second=compile_physical_dag(x,device,snapshot['world_state'],execution_context=context); absolute=bind_physical_plan(second,context)
        start=min(a['t_start_us'] for a in absolute['actions'])
        session.submit(absolute,make_scenario(absolute),expected_revision=context['revision']); session.advance()
        relative_start=min(a['t_start_us'] for a in second['atom_program']['actions'])
        results.append({'case':'second_window_real_t_positive','passed':start==snapshot['time_us']+relative_start and start>0,'start_us':start,'relative_start_us':relative_start,'frontier_us':snapshot['time_us'],'final_us':session.snapshot()['time_us']})
        artifacts.update(second_plan=second,second_context=context,second_bound=absolute,second_trace=session.export_trace())
        def reject(label,fn):
            try:
                value=fn(); results.append({'case':label,'passed':False,'accepted':True,'return_type':type(value).__name__})
            except Exception as exc:
                results.append({'case':label,'passed':hasattr(exc,'code'),'accepted':False,'error_type':type(exc).__name__,'code':getattr(exc,'code',None),'message':str(exc)})
        reject('stale_revision',lambda:EventSession.restore(device,checkpoint).submit(absolute,make_scenario(absolute),expected_revision=-1))
        twice=deepcopy(second); twice['atom_program']=absolute
        reject('double_time_binding',lambda:bind_physical_plan(twice,context))
        negative=deepcopy(x); negative['execution_guard']['equals']=1
        clean=EventSession.restore(device,checkpoint); false_context=clean.compilation_context(negative)
        reject('false_guard_normal_compile',lambda:compile_physical_dag(negative,device,snapshot['world_state'],execution_context=false_context))
        forged=deepcopy(false_context)
        forged['published_results'][bit]['value']=1
        for decision in forged['graph_decisions'].values(): decision['decision']='execute'
        def fake_guard_submission():
            p=compile_physical_dag(negative,device,snapshot['world_state'],execution_context=forged)
            a=bind_physical_plan(p,forged); clone=EventSession.restore(device,checkpoint); clone.compilation_context(negative)
            artifacts['forged_guard_fixture']={'dag':negative,'context':forged,'plan':p,'bound_atom':a}
            clone.submit(a,make_scenario(a),expected_revision=snapshot['revision']); clone.advance()
            artifacts['forged_guard_trace']=clone.export_trace()
            return clone.snapshot()
        reject('forged_false_guard_context',fake_guard_submission)
        original_context=EventSession.restore(device,checkpoint).compilation_context(x)
        other_action=next(e['action_id'] for e in artifacts['first_trace']['events'] if e['kind']=='reset')
        def changed_context(label,change):
            changed=deepcopy(original_context); change(changed)
            def submit_changed():
                clone=EventSession.restore(device,checkpoint)
                clone.compilation_context(x)
                p=compile_physical_dag(x,device,snapshot['world_state'],execution_context=changed)
                a=bind_physical_plan(p,changed)
                clone.submit(a,make_scenario(a),expected_revision=snapshot['revision']); clone.advance()
            reject(label,submit_changed)
        def producer_change(ctx):
            ctx['published_results'][bit]['action_id']=other_action
            ctx['published_results'][bit]['producer_ref']['action_id']=other_action
            for choice in ctx['graph_decisions'].values(): choice['result_refs'][bit]['action_id']=other_action
        changed_context('forged_actual_producer',producer_change)
        def ready_change(ctx):
            ctx['published_results'][bit]['ready_us']+=1
            ctx['published_results'][bit]['available_us']+=1
        changed_context('forged_ready_time',ready_change)
        def refs_change(ctx):
            for choice in ctx['graph_decisions'].values(): choice['result_refs'][bit]['event_trace_ref']='invented-history'
        changed_context('forged_result_refs',refs_change)
        guard_only=deepcopy(original_context)
        for choice in guard_only['graph_decisions'].values():
            choice['external_reads']=[]; choice['result_refs']={}
        guard_only['published_results']={}
        reject('guard_only_bit_still_requires_witness',lambda:EventSession.restore(device,checkpoint).validate_context(guard_only))
        deferred=compile_physical_dag(x,device,snapshot['world_state'],defer_runtime_inputs=True)
        reject('deferred_plan_cannot_bind',lambda:bind_physical_plan(deferred,original_context))
        promoted=deepcopy(deferred); promoted['atom_program']['complete']=True
        def submit_promoted():
            clone=EventSession.restore(device,checkpoint); issued=clone.compilation_context(x); a=bind_physical_plan(promoted,issued)
            artifacts['deferred_promoted_fixture']={'original_plan':deferred,'promoted_plan':promoted,'bound_atom':a,'context':issued}
            clone.submit(a,make_scenario(a),expected_revision=snapshot['revision']); clone.advance()
        reject('deferred_cannot_become_complete_by_flag',submit_promoted)
        duplicate=deepcopy(second); duplicate['atom_program']['actions'].append(deepcopy(duplicate['atom_program']['actions'][0]))
        reject('shared_action_must_not_be_copied',lambda:bind_physical_plan(duplicate,original_context))
        # Delayed result is known in the scenario but cannot be used before
        # publication. All first-window geometry/actions remain real.
        late=EventSession(device,placement['initial_state'],run_id='R6-D05-late')
        ctx=late.compilation_context(se); p=compile_physical_dag(se,device,late.snapshot()['world_state'],execution_context=ctx); a=bind_physical_plan(p,ctx)
        sc=make_scenario(a,value=0); delayed_bit=next(iter(sc['results'])); delay=max(t['t_end_us'] for t in a['actions'])+100.
        sc['results'][delayed_bit]['ready_us']=delay
        late.submit(a,sc,expected_revision=ctx['revision']); late.advance(delay-1)
        conditional=deepcopy(x); conditional['execution_guard']={'bit':delayed_bit,'equals':0}; conditional['external_reads']=[delayed_bit]
        reject('delayed_result_before_ready',lambda:late.compilation_context(conditional))
        late.advance(delay); ctx=late.compilation_context(conditional)
        p=compile_physical_dag(conditional,device,late.snapshot()['world_state'],execution_context=ctx); a=bind_physical_plan(p,ctx)
        expected=delay+device['timings_us']['feedback_latency']; actual=min(v['t_start_us'] for v in a['actions'])
        results.append({'case':'graph_feedback_latency_after_delayed_ready','passed':actual>=expected,'actual_start_us':actual,'required_start_us':expected})
    except Exception as exc:
        results.append({'case':'probe_incomplete','passed':False,'error':str(exc),'traceback':traceback.format_exc()})
    source_after={str(p.relative_to(root)):sha256(p.read_bytes()).hexdigest() for p in source_paths}
    summary={'schema_version':'R6D05Probe/0.1','scope':'single-patch real physical continuation plus explicitly mutated negative contexts','passed':all(r['passed'] for r in results),'full_program_passed':False,'seconds':time.perf_counter()-began,'cases':results,'source_before':source_before,'source_after':source_after,'source_unchanged':source_before==source_after,'quantum_state_simulated':False,'hardware_executed':False}
    (out/'D05-probe.json').write_bytes((json.dumps(summary,ensure_ascii=False,indent=2)+'\n').encode('utf-8'))
    with gzip.open(out/'D05-inputs.json.gz','wb') as f:f.write(json.dumps(artifacts,ensure_ascii=False,separators=(',',':')).encode('utf-8'))
    print(json.dumps(summary,ensure_ascii=False,indent=2),flush=True)
    return 0 if summary['passed'] else 1


if __name__=='__main__': raise SystemExit(main())
