"""User contract: independent 1Q pulses share time, transport uses half corridors."""
import json
from collections import Counter
from dataclasses import replace
import pytest
from neutral_atom_app.visualization.workbench import compile_input, build_inputs
from neutral_atom_env.platform import initialize
from neutral_atom_strategies.scheduling.m4 import run_m4, fill_raman
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_strategies.motion.greedy import GreedyCompiler
from neutral_atom_env.program.scheduled import scheduled_program
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import GateStatus
from neutral_atom_env.visualization import VisualRecorder


def raw(gates,n=4,layout='row'):
    return {'compiler':'greedy','ez_policy':'adaptive','atom_count':n,'layout':layout,'seed':7,
            'gates':[{'id':f'g{i}','gate_type':kind,'qubit_ids':[f'Q{q:03d}' for q in qs],
                      'parameters':[.2,.4,.6] if kind=='U3' else [],'column':col} for i,(kind,qs,col) in enumerate(gates)]}


def state_for(value):
    _,c,p,h=build_inputs(value);return initialize(c,p,h,seed=7)


def test_four_identical_rotations_complete_together_in_one_us():
    value=raw([('H',[0],0),('H',[1],0),('H',[2],0),('H',[3],0)])
    result,state=compile_input(value);record=result['recording']
    assert result['status']=='completed' and state.time_us==1
    assert [(o['start'],o['end']) for o in record['operations']]==[(0,1)]*4
    assert set(record['summary']['resource_busy_us'])>={f'RAMAN:Q{i:03d}' for i in range(4)}
    assert state.metrics()['raman_busy_time_us']==1 and state.metrics()['raman_utilization']==1
    assert any(len(f['active_operations'])==4 and f['gate_counts']['running']==4 for f in record['frames'])


def test_per_qubit_dependencies_make_two_parallel_layers():
    result,state=compile_input(raw([('H',[0],0),('H',[1],0),('T',[0],1),('T',[1],1)]))
    assert result['status']=='completed' and state.time_us==2
    assert {o['gate_id']:(o['start'],o['end']) for o in result['recording']['operations']}=={
        'g0':(0,1),'g1':(0,1),'g2':(1,2),'g3':(1,2)}


def test_parallel_pulses_restore_every_event_and_block_same_qubit_overlap():
    value=raw([('H',[0],0),('H',[1],0),('Z',[0],1)])
    state=state_for(value);base=GreedyCompiler().alternatives('g0',state)[0][0].plan
    with pytest.raises(ValidationError):scheduled_program(base,state,(('g2',0),))
    plan=scheduled_program(base,state,(('g1',0),('g2',1)))
    e=Executor(state);e.submit(plan);snapshots=[state.snapshot()]
    while state.event_queue:e.step();snapshots.append(state.snapshot())
    for saved in snapshots:
        restored=SimulationState.restore(saved);Executor(restored).run();assert restored.snapshot()==state.snapshot()
    old=json.loads(state.snapshot());old['schema_version']=14
    with pytest.raises(ValueError):SimulationState.restore(json.dumps(old))


def test_independent_raman_must_wait_for_a_short_cz_service():
    state=state_for(raw([('CZ',[0,1],0),('CZ',[0,1],1),('H',[2],0)]))
    c=GreedyCompiler(adaptive_sites=True)
    first=min(c.alternatives('g0',state)[0],key=lambda p:p.cost).plan
    e=Executor(state);e.submit(first);e.run()
    base=min(c.alternatives('g1',state)[0],key=lambda p:p.cost).plan
    assert base.estimated_duration_us==pytest.approx(.3)
    plan,slots=fill_raman(base,state)
    assert slots==[] and plan.estimated_duration_us==pytest.approx(.3)
    with pytest.raises(ValidationError,match='Different gate types'):
        scheduled_program(base,state,(('g2',0),))
    e.submit(plan);e.run();assert run_m4(state).status=='completed'


def assert_corridors(state):
    def half(v):return abs((v-2.5)/5-round((v-2.5)/5))<1e-8
    records=[json.loads(r) for r in state.trace.records]
    count=0
    for r in records:
        if r.get('operation_type')!='aod_move' or r['event']['event_type']!='operation_started':continue
        a,b=r['source_configuration'],r['target_configuration']
        x,y=a['x_um'][0],a['y_um'][0];xx,yy=b['x_um'][0],b['y_um'][0]
        assert x==xx or y==yy,('diagonal',a,b)
        # Corridor leg, or <=2.5 um local access touching a corridor.
        assert (y==yy and (half(y) or (abs(xx-x)<=2.5+1e-8 and (half(x) or half(xx))))) or (
                x==xx and (half(x) or (abs(yy-y)<=2.5+1e-8 and (half(y) or half(yy)))))
        count+=1
    assert count>0


@pytest.mark.parametrize('layout',['row','grid','shuffled'])
def test_transport_empty_loaded_and_cleanup_all_use_corridors(layout):
    value=raw([('CZ',[0,1],0),('H',[2],0),('H',[3],0),('CZ',[0,2],1),('T',[1],1)],layout=layout)
    result,state=compile_input(value)
    assert result['status']=='completed',result['diagnostics']
    assert_corridors(state)
    ops=result['recording']['operations'];times={o['gate_id']:o['start'] for o in ops if o['kind']=='raman_rotation'}
    assert times['g1']==times['g2']==0 # Both overlap the unrelated initial handoff.
    effects=Counter(json.loads(r)['gate_id'] for r in state.trace.records if json.loads(r).get('effect_completed'))
    assert effects==Counter({f'g{i}':1 for i in range(5)})
