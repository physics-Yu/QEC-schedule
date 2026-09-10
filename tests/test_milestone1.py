from dataclasses import replace, FrozenInstanceError
import json
import pytest
from neutral_atom_env.domain.models import (Position2D, HolderRef, HolderType, SimulationEvent, EventType)
from neutral_atom_env.domain.operations import ExecuteGateBatchIntent, OperationType, EndDisposition
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.simulation.milestone1_factory import make_single_gate_state
from neutral_atom_env.motion.compiler import MotionCompiler
from neutral_atom_env.hardware.rigid_aod import RigidRectangularAODBackend, distance, segment_clearance
from neutral_atom_env.world import PlacementState


def compile_plan(state):
    return MotionCompiler().compile(ExecuteGateBatchIntent(frozenset({'G000'})),state)


@pytest.mark.parametrize('scenario,captured,atom_distance',[('baseline',1,56),('incidental',2,112)])
def test_complete_physical_cycle(scenario,captured,atom_distance):
    state=make_single_gate_state(scenario);initial=state.snapshot();plan=compile_plan(state)
    assert state.snapshot()==initial
    assert plan.estimated_duration_us==pytest.approx(312.3)
    assert plan.estimated_distance_um==56 and len(plan.captured_atom_ids)==captured
    ex=Executor(state);ex.submit(plan);snapshots=[]
    while state.event_queue:
        ex.step();snapshots.append(state.snapshot())
        state.placement.validate(state.atoms,state.world,state.aod)
    assert state.placement.atom_to_holder==SimulationState.restore(initial).placement.atom_to_holder
    assert state.aod.pose==Position2D(0,0) and not state.aod.is_moving
    assert state.dag.completed and not state.reservations and state.active_plan is None
    metrics=state.metrics()
    assert metrics['completed_gate_count']==1
    assert metrics['cycle_makespan_us']==pytest.approx(312.3)
    assert metrics['circuit_makespan_us']==pytest.approx(156.3)
    assert metrics['total_aod_distance_um']==56 and metrics['total_atom_distance_um']==atom_distance
    assert metrics['aod_load_count']==metrics['aod_offload_count']==1
    assert metrics['captured_atom_count_total']==captured
    assert metrics['incidental_atom_transport_total']==captured-1
    assert metrics['aod_busy_time_us']==pytest.approx(312.3)
    assert metrics['laser_busy_time_us']==pytest.approx(.3)
    assert len(state.trace.records)==20
    # Q001 is a fixed physical partner, not secretly transported.
    for saved in snapshots:
        s=SimulationState.restore(saved)
        assert s.placement.position('Q001',s.world,s.aod)==Position2D(5,-25)
    pulse=next(json.loads(r) for r in state.trace.records if json.loads(r).get('label')=='CZ pulse')
    assert pulse['actual_pairs']==[['Q000','Q001']]


def test_pulse_at_non_slm_coordinate_and_rigid_distances():
    state=make_single_gate_state('incidental');plan=compile_plan(state);backend=RigidRectangularAODBackend()
    loaded=backend.load(state,plan.bindings)
    before=distance(loaded.placement.position('Q000',loaded.world,loaded.aod),loaded.placement.position('Q002',loaded.world,loaded.aod))
    work=loaded
    for op in plan.operations:
        if op.operation_type==OperationType.AOD_MOVE:work=backend.move(work,op.target_pose,transfer=op.transfer_phase,bindings=plan.bindings)
        if op.operation_type==OperationType.ENTANGLING_PULSE:break
    position=work.placement.position('Q000',work.world,work.aod)
    assert position==Position2D(3,-25)
    assert not work.world.is_candidate_site(position)
    assert all(t.position!=position for t in work.world.traps.values())
    assert distance(position,work.placement.position('Q001',work.world,work.aod))==2
    assert distance(position,work.placement.position('Q002',work.world,work.aod))==pytest.approx(before)
    assert backend.validate_pulse(work,'G000')==frozenset({('Q000','Q001')})


@pytest.mark.parametrize('scenario,code',[('unintended','UNINTENDED_PAIR'),('blocked','INVALID_TRANSFER_PATH'),('both_storage','STATIC_PARTNER_REQUIRED')])
def test_invalid_plan_never_mutates_state(scenario,code):
    state=make_single_gate_state(scenario);before=state.snapshot()
    with pytest.raises(ValidationError,match=code):compile_plan(state)
    assert state.snapshot()==before


def test_segment_interior_collision_is_detected():
    start,end,obstacle=Position2D(3,-2.5),Position2D(3,-25),Position2D(3,-10)
    assert distance(start,obstacle)>1 and distance(end,obstacle)>1
    assert segment_clearance(obstacle,start,end)==(0,obstacle)


