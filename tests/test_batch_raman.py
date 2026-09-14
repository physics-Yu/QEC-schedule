"""One same-type optical interval, with per-target physical and quantum effects.

These are the declared first-attempt positives and rejection cases. Root runs
the first formal test invocation; writing this file does not claim a PASS.
"""
from collections import Counter
from dataclasses import replace
import json

import pytest

from neutral_atom_env.circuit import DynamicGateDAG, PhysicalCircuit
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import (
    Atom, GridCoord, HolderRef, HolderType as H, MobileCellIndex as Cell,
    PhysicalGate as Gate, Position2D as P, Rectangle, StaticTrap, Zone, ZoneType,
)
from neutral_atom_env.domain.operations import CaptureBinding, HardwareConfig, OperationType as K, TaskIntent, TaskTarget
from neutral_atom_env.hardware import get_backend
from neutral_atom_env.hardware.dynamic_traps import begin_transfer
from neutral_atom_env.hardware.raman import validate_rotation_batch
from neutral_atom_env.motion.program import ProgramBuilder
from neutral_atom_env.motion.scheduled import scheduled_program
from neutral_atom_env.quantum.stabilizer import StabilizerState
from neutral_atom_env.replay.operation_codec import plan_from_dict
from neutral_atom_env.replay.serializer import primitive
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.operation_program import audit
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.world import AODRuntimeState, PlacementState, WorldState


def batch_state(gates=None, *, n=3, mobile=(), spacing=10, tracked=True):
    gates=tuple(gates) if gates is not None else tuple(Gate(f'h{i}','H',(f'q{i}',)) for i in range(n))
    mobile=set(mobile)
    bounds=Rectangle(P(-20,-20),P(10*n+20,20))
    traps={f's{i}':StaticTrap(f's{i}',GridCoord(2*i,0),P(10*i,0),enabled=i not in mobile) for i in range(n)}
    # The test hardware explicitly permits Raman addressing inside this MZ.
    world=WorldState(bounds,traps,(Zone('MZ',ZoneType.MEASUREMENT,bounds),))
    atoms={f'q{i}':Atom(f'q{i}') for i in range(n)}
    holders={q:HolderRef(H.MOBILE,Cell(0,i)) if i in mobile else HolderRef(H.STATIC,f's{i}')
             for i,q in enumerate(atoms)}
    aod=AODRuntimeState(pose=P(0,0),rows=1,columns=n,spacing_um=spacing,
        enabled_rows=(bool(mobile),),enabled_columns=tuple(i in mobile for i in range(n)))
    state=SimulationState(world,PlacementState(holders),atoms,aod,DynamicGateDAG(PhysicalCircuit(gates)),
        hardware=HardwareConfig(raman_zone_types=('storage','entanglement','measurement')))
    return replace(state,quantum_state=StabilizerState.zero(tuple(atoms))) if tracked else state


def builder(state,ids=None):
    ids=tuple(ids) if ids is not None else tuple(g.id for g in state.dag.circuit.gates)
    return ProgramBuilder(state,TaskIntent('raman-batch-test',TaskTarget(),phase='program',gate_effects=frozenset(ids)))


def execute(state,plan):
    executor=Executor(state);executor.submit(plan);snapshots=[state.snapshot()]
    while state.event_queue:
        executor.step();snapshots.append(state.snapshot())
    return snapshots


