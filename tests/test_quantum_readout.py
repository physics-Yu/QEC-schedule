"""Independent observable expectations for physical projection/reset/control."""
from dataclasses import replace
import json
import pytest

from neutral_atom_env.domain.models import (Atom,PhysicalGate as Gate,Position2D as P,GridCoord,StaticTrap,Zone,ZoneType,
    Rectangle,HolderRef,HolderType,GateStatus)
from neutral_atom_env.domain.operations import OperationType as K,TaskIntent,TaskTarget,HardwareConfig
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.circuit import PhysicalCircuit,DynamicGateDAG
from neutral_atom_env.world import WorldState,PlacementState,AODRuntimeState
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.simulation import Executor
from neutral_atom_env.motion.program import ProgramBuilder
from neutral_atom_env.quantum.stabilizer import StabilizerState
from neutral_atom_env.replay.operation_codec import plan_from_dict
from neutral_atom_env.replay.serializer import primitive


def state_for(gates,n=2,seed=4):
    bounds=Rectangle(P(-10,-10),P(10*n+10,20))
    traps={f's{i}':StaticTrap(f's{i}',GridCoord(2*i,0),P(10*i,0)) for i in range(n)}
    world=WorldState(bounds,traps,(Zone('readout',ZoneType.MEASUREMENT,bounds),))
    atoms={f'q{i}':Atom(f'q{i}') for i in range(n)}
    state=SimulationState(world,PlacementState({q:HolderRef(HolderType.STATIC,f's{i}') for i,q in enumerate(atoms)}),atoms,
        AODRuntimeState(pose=P(-5,-5),rows=1,columns=1),DynamicGateDAG(PhysicalCircuit(tuple(gates))),seed=seed,
        hardware=HardwareConfig(raman_zone_types=('storage','entanglement','measurement')))
    return replace(state,quantum_state=StabilizerState.zero(tuple(atoms)))


def build(state,steps):
    p=ProgramBuilder(state,TaskIntent('quantum-test',TaskTarget(),phase='program',gate_effects=frozenset(g.id for g in state.dag.circuit.gates)))
    for kind,ids in steps:
        if len(ids)==1:p.add(kind,'quantum test',gate_id=ids[0])
        else:p.add(kind,'quantum batch',gate_ids=ids)
    return p.finish('quantum-core'),p.state


def test_h_measure_reset_measure_predicts_and_executes_same_seed():
    state=state_for([Gate('h','H',('q0',)),Gate('m','MEASURE',('q0',)),Gate('r','RESET',('q0',)),Gate('m2','MEASURE',('q0',))])
    before=state.snapshot()
    plan,predicted=build(state,[(K.RAMAN_ROTATION,('h',)),(K.MEASUREMENT,('m',)),(K.RESET,('r',)),(K.MEASUREMENT,('m2',))])
    assert state.snapshot()==before
    assert predicted.measurement_results['m2']==0 and predicted.atoms['q0'].alive
    assert plan_from_dict(primitive(plan))==plan
    e=Executor(state);e.submit(plan);snapshots=[]
    while state.event_queue:e.step();snapshots.append(state.snapshot())
    assert state.time_us==1101 and state.measurement_results==predicted.measurement_results
    assert state.quantum_state==predicted.quantum_state and state.rng_state==predicted.rng_state
    assert state.physical_metrics.measurement_busy_time_us==1000 and state.physical_metrics.reset_busy_time_us==100
    for snapshot in snapshots:
        restored=SimulationState.restore(snapshot);Executor(restored).run()
        assert restored.snapshot()==state.snapshot()


