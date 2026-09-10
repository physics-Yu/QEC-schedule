import json
from dataclasses import replace
import pytest
from neutral_atom_env.visualization import VisualRecorder,summarize_trace
from neutral_atom_env.visualization.summary import summarize_intervals
from neutral_atom_env.simulation.milestone2_factory import make_circuit_state
from neutral_atom_env.simulation.scheduler import EagerScheduler


def recorded_circuit():
    state=make_circuit_state();recorder=VisualRecorder(state)
    result=EagerScheduler(state).run(on_event=recorder.observe)
    assert result.status=='completed'
    return state,recorder


def test_summary_independent_time_budget_and_no_atom_double_count():
    state,recorder=recorded_circuit()
    summary=summarize_trace(state.trace.records,state.metrics())
    actual={row['key']:row['duration_us'] for row in summary['categories']}
    assert actual==pytest.approx({'load':300,'transport':218,'return':218,'offload':300,'pulse':.9,'empty':80,'idle':0})
    assert sum(actual.values())==pytest.approx(1116.9)
    assert summary['transport_atom_time_us']==pytest.approx(436)
    assert summary==recorder.payload()['summary']
    schedule=summary['schedule']
    assert schedule[0]=={'start':0,'end':100,'category':'load'}
    pulses=[op for op in schedule if op['category']=='pulse']
    assert [op['start'] for op in pulses]==pytest.approx([156,488.3,890.6])
    assert [op['end']-op['start'] for op in pulses]==pytest.approx([.3,.3,.3])
    assert schedule[-1]['category']=='empty'
    assert schedule[-1]['start']==pytest.approx(1076.9)
    # 400 carried atoms still occupy the one device for 10 us, not 4000 us.
    many=summarize_intervals([{'start':0,'end':10,'category':'transport','mode':'translation','moving_count':400}],0,20)
    assert many['categories'][1]['duration_us']==10
    assert many['transport_atom_time_us']==4000
    assert many['categories'][-1]['duration_us']==10
    assert many['schedule'][-1]=={'start':10,'end':20,'category':'idle'}
    assert sum(r['fraction'] for r in many['categories'])==pytest.approx(1)


def test_summary_clips_incomplete_operation_and_rejects_overlap():
    operation={'start':10,'end':110,'category':'load','mode':None,'moving_count':0}
    summary=summarize_intervals([operation],10,50)
    assert summary['categories'][0]['duration_us']==40
    assert summary['schedule']==[{'start':10,'end':50,'category':'load'}]
    with pytest.raises(ValueError,match='overlapping'):
        summarize_intervals([operation,operation],0,120)


def test_recorder_is_read_only_and_export_contains_no_checkpoint_history(tmp_path):
    state,recorder=recorded_circuit();before=state.snapshot();payload=recorder.payload()
    assert 'scene' in payload and all('scene' not in f and 'trace' not in f and 'world' not in f for f in payload['frames'])
    assert sum(len(f['atom_updates']) for f in payload['frames'])<len(payload['frames'])*4
    assert len(payload['summary']['categories'])==7
    recorder.write(tmp_path/'viewer.html');recorder.write_json(tmp_path/'recording.json')
    assert state.snapshot()==before
    payload['frames'][0]['atom_updates'].clear()
    assert len(recorder.payload()['frames'][0]['atom_updates'])==4
    text=(tmp_path/'viewer.html').read_text(encoding='utf-8')
    assert 'NeutralAtomViewer.mount' in text and '__SHELL_JSON__' not in text


def test_compact_recorder_does_not_call_snapshot_and_scales_with_changes(tmp_path,monkeypatch):
    from neutral_atom_env.world.config import LayoutConfig
    from neutral_atom_env.world import PlacementState
    from neutral_atom_env.domain.models import Atom,HolderRef,HolderType,SimulationEvent,EventType
    from neutral_atom_env.circuit import PhysicalCircuit,DynamicGateDAG
    from neutral_atom_env.simulation import Executor
    from neutral_atom_env.simulation.state import SimulationState
    world=LayoutConfig(columns=32,rows=16,zone_height_um=100).build()
    atoms={f'Q{i:03d}':Atom(f'Q{i:03d}') for i in range(512)}
    holders=PlacementState({q:HolderRef(HolderType.STATIC,f'S{i:03d}') for i,q in enumerate(atoms)})
    state=replace(make_circuit_state(),world=world,atoms=atoms,placement=holders,dag=DynamicGateDAG(PhysicalCircuit(())))
    monkeypatch.setattr(SimulationState,'snapshot',lambda self:pytest.fail('Recorder must not serialize full checkpoints'))
    recorder=VisualRecorder(state);executor=Executor(state)
    for t in range(1,257):
        executor.schedule(SimulationEvent(t,EventType.WAIT_COMPLETED));event=executor.step();recorder.observe(state,event)
    payload=recorder.payload()
    assert len(payload['frames'])==257
    assert sum(len(f['atom_updates']) for f in payload['frames'])==512
    assert len(json.dumps(payload).encode())<600_000
    recorder.write_json(tmp_path/'large.json')
    # Retained for the Node component scale check, without claiming a physical 512-atom transport.
    from pathlib import Path
    recorder.write_json(Path('artifacts/visualization-scale/recording.json'))
    recorder.write(Path('artifacts/visualization-scale/index.html'))


def test_recorder_supports_no_plan_and_equal_timestamp_commits():
    state=make_circuit_state();recorder=VisualRecorder(state)
    scheduler=EagerScheduler(state)
    for _ in range(2):event=scheduler.step();recorder.observe(state,event)
    assert [f['time'] for f in recorder.frames]==[0,0,0]
    assert recorder.frames[-1]['gate_status']=='reserved'
    with pytest.raises(ValueError,match='increasing'):recorder.observe(state)


def test_row_column_recording_preserves_profile_and_stationary_intersection():
    from neutral_atom_env.simulation.row_column_factory import make_row_column_state
    from pathlib import Path
    state=make_row_column_state('incidental');recorder=VisualRecorder(state)
    assert EagerScheduler(state).run(on_event=recorder.observe).status=='completed'
    payload=recorder.payload();atoms={}
    found=False
    for frame in payload['frames']:
        atoms.update({a['id']:a for a in frame['atom_updates']})
        if frame['label']=='Reconfigure axes' and frame['movement']:
            assert frame['movement']['profile']=='cubic'
            assert atoms['Q002']['activity']=='moving'
            assert atoms['Q000']['activity']=='moving'
            found=True
    assert found
    assert payload['summary']['movement_modes']['axis_deformation']['segments']==2
    recorder.write(Path('artifacts/visualization-row-column/index.html'))
