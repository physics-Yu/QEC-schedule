"""Independent policy expectations on real physical programs and DAGs."""
import pytest

from neutral_atom_env.domain.models import HolderType
from neutral_atom_env.domain.operations import TaskTarget
from neutral_atom_env.motion.task_validation import validate_target
from neutral_atom_env.simulation.m3 import initial_terminal
from neutral_atom_env.simulation.m4 import run_m4
from neutral_atom_env.simulation.m4_policies import critical_paths
from neutral_atom_env.simulation.pipeline import initialize
from neutral_atom_env.visualization.workbench import build_inputs


def make(gates, n=4):
    raw = {'compiler':'greedy','atom_count':n,'layout':'row','seed':7,
           'gates':[{'id':f'g{i}','gate_type':kind,'qubit_ids':[f'Q{q:03d}' for q in qs],
                     'parameters':[],'column':i} for i,(kind,qs) in enumerate(gates)]}
    _,c,p,h = build_inputs(raw)
    return initialize(c,p,h,seed=7)


def test_critical_path_uses_successors_before_local_gate_id_and_ready_budget():
    # g0 is independent. g1 blocks another CZ and then H; it must be searched
    # first even with only one READY gate allowed by the search budget.
    state=make([('CZ',(0,1)),('CZ',(2,3)),('CZ',(2,3)),('H',(2,))])
    paths=critical_paths(state)
    assert paths['g1']==pytest.approx(2*state.hardware.pulse_duration_us+1)
    assert paths['g0']==pytest.approx(state.hardware.pulse_duration_us)
    result=run_m4(state,strategy='critical_path',max_decisions=1,ready_limit=1,site_limit=1)
    assert result.decision_log[0]['selected'].startswith('g1/')
    assert state.dag.nodes['g1'].status.value=='completed'
    assert state.dag.nodes['g0'].status.value=='ready'


def test_critical_path_can_choose_ready_single_qubit_chain_before_cz():
    state=make([('CZ',(0,1)),('H',(2,)),('X',(2,)),('Y',(2,)),('Z',(2,))])
    result=run_m4(state,strategy='critical_path',max_decisions=1,ready_limit=1,site_limit=1)
    assert result.decision_log[0]['selected'].startswith('g1/')
    assert state.dag.nodes['g0'].status.value=='ready'
    assert state.dag.nodes['g1'].status.value=='completed'


@pytest.mark.parametrize('strategy',['basic','greedy','critical_path','lookahead'])
def test_all_policies_preserve_gate_effects_and_same_explicit_terminal(strategy):
    state=make([('H',(0,)),('H',(1,)),('CZ',(0,1)),('CZ',(0,1))],n=2)
    terminal=initial_terminal(state)
    result=run_m4(state,strategy=strategy,site_limit=1,beam_width=1,rollout_budget=4)
    assert result.status=='completed',result.diagnostics
    assert state.metrics()['completed_gate_count']==4
    validate_target(terminal,state)
    assert all(entry['strategy']==strategy for entry in result.decision_log)
    assert all(entry['compile_wall_time_s']>=0 for entry in result.decision_log)


def test_basic_returns_after_each_gate_and_greedy_retains_real_supports():
    raw=[('CZ',(0,1)),('CZ',(0,1))]
    basic=make(raw,n=2); terminal=initial_terminal(basic)
    result=run_m4(basic,strategy='basic',max_decisions=1,site_limit=1,beam_width=1)
    assert result.status=='stalled' and result.decision_log[0]['selected'].endswith('/return')
    validate_target(terminal,basic)
    greedy=make(raw,n=2)
    result=run_m4(greedy,max_decisions=1,site_limit=1)
    assert any(h.holder_type==HolderType.MOBILE for h in greedy.placement.atom_to_holder.values())
    assert result.decision_log[0]['selected_features']['reuse_count']==2


def test_lookahead_evaluates_different_terminal_states_and_includes_cleanup():
    state=make([('CZ',(0,1))],n=2)
    result=run_m4(state,strategy='lookahead',max_decisions=1,site_limit=1,beam_width=1,rollout_budget=4)
    report=result.decision_log[0]['policy_search']
    keep,returned=report['evaluations']
    assert keep['end_holders']!=returned['end_holders']
    assert keep['terminal_cleanup_us']>0 and returned['terminal_cleanup_us']==0
    assert keep['projected_total_us']==pytest.approx(returned['projected_total_us'])
    assert keep['projected_total_us']==pytest.approx(keep['horizon_elapsed_us']+keep['terminal_cleanup_us'])
    assert keep['remaining_lower_bound_us']==returned['remaining_lower_bound_us']==0


