from copy import deepcopy
from dataclasses import replace
import pytest
from neutral_atom_app.visualization.workbench import build_inputs,compile_input,initialize_input,validate_input
from neutral_atom_app.visualization.studio_config import catalog,demo_input
from neutral_atom_app.control import configured_strategy
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_strategies.scheduling.m3 import initial_terminal


def spec(n=4,layout='grid',rows=2,columns=2,strategy='ordered_greedy'):
    return {'studio':{'mode':'custom'},'circuit_profile':'physical','atom_count':n,'layout':layout,
            'seed':13,'ez_policy':'adaptive','ez_neighbor_guard_enabled':True,
            'aod_backend':'row_column_orthogonal','aod_rows':rows,'aod_columns':columns,
            'aod_row_offsets_um':[i*15 for i in range(rows)],'aod_column_offsets_um':[i*20 for i in range(columns)],
            'compilation':{'strategy':'legacy','implementation':strategy,'compile_timeout_s':90},
            'gates':[{'id':'h','gate_type':'H','qubit_ids':['Q000'],'column':0},
                     {'id':'cz','gate_type':'CZ','qubit_ids':['Q000','Q001'],'column':1},
                     {'id':'t','gate_type':'T','qubit_ids':['Q001'],'column':2}]}


@pytest.mark.parametrize('strategy',['ordered_greedy','smt_ordered'])
@pytest.mark.parametrize('layout,n,rows,columns',[('row',6,1,2),('grid',9,2,2),('shuffled',5,1,1)])
def test_arbitrary_editor_layout_and_capacity_split_execute_and_restore(strategy,layout,n,rows,columns):
    v=spec(n,layout,rows,columns,strategy);original=deepcopy(v)
    normalized,circuit,platform,placement=build_inputs(v)
    terminal=initial_terminal(initialize_input(normalized,circuit,platform,placement))
    result,state=compile_input(v)
    assert result['status']=='completed',result['failure_report']
    assert v==original and len(state.atoms)==n
    assert result['input']['layout']==layout and state.hardware.backend=='row_column_orthogonal'
    assert state.metrics()['completed_gate_count']==3
    validate_target(terminal,state)
    assert all(x['strategy']==strategy for x in result['decision_log'])
    assert state.aod.rows==rows and state.aod.columns==columns


@pytest.mark.parametrize('strategy',['ordered_greedy','smt_ordered'])
def test_parallel_same_gate_and_empty_do_not_stage_atoms(strategy):
    v=spec(12,strategy=strategy);v['gates']=[{'id':f'h{i}','gate_type':'H','qubit_ids':[f'Q{i:03d}'],'column':0} for i in range(12)]
    result,state=compile_input(v)
    assert result['status']=='completed' and state.time_us==1
    assert len(result['decision_log'])==1 and state.metrics()['aod_load_count']==0
    v['gates']=[];result,state=compile_input(v)
    assert result['status']=='completed' and state.time_us==0


def test_backend_is_separate_configuration_and_old_paths_keep_rigid():
    v=spec();v['aod_backend']='rigid'
    normalized=validate_input(v)
    assert normalized['compilation_backend']['configuration_error']
    with pytest.raises(ValueError,match='row_column'):compile_input(v)
    v=spec();v['compilation']['implementation']='greedy';v['aod_rows']=v['aod_columns']=1
    v['aod_row_offsets_um']=v['aod_column_offsets_um']=[0];v.pop('aod_backend')
    result,state=compile_input(v)
    assert result['status']=='completed' and state.hardware.backend=='rigid'


def test_budget_failure_is_explicit_and_preserves_executed_prefix():
    v=spec();v['compilation']['max_decisions']=1
    result,state=compile_input(v)
    assert result['status']=='stalled'
    assert result['failure_report']['code']=='DECISION_LIMIT'
    assert len(result['decision_log'])==1 and state.time_us>0
    assert state.metrics()['completed_gate_count']==0


def test_same_ready_cz_pairs_are_chosen_by_new_planner():
    v=spec(4,'row',1,2)
    v['gates']=[{'id':f'cz{i}','gate_type':'CZ','qubit_ids':[f'Q{2*i:03d}',f'Q{2*i+1:03d}'],'column':0} for i in range(2)]
    result,state=compile_input(v)
    assert result['status']=='completed',result['failure_report']
    batches=[d for d in result['decision_log'] if d['kind']=='CZ']
    assert [len(d['gate_ids']) for d in batches]==[2]


def test_qec_readout_uses_policy_and_independent_physical_replay():
    value=demo_input('ordered-qec-ghz2');value.pop('studio')
    value['gates']=[{'id':'h','gate_type':'H','qubit_ids':['Q019'],'column':0},
                    {'id':'m','gate_type':'MEASURE','qubit_ids':['Q019'],'column':1},
                    {'id':'r','gate_type':'RESET','qubit_ids':['Q019'],'column':2}]
    normalized,circuit,platform,placement=build_inputs(value)
    env=NeutralAtomEnv(initialize_input(normalized,circuit,platform,placement));initial=env.snapshot()
    plans=[];submit=env.submit
    def capture(plan):
        submit(plan);plans.append(plan)
    env.submit=capture
    result=configured_strategy(normalized).run(env)
    assert result.status=='completed'
    readouts=[d for d in result.decision_log if d.get('readout_target')]
    assert readouts and readouts[0]['readout_target']['support']=='aod'
    replay=NeutralAtomEnv.restore(initial)
    for plan in plans:replay.submit(plan);replay.run()
    assert replay.snapshot()==env.snapshot()
    assert env.state.measurement_results and all(n.status.value=='completed' for n in env.state.dag.nodes.values())


def test_current_catalog_defaults_and_platform_are_not_fixed_qec():
    c=catalog();assert c['default_algorithm']=='ordered_greedy'
    assert c['workspace_defaults']['atom_count']==4
    assert c['workspace_defaults']['layout']=='grid'
    assert c['workspace_defaults']['aod_backend']=='row_column_orthogonal'


def test_algorithm_does_not_change_platform_geometry_or_relative_offsets():
    v=spec(9,'grid',2,3);_,_,platform,_=build_inputs(v)
    v['compilation']['implementation']='smt_ordered';_,_,other,_=build_inputs(v)
    assert platform==other
    # An incompatible old strategy may preview this same hardware; it cannot
    # silently change world/axes to make itself executable.
    v['compilation']['implementation']='greedy';_,_,legacy,_=build_inputs(v)
    assert platform==legacy
