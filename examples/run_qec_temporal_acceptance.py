"""One bounded full temporal experiment, then compiler-free replay.

Completed and partial evidence is preserved. This script never retries.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))


def dump(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def sources():
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((ROOT/'src').rglob('*')) if p.suffix in {'.py','.js','.html'}}


def check_final(state,circuit,terminal):
    from neutral_atom_env.experiments.surface_qec_temporal import summarize,validate_history
    from neutral_atom_env.motion.task_validation import validate_target
    from neutral_atom_env.replay.checkpoint import restore
    validate_target(terminal,state)
    report=summarize(state)
    assert report['verified_logical_ghz2'] and report['measurement_protocol_complete'],report
    assert validate_history(state.measurement_results)['supported']
    assert len(state.measurement_results)==80
    assert all(a.alive and not a.measured for a in state.atoms.values())
    effects=Counter(g for line in state.trace.records for r in [json.loads(line)] if r.get('effect_completed')
                    for g in (r.get('effect_gate_ids') or [r['effect_gate_id']]))
    assert effects==Counter(g.id for g in circuit.gates)
    flipped=[]
    for line in state.trace.records:
        record=json.loads(line)
        if not record.get('effect_completed'):continue
        for gid,truth in record.get('measurement_true_results',{}).items():
            if truth!=record['measurement_results'][gid]:flipped.append(gid)
    assert flipped==['round2_X0_0'],flipped
    assert restore(state.snapshot()).snapshot()==state.snapshot()
    return report


def compile_case(output):
    from neutral_atom_env.experiments.surface_qec_temporal import experiment_input,summarize
    from neutral_atom_env.visualization.workbench import build_inputs,initialize_input,recording_payload
    from neutral_atom_env.visualization import VisualRecorder
    from neutral_atom_env.visualization.viewer import write_html
    from neutral_atom_env.simulation.qec_temporal import run_qec_temporal
    from neutral_atom_env.simulation.m3 import initial_terminal
    from neutral_atom_env.replay.serializer import primitive
    output.mkdir(parents=True,exist_ok=True)
    raw=experiment_input({'kind':'readout','round':2,'patch':0,'check_type':'X','check_index':0})
    raw['seed']=7
    raw['compile_timeout_s']=1800
    value,circuit,platform,placement=build_inputs(raw)
    state=initialize_input(value,circuit,platform,placement)
    terminal=initial_terminal(state);recorder=VisualRecorder(state)
    before=sources();started=perf_counter();saved=[-1]
    dump(output/'input.json',value)
    dump(output/'strategy.json',{'actual_strategy':'qec_temporal','stage':'4B','attempt':1})
    (output/'last-committed-checkpoint.json').write_text(state.snapshot(),encoding='utf-8')
    def observe(s,event):
        recorder.observe(s,event)
        if event.event_type.value!='plan_completed':return
        count=s.metrics()['completed_gate_count']
        progress={'completed_gates':count,'total_gates':len(circuit.gates),'simulation_time_us':s.time_us,
                  'elapsed_seconds':perf_counter()-started}
        dump(output/'progress.json',progress)
        if count-saved[0]>=40 or count==len(circuit.gates):
            (output/'last-committed-checkpoint.json').write_text(s.snapshot(),encoding='utf-8')
            dump(output/'last-committed-progress.json',progress);saved[0]=count
            print(json.dumps(progress),flush=True)
    result=None;error=None
    try:
        result=run_qec_temporal(state,on_event=observe,terminal=terminal)
        assert result.status=='completed',str(result.diagnostics)
        check_final(state,circuit,terminal)
        assert before==sources(),'Source changed during execution'
    except Exception as exc:
        error={'code':type(exc).__name__,'message':str(exc)}
    (output/'checkpoint.json').write_text(state.snapshot(),encoding='utf-8')
    (output/'trace.jsonl').write_text('\n'.join(state.trace.records)+'\n',encoding='utf-8')
    payload=recording_payload(recorder,value)
    dump(output/'recording.json',payload);write_html(payload,output/'index.html')
    dump(output/'qec_result.json',summarize(state))
    dump(output/'result.json',{'status':'failed' if error else 'checks_passed_replay_pending',
        'actual_strategy':'qec_temporal','error':error,'compile_seconds':perf_counter()-started,'metrics':state.metrics()})
    for name in ('diagnostics','candidate_rejections','decision_log'):
        dump(output/('decisions.json' if name=='decision_log' else name+'.json'),primitive(getattr(result,name,())))
    dump(output/'source-stability.json',{'changed_during_run':before!=sources(),'files':before})
    print(json.dumps({'compile_status':'failed' if error else 'passed','error':error}),flush=True)
    return 1 if error else 0


def verify_case(output):
    from neutral_atom_env.visualization.workbench import build_inputs,initialize_input
    from neutral_atom_env.simulation.m3 import initial_terminal
    from neutral_atom_env.simulation import Executor
    from neutral_atom_env.replay.operation_codec import event_from_dict
    from neutral_atom_env.experiments.surface_qec_temporal import HISTORY_IDS,validate_history
    value,circuit,platform,placement=build_inputs(json.loads((output/'input.json').read_text(encoding='utf-8')))
    state=initialize_input(value,circuit,platform,placement);terminal=initial_terminal(state)
    started=perf_counter();plans=0;checked=False
    for line in (output/'trace.jsonl').read_text(encoding='utf-8').splitlines():
        record=json.loads(line);event=event_from_dict(record['event'])
        if event.event_type.value!='plan_started':continue
        executor=Executor(state);executor.submit(event.plan);plans+=1
        while state.event_queue:
            executor.step()
            if not checked and all(g in state.measurement_results for g in HISTORY_IDS):
                validate_history(state.measurement_results);checked=True
        if plans%20==0:print(json.dumps({'replayed_plans':plans,'completed_gates':state.metrics()['completed_gate_count']}),flush=True)
    assert state.snapshot()==(output/'checkpoint.json').read_text(encoding='utf-8')
    report=check_final(state,circuit,terminal)
    assert checked
    dump(output/'verification.json',{'compiler_free_replay':'PASS','checkpoint_restore':'PASS',
        'exact_snapshot':True,'history_guard':True,'replayed_plans':plans,'final':report,
        'verification_seconds':perf_counter()-started})
    return 0


def main(args):
    output=Path(args.output)
    if args.mode=='compile':return compile_case(output)
    if args.mode=='verify':return verify_case(output)
    output.mkdir(parents=True,exist_ok=False)
    dump(output/'attempt.json',{'stage':'4B','attempt':1,'started_at':datetime.now(timezone.utc).isoformat(),
        'compile_budget_seconds':1800,'verify_budget_seconds':1800,'contract':'docs/qec_temporal_attempt1.md'})
    for mode in ('compile','verify'):
        print(json.dumps({'phase':mode,'status':'started'}),flush=True)
        try:
            run=subprocess.run([sys.executable,__file__,'--mode',mode,'--output',str(output)],
                cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=1800)
            text=run.stdout+run.stderr;code=run.returncode
        except subprocess.TimeoutExpired as exc:
            text='DECLARED_1800_SECOND_BUDGET_EXCEEDED\n'
            for chunk in (exc.stdout,exc.stderr):
                text+=chunk.decode('utf-8',errors='replace') if isinstance(chunk,bytes) else chunk or ''
            code=124
        (output/(mode+'-output.txt')).write_text(text,encoding='utf-8')
        print(json.dumps({'phase':mode,'status':'passed' if not code else 'failed','exit_code':code}),flush=True)
        if code:
            dump(output/'failure.json',{'phase':mode,'exit_code':code,'action':'Persisted for diagnosis; no automatic retry'})
            return code
    return 0


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',default='artifacts/qec-roadmap/step4B-attempt1')
    p.add_argument('--mode',choices=['all','compile','verify'],default='all')
    sys.exit(main(p.parse_args()))