@pytest.mark.parametrize('mobile',[(),(0,1,2),(0,2)])
@pytest.mark.parametrize('tracked',[False,True])
def test_static_mobile_and_mixed_batch_has_one_interval_and_exact_effects(mobile,tracked):
    state=batch_state(mobile=mobile,tracked=tracked);before=state.snapshot();holders=state.placement
    ids=('h0','h1','h2');p=builder(state);p.add(K.RAMAN_ROTATION,'Three simultaneous H gates',gate_ids=ids)
    assert p.state.dag.completed and state.snapshot()==before
    plan=p.finish('batch-raman')
    assert plan.estimated_duration_us==1 and len(plan.operations)==len(plan.operation_intervals)==1
    assert plan.operation_intervals[0].resources.count('AOD_0')==bool(mobile)
    assert plan_from_dict(primitive(plan))==plan
    snapshots=execute(state,plan)
    assert state.time_us==1 and state.dag.completed and state.placement==holders
    assert state.physical_metrics.raman_busy_time_us==1
    assert state.physical_metrics.aod_busy_time_us==0  # Baseline excludes Raman lock time.
    if tracked:
        assert all(state.quantum_state.expectation({q:'X'})==1 for q in state.atoms)
    effects=[json.loads(r) for r in state.trace.records if json.loads(r).get('effect_completed')]
    assert len(effects)==1 and Counter(effects[0]['effect_gate_ids'])==Counter({g:1 for g in ids})
    assert effects[0]['applied'] is True and effects[0]['applied_gate_ids']==list(ids)
    assert effects[0]['applied_by_gate']=={g:True for g in ids}
    for saved in snapshots:
        restored=SimulationState.restore(saved);Executor(restored).run()
        assert restored.snapshot()==state.snapshot()


@pytest.mark.parametrize('requested_bits',[(0,1),(1,1)])
def test_mixed_and_all_false_conditions_have_per_target_light_and_resources(requested_bits):
    gates=(Gate('m','MEASURE',('q2',)),
           Gate('x0','X',('q0',),condition=(('m',requested_bits[0]),)),
           Gate('x1','X',('q1',),condition=(('m',requested_bits[1]),)))
    state=batch_state(gates,mobile=(0,1));before=state.snapshot();p=builder(state)
    p.add(K.MEASUREMENT,'Deterministic zero measurement',gate_id='m')
    p.add(K.RAMAN_ROTATION,'Conditional X batch',gate_ids=('x0','x1'))
    plan=p.finish('conditional-batch');assert state.snapshot()==before
    expected={'x0':requested_bits[0]==0,'x1':requested_bits[1]==0}
    resources=plan.operation_intervals[-1].resources
    for i,gid in enumerate(expected):
        assert ('RAMAN:' if expected[gid] else 'CONTROL:')+f'q{i}' in resources
    assert ('AOD_0' in resources)==any(expected.values())
    snapshots=execute(state,plan)
    assert state.time_us==501 and state.physical_metrics.raman_busy_time_us==int(any(expected.values()))
    assert state.physical_metrics.aod_busy_time_us==500  # Measurement only, matching baseline convention.
    assert state.measurement_results=={'m':0}
    for i,gid in enumerate(expected):
        assert state.quantum_state.expectation({f'q{i}':'Z'})==(-1 if expected[gid] else 1)
    entries=[json.loads(r) for r in state.trace.records if json.loads(r).get('effect_gate_ids')==['x0','x1']]
    assert len(entries)==2
    for entry in entries:
        assert entry['applied']==any(expected.values()) and entry['applied_by_gate']==expected
        assert entry['applied_gate_ids']==[g for g,yes in expected.items() if yes]
    for saved in snapshots:
        restored=SimulationState.restore(saved);Executor(restored).run()
        assert restored.snapshot()==state.snapshot()


def test_batch_and_independent_same_type_pulse_busy_time_is_union():
    state=batch_state();p=builder(state,('h0','h1'))
    p.add(K.RAMAN_ROTATION,'Two targets',gate_ids=('h0','h1'))
    plan=scheduled_program(p.finish('base-batch'),state,(('h2',0),))
    execute(state,plan)
    assert state.time_us==1 and state.physical_metrics.raman_busy_time_us==1 and state.dag.completed


@pytest.mark.parametrize('gates,error',[
    ((Gate('g0','H',('q0',)),Gate('g1','X',('q1',))),'MIXED_RAMAN_BATCH'),
    ((Gate('g0','H',('q0',)),Gate('g1','H',('q0',))),'OVERLAPPING_RAMAN_BATCH'),
    ((Gate('g0','H',('q0',)),Gate('g1','CZ',('q1','q2'))),'UNSUPPORTED_GATE'),
    ((Gate('g0','T',('q0',)),Gate('g1','T',('q1',))),'UNSUPPORTED_TRACKED_GATE'),
])
def test_declared_invalid_gate_batches_reject_without_partial_prediction(gates,error):
    state=batch_state(gates);before=state.snapshot();p=builder(state)
    with pytest.raises(ValidationError,match=error):
        p.add(K.RAMAN_ROTATION,'Invalid batch',gate_ids=('g0','g1'))
    assert state.snapshot()==before and p.state is state and not p.operations


