import json
from dataclasses import replace
import pytest
from neutral_atom_env.domain.models import EventType, SimulationEvent, GateStatus, Position2D
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.simulation.event_queue import EventQueue
from neutral_atom_env.simulation.milestone1_factory import make_single_gate_state
from neutral_atom_env.simulation.milestone2_factory import make_circuit_state
from neutral_atom_env.simulation.scheduler import EagerScheduler
from neutral_atom_env.motion.compiler import MotionCompiler
from neutral_atom_env.domain.operations import ExecuteGateBatchIntent


def plan(state,gate='G000'):
    return MotionCompiler().compile(ExecuteGateBatchIntent({gate}),state)


@pytest.mark.parametrize('kind',[EventType.GATE_RESERVED,EventType.GATE_STARTED,EventType.GATE_COMPLETED,EventType.GATE_FAILED])
def test_physical_executor_rejects_public_logical_shortcuts(kind):
    state=make_single_gate_state()
    # Both in EZ, separated by 5 um: the original bypass reproduction.
    traps=dict(state.world.traps)
    traps['S000']=replace(traps['S000'],position=Position2D(0,-25))
    state=replace(state,world=replace(state.world,traps=traps))
    event=SimulationEvent(0,kind,'G000');before=state.snapshot()
    with pytest.raises(ValidationError,match='PHYSICAL_PLAN_REQUIRED'): Executor(state).schedule(event)
    assert state.snapshot()==before
    injected=replace(state,event_queue=EventQueue().push(event));before=injected.snapshot()
    with pytest.raises(ValidationError,match='PHYSICAL_PLAN_REQUIRED'): Executor(injected).step()
    assert injected.snapshot()==before


def boundaries(scenario='three_gate'):
    state=make_circuit_state(scenario);saved=[state.snapshot()]
    result=EagerScheduler(state).run(lambda s,e:saved.append(s.snapshot()))
    assert result.status=='completed'
    return state,saved


@pytest.mark.parametrize('scenario,wall,logical,distance,atom_distance,cycles',[
    ('repeat',624.6,468.6,112,112,2),
    ('switch_partner',664.6,488.6,132,132,2),
    ('three_gate',1116.9,890.9,258,218,3),
    ('join',1076.9,900.9,238,198,3),
])
def test_independent_multicycle_expectations(scenario,wall,logical,distance,atom_distance,cycles):
    state,saved=boundaries(scenario);metrics=state.metrics()
    assert metrics['episode_wall_time_us']==pytest.approx(wall)
    assert metrics['logical_completion_elapsed_us']==pytest.approx(logical)
    assert metrics['total_aod_distance_um']==distance
    assert metrics['total_atom_distance_um']==atom_distance
    assert metrics['completed_plan_count']==metrics['completed_gate_count']==cycles
    assert metrics['aod_load_count']==metrics['aod_offload_count']==cycles
    assert metrics['aod_utilization']==pytest.approx(1)
    assert metrics['laser_utilization']==pytest.approx(.3*cycles/wall)
    assert metrics['throughput_gates_per_us']==pytest.approx(cycles/wall)
    initial=SimulationState.restore(saved[0])
    assert state.placement==initial.placement and state.aod==initial.aod
    for snap in saved:
        data=json.loads(snap)
        for atom in ('Q001','Q002'):
            assert data['placement']['atom_to_holder'][atom]==json.loads(saved[0])['placement']['atom_to_holder'][atom]
    trace=[json.loads(r) for r in state.trace.records]
    pulses=[r for r in trace if r.get('operation_type')=='entangling_pulse' and r['event']['event_type']=='operation_completed']
    expected=[sorted(g.qubit_ids) for g in state.dag.circuit.gates]
    assert [r['actual_pairs'] for r in pulses]==[[pair] for pair in expected]
    durations=[r['plan_duration_us'] for r in trace if r['event']['event_type']=='plan_completed']
    assert sum(durations)==pytest.approx(wall)
    assert metrics['last_cycle_duration_us']==pytest.approx(durations[-1])