def test_bell_batch_projection_correlates_bits_and_parallel_reset_restores_zero():
    gates=[Gate('m0','MEASURE',('q0',)),Gate('m1','MEASURE',('q1',)),Gate('r0','RESET',('q0',)),Gate('r1','RESET',('q1',))]
    for seed in range(4):
        state=state_for(gates,seed=seed)
        state=replace(state,quantum_state=state.quantum_state.apply_gate('H',('q0',)).apply_gate('CX',('q0','q1')))
        plan,predicted=build(state,[(K.MEASUREMENT,('m0','m1')),(K.RESET,('r0','r1'))])
        Executor(state).submit(plan);Executor(state).run()
        assert state.time_us==600
        assert state.measurement_results['m0']==state.measurement_results['m1']
        assert state.quantum_state.expectation({'q0':'Z'})==state.quantum_state.expectation({'q1':'Z'})==1
        assert all(a.alive and not a.measured for a in state.atoms.values())


@pytest.mark.parametrize('bit',[0,1])
def test_condition_depends_on_measurement_and_applies_exactly_when_true(bit):
    gates=[Gate('m','MEASURE',('q0',)),Gate('correct','X',('q1',),condition=(('m',bit),))]
    state=state_for(gates)
    assert state.dag.nodes['correct'].status==GateStatus.BLOCKED
    plan,_=build(state,[(K.MEASUREMENT,('m',)),(K.RAMAN_ROTATION,('correct',))])
    Executor(state).submit(plan);Executor(state).run()
    assert state.measurement_results['m']==0
    assert state.quantum_state.expectation({'q1':'Z'})==(-1 if bit==0 else 1)
    records=[json.loads(r) for r in state.trace.records]
    correction=next(r for r in records if r.get('gate_id')=='correct' and r.get('effect_completed'))
    assert correction['applied']==(bit==0)
    assert state.time_us==501 and state.physical_metrics.raman_busy_time_us==(1 if bit==0 else 0)


def test_tracked_t_and_untracked_measurement_reject_before_commit():
    state=state_for([Gate('t','T',('q0',))]);before=state.snapshot()
    with pytest.raises(ValidationError,match='UNSUPPORTED_TRACKED_GATE'):
        build(state,[(K.RAMAN_ROTATION,('t',))])
    assert state.snapshot()==before
    state=replace(state_for([Gate('m','MEASURE',('q0',))]),quantum_state=None)
    with pytest.raises(ValidationError,match='QUANTUM_STATE_REQUIRED'):
        build(state,[(K.MEASUREMENT,('m',))])


def test_conditions_and_explicit_barriers_are_validated_at_circuit_boundary():
    with pytest.raises(ValueError,match='earlier measurement'):
        PhysicalCircuit((Gate('x','X',('q0',),condition=(('absent',1),)),))
    with pytest.raises(ValueError,match='Only X/Z'):
        Gate('h','H',('q0',),condition=(('m',0),))
    with pytest.raises(ValueError,match='earlier gates'):
        PhysicalCircuit((Gate('x','X',('q0',),depends_on=('future',)),))
    state=state_for([Gate('h','H',('q0',)),Gate('x','X',('q1',),depends_on=('h',))])
    assert state.dag.nodes['x'].status==GateStatus.BLOCKED


def test_measurement_trace_or_quantum_state_tampering_fails_restore():
    state=state_for([Gate('m','MEASURE',('q0',))]);plan,_=build(state,[(K.MEASUREMENT,('m',))])
    Executor(state).submit(plan);Executor(state).run()
    saved=json.loads(state.snapshot())
    for i,raw in enumerate(saved['trace']):
        entry=json.loads(raw)
        if entry.get('measurement_results'):
            entry['measurement_results']['m']=1;saved['trace'][i]=json.dumps(entry);break
    with pytest.raises(ValidationError,match='Measurement trace outcome'):
        SimulationState.restore(json.dumps(saved))
    saved=json.loads(state.snapshot());saved['measurement_results']['m']=1
    with pytest.raises(ValidationError,match='measurement_results'):
        SimulationState.restore(json.dumps(saved))


