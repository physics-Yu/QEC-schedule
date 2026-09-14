"""Freeze an existing verified QEC reference; never infer PASS from screenshots."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime,timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))


def audit(source,output):
    from neutral_atom_env.visualization.workbench import build_inputs
    from neutral_atom_env.simulation.pipeline import initialize
    from neutral_atom_env.simulation.m3 import initial_terminal
    from neutral_atom_env.replay.checkpoint import restore
    from neutral_atom_env.replay.serializer import primitive,canonical_json
    from neutral_atom_env.experiments.surface_qec import summarize
    source=Path(source).resolve();output=Path(output);output.mkdir(parents=True,exist_ok=True)
    read=lambda name:json.loads((source/name).read_text(encoding='utf-8'))
    value,circuit,platform,placement=build_inputs(read('input.json'))
    state=restore((source/'checkpoint.json').read_text(encoding='utf-8'))
    verified=read('verification.json');browser=read('browser-acceptance.json');result=read('result.json')
    assert verified['compiler_free_replay']=='PASS' and verified['exact_snapshot'] is True
    assert browser['status']=='passed' and browser['real_edit_and_compile'] is True
    assert state.dag.completed and len(circuit.gates)==481
    assert state.dag.circuit==circuit
    assert state.world==platform.world and state.hardware==platform.hardware
    assert state.seed==value['seed']
    assert state.metrics()==result['metrics']
    quantum=summarize(state)
    assert quantum['verified_logical_ghz2'] and quantum['measurement_protocol_complete']
    assert quantum['syndrome_bits']==verified['measurement_results']
    origin=initialize(circuit,platform,placement,seed=value['seed'])
    target=initial_terminal(origin)
    from neutral_atom_env.motion.task_validation import validate_target
    validate_target(target,state)
    hashes={name:hashlib.sha256((source/name).read_bytes()).hexdigest() for name in
        ('input.json','checkpoint.json','trace.jsonl','recording.json','result.json','verification.json','browser-acceptance.json')}
    branch_order=[];reset_projections={};applied_corrections=[]
    conditional_ids={g.id for g in circuit.gates if g.condition}
    for line in (source/'trace.jsonl').read_text(encoding='utf-8').splitlines():
        record=json.loads(line)
        if record['event']['event_type']=='operation_completed' and record.get('operation_type') in ('measurement','reset'):
            branch_order.extend(record.get('effect_gate_ids') or [record['effect_gate_id']])
            reset_projections.update(record.get('reset_projection_results',{}))
        if record.get('effect_completed'):
            applied_corrections.extend(g for g in record.get('applied_gate_ids',()) if g in conditional_ids)
    assert len(branch_order)==64
    contract={'input':value,'platform':primitive(platform),'placement':placement,'terminal':primitive(target),
        'measurement_results':dict(state.measurement_results),'rng_effect_order':branch_order,
        'rng_final_state':primitive(state.rng_state),'reset_projection_results':reset_projections,
        'applied_conditional_gate_ids':sorted(applied_corrections),
        'requirements':{'same_input_except_strategy':True,'same_platform':True,'same_terminal':True,
            'same_measurement_branch_for_single_run_comparison':True,'all_effects_exactly_once':True,
            'independent_physical_replay':True,'quantum_and_protocol_pass':True,
            'step2_total_time_strictly_below_us':state.time_us,'step2_loads_strictly_below':state.metrics()['aod_load_count']}}
    manifest={'status':'passed','created_at':datetime.now(timezone.utc).isoformat(),'source':str(source),
        'artifact_sha256':hashes,'contract_sha256':hashlib.sha256(canonical_json(contract).encode()).hexdigest(),
        'metrics':state.metrics(),'measurement_protocol_complete':True,'logical_xx':quantum['logical_xx'],
        'logical_zz':quantum['logical_zz'],'note':'Existing compiler-free replay evidence was checked; this audit restores and validates the saved reference, not a fresh compilation.'}
    (output/'baseline-contract.json').write_text(canonical_json(contract),encoding='utf-8')
    (output/'baseline-manifest.json').write_text(canonical_json(manifest),encoding='utf-8')
    (output/'baseline-input.json').write_text(canonical_json(value),encoding='utf-8')
    print(canonical_json(manifest))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',default='artifacts/surface-qec-ghz2/browser');parser.add_argument('--output',default='artifacts/qec-roadmap')
    args=parser.parse_args();audit(args.source,args.output)
