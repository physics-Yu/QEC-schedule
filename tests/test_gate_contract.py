"""Independent expectations for the restricted alphabet and broadcast gate type."""
import json
import pytest
from neutral_atom_env.domain.models import PhysicalGate
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware.raman import validate_rotation
from neutral_atom_app.visualization.workbench import validate_input, compile_input
from neutral_atom_strategies.motion.greedy import GreedyCompiler
from neutral_atom_env.program.scheduled import scheduled_program
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from test_parallel_orthogonal import raw, state_for
from test_raman import state_for as physical_state


@pytest.mark.parametrize('kind,params', [('U3',[.1,.2,.3]),('U',[0,0,0]),('RX',[1]),('RY',[1]),
    ('RZ',[1]),('S',[]),('Sdg',[]),('Tdg',[]),('I',[])])
def test_unsupported_gates_rejected_by_ui_api_and_physical_backend(kind,params):
    value=raw([(kind,[0],0)]);value['gates'][0]['parameters']=params
    with pytest.raises(ValueError,match='仅限'):validate_input(value)
    state=physical_state([PhysicalGate('g',kind,('Q000',),params)])
    with pytest.raises(ValidationError,match='UNSUPPORTED_GATE'):validate_rotation(state,'g')


def test_cphase_cannot_masquerade_as_cz_in_low_level_backend():
    from neutral_atom_env.hardware import get_backend
    state=physical_state([PhysicalGate('g','CPHASE',('Q000','Q001'),(.2,))])
    with pytest.raises(ValidationError,match='UNSUPPORTED_GATE'):
        get_backend(state.hardware).validate_pulse(state,'g')


@pytest.mark.parametrize('kind',['H','X','Y','Z','T'])
def test_each_identical_gate_family_parallel_in_one_us(kind):
    result,state=compile_input(raw([(kind,[q],0) for q in range(4)]))
    assert result['status']=='completed' and state.time_us==1
    assert [(o['start'],o['end']) for o in result['recording']['operations']]==[(0,1)]*4


def test_mixed_gate_families_grouped_without_serializing_same_type():
    # Deliberately interleave IDs: g2 must join g0 despite intervening X g1.
    result,state=compile_input(raw([('H',[0],0),('X',[1],0),('H',[2],0),('X',[3],0)]))
    assert result['status']=='completed' and state.time_us==2
    times={o['gate_id']:(o['start'],o['end']) for o in result['recording']['operations']}
    assert times=={'g0':(0,1),'g2':(0,1),'g1':(1,2),'g3':(1,2)}


def test_executor_rejects_mixed_overlap_atomically_and_restores_valid_boundary():
    from dataclasses import replace
    state=state_for(raw([('H',[0],0),('X',[1],0)]))
    base=GreedyCompiler().alternatives('g0',state)[0][0].plan
    before=state.snapshot()
    with pytest.raises(ValidationError,match='Different gate types'):
        scheduled_program(base,state,(('g1',.5),))
    assert state.snapshot()==before
    valid=scheduled_program(base,state,(('g1',1),))
    bad_interval=replace(valid.operation_intervals[1],start_us=.5,end_us=1.5)
    bad=replace(valid,operation_intervals=(valid.operation_intervals[0],bad_interval))
    with pytest.raises(ValidationError):Executor(state).submit(bad)
    assert state.snapshot()==before
    executor=Executor(state);executor.submit(valid);snapshots=[state.snapshot()]
    while state.event_queue:executor.step();snapshots.append(state.snapshot())
    assert state.time_us==2
    for saved in snapshots:
        resumed=SimulationState.restore(saved);Executor(resumed).run()
        assert resumed.snapshot()==state.snapshot()
    old=json.loads(state.snapshot());old['schema_version']=14
    with pytest.raises(ValueError):SimulationState.restore(json.dumps(old))


def test_cz_and_1q_effects_do_not_overlap_but_transport_still_does():
    result,state=compile_input(raw([('CZ',[0,1],0),('H',[2],0),('H',[3],0),('T',[2],1)]))
    assert result['status']=='completed'
    kinds={g.id:g.gate_type for g in state.dag.circuit.gates}
    effects=[o for o in result['recording']['operations'] if o['kind'] in {'raman_rotation','entangling_pulse'}]
    for i,a in enumerate(effects):
        for b in effects[i+1:]:
            if max(a['start'],b['start'])<min(a['end'],b['end']):
                assert kinds[a['gate_id']]==kinds[b['gate_id']]
    h=[o for o in effects if kinds[o['gate_id']]=='H']
    assert len(h)==2 and h[0]['start']==h[1]['start']==0
    assert any(o['kind']=='aod_load' and o['start']==0 and o['end']>=1 for o in result['recording']['operations'])
