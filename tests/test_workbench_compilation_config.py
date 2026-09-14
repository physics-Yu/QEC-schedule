"""Scheduling configuration cannot replace a circuit or weaken its protocol."""
from copy import deepcopy
import hashlib
import json

import pytest

from neutral_atom_experiments.surface_qec import experiment_input as qec_input
from neutral_atom_experiments.surface_qec_temporal import experiment_input as temporal_input
from neutral_atom_experiments.surface_qec_temporal_four import experiment_input as four_input
from neutral_atom_app.visualization.workbench import validate_input, build_inputs, compile_input, preview, M4_STRATEGIES, ROW_STRATEGIES, PATCH_STRATEGIES
from neutral_atom_app.visualization.workbench_server import CompileJobs


def physical():
    return {'atom_count':2,'layout':'row','seed':7,'ez_policy':'adaptive','aod_traps':2,
            'gates':[{'id':'h0','gate_type':'H','qubit_ids':['Q000'],'column':0},
                     {'id':'h1','gate_type':'H','qubit_ids':['Q001'],'column':0}]}


@pytest.mark.parametrize('strategy,compiler',[('recommended','greedy'),('baseline','basic')])
def test_independent_configuration_compiles_the_same_real_circuit(strategy,compiler):
    raw=physical()|{'circuit_profile':'physical','compilation':{'strategy':strategy,'ready_limit':7}}
    original=deepcopy(raw)
    result,state=compile_input(raw)
    assert result['status']=='completed',result['diagnostics']
    assert result['input']['compiler']==compiler and result['run_options']['strategy']==compiler
    assert state.metrics()['completed_gate_count']==2
    assert state.quantum_state is None
    assert result['input']['gates']==validate_input(raw)['gates']
    assert raw==original
    pulses=[p for p in result['recording']['operations'] if p['kind']=='raman_rotation']
    assert len(pulses)==2 and {p['start'] for p in pulses}=={0.0}


def test_strategy_change_preserves_quantum_semantics_and_initial_platform():
    raw=qec_input();raw['gates']=[{'id':'edited','gate_type':'H','qubit_ids':['Q003'],'column':0}]
    base=raw|{'circuit_profile':'qec_ghz2','compilation':{'strategy':'baseline'}}
    recommended=raw|{'circuit_profile':'qec_ghz2','compilation':{'strategy':'recommended'}}
    a,ca,pa,ma=build_inputs(base);b,cb,pb,mb=build_inputs(recommended)
    assert a['compiler']=='qec_ghz2' and b['compiler']=='qec_joint'
    assert ca==cb and pa==pb and ma==mb
    assert a['gates']==b['gates'] and a['qec_protocol']==b['qec_protocol']
    assert a['qec_enabled'] is b['qec_enabled'] is True
    assert a['circuit_profile']==b['circuit_profile']=='qec_ghz2'
    assert b['compilation_backend']['available_strategies']==['recommended','baseline']


@pytest.mark.parametrize('profile,factory',[('qec_temporal',temporal_input),('qec_temporal_four',four_input)])
def test_temporal_profile_keeps_its_guard_and_rejects_unimplemented_baseline(profile,factory):
    raw=factory({'kind':'readout','round':2,'patch':0,'check_type':'X','check_index':0})
    raw.update(circuit_profile=profile,compilation={'strategy':'recommended'})
    value=validate_input(raw)
    assert value['compiler']==profile
    assert value['compilation_backend']['available_strategies']==['recommended']
    assert [g['id'] for g in value['gates'] if g.get('readout_flip')]==['round2_X0_0']
    assert value==validate_input(json.loads(json.dumps(value)))
    with pytest.raises(ValueError,match='not supported'):
        validate_input(raw|{'compilation':{'strategy':'baseline'}})
    with pytest.raises(ValueError,match='guards cannot be bypassed'):
        validate_input(raw|{'compilation':{'strategy':'legacy','implementation':'qec_joint'}})


@pytest.mark.parametrize('compiler',sorted(M4_STRATEGIES|ROW_STRATEGIES|PATCH_STRATEGIES))
def test_flat_historical_dispatch_is_preserved_exactly(compiler):
    raw=physical()|{'compiler':compiler,'ready_limit':9}
    value=validate_input(raw)
    assert value['compiler']==compiler and value['ready_limit']==9
    assert value['compilation']['ready_limit']==9
    assert value==validate_input(value)


