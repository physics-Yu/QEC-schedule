"""A batch is one physical laser interval, with all pairs audited together."""
from collections import Counter
from dataclasses import replace
import json

import pytest

from neutral_atom_env.circuit import PhysicalCircuit, DynamicGateDAG
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import Atom, GateStatus as G, GridCoord, HolderRef, HolderType as H, MobileCellIndex as Cell, PhysicalGate, Position2D as P, Rectangle, StaticTrap, Zone, ZoneType
from neutral_atom_env.domain.operations import HardwareConfig, OperationType as K, TaskIntent, TaskTarget
from neutral_atom_env.hardware import get_backend
from neutral_atom_env.program.binding import exact_validate
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_env.replay.operation_codec import plan_from_dict
from neutral_atom_env.replay.serializer import primitive
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.visualization.recording import VisualRecorder
from neutral_atom_env.world import WorldState, PlacementState, AODRuntimeState


def batch_state(n=2, *, gates=None, backend='rigid'):
    bounds=Rectangle(P(-10,-10),P(10*n+10,15))
    traps={f'S{i}':StaticTrap(f'S{i}',GridCoord(2*i,0),P(10*i,0)) for i in range(n)}
    world=WorldState(bounds,traps,(Zone('EZ',ZoneType.ENTANGLEMENT,bounds),))
    holders={};atoms={}
    for i in range(n):
        holders[f'Q{2*i:03d}']=HolderRef(H.STATIC,f'S{i}')
        holders[f'Q{2*i+1:03d}']=HolderRef(H.MOBILE,Cell(0,i))
    atoms={q:Atom(q) for q in holders}
    circuit=PhysicalCircuit(tuple(gates) if gates is not None else tuple(
        PhysicalGate(f'g{i}','CZ',(f'Q{2*i:03d}',f'Q{2*i+1:03d}')) for i in range(n)))
    aod=AODRuntimeState(pose=P(2,0),rows=1,columns=n,spacing_um=10,
        enabled_rows=(True,),enabled_columns=(True,)*n)
    return SimulationState(world,PlacementState(holders),atoms,aod,DynamicGateDAG(circuit),hardware=HardwareConfig(backend=backend))


def builder(state, ids=None):
    ids=tuple(ids or (g.id for g in state.dag.circuit.gates))
    return ProgramBuilder(state,TaskIntent('batch-test',TaskTarget(),phase='program',gate_effects=frozenset(ids)))


@pytest.mark.parametrize('n',[1,2,18])
@pytest.mark.parametrize('backend',['rigid','row_column'])
def test_single_interval_completes_all_gates_once_and_restores(n,backend):
    state=batch_state(n,backend=backend);initial=state.snapshot();p=builder(state)
    ids=tuple(g.id for g in state.dag.circuit.gates)
    p.add(K.ENTANGLING_PULSE,'True simultaneous CZ',gate_ids=ids)
    assert p.state.dag.completed and state.snapshot()==initial
    plan=p.finish('batch-test')
    assert len(plan.operations)==len(plan.operation_intervals)==1
    assert plan.estimated_duration_us==.3
    assert set(plan.operation_intervals[0].atom_ids)==set(state.atoms)
    assert plan_from_dict(primitive(plan))==plan
    recorder=VisualRecorder(state);executor=Executor(state);executor.submit(plan)
    snapshots=[]
    while state.event_queue:
        executor.step();recorder.observe(state);snapshots.append(state.snapshot())
    assert state.dag.completed and state.time_us==.3
    assert state.physical_metrics.laser_busy_time_us==.3
    effects=[json.loads(r) for r in state.trace.records if json.loads(r).get('effect_completed')]
    assert len(effects)==1
    assert Counter(effects[0]['effect_gate_ids'])==Counter({g:1 for g in ids})
    assert len(effects[0]['actual_pairs'])==n
    pulses=[o for o in recorder.payload()['operations'] if o['kind']=='entangling_pulse']
    assert len(pulses)==1 and pulses[0]['batch_size']==n and set(pulses[0]['gate_ids'])==set(ids)
    for snapshot in snapshots:
        restored=SimulationState.restore(snapshot);Executor(restored).run()
        assert restored.snapshot()==state.snapshot()


def test_batch_completion_releases_all_guards_before_suffix():
    state=batch_state();p=builder(state)
    p.add(K.ENTANGLING_PULSE,'CZ batch',gate_ids=('g0','g1'))
    p.add(K.AOD_MOVE,'Park at former reserved neighbors',target=P(5,0))
    p.intent=replace(p.intent,target=TaskTarget(aod_configuration=p.state.aod.configuration()))
    plan=p.finish('batch-suffix');Executor(state).submit(plan);Executor(state).run()
    assert state.dag.completed and state.aod.pose==P(5,0)


