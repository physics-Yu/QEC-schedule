import json
from dataclasses import replace
from math import pi
import pytest
from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate, GateStatus, HolderType, HolderRef, MobileCellIndex
from neutral_atom_env.domain.operations import ExecuteGateBatchIntent, OperationType as K
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_strategies.motion.single_trap import SingleTrapCompiler
from neutral_atom_env.program.binding import exact_validate
from neutral_atom_env.platform import Platform, initialize
from neutral_atom_app.pipeline import run_circuit
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.visualization import VisualRecorder


def state_for(gates):
    return initialize(PhysicalCircuit(tuple(gates)), Platform.load('configs/platforms/single_trap.json'),
                      {f'Q{i:03d}':f'S{i:03d}' for i in range(8)})


def test_raman_cost_is_fixed_in_hardware_and_restore():
    from neutral_atom_env.domain.operations import HardwareConfig
    assert HardwareConfig().raman_duration_us == 1
    for duration in (0, 5, 7.5, True, float('nan')):
        with pytest.raises(ValueError, match='fixed at 1 us'):
            HardwareConfig(raman_duration_us=duration)
    saved=json.loads(state_for([PhysicalGate('g','H',('Q000',))]).snapshot())
    saved['hardware']['raman_duration_us']=5
    with pytest.raises(ValidationError,match='fixed at 1 us'):
        SimulationState.restore(json.dumps(saved))


@pytest.mark.parametrize('kind,params,u', [('U3',(.2,.3,.4),(.2,.3,.4)),('H',(),(pi/2,0,pi)),
    ('RX',(.7,),(.7,-pi/2,pi/2)),('RZ',(.8,),(0,0,.8)),('Y',(),(pi,pi/2,pi/2)),('Sdg',(),(0,0,-pi/2))])
def test_normalization(kind,params,u):
    gate=PhysicalGate('g',kind,('Q000',),params)
    assert gate.u_parameters==u and gate.parameters==params and gate.gate_type==kind


@pytest.mark.parametrize('kind,params', [('U3',()),('RX',()),('H',(1,)),('CZ',(1,)),
    ('U3',(0,float('nan'),1)),('U3',(0,True,1)),('RZ',(float('inf'),))])
def test_bad_parameters(kind,params):
    with pytest.raises(ValueError):
        PhysicalGate('g',kind,('Q000','Q001') if kind=='CZ' else ('Q000',),params)


def test_real_rotation_boundaries_and_restore():
    state=state_for([PhysicalGate('g','T',('Q000',))])
    before=state.snapshot(); placement=state.placement; axes=state.aod
    plan=SingleTrapCompiler().compile(ExecuteGateBatchIntent({'g'}),state)
    assert state.snapshot()==before and plan.resources==('RAMAN:Q000','atom:Q000','trap:S000')
    assert not plan.bindings and plan.estimated_distance_um==0 and plan.estimated_duration_us==1
    executor=Executor(state); executor.submit(plan)
    snapshots=[state.snapshot()]; recorder=VisualRecorder(state)
    while state.event_queue:
        executor.step(); snapshots.append(state.snapshot()); recorder.observe(state)
        assert state.placement==placement and state.aod==axes
    assert state.time_us==1 and state.dag.completed
    assert state.metrics()['raman_busy_time_us']==1 and state.metrics()['aod_busy_time_us']==0
    for snapshot in snapshots:
        resumed=SimulationState.restore(snapshot); Executor(resumed).run()
        assert resumed.snapshot()==state.snapshot()
    operations=recorder.payload()['operations']
    assert len(operations)==1 and operations[0]['u_parameters_rad']==[0,0,pi/4]
    assert any(f['gate_status']=='running' and f['atom_updates'][0]['activity']=='gating' for f in recorder.frames if f['atom_updates'])
    effects=[json.loads(r) for r in state.trace.records if json.loads(r).get('effect_completed')]
    assert len(effects)==1 and effects[0]['gate_id']=='g'


def test_tampered_duration_duplicate_effect_and_resources_rejected_atomically():
    state=state_for([PhysicalGate('g','H',('Q000',))]); before=state.snapshot()
    plan=SingleTrapCompiler().compile(ExecuteGateBatchIntent({'g'}),state)
    for bad in [replace(plan,operations=(replace(plan.operations[0],duration_us=0),)),
                replace(plan,operations=plan.operations+(replace(plan.operations[0],id='op01'),)),
                replace(plan,resources=('AOD_0',))]:
        with pytest.raises(ValidationError): Executor(state).submit(bad)
        assert state.snapshot()==before


