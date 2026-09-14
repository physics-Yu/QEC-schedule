"""M3-B behavior: no-gate motion, explicit targets and exactly-once split effect."""
import json
from dataclasses import replace
import pytest
from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate, HolderRef, HolderType, GateStatus, Position2D
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget, ExecuteGateBatchIntent, OperationType as K
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_env.motion.single_trap import SingleTrapCompiler
from neutral_atom_env.motion.tasks import TargetTaskCompiler, TaskProgram, split_gate_program
from neutral_atom_env.motion.program import ProgramBuilder
from neutral_atom_env.simulation.pipeline import initialize, Platform
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.visualization import VisualRecorder
from neutral_atom_env.replay.serializer import canonical_json


def make_state(gates=()):
    return initialize(PhysicalCircuit(tuple(gates)),Platform.load('configs/platforms/single_trap.json'),
                      {f'Q{i:03d}':f'S{i:03d}' for i in range(8)})


def destination(state):
    return next(t.id for t in state.world.traps.values() if t.id not in state.placement.static_occupancy
                and t.position.y_um < -10)


def transport_intent(state):
    return TaskIntent('park-Q000',TaskTarget((('Q000',HolderRef(HolderType.STATIC,destination(state))),)),
                      frozenset({'Q000'}),allowed_atom_ids=frozenset({'Q000'}))


def execute(state,plan,recorder=None):
    executor=Executor(state);executor.submit(plan);saved=[state.snapshot()]
    while state.event_queue:
        executor.step();saved.append(state.snapshot())
        if recorder:recorder.observe(state)
    return saved


def assert_restore_boundaries(snapshots,final):
    for snapshot in snapshots:
        restored=SimulationState.restore(snapshot)
        Executor(restored).run()
        assert restored.snapshot()==final


def test_zero_gate_transport_reaches_ez_with_real_events_and_restores_every_boundary():
    state=make_state();initial=state.snapshot();dag=state.dag
    intent=transport_intent(state)
    plan=TargetTaskCompiler().compile(intent,state)
    assert state.snapshot()==initial
    assert not plan.intent.gate_ids and not any(o.gate_id for o in plan.operations)
    assert all(o.operation_type not in (K.ENTANGLING_PULSE,K.RAMAN_ROTATION) for o in plan.operations)
    assert 'ENTANGLING_LASER_0' not in plan.resources and 'RAMAN:Q000' not in plan.resources
    assert all(set(interval.atom_ids)<={'Q000'} for interval in plan.operation_intervals)
    assert plan.operation_intervals[0].start_us==0
    assert plan.operation_intervals[-1].end_us==plan.estimated_duration_us
    recorder=VisualRecorder(state);snapshots=execute(state,plan,recorder)
    assert state.dag==dag and state.placement.atom_to_holder['Q000']==dict(intent.target.holders)['Q000']
    assert state.metrics()['aod_load_count']==state.metrics()['aod_offload_count']==1
    assert state.time_us>200 and state.metrics()['completed_gate_count']==0
    assert state.metrics()['last_pulse_time_us']==0
    assert_restore_boundaries(snapshots,state.snapshot())
    payload=recorder.payload()
    assert payload['operations'] and all(op['gate_id'] is None for op in payload['operations'])
    assert payload['plans'][0]['task_id']=='park-Q000'
    assert not any(frame['gate_status']=='running' for frame in payload['frames'])


