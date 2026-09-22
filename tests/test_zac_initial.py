"""SA initial state is executed for real and every arm shares an absolute terminal."""
from copy import deepcopy
import json
import pytest
from neutral_atom_experiments.zac_reuse import normalize_spec, demos, frontend, run_one, DEFAULT_SOURCE, make_state
from neutral_atom_experiments.zac_initial import comparisons, MODES
from neutral_atom_experiments.zac_initial_report import rows
from neutral_atom_env import NeutralAtomEnv


def test_initial_option_validation_and_completed_only_comparisons():
    for mode in ('fixed','sa','compare'):
        assert normalize_spec(dict(demos()['cross'],initial_placement=mode))['initial_placement']==mode
    with pytest.raises(ValueError): normalize_spec(dict(demos()['cross'],initial_placement='unknown'))
    case=dict(id='test',spec=normalize_spec(demos()['cross']),variants={})
    for mode,total in zip(MODES,(100,80,90,60)):
        case['variants'][mode]=dict(status='completed',result=dict(replay_equal=True,effects_once=True,
            terminal_verified=True,terminal_target_sha256='common',initial_sha256=mode.split('_')[0],
            metrics=dict(episode_wall_time_us=total)))
    assert comparisons(case)['combined_effect']['change_percent']==pytest.approx(-40)
    assert comparisons(case)['sa_effect_with_reuse']['change_percent']==pytest.approx(-25)
    case['variants']['sa_reuse']['status']='failed'
    assert comparisons(case)['combined_effect']['change_percent'] is None
    assert rows(dict(cases=[case]))[-1]['total_us'] is None
    assert rows(dict(cases=[case]))[-1]['executed_prefix_us']==60
    case['variants']['sa_reuse']['status']='completed'
    case['variants']['sa_reuse']['result']['terminal_target_sha256']='different'
    assert not comparisons(case)['sa_effect_with_reuse']['comparable']
    case['variants']['sa_reuse']['result']['terminal_target_sha256']='common'
    case['variants']['sa_reuse']['result']['initial_sha256']='different'
    assert not comparisons(case)['sa_reuse_effect']['comparable']


@pytest.mark.skipif(not (DEFAULT_SOURCE/'zac/zac.py').exists(),reason='Original ZAC not installed')
def test_author_sa_drives_actual_initial_state_and_common_terminal(tmp_path):
    spec=normalize_spec(dict(demos()['eight'],initial_placement='sa',bounded_spares=True))
    placement=frontend(spec,DEFAULT_SOURCE,tmp_path/'upstream',True)
    info=placement['initial_placement']
    assert info['method']=='sa' and info['seed']==0
    assert 'SA-based placement' in (tmp_path/'upstream/upstream.log').read_text()
    assert 'zac/placer/saplacer.py' in placement['source_hashes']
    assert info['selected_cost']<info['baseline_cost']
    assert info['mapping']!=spec['initial_mapping']
    result,payload=run_one(spec,placement,tmp_path/'physical')
    assert result['status']=='completed',result['error']
    assert result['effects_once'] and result['replay_equal'] and result['terminal_verified']
    initial=json.loads((tmp_path/'physical/initial.json').read_text())
    final=json.loads((tmp_path/'physical/checkpoint.json').read_text())
    reference=json.loads(NeutralAtomEnv(make_state(spec)).snapshot())
    assert initial['placement']!=reference['placement']
    for key in ('placement','slm_enabled','aod'): assert final[key]==reference[key]
    assert sum(len(o['gate_ids']) for o in payload['operations'] if o['kind']=='entangling_pulse')==len(spec['pairs'])
