"""Independent M3-A support, swept-safety, timing and continuation contracts."""
import json
from dataclasses import replace
import pytest
from neutral_atom_env.circuit import PhysicalCircuit, DynamicGateDAG
from neutral_atom_env.domain.models import (Atom, HolderRef, HolderType as H, MobileCellIndex as Cell,
    Position2D as P, Rectangle, StaticTrap, GridCoord, Zone, ZoneType)
from neutral_atom_env.domain.operations import CaptureBinding as Binding, OperationType as K, ExecuteGateBatchIntent
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.world import WorldState, PlacementState, AODRuntimeState
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.simulation import Executor
from neutral_atom_env.hardware import get_backend
from neutral_atom_env.hardware.dynamic_traps import (trap_state, switch_traps, begin_transfer, finish_transfer)


def array_state(count=4, rows=2, columns=2):
    positions = [P(0,0), P(5,0), P(0,5), P(5,5)][:count]
    bounds = Rectangle(P(-20,-20), P(40,40))
    traps = {f'S{i}': StaticTrap(f'S{i}', GridCoord(round(p.x_um/5),round(p.y_um/5)), p) for i,p in enumerate(positions)}
    world = WorldState(bounds, traps, (Zone('SZ', ZoneType.STORAGE, bounds),))
    return SimulationState(world, PlacementState({f'Q{i:03d}': HolderRef(H.STATIC, f'S{i}') for i in range(count)}),
        {f'Q{i:03d}': Atom(f'Q{i:03d}') for i in range(count)}, AODRuntimeState(rows=rows,columns=columns),
        DynamicGateDAG(PhysicalCircuit(())))


def capture(state):
    backend = get_backend(state.hardware)
    bindings = backend.capture_closure(state, state.aod.pose)
    return backend.load(state, bindings), bindings


def test_capacity_geometry_masks_and_holder_are_independent():
    state = array_state(0)
    masks = replace(trap_state(state), rows=(True,False), columns=(True,True))
    enabled = switch_traps(state, masks)
    assert enabled.aod.active_cells == (Cell(0,0), Cell(0,1))
    assert enabled.aod.configuration() == state.aod.configuration()
    assert not enabled.placement.mobile_occupancy
    assert (enabled.aod.rows, enabled.aod.columns) == (2,2)
    assert not state.aod.active_cells
    with pytest.raises(ValidationError, match='INVALID_AOD_MASK'):
        replace(state.aod, enabled_rows=(True,))
    with pytest.raises(ValidationError, match='INVALID_AOD_MASK'):
        replace(state.aod, enabled_columns=(1,0))


@pytest.mark.parametrize('backend_name', ['rigid','row_column'])
def test_empty_active_sweep_checks_segment_interior_and_dark_move_is_timed(backend_name):
    state = array_state(1,1,1)
    state = replace(state, aod=replace(state.aod,pose=P(-5,0)), hardware=replace(state.hardware,backend=backend_name))
    backend = get_backend(state.hardware)
    active = switch_traps(state, replace(trap_state(state),rows=(True,),columns=(True,)))
    before = active.snapshot()
    # Both endpoints are 5 um clear; the middle exactly crosses Q000.
    with pytest.raises(ValidationError, match='ACTIVE_TRAP_SWEEP'):
        backend.move(active,P(5,0),transfer='depart')
    assert active.snapshot() == before
    dark = backend.move(state,P(5,0))
    assert dark.aod.pose == P(5,0) and not dark.aod.active_cells
    assert backend.move_duration(state.aod,P(5,0),state.hardware) > 0
    if backend_name == 'rigid':
        assert backend.move_duration(state.aod,P(5,0),state.hardware) == 20


def test_enable_checks_all_cross_intersections_and_cannot_capture_implicitly():
    state = array_state()
    before = state.snapshot()
    with pytest.raises(ValidationError, match='ACTIVE_TRAP_SWEEP'):
        switch_traps(state,replace(trap_state(state),rows=(True,True),columns=(True,True)))
    diagonal = (Binding('Q000',Cell(0,0),'S0'),Binding('Q003',Cell(1,1),'S3'))
    with pytest.raises(ValidationError, match='CAPTURE_CHANGED'):
        begin_transfer(get_backend(state.hardware), state, diagonal, K.AOD_LOAD)
    assert state.snapshot() == before