def test_split_cz_preserves_cost_and_releases_successor_before_cleanup():
    state=make_state([PhysicalGate('cz','CZ',('Q000','Q001')),PhysicalGate('h','H',('Q000',))])
    before=state.snapshot();origin=state.placement;axes=state.aod.configuration()
    full=SingleTrapCompiler().compile(ExecuteGateBatchIntent({'cz'}),state)
    tasks=split_gate_program(full,state,task_prefix='cz-first')
    assert state.snapshot()==before and [p.intent.phase for p in tasks]==['prepare','effect','cleanup']
    assert [p.intent.effect_gate_id for p in tasks]==[None,'cz',None]
    recorder=VisualRecorder(state)
    stages=[]
    for task in tasks:
        plan=task.compile(state)
        snapshots=execute(state,plan,recorder)
        assert_restore_boundaries(snapshots,state.snapshot())
        stages.append(state.snapshot())
        if task.intent.phase=='prepare':
            assert state.dag.nodes['cz'].status==GateStatus.READY
            assert state.dag.nodes['h'].status==GateStatus.BLOCKED
            assert state.placement.mobile_occupancy
        else:
            assert state.dag.nodes['cz'].status==GateStatus.COMPLETED
            assert state.dag.nodes['h'].status==GateStatus.READY
    assert state.time_us==pytest.approx(full.estimated_duration_us)
    assert state.metrics()['total_aod_distance_um']==pytest.approx(full.estimated_distance_um)
    assert state.placement==origin and state.aod.configuration()==axes
    effects=[json.loads(r) for r in state.trace.records if json.loads(r).get('effect_completed')]
    assert len(effects)==1 and effects[0]['gate_id']=='cz' and effects[0]['task_id']=='cz-first/effect'
    assert effects[0]['operation_ref']=='cz-first/effect/op00'
    assert state.metrics()['completed_plan_count']==3
    assert all(o['gate_id'] is None for o in recorder.operations if o['task_phase']!='effect')
    assert any(o['category']=='return' for o in recorder.operations if o['task_phase']=='cleanup')
    from neutral_atom_env.visualization.summary import summarize_trace
    traced=summarize_trace(state.trace.records,state.metrics())
    assert traced['categories']==recorder.payload()['summary']['categories']
    cleanup_path=recorder.payload()['plans'][-1]['paths']['Q001']
    assert len(cleanup_path)>1  # Already loaded at the cleanup task's origin.
    # Neither a stale effect recipe nor a fresh request can repeat a completed gate.
    with pytest.raises((ValidationError,ValueError)):
        tasks[1].compile(state)
    effect=TaskIntent('repeat',TaskTarget(),effect_gate_id='cz',phase='effect')
    with pytest.raises(ValidationError):TargetTaskCompiler().compile(effect,state)
    # A READY successor uses the same real 1 us Raman backend after cleanup.
    h=TaskIntent('h-effect',TaskTarget(),effect_gate_id='h',phase='effect')
    execute(state,TargetTaskCompiler().compile(h,state),recorder)
    assert state.dag.completed and state.metrics()['raman_busy_time_us']==1


def test_effect_task_can_run_on_stable_slm_while_other_atom_remains_loaded_serially():
    state=make_state([PhysicalGate('cz','CZ',('Q000','Q001')),PhysicalGate('h','H',('Q000',))])
    plan=SingleTrapCompiler().compile(ExecuteGateBatchIntent({'cz'}),state)
    tasks=split_gate_program(plan,state,task_prefix='mixed')
    for task in tasks[:2]:execute(state,task.compile(state))
    h=TaskIntent('h-before-cleanup',TaskTarget(),effect_gate_id='h',phase='effect')
    with pytest.raises(ValidationError,match='RAMAN_NEIGHBOR_TOO_CLOSE'):
        TargetTaskCompiler().compile(h,state)
    # Keep the partner loaded, but explicitly separate the 2 um CZ pair.
    from neutral_atom_env.motion.persistent import PersistentTargetCompiler
    original_axes=state.aod.configuration()
    away=replace(original_axes,x_um=(original_axes.x_um[0]-5,))
    execute(state,PersistentTargetCompiler().compile(TaskIntent('separate-for-h',TaskTarget(aod_configuration=away)),state))
    holder=state.placement;axes=state.aod.configuration()
    raman=TargetTaskCompiler().compile(h,state)
    assert raman.resources==('RAMAN:Q000','atom:Q000','trap:'+holder.atom_to_holder['Q000'].holder_id)
    snapshots=execute(state,raman)
    assert_restore_boundaries(snapshots,state.snapshot())
    assert state.placement==holder and state.aod.configuration()==axes
    execute(state,PersistentTargetCompiler().compile(TaskIntent('resume-cleanup-pose',TaskTarget(aod_configuration=original_axes)),state))
    execute(state,tasks[2].compile(state))
    assert state.dag.completed and not state.placement.mobile_occupancy