def test_raman_accepts_stationary_loaded_but_rejects_motion_and_unaddressed_zone():
    from neutral_atom_env.hardware.raman import validate_rotation
    from neutral_atom_env.world import PlacementState
    state=state_for([PhysicalGate('g','H',('Q000',))])
    no_zone=replace(state,hardware=replace(state.hardware,raman_zone_types=('entanglement',)))
    with pytest.raises(ValidationError,match='RAMAN_ZONE'):validate_rotation(no_zone,'g')
    holders=dict(state.placement.atom_to_holder); holders['Q000']=HolderRef(HolderType.MOBILE,MobileCellIndex(0,0))
    loaded=replace(state,placement=PlacementState(holders),aod=replace(state.aod,enabled_rows=(True,),enabled_columns=(True,)),slm_enabled=dict(state.slm_enabled)|{'S000':False})
    assert validate_rotation(loaded,'g').id=='g'
    with pytest.raises(ValidationError,match='RAMAN_TARGET_MOVING'):validate_rotation(replace(loaded,aod=replace(loaded.aod,is_moving=True)),'g')


def test_mixed_circuit_real_transport_and_three_rotations():
    gates=[PhysicalGate('G000','H',('Q000',)),PhysicalGate('G001','CZ',('Q000','Q001')),
           PhysicalGate('G002','T',('Q001',)),PhysicalGate('G003','Z',('Q000',))]
    state=state_for(gates)
    result,final,recorder=run_circuit(state.dag.circuit,Platform(state.world,state.hardware,state.aod),
                                    {q:h.holder_id for q,h in state.placement.atom_to_holder.items()})
    assert result.status=='completed' and final.placement==state.placement
    assert final.time_us==pytest.approx(600+2*(181+2*(5**2+35**2)**.5)+.3+3)
    assert final.metrics()['raman_busy_time_us']==3
    effects=[op for op in recorder.operations if op['kind'] in ('raman_rotation','entangling_pulse')]
    assert [op['gate_id'] for op in effects]==['G000','G001','G002','G003']
    rows={r['key']:r for r in recorder.payload()['summary']['categories']}
    assert rows['raman']['duration_us']==3 and rows['pulse']['duration_us']==pytest.approx(.3)


def test_aliases_match_independent_standard_unitaries_up_to_global_phase():
    from cmath import exp
    from math import cos, sin, sqrt
    a=.73; c=cos(a/2); s=sin(a/2)
    expected={'I':[1,0,0,1], 'X':[0,1,1,0], 'Y':[0,-1j,1j,0], 'Z':[1,0,0,-1],
              'H':[1/sqrt(2),1/sqrt(2),1/sqrt(2),-1/sqrt(2)],
              'S':[1,0,0,1j], 'Sdg':[1,0,0,-1j], 'T':[1,0,0,exp(1j*pi/4)],
              'Tdg':[1,0,0,exp(-1j*pi/4)], 'RX':[c,-1j*s,-1j*s,c],
              'RY':[c,-s,s,c], 'RZ':[exp(-1j*a/2),0,0,exp(1j*a/2)]}
    for kind,target in expected.items():
        theta,phi,lam=PhysicalGate('g',kind,('Q000',),(a,) if kind.startswith('R') else ()).u_parameters
        u=[cos(theta/2),-exp(1j*lam)*sin(theta/2),exp(1j*phi)*sin(theta/2),exp(1j*(phi+lam))*cos(theta/2)]
        index=next(i for i,v in enumerate(target) if abs(v)>1e-6);phase=u[index]/target[index]
        assert abs(phase)==pytest.approx(1)
        assert all(abs(x-phase*y)<1e-12 for x,y in zip(u,target)),kind


def test_rotation_plan_bound_to_parameters_and_recovery_rejects_damage():
    from neutral_atom_env.circuit import DynamicGateDAG
    gate=PhysicalGate('g','T',('Q000',)); state=state_for([gate])
    plan=SingleTrapCompiler().compile(ExecuteGateBatchIntent({'g'}),state)
    changed=replace(state,dag=DynamicGateDAG(PhysicalCircuit((replace(gate,gate_type='X'),))))
    with pytest.raises(ValidationError,match='OUTDATED_STATE'):Executor(changed).submit(plan)
    executor=Executor(state);executor.submit(plan);executor.step();executor.step()
    assert state.dag.nodes['g'].status==GateStatus.RUNNING
    for damage in ['parameters','duration','status','schema']:
        saved=json.loads(state.snapshot())
        if damage=='parameters':saved['circuit']['gates'][0]['parameters']=[.2,.3]
        if damage=='duration':saved['active_plan']['plan']['operations'][0]['duration_us']=0
        if damage=='status':saved['dag']['g']['status']='completed'
        if damage=='schema':saved['schema_version']=10
        with pytest.raises((ValidationError,ValueError)):SimulationState.restore(json.dumps(saved))
