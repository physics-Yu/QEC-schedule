import json
from dataclasses import replace
import pytest
from neutral_atom_env.domain.models import HolderType,HolderRef,Position2D,EventType,MobileCellIndex
from neutral_atom_env.domain.operations import ExecuteGateBatchIntent,OperationType as K
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware import get_backend
from neutral_atom_env.motion.compiler import MotionCompiler,exact_validate
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.simulation.scheduler import EagerScheduler
from neutral_atom_env.simulation.rigid_parking_factory import make_rigid_parking_state
from neutral_atom_env.visualization import VisualRecorder
from neutral_atom_env.world import PlacementState


def run(scenario='pair'):
    state=make_rigid_parking_state(scenario);initial=state.snapshot();recorder=VisualRecorder(state)
    snapshots=[initial]
    def observe(s,e):snapshots.append(s.snapshot());recorder.observe(s,e)
    assert EagerScheduler(state).run(observe).status=='completed'
    return state,snapshots,recorder


def test_joint_rigid_cycle_independent_geometry_and_timing():
    final,snapshots,recorder=run();initial=SimulationState.restore(snapshots[0])
    assert all(h.holder_type==HolderType.STATIC for h in initial.placement.atom_to_holder.values())
    assert initial.placement.static_occupancy.get('EZ_PARK') is None
    at=lambda time:SimulationState.restore(next(s for s in reversed(snapshots) if json.loads(s)['time_us']==pytest.approx(time)))
    before_park,parked,pulse,restored,recaptured=(at(t) for t in (180,280,296,312.3,412.3))
    assert len(before_park.placement.mobile_occupancy)==2
    assert parked.placement.atom_to_holder['Q000']==HolderRef(HolderType.STATIC,'EZ_PARK')
    assert len(parked.placement.mobile_occupancy)==1
    assert pulse.placement.position('Q000',pulse.world,pulse.aod)==Position2D(5,-35)
    assert pulse.placement.position('Q001',pulse.world,pulse.aod)==Position2D(7,-35)
    assert restored.placement.position('Q001',restored.world,restored.aod)==Position2D(15,-35)
    assert recaptured.aod.configuration()==before_park.aod.configuration()
    assert recaptured.placement==before_park.placement
    assert final.placement==initial.placement and final.aod==initial.aod
    # 2x joint 40 um legs + 2x local 8 um; only one atom moves locally.
    m=final.metrics()
    assert m['total_aod_distance_um']==96
    assert m['total_atom_distance_um']==176
    assert m['episode_wall_time_us']==pytest.approx(4*100+96/.5+.3)
    assert m['logical_completion_elapsed_us']==pytest.approx(296.3)
    assert m['aod_load_count']==m['aod_offload_count']==2
    partial=[o for o in recorder.operations if o['kind'] in ('aod_park','aod_recapture')]
    assert [o['captured'] for o in partial]==[['Q000'],['Q000']]
    # Planned path overlay must stop moving a parked operand.
    path=recorder.payload()['plans'][0]['paths']['Q000']
    assert path[-1]=={'x_um':5,'y_um':-35}


def test_restore_every_transfer_boundary_and_pending_plan():
    final,snapshots,_=run()
    initial=make_rigid_parking_state('pair');executor=Executor(initial)
    executor.submit(MotionCompiler().compile(ExecuteGateBatchIntent({'G000'}),initial))
    for saved in [initial.snapshot(),*snapshots]:
        resumed=SimulationState.restore(saved)
        assert EagerScheduler(resumed).run().status=='completed'
        assert resumed.snapshot()==final.snapshot()


def test_all_sz_full_circuit_keeps_incidental_atoms_and_gate_dependencies():
    final,snapshots,recorder=run('circuit')
    initial=SimulationState.restore(snapshots[0])
    assert final.metrics()['completed_gate_count']==final.metrics()['completed_plan_count']==6
    assert final.placement==initial.placement and final.aod==initial.aod
    trace=[json.loads(r) for r in final.trace.records]
    pulses=[r for r in trace if r.get('operation_type')=='entangling_pulse' and r['event']['event_type']=='operation_completed']
    assert [r['actual_pairs'] for r in pulses]==[[sorted(g.qubit_ids)] for g in initial.dag.circuit.gates]
    assert all(len(o['captured'])==4 for o in recorder.operations if o['kind']=='aod_load')
    assert final.metrics()['incidental_atom_transport_total']==12
    # Resume at a partial-transfer boundary in a later plan, with prior gates complete.
    saved=next(s for s in snapshots if json.loads(s)['metrics']['completed_plan_count']==3 and any(h['holder_type']=='static' and h['holder_id']=='EZ_PARK' for h in json.loads(s)['placement']['atom_to_holder'].values()))
    resumed=SimulationState.restore(saved);assert EagerScheduler(resumed).run().status=='completed'
    assert resumed.snapshot()==final.snapshot()


