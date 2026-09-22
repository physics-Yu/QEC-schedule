from copy import deepcopy
import json
import pytest
from neutral_atom_app.studio_placement import prepare, compare_studio, search_options, StudioPlacementJobs
from neutral_atom_app.visualization.workbench import build_inputs, validate_input


def edited_input():
    return dict(studio={'mode':'custom'},circuit_profile='physical',
        compilation={'strategy':'legacy','implementation':'ordered_greedy','compile_timeout_s':60},
        atom_count=4,layout='grid',seed=7,ez_policy='adaptive',aod_backend='row_column_orthogonal',
        aod_rows=2,aod_columns=2,aod_row_offsets_um=[0,15],aod_column_offsets_um=[0,20],
        ez_neighbor_guard_enabled=False,
        placement_search=dict(evaluations=3,workers=2,proposal_pool=64,terminal_mode='stable',expand_storage=True),
        gates=[dict(id='cz0',gate_type='CZ',qubit_ids=['Q000','Q003'],column=0),
               dict(id='cz1',gate_type='CZ',qubit_ids=['Q001','Q002'],column=0),
               dict(id='h0',gate_type='H',qubit_ids=['Q000'],column=1)])


def test_preserve_editor_circuit_hardware_options_and_explicit_domain():
    raw=edited_input();copy=deepcopy(raw)
    original,circuit,platform,mapping=build_inputs(raw)
    v,c,p,m,o=prepare(raw)
    assert raw==copy and c==circuit and m==mapping
    assert p.hardware==platform.hardware and p.aod==platform.aod
    assert p.world.bounds==platform.world.bounds and p.world.zones==platform.world.zones
    assert len(p.world.traps)>len(platform.world.traps)
    raw['placement_search']['expand_storage']=False
    assert prepare(raw)[2]==platform
    assert validate_input(v)['placement_search']==o
    raw['compilation']['implementation']='smt_ordered'
    assert prepare(raw)[0]['compiler']=='smt_ordered'


def test_actual_editor_input_parallel_completion_and_reload(tmp_path):
    r=compare_studio(edited_input(),tmp_path/('a'*32))
    assert r['status']=='completed',r['trials']
    assert len(r['trials'])==3 and all(t['valid'] for t in r['trials'])
    assert r['recordings']['baseline']['summary']['metrics']['completed_gate_count']==3
    assert r['recordings']['optimized']['summary']['metrics']['completed_gate_count']==3
    assert r['recordings']['optimized']['duration']<=r['recordings']['baseline']['duration']
    assert r['input']['gates']==validate_input(edited_input())['gates']
    assert StudioPlacementJobs(tmp_path).get('a'*32,True)['status']=='completed'
    assert StudioPlacementJobs(tmp_path).get('../x',True) is None
    for path in (tmp_path/('a'*32)/'search').glob('trial-*/result.json'):
        evidence=json.loads(path.read_text(encoding='utf-8'))
        assert evidence['replay_equal'] and evidence['terminal_mode']=='stable'


@pytest.mark.parametrize('terminal',['stable','fixed'])
def test_zoned_backend_is_used_by_parallel_placement_workers(tmp_path,terminal):
    raw=edited_input()
    raw['compilation']['implementation']='zoned_ids'
    raw['placement_search'].update(evaluations=2,terminal_mode=terminal)
    r=compare_studio(raw,tmp_path/terminal)
    assert r['status']=='completed',r['trials']
    for path in (tmp_path/terminal/'search').glob('trial-*/result.json'):
        evidence=json.loads(path.read_text(encoding='utf-8'))
        if evidence['valid']:
            assert evidence['replay_equal'] and evidence['terminal_mode']==terminal
            assert all(d['strategy']=='zoned_ids' for d in evidence['execution']['decision_log'])


@pytest.mark.parametrize('raw',[{'workers':0},{'workers':True},{'evaluations':65},{'expand_storage':1},{'terminal_mode':'bad'},{'typo':1}])
def test_bad_search_options(raw):
    with pytest.raises(ValueError):search_options(raw)


def test_legacy_algorithm_is_not_silently_replaced():
    raw=edited_input();raw['compilation']['implementation']='greedy'
    with pytest.raises(ValueError,match='有序'):prepare(raw)


def test_cancellation_keeps_running_wave_visible(monkeypatch,tmp_path):
    from threading import Event
    from time import sleep, monotonic
    started=Event();finish=Event()
    def blocked(raw,directory,progress,cancelled):
        started.set();assert finish.wait(5)
        assert cancelled.is_set()
        raise InterruptedError('cancelled after current wave')
    monkeypatch.setattr('neutral_atom_app.studio_placement.compare_studio',blocked)
    jobs=StudioPlacementJobs(tmp_path);key=jobs.start(edited_input());assert started.wait(5)
    jobs.cancel(key);assert jobs.get(key)['status']=='cancelling'
    with pytest.raises(ValueError,match='当前批次'):jobs.start(edited_input())
    finish.set();deadline=monotonic()+5
    while jobs.get(key)['status']=='cancelling' and monotonic()<deadline:sleep(.01)
    assert jobs.get(key)['status']=='cancelled'
    assert (tmp_path/key/'failure.json').exists()


def test_same_contract_reuses_completed_search_but_edits_invalidate(monkeypatch,tmp_path):
    from time import sleep,monotonic
    calls=[]
    def complete(raw,*args):
        calls.append(raw)
        return {'status':'completed'}
    monkeypatch.setattr('neutral_atom_app.studio_placement.compare_studio',complete)
    jobs=StudioPlacementJobs(tmp_path);raw=edited_input()
    first=jobs.start(raw);deadline=monotonic()+5
    while jobs.get(first)['status']=='running' and monotonic()<deadline:sleep(.01)
    same=deepcopy(raw);same['placement_search']['enabled']=False
    assert jobs.start(same)==first
    assert len(calls)==1 and jobs.get(first)['cache_hits']==1
    edited=deepcopy(raw);edited['gates'][-1]['gate_type']='T'
    assert jobs.start(edited)!=first
