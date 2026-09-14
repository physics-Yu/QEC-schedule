"""Compiler-free replay and before/after-correction evidence for saved QEC jobs."""
import argparse
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import sys
from time import perf_counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))


def verify(directory):
    from neutral_atom_env.visualization.workbench import build_inputs
    from neutral_atom_env.simulation.pipeline import initialize
    from neutral_atom_env.simulation.executor import Executor
    from neutral_atom_env.quantum.stabilizer import StabilizerState
    from neutral_atom_env.experiments.surface_qec import summarize,quantum_summary
    from neutral_atom_env.replay.checkpoint import restore
    from neutral_atom_env.replay.operation_codec import event_from_dict
    directory=Path(directory);started=perf_counter()
    value=json.loads((directory/'input.json').read_text(encoding='utf-8'))
    value,circuit,platform,placement=build_inputs(value)
    state=initialize(circuit,platform,placement,seed=value['seed'])
    state=replace(state,quantum_state=StabilizerState.zero(tuple(sorted(state.atoms))))
    origin=state.placement
    expected=(directory/'checkpoint.json').read_text(encoding='utf-8')
    assert restore(expected).snapshot()==expected
    records=[json.loads(line) for line in (directory/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
    pulses=Counter();effects=Counter();before=None;plans=0
    for record in records:
        if record.get('effect_completed'):
            effects.update(record.get('effect_gate_ids') or ([record['effect_gate_id']] if record.get('effect_gate_id') else []))
        event=event_from_dict(record['event'])
        if event.event_type.value!='plan_started':continue
        executor=Executor(state);executor.submit(event.plan);plans+=1
        while state.event_queue:
            executor.step()
            # This observes committed physical measurement, before any final
            # correction slots can finish; it does not query injected-fault metadata.
            if before is None and all(f'final_{kind}{b}_{i}' in state.measurement_results
                    for kind in ('X','Z') for b in range(2) for i in range(4)):
                before=quantum_summary(state.quantum_state,state.measurement_results)
        if plans%10==0:print(json.dumps({'replayed_plans':plans,'completed_gates':state.metrics()['completed_gate_count']}),flush=True)
    assert state.snapshot()==expected,'Compiler-free replay differs from committed checkpoint'
    assert state.placement==origin,'Declared initial SLM placement not restored'
    assert all(effects[g.id]==1 for g in circuit.gates),'Gate effects not exactly once'
    final=summarize(state)
    assert final['verified_logical_ghz2'] and final['measurement_protocol_complete'],final
    assert len(state.measurement_results)==32
    assert all(not a.measured for a in state.atoms.values())
    result={'compiler_free_replay':'PASS','checkpoint_restore':'PASS','exact_snapshot':True,
            'placement_restored':True,'exactly_once_effects':len(effects),'measurement_results':dict(state.measurement_results),
            'before_final_correction':before,'final':final,'replayed_plans':plans,'verification_seconds':perf_counter()-started}
    (directory/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':'PASS','effects':len(effects),'plans':plans,'seconds':result['verification_seconds'],
                      'before_xx':before['logical_xx'],'before_zz':before['logical_zz'],
                      'after_xx':final['logical_xx'],'after_zz':final['logical_zz']}),flush=True)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory');verify(parser.parse_args().directory)