def test_free_terminal_is_honored_in_branch_cost_and_final_execution():
    state=make([('CZ',(0,1))],n=2)
    result=run_m4(state,strategy='lookahead',terminal=TaskTarget(),site_limit=1,beam_width=1,rollout_budget=4)
    assert result.status=='completed' and result.decisions==1
    first=result.decision_log[0]['policy_search']['evaluations'][0]
    assert first['terminal_cleanup_us']==0
    assert state.time_us==pytest.approx(first['projected_total_us'])


def test_node_budget_truncates_search_without_silently_skipping_gate():
    state=make([('CZ',(0,1)),('CZ',(0,1))],n=2)
    result=run_m4(state,strategy='lookahead',max_decisions=1,site_limit=1,beam_width=2,rollout_budget=1)
    assert result.status=='stalled'
    assert result.diagnostics[0]['code']=='DECISION_BUDGET_EXHAUSTED'
    report=result.decision_log[0]['policy_search']
    assert report['nodes_used']==1 and report['budget_exhausted']
    assert report['omitted_roots']>0
    assert report['evaluations'][0]['actual_depth']==1
    assert report['evaluations'][0]['unexpanded_budget_horizons']==1
    assert state.metrics()['completed_gate_count']==1


def test_exact_node_limit_with_complete_unique_branch_is_not_search_truncation():
    state=make([('H',(0,))],n=1)
    result=run_m4(state,strategy='lookahead',beam_width=1,rollout_budget=1)
    assert result.status=='completed'
    report=result.decision_log[0]['policy_search']
    assert report['nodes_used']==1 and report['limit_reached']
    assert not report['budget_exhausted']
    assert report['omitted_roots']==report['omitted_children']==report['unexpanded_horizons']==0
    assert report['evaluations'][0]['actual_depth']==1
    assert report['evaluations'][0]['skipped_budget_children']==0


@pytest.mark.parametrize('strategy',['basic','lookahead'])
def test_all_policy_branches_failed_preserves_audit_evidence_without_live_mutation(monkeypatch,strategy):
    from neutral_atom_env.domain.errors import ValidationError
    from neutral_atom_env.simulation import m4, m4_policies
    state=make([('H',(0,))],n=1); before=state.snapshot()
    def reject(*args,**kwargs):
        raise ValidationError('INJECTED_BRANCH_AUDIT', 'Independent audit rejected this speculative branch')
    if strategy=='basic':
        monkeypatch.setattr(m4_policies,'return_candidate',reject)
    else:
        monkeypatch.setattr(m4,'fill_raman',reject)
    result=run_m4(state,strategy=strategy,beam_width=1,rollout_budget=1)
    assert result.status=='stalled' and result.decisions==0 and not result.decision_log
    assert result.diagnostics[0]['code']==('BASIC_RETURN_EXHAUSTED' if strategy=='basic' else 'LOOKAHEAD_CANDIDATES_EXHAUSTED')
    assert result.diagnostics[0]['phase']=='policy_selection'
    report=result.diagnostics[0]['policy_search']
    assert report['node_budget']==1
    assert report['nodes_used']==(0 if strategy=='basic' else 1)
    assert result.candidate_rejections
    assert result.candidate_rejections[-1]['violation']['code']=='INJECTED_BRANCH_AUDIT'
    assert result.candidate_rejections[-1]['decision']==0
    assert state.snapshot()==before


def test_future_candidate_failure_keeps_original_reason_and_rollout_counts(monkeypatch):
    from neutral_atom_env.domain.errors import ValidationError
    from neutral_atom_env.motion.greedy import GreedyCompiler
    original=GreedyCompiler.alternatives
    def fail_future(self,gate_id,state,**kwargs):
        if state.version>0:
            raise ValidationError('INJECTED_FUTURE_SEARCH', 'Future candidate search failed')
        return original(self,gate_id,state,**kwargs)
    monkeypatch.setattr(GreedyCompiler,'alternatives',fail_future)
    state=make([('CZ',(0,1)),('CZ',(0,1))],n=2); before=state.snapshot()
    result=run_m4(state,strategy='lookahead',site_limit=1,beam_width=1,rollout_budget=4)
    assert result.status=='stalled' and result.decisions==0
    assert result.diagnostics[0]['policy_search']['nodes_used']==2
    assert {r['violation']['code'] for r in result.candidate_rejections}=={'INJECTED_FUTURE_SEARCH'}
    assert state.snapshot()==before


@pytest.mark.parametrize('kwargs',[{'strategy':'unknown'},{'lookahead_depth':0},
    {'lookahead_depth':9},{'beam_width':True},{'rollout_budget':0},{'rollout_budget':4097}])
def test_invalid_policy_parameters_are_rejected(kwargs):
    with pytest.raises(ValueError):run_m4(make([]),**kwargs)