def test_extra_actual_pair_is_rejected_without_partial_prediction():
    state=batch_state(3);p=builder(state,('g0','g1'));before=state.snapshot()
    with pytest.raises(ValidationError,match='UNINTENDED_PAIR'):
        p.add(K.ENTANGLING_PULSE,'Omitted illuminated pair',gate_ids=('g0','g1'))
    assert not p.operations and p.state is state and state.snapshot()==before


def test_shared_qubits_and_non_cz_are_rejected():
    gates=(PhysicalGate('g0','CZ',('Q000','Q001')),PhysicalGate('g1','CZ',('Q000','Q003')))
    state=batch_state(gates=gates)
    with pytest.raises(ValidationError,match='OVERLAPPING_CZ_BATCH'):
        get_backend(state.hardware).validate_pulse_batch(state,('g0','g1'))
    state=batch_state(gates=(PhysicalGate('h','H',('Q000',)),PhysicalGate('g1','CZ',('Q002','Q003'))))
    with pytest.raises(ValidationError,match='UNSUPPORTED_GATE'):
        get_backend(state.hardware).validate_pulse_batch(state,('h','g1'))


def test_blocked_or_duplicate_effect_is_rejected_atomically():
    gates=(PhysicalGate('h','H',('Q000',)),PhysicalGate('g0','CZ',('Q000','Q001')),PhysicalGate('g1','CZ',('Q002','Q003')))
    state=batch_state(gates=gates);p=builder(state,('g0','g1'))
    with pytest.raises(ValidationError,match='blocked'):
        p.add(K.ENTANGLING_PULSE,'Blocked batch',gate_ids=('g0','g1'))
    assert p.state is state and not p.operations
    state=batch_state();p=builder(state);p.add(K.ENTANGLING_PULSE,'First',gate_ids=('g0','g1'))
    with pytest.raises(ValidationError,match='already completed'):
        p.add(K.ENTANGLING_PULSE,'Duplicate',gate_ids=('g0','g1'))
    assert len(p.operations)==1


def test_audit_rejects_missing_or_repeated_effects_from_external_plan():
    state=batch_state();p=builder(state);p.add(K.ENTANGLING_PULSE,'batch',gate_ids=('g0','g1'));plan=p.finish('audit')
    missing=replace(plan,operations=(replace(plan.operations[0],gate_ids=('g0',)),))
    with pytest.raises(ValidationError,match='Missing or duplicate'):
        exact_validate(missing,state)
    repeated=replace(plan,operations=(plan.operations[0],replace(plan.operations[0],id='op01',depends_on=('op00',))),
        operation_intervals=(plan.operation_intervals[0],replace(plan.operation_intervals[0],operation_id='op01',start_us=.3,end_us=.6)))
    with pytest.raises(ValidationError,match='Missing or duplicate'):
        exact_validate(repeated,state)


def test_vertical_pairs_on_true_two_dimensional_rigid_array():
    # Four distinct pairs occupy a 2x2 square. One y displacement addresses all
    # four together; no single-row flattening or independent mobile motion.
    state=batch_state(4)
    positions=((0,0),(10,0),(0,10),(10,10))
    traps={f'S{i}':StaticTrap(f'S{i}',GridCoord(x//5,y//5),P(x,y)) for i,(x,y) in enumerate(positions)}
    holders=dict(state.placement.atom_to_holder)
    for i in range(4):holders[f'Q{2*i+1:03d}']=HolderRef(H.MOBILE,Cell(i//2,i%2))
    state=replace(state,world=replace(state.world,traps=traps),placement=PlacementState(holders),
        aod=AODRuntimeState(pose=P(0,2),rows=2,columns=2,spacing_um=10,
            enabled_rows=(True,True),enabled_columns=(True,True)))
    p=builder(state);p.add(K.ENTANGLING_PULSE,'2D batch',gate_ids=('g0','g1','g2','g3'))
    plan=p.finish('2d-batch');Executor(state).submit(plan);Executor(state).run()
    assert state.time_us==.3 and state.dag.completed
    assert state.aod.rows==state.aod.columns==2


def test_missing_geometry_and_duplicate_ir_ids_cannot_execute():
    state=batch_state();p=builder(state)
    with pytest.raises(ValueError,match='unique CZ'):
        p.add(K.ENTANGLING_PULSE,'duplicate ids',gate_ids=('g0','g0'))
    apart=replace(state,aod=replace(state.aod,pose=P(2,2)))
    with pytest.raises(ValidationError,match='UNINTENDED_PAIR'):
        builder(apart).add(K.ENTANGLING_PULSE,'not in interaction range',gate_ids=('g0','g1'))


def test_schema_17_cannot_silently_drop_batch_semantics():
    state=batch_state();old=json.loads(state.snapshot());old['schema_version']=17
    with pytest.raises(ValidationError,match='schema 19'):
        SimulationState.restore(json.dumps(old))
