"""Two actual Executor lanes, including equal row/column indices on each device."""
import shutil
import subprocess

import pytest

from neutral_atom_env.circuit import DynamicGateDAG, PhysicalCircuit
from neutral_atom_env.domain.models import (
    Atom, HolderRef, HolderType, MobileCellIndex, Position2D as P, Rectangle,
    Zone, ZoneType,
)
from neutral_atom_env.domain.operations import (
    Operation, OperationInterval, OperationType as K, TaskIntent, TaskTarget,
)
from neutral_atom_env.hardware.multi_aod import backend_for
from neutral_atom_env.program.scheduled import build_scheduled_program
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.visualization import VisualRecorder
from neutral_atom_env.world import AODRuntimeState, PlacementState, WorldState


def two_lane_state():
    bounds=Rectangle(P(0,0),P(200,100))
    world=WorldState(bounds,{},(Zone('compute',ZoneType.ENTANGLEMENT,bounds),))
    aod=AODRuntimeState(pose=P(20,30),rows=1,columns=1,
        enabled_rows=(True,),enabled_columns=(True,),
        envelope=Rectangle(P(0,0),P(80,100)))
    magic=AODRuntimeState(pose=P(120,30),rows=1,columns=1,
        enabled_rows=(True,),enabled_columns=(True,),aod_id='AOD_MAGIC',
        envelope=Rectangle(P(100,0),P(200,100)))
    placement=PlacementState({
        'Q000':HolderRef(HolderType.MOBILE,MobileCellIndex(0,0)),
        'Q001':HolderRef(HolderType.MOBILE,MobileCellIndex(0,0,'AOD_MAGIC')),
    })
    return SimulationState(world,placement,{q:Atom(q) for q in placement.atom_to_holder},
        aod,DynamicGateDAG(PhysicalCircuit(())),aods={'AOD_0':aod,'AOD_MAGIC':magic})


def record_two_moves():
    state=two_lane_state()
    ops=[];intervals=[]
    for index,(device,target) in enumerate((('AOD_0',P(40,30)),('AOD_MAGIC',P(150,40)))):
        duration=backend_for(state,device).move_duration(state.aods[device],target,state.hardware)
        op=Operation(f'op{index:02d}',K.AOD_MOVE,'Independent lane move',duration,
            target_pose=target,aod_id=device)
        ops.append(op);intervals.append(OperationInterval(op.id,0,duration,(),()))
    intent=TaskIntent('two-lane-observer',TaskTarget(),atom_ids=frozenset(state.atoms),phase='program')
    plan=build_scheduled_program(state,intent,ops,intervals,planner_id='observer-test')
    recorder=VisualRecorder(state,scene_metadata={
        'aod_labels':{'AOD_0':'算法 AOD','AOD_MAGIC':'魔态 AOD'},
        'zone_labels':{'compute':'COMPUTE'},
    })
    executor=Executor(state);executor.submit(plan)
    while state.event_queue:
        executor.step();recorder.observe(state)
    return state,recorder


def test_recorded_device_identity_and_movements_are_actual_and_read_only():
    state,recorder=record_two_moves();before=state.snapshot();data=recorder.payload()
    assert state.placement.position('Q000',state.world,state.aods)==P(40,30)
    assert state.placement.position('Q001',state.world,state.aods)==P(150,40)
    assert data['summary']['overlapping']
    assert set(data['summary']['resource_busy_us'])>={'AOD_0','AOD_MAGIC'}
    moves={o['aod_id']:o for o in data['operations'] if o['kind']=='aod_move'}
    assert moves['AOD_0']['moving_atom_ids']==['Q000']
    assert moves['AOD_MAGIC']['moving_atom_ids']==['Q001']
    assert all(o['moving_count']==1 for o in moves.values())
    concurrent=[f for f in data['frames'] if set(f['movements'])=={'AOD_0','AOD_MAGIC'}]
    assert concurrent
    assert concurrent[0]['movement']==concurrent[0]['movements']['AOD_0']
    assert concurrent[0]['axes_by_aod']['AOD_0']['x_um']==[20]
    assert concurrent[0]['axes_by_aod']['AOD_MAGIC']['x_um']==[120]
    assert state.snapshot()==before
    data['frames'][0]['aods']['AOD_MAGIC']['pose']['x_um']=0
    assert recorder.payload()['frames'][0]['aods']['AOD_MAGIC']['pose']['x_um']==120


def test_viewer_interpolates_each_committed_lane_and_reverse_seeks(tmp_path):
    _,recorder=record_two_moves()
    html=recorder.write(tmp_path/'two-lanes.html')
    node=shutil.which('node')
    assert node,'Node.js required for declared observer contract check'
    result=subprocess.run([node,'tests/multi_aod_viewer.cjs',str(html)],
        check=True,capture_output=True,text=True)
    assert 'PASS' in result.stdout


def test_metadata_cannot_replace_observed_geometry():
    with pytest.raises(ValueError,match='metadata'):
        VisualRecorder(two_lane_state(),scene_metadata={'bounds':'fabricated'})


def test_fitted_camera_remains_visible_across_canvas_size_changes(tmp_path):
    _,recorder=record_two_moves()
    html=recorder.write(tmp_path/'fit-resize.html')
    node=shutil.which('node')
    assert node,'Node.js required for declared camera contract check'
    result=subprocess.run([node,'tests/viewer_fit_resize.cjs',str(html)],
        check=True,capture_output=True,text=True)
    assert 'PASS' in result.stdout
