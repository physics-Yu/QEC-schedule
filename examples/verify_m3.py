"""Replay supplied plans without a compiler and independently check acceptance data."""
import argparse,json,sys
from collections import Counter,defaultdict
from math import isclose
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_env.visualization.workbench import build_inputs
from neutral_atom_env.simulation.pipeline import initialize
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.replay.operation_codec import event_from_dict
from neutral_atom_env.simulation.m3 import initial_terminal
from neutral_atom_env.motion.task_validation import validate_target
from neutral_atom_env.replay.serializer import canonical_json


def verify(directory):
    directory=Path(directory)
    read=lambda name:json.loads((directory/(name+'.json')).read_text(encoding='utf-8'))
    value,circuit,platform,placement=build_inputs(read('input'),max_atoms=256)
    state=initialize(circuit,platform,placement,seed=value['seed']);terminal=initial_terminal(state)
    saved=(directory/'checkpoint.json').read_text(encoding='utf-8')
    expected=SimulationState.restore(saved)
    records=[json.loads(r) for r in expected.trace.records]
    # Neither strategy is called here. Submit exactly the operations that were recorded.
    for r in records:
        event=event_from_dict(r['event'])
        if event.event_type.value=='plan_started':
            e=Executor(state);e.submit(event.plan);e.run()
    assert state.snapshot()==saved,'Shared validator/Executor replay differs from checkpoint'
    result=read('result');recording=read('recording')
    assert result['metrics']==state.metrics()
    effects=Counter(g for r in records if r.get('effect_completed')
                    for g in (r.get('effect_gate_ids') or (r['gate_id'],)))
    expected_gates={g.id for g in circuit.gates}
    if result['status']=='completed':
        assert effects==Counter({g:1 for g in expected_gates}),'Missing or duplicate logical effect'
        validate_target(terminal,state)
    else:assert all(g in expected_gates and count==1 for g,count in effects.items())
    intervals=defaultdict(list);durations=Counter();loads=offloads=0
    for op in recording['operations']:
        assert op['end']>op['start']
        if op['kind']=='raman_rotation':assert isclose(op['end']-op['start'],1,abs_tol=1e-8)
        if op['kind']=='entangling_pulse':assert isclose(op['end']-op['start'],.3,abs_tol=1e-8)
        loads+=op['kind'] in {'aod_load','aod_recapture'}
        offloads+=op['kind'] in {'aod_offload','aod_park'}
        for resource in op['resources']:intervals[resource].append((op['start'],op['end']))
    for resource,values in intervals.items():
        previous=-1
        for a,b in sorted(values):
            assert a>=previous-1e-8,resource+' overbooked';previous=b;durations[resource]+=b-a
        assert isclose(durations[resource],recording['summary']['resource_busy_us'][resource],abs_tol=1e-8)
    assert loads==state.metrics()['aod_load_count'] and offloads==state.metrics()['aod_offload_count']
    report={'status':'verified','run_status':result['status'],'atoms':len(state.atoms),'effects':sum(effects.values()),
            'operations':len(recording['operations']),'plans':state.metrics()['completed_plan_count'],
            'wall_time_us':state.time_us,'overlap_time_us':recording['summary']['overlap_time_us'],
            'recording_bytes':(directory/'recording.json').stat().st_size,'html_bytes':(directory/'index.html').stat().st_size}
    (directory/'verification.json').write_text(canonical_json(report),encoding='utf-8')
    print(canonical_json(report))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory');verify(p.parse_args().directory)