@pytest.mark.parametrize('distance,allowed',[(4.99,False),(5,True),(5.01,True)])
def test_all_targets_keep_original_neighbor_distance_boundary(distance,allowed):
    state=batch_state(n=2,mobile=(0,1),spacing=distance);p=builder(state)
    if allowed:
        p.add(K.RAMAN_ROTATION,'Boundary',gate_ids=('h0','h1'))
        execute(state,p.finish('distance-boundary'))
        assert state.time_us==1
    else:
        with pytest.raises(ValidationError,match='RAMAN_NEIGHBOR_TOO_CLOSE'):
            p.add(K.RAMAN_ROTATION,'Too close',gate_ids=('h0','h1'))
        assert not p.operations and p.state is state


def test_mobile_motion_handoff_and_measured_target_are_rejected():
    state=batch_state(n=2,mobile=(1,))
    moving=replace(state,aod=replace(state.aod,is_moving=True))
    with pytest.raises(ValidationError,match='RAMAN_TARGET_MOVING'):
        validate_rotation_batch(moving,('h0','h1'))
    static=batch_state(n=2)
    handoff=begin_transfer(get_backend(static.hardware),static,(CaptureBinding('q1',Cell(0,1),'s1'),),K.AOD_LOAD)
    with pytest.raises(ValidationError,match='RAMAN_HANDOFF_ACTIVE'):
        validate_rotation_batch(handoff,('h0','h1'))
    measured=replace(static,atoms={q:replace(a,measured=q=='q1') for q,a in static.atoms.items()})
    with pytest.raises(ValidationError,match='RAMAN_TARGET_UNAVAILABLE'):
        validate_rotation_batch(measured,('h0','h1'))


@pytest.mark.parametrize('move_first',[False,True])
def test_moving_neighbor_sweep_validates_second_batch_target_in_both_start_orders(move_first):
    # q0 is always safely distant. Only q1 has a neighbor passing within 2.5um;
    # both endpoints are 6.5um away, so endpoint-only / first-target checks fail.
    state=batch_state((Gate('h0','H',('q0',)),Gate('h1','H',('q1',))),mobile=(2,))
    holders=dict(state.placement.atom_to_holder);holders['q2']=HolderRef(H.MOBILE,Cell(0,0))
    state=replace(state,placement=PlacementState(holders),
        aod=AODRuntimeState(pose=P(7.5,6),rows=1,columns=1,enabled_rows=(True,),enabled_columns=(True,)),
        hardware=replace(state.hardware,speed_um_per_us=20))
    p=builder(state)
    def move():p.add(K.AOD_MOVE,'Neighbor transit',target=P(7.5,-6))
    def light():p.add(K.RAMAN_ROTATION,'Two static targets',gate_ids=('h0','h1'))
    if move_first:move();light()
    else:light();move()
    base=p.finish('sequential-safe')
    concurrent=replace(base,operations=tuple(replace(o,depends_on=()) for o in base.operations),
        operation_intervals=tuple(replace(i,start_us=0,end_us=o.duration_us)
                                  for i,o in zip(base.operation_intervals,base.operations)))
    before=state.snapshot()
    with pytest.raises(ValidationError,match='RAMAN_NEIGHBOR_TOO_CLOSE'):
        audit(concurrent,state,metadata=False)
    assert state.snapshot()==before


def test_batch_target_trace_tampering_is_rejected_on_restore():
    state=batch_state();p=builder(state);p.add(K.RAMAN_ROTATION,'Batch',gate_ids=('h0','h1','h2'))
    execute(state,p.finish('tamper-batch'))
    saved=json.loads(state.snapshot())
    for i,raw in enumerate(saved['trace']):
        record=json.loads(raw)
        if record.get('effect_completed'):
            record['applied_gate_ids']=['h0'];saved['trace'][i]=json.dumps(record);break
    with pytest.raises(ValidationError,match='Raman batch applied targets'):
        SimulationState.restore(json.dumps(saved))
