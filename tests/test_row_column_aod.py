import json
from dataclasses import replace
from math import sqrt
import pytest
from neutral_atom_env.domain.aod import AODConfiguration, motion_target
from neutral_atom_env.domain.models import Position2D, MobileCellIndex, StaticTrap, GridCoord, HolderRef, HolderType, Atom
from neutral_atom_env.domain.operations import ExecuteGateBatchIntent, OperationType, HardwareConfig
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware import get_backend
from neutral_atom_env.simulation.row_column_factory import make_row_column_state
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.simulation import Executor
from neutral_atom_env.motion.compiler import MotionCompiler
from neutral_atom_env.world import PlacementState


def run_case(scenario='pair_compression',planner=None,target_configuration=None):
    state=make_row_column_state(scenario);saved=[state.snapshot()]
    plan=MotionCompiler(planner).compile(ExecuteGateBatchIntent({'G000'}),state,target_configuration=target_configuration)
    executor=Executor(state);executor.submit(plan)
    while state.event_queue:executor.step();saved.append(state.snapshot())
    return state,plan,saved


def test_backend_selection_and_rigid_cannot_compress():
    assert get_backend(HardwareConfig()).name=='rigid'
    with pytest.raises(ValueError,match='Unknown'):HardwareConfig(backend='invented')
    state=make_row_column_state(backend='rigid')
    with pytest.raises(ValidationError,match='STATIC_PARTNER_REQUIRED'):
        MotionCompiler().compile(ExecuteGateBatchIntent({'G000'}),state)
    with pytest.raises(ValidationError,match='UNSUPPORTED_DEFORMATION'):
        get_backend(state.hardware).move(state,AODConfiguration((0,2,4),(0,5)))


def test_independent_columns_rows_are_shared_and_ordered():
    state=make_row_column_state();backend=get_backend(state.hardware)
    target=AODConfiguration((0,3,9),(0,7))
    moved=backend.move(state,target)
    assert moved.aod.position(MobileCellIndex(0,1))==Position2D(3,0)
    assert moved.aod.position(MobileCellIndex(1,1))==Position2D(3,7)
    assert moved.aod.position(MobileCellIndex(1,2))==Position2D(9,7)
    assert state.aod.position(MobileCellIndex(0,1))==Position2D(5,0)
    for xs,ys in [((0,6,5),(0,5)),((0,0,5),(0,5)),((0,5,10),(5,0))]:
        with pytest.raises(ValidationError,match='AOD_AXIS_ORDER'):AODConfiguration(xs,ys)
    with pytest.raises(ValidationError,match='AOD_AXIS_SPACING'):
        backend.move(state,AODConfiguration((0,.5,10),(0,5)))
    with pytest.raises(ValidationError,match='AOD_AXIS_COUNT'):
        backend.move(state,AODConfiguration((0,5),(0,5)))
    with pytest.raises(ValidationError,match='AOD_OUTSIDE_WORLD'):
        backend.move(state,AODConfiguration((0,5,31),(0,5)))


@pytest.mark.parametrize('scenario,count,atom_distance',[('pair_compression',2,116),('incidental',3,174)])
def test_mobile_pair_compression_and_independent_metrics(scenario,count,atom_distance):
    final,plan,saved=run_case(scenario)
    pulse=next(SimulationState.restore(s) for s in saved if json.loads(s)['dag']['G000']['status']=='running')
    assert pulse.aod.configuration()==AODConfiguration((4,6,8),(-25,-20))
    assert pulse.placement.position('Q000',pulse.world,pulse.aod)==Position2D(4,-25)
    assert pulse.placement.position('Q001',pulse.world,pulse.aod)==Position2D(6,-25)
    assert len(pulse.placement.mobile_occupancy)==count
    metrics=final.metrics()
    # Envelope: 2*(2.5+25+4.5)=64. Adjacent operands each travel 58.
    # Incidental Q002: 2*(2.5+25+1.5)=58, including lateral realignment.
    assert metrics['total_aod_distance_um']==64
    assert metrics['total_atom_distance_um']==atom_distance
    duration=200+.3+2*(sqrt(6*2.5/.01)+sqrt(6*25/.01)+sqrt(6*4.5/.01))
    assert metrics['cycle_makespan_us']==pytest.approx(duration)
    assert metrics['captured_atom_count_total']==count
    assert get_backend(pulse.hardware).actual_pairs(pulse)==frozenset({('Q000','Q001')})
    initial=SimulationState.restore(saved[0])
    assert final.aod==initial.aod and final.placement==initial.placement
    assert not final.active_plan and not final.reservations and final.dag.completed
    assert plan.estimated_distance_um==64


def test_cubic_peak_limits_are_respected():
    state=make_row_column_state();backend=get_backend(state.hardware)
    target=AODConfiguration((4,6,8),(-25,-20));d=backend.move_distance(state.aod,target)
    for hw in [state.hardware,replace(state.hardware,max_acceleration_um_per_us2=100,max_jerk_um_per_us3=100),
               replace(state.hardware,max_jerk_um_per_us3=1e-6)]:
        t=backend.move_duration(state.aod,target,hw)
        assert 1.5*d/t<=hw.speed_um_per_us+1e-10
        assert 6*d/t**2<=hw.max_acceleration_um_per_us2+1e-10
        assert 12*d/t**3<=hw.max_jerk_um_per_us3+1e-10