def test_successor_released_at_pulse_but_next_plan_waits_for_cleanup():
    state=make_circuit_state('switch_partner');scheduler=EagerScheduler(state)
    while state.dag.nodes['G000'].status!=GateStatus.COMPLETED:scheduler.step()
    assert state.time_us==pytest.approx(156.3)
    assert state.dag.nodes['G001'].status==GateStatus.READY
    assert state.metrics()['logical_completion_elapsed_us'] is None
    assert state.metrics()['last_pulse_elapsed_us']==pytest.approx(156.3)
    assert state.active_plan and state.reservations and state.placement.mobile_occupancy
    while state.active_plan:scheduler.step()
    assert state.time_us==pytest.approx(312.3)
    assert state.dag.nodes['G001'].status==GateStatus.READY
    scheduler.step()
    assert state.active_plan.started_us==pytest.approx(312.3)


def test_join_waits_for_both_independent_predecessors():
    state=make_circuit_state('join');scheduler=EagerScheduler(state)
    assert [g.id for g in state.dag.ready_gates()]==['G000','G001']
    while state.dag.nodes['G000'].status!=GateStatus.COMPLETED:scheduler.step()
    assert state.dag.nodes['G002'].remaining_predecessors==1
    assert state.dag.nodes['G002'].status==GateStatus.BLOCKED
    while state.dag.nodes['G001'].status!=GateStatus.COMPLETED:scheduler.step()
    assert state.dag.nodes['G002'].status==GateStatus.READY


def test_resume_every_boundary_including_second_plan_and_empty_moves():
    final,saved=boundaries()
    for snapshot in saved:
        resumed=SimulationState.restore(snapshot)
        assert EagerScheduler(resumed).run().status=='completed'
        assert resumed.snapshot()==final.snapshot()
    state=make_circuit_state();executor=Executor(state);executor.submit(plan(state))
    resumed=SimulationState.restore(state.snapshot())
    EagerScheduler(resumed).run()
    assert resumed.snapshot()==final.snapshot()


@pytest.mark.parametrize('damage',['missing','duplicate','owner','operation','time','cursor','started','reservation','plan','moving','holder','drop_runtime'])
def test_corrupt_active_boundaries_rejected(damage):
    _,saved=boundaries()
    for snapshot in saved:
        data=json.loads(snapshot)
        if not data['active_plan']:continue
        pending=data['event_queue']['pending'];runtime=data['active_plan']
        if damage=='missing':pending.clear()
        elif damage=='duplicate':
            pending.append([pending[0][0],data['event_queue']['next_sequence'],dict(pending[0][2])]);data['event_queue']['next_sequence']+=1
        elif damage=='owner':pending[0][2]['plan_id']='wrong'
        elif damage=='operation':
            if pending[0][2]['operation_id'] is None:continue
            pending[0][2]['operation_id']='wrong'
        elif damage=='time':pending[0][0]+=1;pending[0][2]['time_us']+=1
        elif damage=='cursor':runtime['operation_index']+=1
        elif damage=='started':runtime['started_us']+=.1
        elif damage=='reservation':data['reservations'].pop()
        elif damage=='plan':runtime['plan']['operations'][0]['duration_us']+=1
        elif damage=='moving':data['aod']['is_moving']=not data['aod']['is_moving']
        elif damage=='holder':data['aod']['pose']['x_um']+=.1
        elif damage=='drop_runtime':data['active_plan']=None;data['reservations']=[];pending.clear()
        with pytest.raises(ValidationError,match='INVALID_CHECKPOINT'):SimulationState.restore(json.dumps(data))


def test_stalled_diagnostics_and_read_only_candidate_search():
    state=make_circuit_state('unsupported');before=state.snapshot()
    result=EagerScheduler(state).run()
    assert result.status=='stalled' and state.snapshot()==before
    assert result.diagnostics['pending_event_count']==0
    assert result.diagnostics['holders']
    assert result.diagnostics['candidate_failures'][0]['violation']['code']=='STATIC_PARTNER_REQUIRED'


def test_feasible_ready_gate_is_not_hidden_by_first_failure():
    from neutral_atom_env.circuit import PhysicalCircuit,DynamicGateDAG
    from neutral_atom_env.domain.models import PhysicalGate
    state=make_circuit_state()
    gates=(PhysicalGate('G000','H',('Q001',)),PhysicalGate('G001','CZ',('Q000','Q002')))
    state=replace(state,dag=DynamicGateDAG(PhysicalCircuit(gates)));before=state.snapshot()
    chosen,failures=EagerScheduler(state).policy.compile_first(state)
    assert chosen.intent.gate_ids==frozenset({'G001'}) and failures[0][0]=='G000'
    assert before==state.snapshot()
    result=EagerScheduler(state).run()
    assert result.status=='stalled' and state.dag.nodes['G001'].status==GateStatus.COMPLETED