def test_loaded_cartesian_array_cannot_drop_shared_row_or_column():
    loaded, bindings = capture(array_state())
    loaded = replace(loaded, hardware=replace(loaded.hardware,selective_transfer_enabled=True))
    backend = get_backend(loaded.hardware)
    before = loaded.snapshot()
    for masks in (replace(trap_state(loaded),rows=(False,True)), replace(trap_state(loaded),columns=(False,True))):
        with pytest.raises(ValidationError, match='HOLDER_SUPPORT_DISABLED'):
            switch_traps(loaded,masks)
    with pytest.raises(ValidationError, match='SHARED_AXIS_SUPPORT'):
        backend.park(loaded,bindings[:1])
    # Whole-row handoff is possible, with both source holders retained until finish.
    mid = begin_transfer(backend, loaded, bindings[:2], K.AOD_PARK)
    assert mid.placement == loaded.placement and mid.aod.active_cells == loaded.aod.active_cells
    assert mid.slm_enabled['S0'] and mid.slm_enabled['S1']
    parked = finish_transfer(backend, mid, bindings[:2], K.AOD_PARK)
    assert parked.aod.enabled_rows == (False,True)
    assert parked.placement.mobile_occupancy == {Cell(1,0):'Q002',Cell(1,1):'Q003'}
    assert loaded.snapshot() == before


def test_transfer_establishes_support_then_commits_without_moving_geometry():
    state = array_state(1,1,1)
    backend = get_backend(state.hardware)
    binding = (Binding('Q000',Cell(0,0),'S0'),)
    mid = begin_transfer(backend,state,binding,K.AOD_LOAD)
    assert mid.transfer.stage == 'target_supported'
    assert mid.placement == state.placement and mid.slm_enabled['S0'] and mid.aod.is_enabled(Cell(0,0))
    with pytest.raises(ValidationError, match='TRANSFER_BUSY'):
        backend.move(mid,P(5,0))
    with pytest.raises(ValidationError, match='HOLDER_SUPPORT_DISABLED|TRANSFER_SUPPORT_LOST'):
        replace(mid,slm_enabled={'S0':False})
    loaded = finish_transfer(backend,mid,binding,K.AOD_LOAD)
    assert loaded.placement.atom_to_holder['Q000'] == HolderRef(H.MOBILE,Cell(0,0))
    assert not loaded.slm_enabled['S0'] and loaded.transfer is None
    unloading = begin_transfer(backend,loaded,binding,K.AOD_OFFLOAD)
    assert unloading.placement == loaded.placement and unloading.slm_enabled['S0']
    final = finish_transfer(backend,unloading,binding,K.AOD_OFFLOAD)
    assert final.placement == state.placement and trap_state(final) == trap_state(state)
    assert final.aod.configuration() == state.aod.configuration()


def test_offload_can_enable_a_previously_dark_destination():
    loaded, bindings = capture(array_state(1,1,1))
    # Initial configuration is metadata; runtime enabled is independently false.
    assert loaded.world.traps['S0'].enabled and not loaded.slm_enabled['S0']
    final = get_backend(loaded.hardware).offload(loaded,bindings)
    assert final.slm_enabled['S0'] and not final.aod.active_cells


def test_slm_switch_is_individual_and_cannot_remove_an_occupied_support():
    state=array_state(1,1,1)
    empty=StaticTrap('EMPTY',GridCoord(2,2),P(10,10),enabled=False)
    state=replace(state,world=replace(state.world,traps=dict(state.world.traps)|{'EMPTY':empty}),slm_enabled=None)
    original=trap_state(state)
    on=switch_traps(state,replace(original,slm=(('EMPTY',True),('S0',True))))
    assert on.slm_enabled=={'EMPTY':True,'S0':True} and not on.world.traps['EMPTY'].enabled
    assert switch_traps(on,original).snapshot()==state.snapshot()
    with pytest.raises(ValidationError,match='HOLDER_SUPPORT_DISABLED'):
        switch_traps(state,replace(original,slm=(('EMPTY',False),('S0',False))))