def test_swept_mobile_pair_collision_with_safe_endpoints():
    # Relative separation goes from (2,4) to (4,2): endpoints > 4.3, midpoint < 4.3.
    state=make_row_column_state();traps=dict(state.world.traps)
    traps['S000']=replace(traps['S000'],position=Position2D(0,0))
    traps['S001']=replace(traps['S001'],position=Position2D(2,4))
    aod=replace(state.aod,rows=2,columns=2).configured(AODConfiguration((0,2),(0,4)))
    state=replace(state,world=replace(state.world,traps=traps,grid_spacing_um=1),aod=aod,
                  hardware=replace(state.hardware,minimum_clearance_um=4.3))
    backend=get_backend(state.hardware);state=backend.load(state,backend.capture_closure(state,state.aod.pose))
    before=state.snapshot()
    with pytest.raises(ValidationError,match='MOBILE_CLEARANCE'):
        backend.move(state,AODConfiguration((0,4),(0,2)))
    assert state.snapshot()==before


def test_static_obstacle_in_middle_of_deformation_is_rejected():
    state=make_row_column_state();backend=get_backend(state.hardware)
    bindings=backend.capture_closure(state,state.aod.pose)
    state=backend.load(state,bindings)
    state=backend.move(state,Position2D(0,-25),transfer="depart",bindings=bindings)
    traps=dict(state.world.traps);traps['S002']=replace(traps['S002'],position=Position2D(2,-25),grid=GridCoord(2,-25))
    state=replace(state,world=replace(state.world,traps=traps,grid_spacing_um=1))
    before=state.snapshot()
    with pytest.raises(ValidationError,match='PATH_BLOCKED'):backend.move(state,AODConfiguration((4,6,8),(-25,-20)))
    assert state.snapshot()==before


def test_incidental_atom_can_create_unintended_pair():
    state=make_row_column_state();traps=dict(state.world.traps)
    traps['S002']=replace(traps['S002'],position=Position2D(10,0),grid=GridCoord(2,0))
    state=replace(state,world=replace(state.world,traps=traps));before=state.snapshot()
    with pytest.raises(ValidationError,match='UNINTENDED_PAIR'):
        MotionCompiler().compile(ExecuteGateBatchIntent({'G000'}),state)
    assert state.snapshot()==before


def test_restore_every_boundary_and_reject_axis_or_target_corruption():
    final,plan,saved=run_case('incidental')
    for snap in saved:
        from neutral_atom_env.simulation.scheduler import EagerScheduler
        restored=SimulationState.restore(snap);EagerScheduler(restored).run();assert restored.snapshot()==final.snapshot()
        data=json.loads(snap)
        if not data['active_plan']:continue
        data['aod']['column_offsets_um']=[0,5.1,10]
        with pytest.raises(ValidationError,match='INVALID_CHECKPOINT'):SimulationState.restore(json.dumps(data))
    initial=make_row_column_state();ex=Executor(initial)
    compiled=MotionCompiler().compile(ExecuteGateBatchIntent({'G000'}),initial)
    move=next(o for o in compiled.operations if o.target_configuration)
    altered=replace(move,target_configuration=move.target_configuration.translated(.1,0))
    damaged=replace(compiled,operations=tuple(altered if o==move else o for o in compiled.operations))
    with pytest.raises(ValidationError,match='PLAN_TAMPERED'):ex.submit(damaged)


def test_mobile_static_gate_remains_supported_on_new_backend():
    state=make_row_column_state('mobile_static');plan=MotionCompiler().compile(ExecuteGateBatchIntent({'G000'}),state)
    ex=Executor(state);ex.submit(plan);ex.run()
    assert state.dag.completed and state.metrics()['total_atom_distance_um']==56


def test_cubic_observer_and_stationary_intersection_activity():
    from neutral_atom_env.replay.trajectory import sample_positions
    from neutral_atom_env.testing.scene import build_scene
    final,plan,saved=run_case('incidental',target_configuration=AODConfiguration((5.5,7.5,10),(-25,-20)))
    start=next(s for s in saved if json.loads(s)['aod']['is_moving'] and
               json.loads(s)['active_plan']['plan']['operations'][json.loads(s)['active_plan']['operation_index']]['label']=='Reconfigure axes')
    data=json.loads(start);op=data['active_plan']['plan']['operations'][data['active_plan']['operation_index']]
    quarter=data['time_us']+op['duration_us']*.25
    positions=sample_positions(saved,quarter)
    assert positions['Q000'].x_um==pytest.approx(2.96875)
    assert positions['Q001'].x_um==pytest.approx(7.5)
    assert positions['Q002']==Position2D(7.5,-20)
    assert {a.id:a.activity for a in build_scene(start).atoms}=={'Q000':'moving','Q001':'idle','Q002':'idle','Q003':'idle'}
    assert final.aod.pose==Position2D(0,0)


def test_same_column_pair_compresses_rows():
    state=make_row_column_state();traps=dict(state.world.traps)
    traps['S001']=replace(traps['S001'],position=Position2D(0,5),grid=GridCoord(0,1))
    state=replace(state,world=replace(state.world,traps=traps));initial=state.snapshot()
    plan=MotionCompiler().compile(ExecuteGateBatchIntent({'G000'}),state)
    ex=Executor(state);ex.submit(plan)
    while state.dag.nodes['G000'].status.value!='running':ex.step()
    assert state.placement.position('Q000',state.world,state.aod)==Position2D(5,-26)
    assert state.placement.position('Q001',state.world,state.aod)==Position2D(5,-24)
    assert state.aod.configuration()==AODConfiguration((5,10,15),(-26,-24))
    ex.run()
    assert state.aod==SimulationState.restore(initial).aod and state.dag.completed
