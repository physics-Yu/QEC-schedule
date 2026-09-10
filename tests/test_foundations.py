import json
import os
from pathlib import Path
import subprocess
import sys
from dataclasses import replace
import pytest
from neutral_atom_env.domain.models import SimulationEvent, EventType, Position2D
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.simulation import make_demo_state
from neutral_atom_env.testing.logical_executor import LogicalTestExecutor as Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.replay.trace import Trace
from neutral_atom_env.world.config import LayoutConfig
from neutral_atom_env.testing.scenarios import SCENARIOS
from neutral_atom_env.testing.scene import build_scene


@pytest.mark.parametrize('name,title,question,run',SCENARIOS,ids=[s[0] for s in SCENARIOS])
def test_acceptance_scenarios(name,title,question,run):
    evidence=run()
    assert evidence.checks


def prepared_checkpoint():
    state=make_demo_state(99);ex=Executor(state)
    for event in [SimulationEvent(0,EventType.RNG_DRAW),SimulationEvent(1,EventType.GATE_RESERVED,'g2'),
                  SimulationEvent(1,EventType.GATE_STARTED,'g2'),SimulationEvent(2,EventType.GATE_COMPLETED,'g2'),
                  SimulationEvent(2,EventType.RNG_DRAW),SimulationEvent(2,EventType.WAIT_COMPLETED)]:
        ex.schedule(event)
    for _ in range(3):ex.step()
    return state


def test_cross_process_checkpoint_and_hash_seed(tmp_path):
    original=prepared_checkpoint();saved=original.snapshot()
    input_path=tmp_path/'checkpoint.json';input_path.write_text(saved,encoding='utf-8')
    Executor(original).run()
    code="""import sys
from pathlib import Path
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.testing.logical_executor import LogicalTestExecutor as Executor
s=SimulationState.restore(Path(sys.argv[1]).read_text(encoding='utf-8'))
Executor(s).run()
Path(sys.argv[2]).write_text(s.snapshot(),encoding='utf-8')
"""
    for seed in ['1','782']:
        output=tmp_path/f'continued-{seed}.json'
        env=dict(os.environ,PYTHONHASHSEED=seed)
        subprocess.run([sys.executable,'-c',code,str(input_path),str(output)],env=env,check=True,capture_output=True)
        assert output.read_text(encoding='utf-8')==original.snapshot()


@pytest.mark.parametrize('field',['schema','queue','dag','rng','trace','metrics','time'])
def test_corrupt_checkpoint_rejected(field):
    data=json.loads(prepared_checkpoint().snapshot())
    if field=='schema':data['schema_version']=800
    elif field=='queue':data['event_queue']['pending'][1][1]=data['event_queue']['pending'][0][1]
    elif field=='dag':data['dag']['g3']['remaining_predecessors']=0
    elif field=='rng':data['rng_state']=[3,[1],None]
    elif field=='trace':data['trace']=[]
    elif field=='metrics':data['metrics']['completed_gate_count']=500
    else:data['time_us']=100
    with pytest.raises(ValidationError,match='INVALID_CHECKPOINT'):
        SimulationState.restore(json.dumps(data))


def test_restore_queue_sequence_when_new_equal_time_event_added():
    a=prepared_checkpoint();b=SimulationState.restore(a.snapshot())
    for state in (a,b):
        ex=Executor(state)
        ex.schedule(SimulationEvent(2,EventType.RNG_DRAW))
        ex.run()
    assert a.snapshot()==b.snapshot()
    assert json.loads(a.trace.records[-1])['event']['event_type']=='rng_draw'


def test_failed_trace_build_does_not_partially_commit(monkeypatch):
    state=make_demo_state();ex=Executor(state)
    ex.schedule(SimulationEvent(1,EventType.GATE_RESERVED,'g2'))
    before=state.snapshot()
    def fail(*args):raise RuntimeError('trace write preparation failed')
    monkeypatch.setattr(Trace,'appended',fail)
    with pytest.raises(RuntimeError):ex.step()
    assert state.snapshot()==before


