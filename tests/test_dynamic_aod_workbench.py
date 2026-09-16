"""Dynamic axis decisions must execute, not merely appear in UI labels."""
from copy import deepcopy
import pytest
from neutral_atom_app.visualization.workbench import build_inputs, initialize_input
from neutral_atom_app.control import configured_strategy
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.visualization import VisualRecorder
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_strategies.scheduling.m3 import initial_terminal


def dynamic_input(strategy='ordered_greedy'):
    return dict(studio={'mode':'custom'},circuit_profile='physical',atom_count=6,
        layout='row',seed=7,ez_policy='adaptive',ez_neighbor_guard_enabled=True,
        aod_backend='row_column_orthogonal',aod_rows=1,aod_columns=3,
        aod_row_offsets_um=[0],aod_column_offsets_um=[0,15,35],
        compilation={'strategy':'legacy','implementation':strategy,'compile_timeout_s':90},
        gates=[dict(id=f'G{i:03d}',gate_type='CZ',qubit_ids=[f'Q{a:03d}',f'Q{b:03d}'],column=0)
               for i,(a,b) in enumerate(((0,1),(2,4),(3,5)))])


@pytest.mark.parametrize('strategy',['ordered_greedy','smt_ordered'])
def test_loaded_nonuniform_axes_are_compiled_executed_and_replayed(strategy):
    value=dynamic_input(strategy);original=deepcopy(value)
    v,c,p,s=build_inputs(value)
    env=NeutralAtomEnv(initialize_input(v,c,p,s));initial=env.snapshot()
    terminal=initial_terminal(env.state);recorder=VisualRecorder(env.state)
    plans=[];submit=env.submit
    def capture(plan):
        submit(plan);plans.append(plan)
    env.submit=capture
    result=configured_strategy(v).run(env,on_event=recorder.observe)
    assert result.status=='completed',result.diagnostics
    batches=[d for d in result.decision_log if d['kind']=='CZ']
    assert [len(d['gate_ids']) for d in batches]==[3]
    moves=[o for o in recorder.payload()['operations'] if o['kind']=='aod_move']
    def relative(c,k):return [x-c[k][0] for x in c[k]]
    loaded=[o for o in moves if o['moving_count']==3 and any(
        relative(o['source_axes'],k)!=relative(o['target_axes'],k) for k in ('x_um','y_um'))]
    assert loaded, 'Must change spacing while carrying atoms, not just reconfigure empty axes'
    assert all(len(o['moving_atom_ids'])==o['moving_count'] for o in moves)
    assert any(relative(o['source_axes'],'x_um')!=[0,15,35] for o in loaded)
    assert value==original
    validate_target(terminal,env.state)
    replay=NeutralAtomEnv.restore(initial)
    for plan in plans:replay.submit(plan);replay.run()
    assert replay.snapshot()==env.snapshot()