def test_episode_origin_excludes_wait_before_first_plan():
    state=make_circuit_state('repeat');ex=Executor(state)
    ex.schedule(SimulationEvent(10,EventType.WAIT_COMPLETED));ex.run()
    EagerScheduler(state).run();m=state.metrics()
    assert m['episode_start_us']==10 and m['simulation_time_us']==pytest.approx(634.6)
    assert m['episode_wall_time_us']==pytest.approx(624.6)
    assert m['logical_completion_elapsed_us']==pytest.approx(468.6)


def test_parameterized_gate_is_rejected_without_aliasing_cz():
    from neutral_atom_env.circuit import PhysicalCircuit,DynamicGateDAG
    state=make_single_gate_state()
    gate=replace(state.dag.circuit.gates[0],gate_type='CPHASE')
    state=replace(state,dag=DynamicGateDAG(PhysicalCircuit((gate,))))
    before=state.snapshot()
    with pytest.raises(ValidationError,match='UNSUPPORTED_GATE'):plan(state)
    assert state.snapshot()==before


def test_grid_metadata_matches_factory_world_coordinates():
    from neutral_atom_env.world.config import LayoutConfig
    worlds=[LayoutConfig().build()]+[make_single_gate_state(s).world for s in ('baseline','incidental','blocked','unintended','both_storage')]+[make_circuit_state().world]
    for world in worlds:
        for trap in world.traps.values():
            assert trap.position==Position2D(world.grid_origin.x_um+trap.grid.x*world.grid_spacing_um,
                                             world.grid_origin.y_um+trap.grid.y*world.grid_spacing_um)


def test_nonzero_capture_cell_uses_operand_position_for_partner_alignment():
    from neutral_atom_env.domain.models import GridCoord
    state=make_single_gate_state()
    traps=dict(state.world.traps)
    traps['S000']=replace(traps['S000'],position=Position2D(5,0),grid=GridCoord(1,0))
    state=replace(state,world=replace(state.world,traps=traps))
    compiled=plan(state)
    assert compiled.bindings[0].cell.column==1
    scheduler=EagerScheduler(state)
    while state.dag.nodes['G000'].status!=GateStatus.RUNNING:scheduler.step()
    assert state.placement.position('Q000',state.world,state.aod)==Position2D(3,-25)
    assert state.aod.pose==Position2D(-2,-25)
    assert scheduler.run().status=='completed'


def test_empty_queue_active_runtime_cannot_silently_finish():
    state=make_single_gate_state();ex=Executor(state);ex.submit(plan(state));ex.step();ex.step()
    damaged=replace(state,event_queue=EventQueue((),state.event_queue.next_sequence))
    before=damaged.snapshot()
    with pytest.raises(ValidationError,match='INVALID_RUNTIME'):Executor(damaged).run()
    with pytest.raises(ValidationError,match='INVALID_RUNTIME'):EagerScheduler(damaged).run()
    assert damaged.snapshot()==before


def test_new_source_capture_includes_incidental_atom_in_full_cycle():
    from neutral_atom_env.domain.models import Atom,StaticTrap,GridCoord,HolderRef,HolderType
    from neutral_atom_env.world import PlacementState
    state=make_circuit_state()
    traps=dict(state.world.traps);traps['S004']=StaticTrap('S004',GridCoord(5,1),Position2D(25,5))
    atoms=dict(state.atoms);atoms['Q004']=Atom('Q004')
    holders=dict(state.placement.atom_to_holder);holders['Q004']=HolderRef(HolderType.STATIC,'S004')
    state=replace(state,world=replace(state.world,traps=traps),atoms=atoms,placement=PlacementState(holders))
    assert EagerScheduler(state).run().status=='completed'
    m=state.metrics()
    assert m['episode_wall_time_us']==pytest.approx(1116.9)
    assert m['total_aod_distance_um']==258 and m['total_atom_distance_um']==304
    assert m['captured_atom_count_total']==4 and m['incidental_atom_transport_total']==1
    assert state.placement.atom_to_holder==holders
