"""One declared step-3 attempt. Failure is reported, never automatically retried."""
import argparse
from collections import Counter
from dataclasses import replace
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys
from time import perf_counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))


def main():
    from neutral_atom_env.visualization.workbench import build_inputs
    from neutral_atom_env.simulation.pipeline import initialize
    from neutral_atom_env.simulation.qec_joint import run_qec_joint
    from neutral_atom_env.quantum.stabilizer import StabilizerState
    from neutral_atom_env.experiments.surface_qec import summarize
    from neutral_atom_env.replay.serializer import canonical_json
    from neutral_atom_env.replay.checkpoint import restore
    from neutral_atom_env.motion.task_validation import validate_target
    from neutral_atom_env.simulation.m3 import initial_terminal
    from neutral_atom_env.visualization import VisualRecorder
    from neutral_atom_env.visualization.viewer import write_html
    from qec_roadmap_status import update
    parser=argparse.ArgumentParser();parser.add_argument('--output',default='artifacts/qec-roadmap/step3-attempt1')
    parser.add_argument('--contract',default='artifacts/qec-roadmap/baseline-contract.json');args=parser.parse_args()
    output=Path(args.output);output.mkdir(parents=True,exist_ok=False)
    contract=json.loads(Path(args.contract).read_text(encoding='utf-8'))
    value,circuit,platform,placement=build_inputs(contract['input'])
    assert canonical_json(value)==canonical_json(contract['input'])
    assert canonical_json(platform)==canonical_json(contract['platform'])
    state=initialize(circuit,platform,placement,seed=value['seed'])
    state=replace(state,quantum_state=StabilizerState.zero(tuple(sorted(state.atoms))))
    terminal=initial_terminal(state);recorder=VisualRecorder(state)
    (output/'input.json').write_text(canonical_json(value),encoding='utf-8')
    (output/'strategy.json').write_text(canonical_json({'actual_strategy':'qec_joint','reference_strategy':value['compiler'],
        'attempt':1,'started_at':datetime.now(timezone.utc).isoformat(),'retry_authorized':False}),encoding='utf-8')
    def source_hashes():
        return {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path('src').rglob('*')) if p.suffix in {'.py','.js','.html'}}
    source_before=source_hashes();started=perf_counter();last=[-1]
    def observe(s,event):
        recorder.observe(s,event)
        count=s.metrics()['completed_gate_count']
        if event.event_type.value=='plan_completed' and count!=last[0]:
            last[0]=count;info={'completed_gates':count,'total_gates':len(circuit.gates),'simulation_time_us':s.time_us,'wall_seconds':perf_counter()-started}
            (output/'progress.json').write_text(canonical_json(info),encoding='utf-8');print(canonical_json(info),flush=True)
    result=None;error=None
    try:
        result=run_qec_joint(state,on_event=observe,terminal=terminal)
        assert result.status=='completed',str(result.diagnostics)
        validate_target(terminal,state)
        report=summarize(state)
        assert report['verified_logical_ghz2'] and report['measurement_protocol_complete'],'Quantum/protocol acceptance failed'
        assert dict(state.measurement_results)==contract['measurement_results'],'PAIRED_BRANCH_MISMATCH: same seed gave a different complete measurement branch; no speedup claim is allowed'
        rows=[json.loads(r) for r in state.trace.records]
        reset={g:b for r in rows for g,b in r.get('reset_projection_results',{}).items()}
        assert reset==contract['reset_projection_results'],'RESET projection branch differs'
        conditional={g.id for g in circuit.gates if g.condition}
        applied=sorted(g for r in rows if r.get('effect_completed') for g in r.get('applied_gate_ids',()) if g in conditional)
        assert applied==contract['applied_conditional_gate_ids'],'Actual conditional corrections differ'
        effects=Counter(g for r in rows if r.get('effect_completed') for g in (r.get('effect_gate_ids') or ([r['effect_gate_id']] if r.get('effect_gate_id') else [])))
        assert effects==Counter(g.id for g in circuit.gates),'Effects not exactly once'
        assert state.time_us<20885.9-1e-6,'NO_TIME_IMPROVEMENT_OVER_STEP2'
        assert state.metrics()['aod_load_count']<45,'NO_LOAD_IMPROVEMENT_OVER_STEP2'
        assert state.metrics()['raman_busy_time_us']<=33+1e-7,'MOBILE_BATCH_PARALLELISM_NOT_RECOVERED'
        assert restore(state.snapshot()).snapshot()==state.snapshot(),'Checkpoint restoration differs'
        assert source_hashes()==source_before,'Source changed during formal attempt'
    except Exception as exc:
        error={'code':type(exc).__name__,'message':str(exc)}
    elapsed=perf_counter()-started
    # Always preserve the actual partial state and observer output.
    payload=recorder.payload();payload['scene']['atom_roles']=contract['input'].get('qec_protocol',{}).get('atom_roles',{})
    for name,data in [('recording',payload),('qec_result',summarize(state)),('result',{'status':'failed' if error else 'checks_passed_replay_pending',
            'actual_strategy':'qec_joint','metrics':state.metrics(),'compile_seconds':elapsed,'error':error}),
            ('diagnostics',result.diagnostics if result else [error]),('decisions',getattr(result,'decision_log',())),
            ('candidate_rejections',getattr(result,'candidate_rejections',())),('source-stability',{'changed_during_run':source_hashes()!=source_before})]:
        (output/f'{name}.json').write_text(canonical_json(data),encoding='utf-8')
    (output/'checkpoint.json').write_text(state.snapshot(),encoding='utf-8')
    (output/'trace.jsonl').write_text('\n'.join(state.trace.records)+'\n',encoding='utf-8')
    write_html(payload,output/'index.html')
    if error:
        failure={'facts':[f"步骤3首次正式完整对照未通过：{error['message']}",f"实际完成{state.metrics()['completed_gate_count']}/{len(circuit.gates)}，物理时间{state.time_us} μs"],
            'hypotheses':['原因待只读诊断；不得把配对分支不匹配误报为物理无解。'],
            'proposed_retry_scope':['先定位失败记录，明确拟议修正和验证范围，用户在对话审批后才启动新尝试。']}
        update('artifacts/qec-roadmap/status.json','step3','fail',failure=failure,evidence=[{'label':'实际失败产物','path':'step3-attempt1/result.json'}])
    print(canonical_json({'status':'failed' if error else 'checks_passed_replay_pending','error':error,'metrics':state.metrics(),'compile_seconds':elapsed}),flush=True)
    return 1 if error else 0


if __name__=='__main__':raise SystemExit(main())