def test_task_constraints_and_tampering_fail_without_committing():
    state=make_state([PhysicalGate('h','H',('Q002',))]);intent=transport_intent(state)
    plan=TargetTaskCompiler().compile(intent,state);before=state.snapshot()
    bad_plans=[replace(plan,intent=replace(intent,allowed_atom_ids=frozenset())),
               replace(plan,intent=replace(intent,allowed_site_ids=frozenset({'S000'}))),
               replace(plan,intent=replace(intent,max_duration_us=1)),
               replace(plan,intent=replace(intent,target=TaskTarget((('Q000',HolderRef(HolderType.STATIC,'S001')),)))),
               replace(plan,operation_intervals=(replace(plan.operation_intervals[0],end_us=10000),)+plan.operation_intervals[1:]),
               replace(plan,operations=(replace(plan.operations[0],gate_id='h'),)+plan.operations[1:]),
               replace(plan,operations=(plan.operations[0],replace(plan.operations[1],depends_on=()))+plan.operations[2:]),
               replace(plan,resources=('AOD_0',))]
    for bad in bad_plans:
        with pytest.raises(ValidationError):Executor(state).submit(bad)
        assert state.snapshot()==before
    with pytest.raises(ValidationError):
        ProgramBuilder(state,intent).add(K.RAMAN_ROTATION,'Illegal hidden effect')
    assert state.snapshot()==before


@pytest.mark.parametrize('damage',['origin_dag','live_dag','interval','gate','schema'])
def test_task_checkpoint_rejects_corrupted_effect_and_motion_metadata(damage):
    state=make_state([PhysicalGate('h','H',('Q002',))])
    plan=TargetTaskCompiler().compile(transport_intent(state),state)
    executor=Executor(state);executor.submit(plan);executor.step();executor.step()
    data=json.loads(state.snapshot())
    if damage=='origin_dag':data['active_plan']['plan']['initial_dag']='{}'
    if damage=='live_dag':data['dag']['h']['status']='completed'
    if damage=='interval':data['active_plan']['plan']['operation_intervals'][0]['start_us']=1
    if damage=='gate':data['active_plan']['plan']['operations'][0]['gate_id']='h'
    if damage=='schema':data['schema_version']=11
    with pytest.raises((ValidationError,ValueError)):SimulationState.restore(json.dumps(data))


def test_dark_reposition_and_task_identity_and_impossible_target():
    state=make_state();axes=state.aod.configuration()
    target=replace(axes,x_um=tuple(x+5 for x in axes.x_um))
    intent=TaskIntent('dark-reposition',TaskTarget(aod_configuration=target))
    plan=TargetTaskCompiler().compile(intent,state)
    assert plan.resources==('AOD_0',) and not plan.bindings
    execute(state,plan)
    assert state.metrics()['total_atom_distance_um']==0 and state.metrics()['total_aod_distance_um']==5
    assert state.time_us==10 and state.aod.configuration()==target
    duplicate=replace(intent,target=TaskTarget(aod_configuration=axes))
    with pytest.raises(ValidationError,match='already executed'):TargetTaskCompiler().compile(duplicate,state)
    impossible=TaskIntent('occupied',TaskTarget((('Q000',HolderRef(HolderType.STATIC,'S001')),)),frozenset({'Q000'}))
    before=state.snapshot()
    with pytest.raises(ValidationError,match='OCCUPIED'):TargetTaskCompiler().compile(impossible,state)
    assert state.snapshot()==before
