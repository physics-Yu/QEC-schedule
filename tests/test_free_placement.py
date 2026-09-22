"""Free geometry must reach empty/disabled sites and alter occupied shape."""
from dataclasses import replace
import json
import pytest
from neutral_atom_strategies.placement import (Site,PlacementProblem,CompilerSearchConfig,PhysicalEvaluation,
                                             optimize_free_placement)
from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate
from neutral_atom_app.placement_workbench import build_problem,default_input
from neutral_atom_app.placement import platform_placement_problem
from neutral_atom_app.placement_execution import optimize_free_layout


def test_full_domain_is_not_old_footprint_and_shape_can_win():
    p=PlacementProblem(PhysicalCircuit((PhysicalGate('cz','CZ',('a','b')),)),('a','b'),
        (Site('s0',0,0),Site('s1',10,0),Site('s2',0,10)),(Site('ez',0,-40),),(('a','s0'),('b','s1')))
    r=optimize_free_placement(p,lambda m:PhysicalEvaluation(True,1 if dict(m)['b']=='s2' else 2),
                             contract='controlled test',config=CompilerSearchConfig(max_evaluations=6,allow_vacancies=True))
    assert r.selected.evaluation.total_time_us==1 and r.diagnostics['full_space_evaluated']
    assert r.diagnostics['selected_changed_occupancy'] and r.diagnostics['selected_changed_shape']
    assert r.diagnostics['allowed_site_count']==3


def test_free_api_rejects_accidental_permutation_config():
    value,circuit,platform,mapping,_=build_problem(default_input())
    p=platform_placement_problem(circuit,platform,mapping,include_disabled=True)
    assert len(p.storage)==32 and len(mapping)==8
    assert len(platform_placement_problem(circuit,platform,mapping).storage)==8
    with pytest.raises(ValueError,match='allow_vacancies'):
        optimize_free_placement(p,lambda m:None,contract='test',config=CompilerSearchConfig())


def test_disabled_sites_prepared_before_env_and_common_terminal_restored(tmp_path):
    raw=default_input();raw.update(atom_count=2,source_rows=2,source_columns=2,aod_rows=2,aod_columns=2,
        gates=[dict(id='cz',gate_type='CZ',qubit_ids=['Q000','Q001'])])
    _,circuit,platform,mapping,_=build_problem(raw)
    before=platform.world.traps['S002'].enabled
    result=optimize_free_layout(circuit,platform,mapping,output=tmp_path,
        config=CompilerSearchConfig(max_evaluations=4,allow_vacancies=True,exhaustive_limit=0),
        compiler_options=dict(compile_timeout_s=30))
    assert not before and platform.world.traps['S002'].enabled==before
    assert result.baseline.evaluation.valid
    assert result.diagnostics['evaluated_changed_occupancy']>0
    assert result.diagnostics['evaluated_changed_shape']>0
    from neutral_atom_env import NeutralAtomEnv
    changed=0
    for t in result.trials:
        initial=NeutralAtomEnv.restore((tmp_path/f'trial-{t.index:04d}'/'initial.json').read_text()).state
        assert all(initial.slm_enabled[s] for q,s in t.mapping)
        if any(not platform.world.traps[s].enabled for q,s in t.mapping):changed+=1
        if t.evaluation.valid:
            final=NeutralAtomEnv.restore((tmp_path/f'trial-{t.index:04d}'/'final.json').read_text()).state
            assert {q:h.holder_id for q,h in final.placement.atom_to_holder.items()}==mapping
            assert final.slm_enabled=={s:t.enabled for s,t in platform.world.traps.items()}
    assert changed