@pytest.mark.parametrize('config',[{'rows':0},{'columns':1.5},{'spacing_um':0},{'spacing_um':float('nan')},
    {'isolation_gap_um':0},{'zone_height_um':2},{'disabled_traps':(999,)},{'disabled_traps':(1,1)}])
def test_invalid_layout_config(config):
    with pytest.raises(ValidationError,match='INVALID_LAYOUT_CONFIG'):LayoutConfig(**config)


def test_grid_origin_and_allowed_static_regions():
    from neutral_atom_env.domain.models import ZoneType
    world=LayoutConfig().build()
    world=replace(world,static_zone_types=(ZoneType.STORAGE,))
    assert not world.is_candidate_site(Position2D(0,-40))
    assert world.is_candidate_site(Position2D(0,0))
    with pytest.raises(ValidationError,match='INVALID_STATIC_SITE'):
        replace(world,grid_origin=Position2D(1,0))


def test_render_theme_changes_only_output(tmp_path):
    from neutral_atom_env.testing.theme import VisualTheme
    from neutral_atom_env.testing.renderer import render_layout,render_dag
    state=make_demo_state();before=state.snapshot();scene=build_scene(before)
    render_layout(before,tmp_path/'original.svg')
    changed=replace(VisualTheme.load(),static_color='#123456',atom_size=40)
    render_layout(before,tmp_path/'changed.svg',changed)
    render_dag(before,tmp_path/'dag.svg',changed)
    assert '#123456' in (tmp_path/'changed.svg').read_text(encoding='utf-8')
    assert (tmp_path/'changed.svg').read_bytes()!=(tmp_path/'original.svg').read_bytes()
    assert build_scene(state.snapshot())==scene and state.snapshot()==before


def test_dictionary_permutation_preserves_scene_and_checkpoint():
    a=make_demo_state();b=replace(a,atoms=dict(reversed(list(a.atoms.items()))),
         world=replace(a.world,traps=dict(reversed(list(a.world.traps.items())))))
    assert a.snapshot()==b.snapshot()
    assert build_scene(a.snapshot())==build_scene(b.snapshot())


def test_unified_qubit_identity_across_state_scene_and_checkpoint():
    from dataclasses import fields
    from neutral_atom_env.domain.models import Atom
    from neutral_atom_env.testing.scene import SceneAtom
    state=make_demo_state()
    assert set(state.atoms)=={'Q000','Q001','Q002','Q003'}
    assert 'physical_qubit_id' not in {f.name for f in fields(Atom)}
    assert 'qubit_id' not in {f.name for f in fields(SceneAtom)}
    for gate in state.dag.circuit.gates:
        assert all(state.atoms[q].id==q for q in gate.qubit_ids)
    scene=build_scene(state.snapshot())
    assert {a.id for a in scene.atoms}==set(state.placement.atom_to_holder)
    assert 'physical_qubit_id' not in state.snapshot()
    assert SimulationState.restore(state.snapshot()).snapshot()==state.snapshot()


def test_gate_cannot_reference_an_alternate_atom_identifier():
    from neutral_atom_env.domain.models import PhysicalGate
    from neutral_atom_env.circuit import PhysicalCircuit, DynamicGateDAG
    state=make_demo_state()
    circuit=PhysicalCircuit((PhysicalGate('G000','H',('A000',)),))
    with pytest.raises(ValidationError,match='UNKNOWN_QUBIT'):
        replace(state,dag=DynamicGateDAG(circuit))


@pytest.mark.parametrize('old_schema',[1,2,3])
def test_legacy_identity_checkpoints_explicitly_rejected(old_schema):
    data=json.loads(make_demo_state().snapshot())
    data['schema_version']=old_schema
    with pytest.raises(ValidationError,match='regenerate older checkpoints'):
        SimulationState.restore(json.dumps(data))