@pytest.mark.parametrize('failure,code',[('occupied','OFFLOAD_OCCUPIED'),('misaligned','OFFLOAD_MISALIGNMENT'),('disabled','OFFLOAD_DISABLED')])
def test_offload_constraints(failure,code):
    state=make_single_gate_state();plan=compile_plan(state);backend=RigidRectangularAODBackend()
    state=backend.load(state,plan.bindings)
    if failure=='occupied':
        holders=dict(state.placement.atom_to_holder);holders['Q003']=HolderRef(HolderType.STATIC,'S000')
        state=replace(state,placement=PlacementState(holders))
    elif failure=='misaligned':state=replace(state,aod=replace(state.aod,pose=Position2D(.1,0)))
    else:
        traps=dict(state.world.traps);traps['S000']=replace(traps['S000'],enabled=False)
        state=replace(state,world=replace(state.world,traps=traps))
    before=state.snapshot()
    with pytest.raises(ValidationError,match=code):backend.offload(state,plan.bindings)
    assert state.snapshot()==before


def test_plan_version_tamper_and_resource_guards():
    state=make_single_gate_state();plan=compile_plan(state);ex=Executor(state)
    with pytest.raises(FrozenInstanceError):plan.estimated_duration_us=0
    with pytest.raises(ValidationError,match='PLAN_TAMPERED'):
        ex.submit(replace(plan,operations=plan.operations[:-1]))
    before=state.snapshot()
    with pytest.raises(ValidationError,match='UNSUPPORTED_DISPOSITION'):
        MotionCompiler().compile(replace(plan.intent,end_disposition=EndDisposition.KEEP_LOADED),state)
    assert before==state.snapshot()
    ex.schedule(SimulationEvent(1,EventType.WAIT_COMPLETED));ex.step()
    with pytest.raises(ValidationError,match='OUTDATED_STATE'):ex.submit(plan)
    plan=compile_plan(state);ex.submit(plan);ex.step()
    assert len(state.reservations)==len(plan.resources)
    with pytest.raises(ValidationError,match='RESOURCE_BUSY'):compile_plan(state)
    with pytest.raises(ValidationError,match='RESOURCE_BUSY'):ex.schedule(SimulationEvent(2,EventType.WAIT_COMPLETED))


def test_resume_at_every_event_boundary():
    state=make_single_gate_state('incidental');ex=Executor(state);ex.submit(compile_plan(state))
    boundaries=[state.snapshot()]
    while state.event_queue:ex.step();boundaries.append(state.snapshot())
    for snapshot in boundaries:
        resumed=SimulationState.restore(snapshot);Executor(resumed).run()
        assert resumed.snapshot()==state.snapshot()
        assert resumed.trace.records==state.trace.records


def test_failed_physical_event_is_atomic():
    state=make_single_gate_state();ex=Executor(state);ex.submit(compile_plan(state))
    ex.step() # plan reservation
    ex.step() # load start
    event=state.event_queue.peek()
    altered=replace(event,time_us=event.time_us+1)
    from neutral_atom_env.simulation.event_queue import EventQueue
    state=replace(state,event_queue=EventQueue(((altered.time_us,0,altered),),1))
    before=state.snapshot()
    with pytest.raises(ValidationError,match='INVALID_COMPLETION_TIME'):Executor(state).step()
    assert state.snapshot()==before


def test_playback_interpolation_is_continuous_and_observer_only():
    from neutral_atom_env.replay.trajectory import sample_positions
    from neutral_atom_env.testing.scene import build_scene
    state=make_single_gate_state();snapshots=[state.snapshot()];ex=Executor(state);ex.submit(compile_plan(state))
    while state.event_queue:ex.step();snapshots.append(state.snapshot())
    before=state.snapshot()
    assert sample_positions(snapshots,108)['Q000']==Position2D(2.5,-1.5)
    p=sample_positions(snapshots,133.5)['Q000']
    assert p.x_um==2.5 and p.y_um==pytest.approx(-14.25)
    assert sample_positions(snapshots,156.1)['Q000']==Position2D(3,-25)
    assert sample_positions(snapshots,312.3)['Q000']==Position2D(0,0)
    for t in (0,100,108,133.5,156.1,200,312.3):
        assert sample_positions(snapshots,t)['Q001']==Position2D(5,-25)
    pulse=next(s for s in snapshots if json.loads(s)['dag']['G000']['status']=='running')
    assert {a.id for a in build_scene(pulse).atoms if a.activity=='gating'}=={'Q000','Q001'}
    assert state.snapshot()==before


def test_capture_closure_never_ignores_unaligned_atom():
    from neutral_atom_env.domain.models import StaticTrap,GridCoord
    state=make_single_gate_state()
    traps=dict(state.world.traps);traps['S002']=replace(traps['S002'],position=Position2D(2,0))
    state=replace(state,world=replace(state.world,traps=traps,grid_spacing_um=1))
    with pytest.raises(ValidationError,match='CAPTURE_MISALIGNMENT'):compile_plan(state)


def test_two_micrometer_radius_is_not_relaxed_by_compiler():
    state=make_single_gate_state()
    state=replace(state,hardware=replace(state.hardware,interaction_distance_um=1.99))
    with pytest.raises(ValidationError,match='UNINTENDED_PAIR'):compile_plan(state)
    assert state.hardware.interaction_distance_um==1.99


def test_eager_policy_is_read_only():
    from neutral_atom_env.planning.eager_baseline import EagerBaseline
    state=make_single_gate_state();before=state.snapshot()
    intent=EagerBaseline().choose(state)
    assert intent.gate_ids==frozenset({'G000'}) and intent.end_disposition==EndDisposition.RETURN_AND_OFFLOAD
    assert state.snapshot()==before
