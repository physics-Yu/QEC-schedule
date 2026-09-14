"""Editor inputs select a real policy while preserving identical hardware."""
import pytest

from neutral_atom_env.visualization.workbench import build_inputs, validate_input, compile_input
from neutral_atom_env.replay.serializer import primitive


def request(strategy='greedy'):
    return {'compiler':strategy, 'ez_policy':'adaptive', 'atom_count':2, 'layout':'row', 'seed':7,
            'lookahead_depth':2, 'beam_width':2, 'rollout_budget':6, 'site_limit':1,
            'gates':[{'id':'h0','gate_type':'H','qubit_ids':['Q000'],'column':0},
                     {'id':'h1','gate_type':'H','qubit_ids':['Q001'],'column':0}]}


@pytest.mark.parametrize('strategy', ['basic','greedy','critical_path','lookahead'])
def test_all_m4_editor_policies_use_identical_platform_and_actual_parallel_effects(strategy):
    expected=build_inputs(request())
    value,circuit,platform,placement=build_inputs(request(strategy))
    assert primitive(platform)==primitive(expected[2]) and placement==expected[3]
    result,state=compile_input(value)
    assert result['input']['compiler']==strategy and result['status']=='completed'
    assert result['compile_seconds']>=0
    assert state.time_us==1 and state.dag.completed
    pulses=[o for o in result['recording']['operations'] if o['kind']=='raman_rotation']
    assert len(pulses)==2 and {o['start'] for o in pulses}=={0.}
    assert result['decision_log'][0]['strategy']==strategy


@pytest.mark.parametrize('key,value', [('lookahead_depth',0),('lookahead_depth',9),('beam_width',True),
    ('beam_width',33),('rollout_budget',0),('rollout_budget',4097),('ready_limit',0),('site_limit',129)])
def test_editor_search_limits_reject_invalid_input(key,value):
    with pytest.raises(ValueError):
        validate_input(request()|{key:value})


@pytest.mark.parametrize('strategy', ['basic','greedy','critical_path','lookahead'])
def test_multitrap_policies_are_not_silently_replaced(strategy):
    value=validate_input(request(strategy)|{'aod_traps':4})
    assert value['compiler']==strategy and value['aod_traps']==4