def test_quantum_cz_batch_applies_each_cluster_edge_once():
    from test_batch_cz import batch_state,builder
    state=batch_state()
    quantum=StabilizerState.zero(tuple(sorted(state.atoms)))
    for q in state.atoms:quantum=quantum.apply_gate('H',(q,))
    state=replace(state,quantum_state=quantum)
    p=builder(state);p.add(K.ENTANGLING_PULSE,'Quantum CZ batch',gate_ids=('g0','g1'))
    Executor(state).submit(p.finish('tracked-batch'));Executor(state).run()
    for a,b in [('Q000','Q001'),('Q002','Q003')]:
        assert state.quantum_state.expectation({a:'X',b:'Z'})==1
        assert state.quantum_state.expectation({a:'Z',b:'X'})==1
        assert state.quantum_state.expectation({a:'X'})==0


def test_readout_requires_measurement_zone_and_stable_support():
    from neutral_atom_env.hardware.readout import validate_readout
    state=state_for([Gate('m','MEASURE',('q0',))])
    moving=replace(state,aod=replace(state.aod,is_moving=True))
    with pytest.raises(ValidationError,match='READOUT_UNSTABLE'):
        validate_readout(moving,('m',),K.MEASUREMENT)
    sz=replace(state,world=replace(state.world,zones=(Zone('storage',ZoneType.STORAGE,state.world.bounds),)))
    before=sz.snapshot()
    with pytest.raises(ValidationError,match='READOUT_ZONE_UNAVAILABLE'):
        build(sz,[(K.MEASUREMENT,('m',))])
    assert sz.snapshot()==before


def test_recorder_results_control_resources_and_post_program_rng():
    from neutral_atom_env.visualization.recording import VisualRecorder
    from neutral_atom_env.domain.models import SimulationEvent,EventType
    state=state_for([Gate('m','MEASURE',('q0',)),Gate('skip','X',('q1',),condition=(('m',1),))])
    plan,_=build(state,[(K.MEASUREMENT,('m',)),(K.RAMAN_ROTATION,('skip',))])
    recorder=VisualRecorder(state);executor=Executor(state);executor.submit(plan)
    while state.event_queue:executor.step();recorder.observe(state)
    payload=recorder.payload();readout,control=payload['operations']
    assert readout['gate_type']=='MEASURE' and readout['measurement_results']=={'m':0}
    assert control['applied'] is False and control['category']=='control'
    assert 'CONTROL:q1' in control['resources'] and not any(r.startswith('RAMAN:') for r in control['resources'])
    assert payload['frames'][-1]['measurement_results']=={'m':0}
    assert payload['frames'][0]['measurement_results']=={}
    executor.schedule(SimulationEvent(state.time_us,EventType.RNG_DRAW));executor.run()
    assert SimulationState.restore(state.snapshot()).snapshot()==state.snapshot()


def test_dag_transition_reuses_static_graph_without_changing_dependency_counts(monkeypatch):
    gates=(Gate('m','MEASURE',('q0',)),Gate('h','H',('q1',)),
           Gate('z','Z',('q1',),condition=(('m',0),),depends_on=('h',)))
    dag=DynamicGateDAG(PhysicalCircuit(gates));before=primitive(dag.nodes)
    original=DynamicGateDAG.__init__
    def rebuilding(*args):raise AssertionError('Transition rebuilt immutable dependency graph')
    monkeypatch.setattr(DynamicGateDAG,'__init__',rebuilding)
    for gid in ('m','h'):
        for status in (GateStatus.RESERVED,GateStatus.RUNNING,GateStatus.COMPLETED):dag=dag.transitioned(gid,status)
    assert dag.nodes['z'].status==GateStatus.READY and dag.nodes['z'].remaining_predecessors==0
    assert before['z']['remaining_predecessors']==2
    monkeypatch.setattr(DynamicGateDAG,'__init__',original)
    assert DynamicGateDAG.restored(dag.circuit,primitive(dag.nodes))==dag