@pytest.fixture(scope='module')
def switched_program():
    from neutral_atom_env.simulation.pipeline import initialize, Platform, load_circuit
    from neutral_atom_env.motion.single_trap import SingleTrapCompiler
    from neutral_atom_env.motion.program import ProgramBuilder
    from neutral_atom_env.visualization import VisualRecorder
    platform = Platform.load('configs/platforms/single_trap.json')
    platform = replace(platform,aod=replace(platform.aod,pose=P(-5,0)))
    circuit = load_circuit('configs/circuits/single_trap.json')
    placement = json.loads(open('configs/placements/eight_atoms.json',encoding='utf-8').read())
    # The real config's mapping is consumed by the same pipeline as the CLI.
    state = initialize(circuit,platform,placement.get('placement',placement))
    intent = ExecuteGateBatchIntent({'G000'})
    full = SingleTrapCompiler().compile(intent,state)
    builder = ProgramBuilder(state,intent)
    origin = trap_state(state)
    builder.add(K.TRAP_SWITCH,'Enable empty AOD at clear pose',switch_state=replace(origin,rows=(True,),columns=(True,)))
    builder.add(K.TRAP_SWITCH,'Disable empty AOD before timed reposition',switch_state=origin)
    for op in full.operations:
        builder.add(op.operation_type,op.label,target=op.target_pose,bindings=op.transfer_bindings,
                    phase=op.transfer_phase,switch_state=op.switch_state)
    plan = builder.finish('m3-a-switch-acceptance')
    recorder = VisualRecorder(state)
    executor = Executor(state);executor.submit(plan)
    snapshots = [state.snapshot()]
    while state.event_queue:
        event=executor.step();snapshots.append(state.snapshot());recorder.observe(state,event)
    return state, plan, snapshots, recorder


def test_switch_and_handoff_checkpoint_boundaries_have_deterministic_continuations(switched_program):
    final, plan, snapshots, recorder = switched_program
    assert plan.operations[0].duration_us == plan.operations[1].duration_us == 1
    assert sum(op.duration_us for op in plan.operations) == pytest.approx(final.metrics()['episode_wall_time_us'])
    chosen=[]
    for saved in snapshots:
        state=SimulationState.restore(saved)
        if state.active_plan and state.active_plan.operation_started_us is not None:
            op=state.active_plan.plan.operations[state.active_plan.operation_index]
            if op.operation_type in {K.TRAP_SWITCH,K.AOD_LOAD,K.AOD_OFFLOAD}:
                chosen.append(state)
    for state in chosen:
        Executor(state).run()
        assert state.snapshot()==final.snapshot()
    payload=recorder.payload()
    assert payload['format']=='neutral-atom-view/2'
    assert any(f['transfer'] and f['transfer']['stage']=='target_supported' for f in payload['frames'])
    assert any(not any(f['aod']['enabled_rows']) and f['movement'] for f in payload['frames'])
    assert next(r for r in payload['summary']['categories'] if r['key']=='switch')['duration_us']==2


@pytest.mark.parametrize('damage',['schema','missing_mask','row','slm','stage','destination'])
def test_corrupt_support_or_transfer_checkpoints_are_rejected(switched_program,damage):
    _,_,snapshots,_=switched_program
    data=json.loads(next(s for s in snapshots if json.loads(s)['transfer'] is not None))
    if damage=='schema':data['schema_version']=9
    elif damage=='missing_mask':del data['slm_enabled']
    elif damage=='row':data['aod']['enabled_rows']=[False]
    elif damage=='slm':data['slm_enabled'][data['transfer']['bindings'][0]['static_trap_id']]=False
    elif damage=='stage':data['transfer']['stage']='source_removed'
    else:data['transfer']['target_traps']['rows']=[False]
    with pytest.raises(ValidationError):SimulationState.restore(json.dumps(data))


def test_completed_support_state_cannot_change_without_an_event(switched_program):
    final,_,_,_=switched_program
    data=json.loads(final.snapshot())
    data['slm_enabled']['EZ1']=False  # Empty, but no operation actually switched it.
    with pytest.raises(ValidationError,match='Idle supports'):
        SimulationState.restore(json.dumps(data))