@pytest.mark.parametrize('damage',['capability','misaligned','wrong_cell','empty','duplicate','moving','occupied'])
def test_partial_transfer_hardware_rejects_invalid_handoffs_atomically(damage):
    _,snapshots,_=run()
    state=SimulationState.restore(next(s for s in snapshots if json.loads(s)['time_us']==180))
    op=next(o for o in state.active_plan.plan.operations if o.operation_type==K.AOD_PARK)
    bindings=op.transfer_bindings
    if damage=='capability':state=replace(state,hardware=replace(state.hardware,selective_transfer_enabled=False))
    elif damage=='misaligned':state=replace(state,aod=replace(state.aod,pose=Position2D(5.1,-35)))
    elif damage=='wrong_cell':bindings=(replace(bindings[0],cell=MobileCellIndex(0,1)),)
    elif damage=='empty':bindings=()
    elif damage=='duplicate':bindings=bindings*2
    elif damage=='moving':state=replace(state,aod=replace(state.aod,is_moving=True))
    elif damage=='occupied':state=replace(state,placement=PlacementState(dict(state.placement.atom_to_holder)|{'Q001':HolderRef(HolderType.STATIC,'EZ_PARK')}))
    before=state.snapshot()
    with pytest.raises(ValidationError):get_backend(state.hardware).park(state,bindings)
    assert state.snapshot()==before


@pytest.mark.parametrize('damage',['binding','skip_park','skip_recapture','phase','duration','reservation','deformation'])
def test_plan_audit_rejects_forged_transfers(damage):
    state=make_rigid_parking_state('pair');plan=MotionCompiler().compile(ExecuteGateBatchIntent({'G000'}),state)
    ops=list(plan.operations)
    if damage=='binding':ops[4]=replace(ops[4],transfer_bindings=(replace(ops[4].transfer_bindings[0],atom_id='Q001'),))
    elif damage=='skip_park':ops.pop(4)
    elif damage=='skip_recapture':ops.pop(8)
    elif damage=='phase':ops[5]=replace(ops[5],transfer_phase='approach',transfer_bindings=ops[4].transfer_bindings)
    elif damage=='duration':ops[4]=replace(ops[4],duration_us=.01)
    elif damage=='reservation':plan=replace(plan,resources=tuple(r for r in plan.resources if r!='trap:EZ_PARK'))
    elif damage=='deformation':ops[5]=replace(ops[5],target_configuration=state.aod.configuration())
    before=state.snapshot()
    with pytest.raises(ValidationError):Executor(state).submit(replace(plan,operations=tuple(ops)))
    assert state.snapshot()==before


def test_damaged_parked_checkpoint_and_completion_are_rejected():
    _,snapshots,_=run()
    saved=next(s for s in snapshots if json.loads(s)['time_us']==280)
    data=json.loads(saved);data['placement']['atom_to_holder']['Q000']={'holder_type':'mobile','holder_id':{'row':0,'column':0}}
    with pytest.raises(ValidationError):SimulationState.restore(json.dumps(data))
    state=SimulationState.restore(saved)
    entry=state.event_queue.entries[0];event=replace(entry[2],time_us=entry[0]+1)
    from neutral_atom_env.simulation.event_queue import EventQueue
    state=replace(state,event_queue=EventQueue(((entry[0]+1,entry[1],event),),state.event_queue.next_sequence))
    before=state.snapshot()
    with pytest.raises(ValidationError):Executor(state).step()
    assert state.snapshot()==before


def test_no_ez_parking_trap_reports_stalled_without_hidden_preparation():
    state=make_rigid_parking_state('pair')
    state=replace(state,world=replace(state.world,traps={k:v for k,v in state.world.traps.items() if k!='EZ_PARK'}))
    before=state.snapshot();result=EagerScheduler(state).run()
    assert result.status=='stalled' and result.diagnostics['candidate_failures']
    assert state.snapshot()==before


@pytest.mark.parametrize('damage',['occupied_cell','misaligned','moving','capability'])
def test_recapture_rejects_wrong_alignment_cell_and_capability(damage):
    _,snapshots,_=run()
    state=SimulationState.restore(next(s for s in snapshots if json.loads(s)['time_us']==pytest.approx(312.3)))
    bindings=next(o.transfer_bindings for o in state.active_plan.plan.operations if o.operation_type==K.AOD_RECAPTURE)
    if damage=='occupied_cell':bindings=(replace(bindings[0],cell=MobileCellIndex(0,1)),)
    elif damage=='misaligned':state=replace(state,aod=replace(state.aod,pose=Position2D(5.1,-35)))
    elif damage=='moving':state=replace(state,aod=replace(state.aod,is_moving=True))
    elif damage=='capability':state=replace(state,hardware=replace(state.hardware,selective_transfer_enabled=False))
    before=state.snapshot()
    with pytest.raises(ValidationError):get_backend(state.hardware).recapture(state,bindings)
    assert state.snapshot()==before