@pytest.mark.parametrize('compiler',['legacy','resident','returning'])
def test_historical_m3_implementations_remain_importable_but_are_not_main_choices(compiler):
    raw=physical()|{'compiler':compiler,'aod_traps':1}
    value=validate_input(raw)
    assert value['compilation']=={'strategy':'legacy','implementation':compiler}
    assert value['compilation_backend']['legacy'] is True
    assert value['compiler']==compiler


def test_nested_configuration_wins_over_stale_compatibility_mirrors_and_is_detached():
    raw=physical()|{'compiler':'basic','circuit_profile':'physical','ready_limit':99,
                   'compilation':{'strategy':'recommended','ready_limit':4,'compile_timeout_s':30}}
    original=deepcopy(raw)
    value=validate_input(raw)
    assert value['compiler']=='greedy' and value['ready_limit']==4 and value['compile_timeout_s']==30
    assert raw==original
    value['compilation']['ready_limit']=8
    assert raw==original
    assert validate_input(value)['ready_limit']==8


def test_replacing_compilation_does_not_inherit_omitted_old_flat_budgets():
    old=validate_input(physical()|{'compiler':'greedy','ready_limit':128,
                                  'route_expansions':1000000,'compile_timeout_s':86400})
    value=validate_input(old|{'compilation':{'strategy':'baseline','site_limit':2}})
    assert value['compilation']=={'strategy':'baseline','site_limit':2}
    assert value['site_limit']==2 and value['compiler']=='basic'
    assert not {'ready_limit','route_expansions','compile_timeout_s'} & value.keys()


def test_explicit_profile_and_configuration_do_not_require_legacy_qec_flags():
    raw=qec_input();raw.pop('compiler');raw.pop('qec_enabled')
    raw.update(circuit_profile='qec_ghz2',compilation={'strategy':'recommended'})
    value=validate_input(raw)
    assert value['qec_enabled'] is True and value['compiler']=='qec_joint'
    assert value['gates']==validate_input(qec_input())['gates']


@pytest.mark.parametrize('change',[
    {'circuit_profile':'invented'}, {'circuit_profile':None}, {'compilation':[]},
    {'compilation':{'strategy':'unknown'}}, {'compilation':{'strategy':[]}},
    {'compilation':{'strategy':'legacy'}}, {'compilation':{'strategy':'recommended','implementation':'greedy'}},
    {'compilation':{'strategy':'recommended','noise':'ignore'}},
    {'compilation':{'strategy':'recommended','ready_limit':129}},
    {'compilation':{'strategy':'recommended','compile_timeout_s':True}},
    {'circuit_profile':'qec_temporal','compilation':{'strategy':'recommended'}},
])
def test_invalid_or_incompatible_configuration_is_rejected(change):
    with pytest.raises(ValueError):validate_input(physical()|{'compiler':'greedy'}|change)


def test_preview_exposes_resolved_backend_without_compiling_or_changing_gates():
    raw=physical()|{'circuit_profile':'physical','compilation':{'strategy':'baseline'}}
    result=preview(raw)
    assert result['input']['compiler']=='basic'
    assert result['input']['compilation_backend']['compiler']=='basic'
    assert result['recording']['duration']==0
    assert result['input']['gates']==validate_input(raw)['gates']


def test_saved_execution_uses_actual_strategy_over_stale_nested_editor_choice(tmp_path):
    raw=qec_input();raw['gates']=[]
    value=validate_input(raw|{'circuit_profile':'qec_ghz2','compilation':{'strategy':'recommended'}})
    recording=preview(value)['recording']
    source=tmp_path/'saved';source.mkdir()
    documents={'input.json':value,'recording.json':recording,
               'strategy.json':{'actual_strategy':'qec_persistent'},
               'result.json':{'status':'completed','actual_strategy':'qec_persistent',
                              'metrics':{'simulation_time_us':0,'completed_gate_count':0}}}
    for name,data in documents.items():(source/name).write_text(json.dumps(data),encoding='utf-8')
    before={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
    jobs=CompileJobs(tmp_path/'unused')
    try:
        result=jobs.get(jobs.restore(source),True)
        assert result['input']['compiler']=='qec_persistent'
        assert result['input']['compilation']=={'strategy':'legacy','implementation':'qec_persistent'} | {
            k:v for k,v in value['compilation'].items() if k not in {'strategy','implementation'}}
        assert result['provenance']['actual_strategy']=='qec_persistent'
        assert result['recording']==recording and jobs.active is None
        assert before=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir()}
    finally:jobs.close()
