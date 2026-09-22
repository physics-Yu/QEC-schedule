"""Search contract tests plus real controller/replay acceptance on a tiny input."""
from dataclasses import replace
from itertools import permutations
import json

import pytest

from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate
from neutral_atom_strategies.placement import (PlacementProblem,Site,PhysicalEvaluation,
    CompilerSearchConfig,optimize_with_compiler)


def problem(n=4):
    return PlacementProblem(PhysicalCircuit((PhysicalGate('cz','CZ',('q0','q1')),)),
        tuple(f'q{i}' for i in range(n)),tuple(Site(f's{i}',i*10,0) for i in range(n)),
        (Site('ez',0,50),),tuple((f'q{i}',f's{i}') for i in range(n)))


def test_exhaustive_callback_can_prefer_worse_geometric_score():
    p = problem(3)
    # Controlled objective tests selection, not a claim about physical duration.
    # Best execution puts q0 and q1 far apart, opposing the ranking proxy.
    def oracle(m):
        v = dict(m)
        return PhysicalEvaluation(True,100-abs(int(v['q0'][1:])-int(v['q1'][1:]))*10)
    r = optimize_with_compiler(p,oracle,contract='test objective',
                              config=CompilerSearchConfig(max_evaluations=10))
    expected = min(oracle(tuple(zip(p.qubits,s))).total_time_us for s in permutations(['s0','s1','s2']))
    assert r.selected.evaluation.total_time_us == expected == 80
    assert r.selected.proposal_score > r.baseline.proposal_score
    assert r.status == 'improved' and r.diagnostics['full_space_evaluated']
    assert len(r.trials) == 6


def test_input_is_baseline_and_tie_failures_cannot_replace_it():
    p = problem(3); p = replace(p,initial_mapping=tuple(zip(p.qubits,('s2','s1','s0'))))
    seen=[]
    def oracle(m):
        seen.append(m)
        if len(seen)==2: raise RuntimeError('route budget')
        return PhysicalEvaluation(True,12)
    r = optimize_with_compiler(p,oracle,contract='test objective')
    assert r.selected is r.baseline and r.improvement_percent == 0
    assert seen[0] == p.initial_mapping and len(set(seen))==len(seen)
    assert 'route budget' in r.trials[1].evaluation.failure
    assert r.diagnostics['failures']==1


def test_stochastic_search_is_seeded_bounded_and_keeps_locks():
    p = replace(problem(8),locked=(('q0','s0'),))
    config=CompilerSearchConfig(max_evaluations=12,proposal_pool=12,exhaustive_limit=0,seed=8)
    def oracle(m):
        return PhysicalEvaluation(True,sum((i-int(s[1:]))**2 for i,(q,s) in enumerate(m))+1)
    a = optimize_with_compiler(p,oracle,contract='test',config=config)
    b = optimize_with_compiler(p,oracle,contract='test',config=config)
    assert [t.mapping for t in a.trials] == [t.mapping for t in b.trials]
    assert len(a.trials) == 12 and a.selected is a.baseline
    assert all(dict(t.mapping)['q0']=='s0' for t in a.trials)
    assert any(t.origin.startswith('explore:') for t in a.trials)
    assert not a.diagnostics['full_space_evaluated']


def test_small_space_larger_than_budget_uses_feedback_search():
    r=optimize_with_compiler(problem(3),lambda m:PhysicalEvaluation(True,10),contract='test',
        config=CompilerSearchConfig(max_evaluations=3,exhaustive_limit=64))
    assert len(r.trials)==3 and not r.diagnostics['full_space_evaluated']
    assert all(t.origin!='enumeration' for t in r.trials)


def test_vacancies_opt_in_and_locked_problem_exhausts():
    p = problem(2); p = replace(p,storage=p.storage+(Site('extra',25,7),))
    def oracle(m):return PhysicalEvaluation(True,1 if 'extra' in dict(m).values() else 2)
    a = optimize_with_compiler(p,oracle,contract='test')
    b = optimize_with_compiler(p,oracle,contract='test',config=CompilerSearchConfig(allow_vacancies=True))
    assert len(a.trials)==2 and a.status=='baseline_retained'
    assert len(b.trials)==6 and b.status=='improved'
    locked = replace(p,locked=p.initial_mapping)
    c = optimize_with_compiler(locked,oracle,contract='test')
    assert len(c.trials)==1 and c.diagnostics['full_space_evaluated']


def test_no_valid_and_invalid_baseline_are_distinct():
    p=problem(2)
    r=optimize_with_compiler(p,lambda m:PhysicalEvaluation(False,failure='no route'),contract='test')
    assert r.selected is None and r.status=='no_valid_execution' and r.improvement_percent is None
    r=optimize_with_compiler(p,lambda m:PhysicalEvaluation(False,failure='timeout') if m==p.initial_mapping
                             else PhysicalEvaluation(True,10),contract='test')
    assert r.status=='valid_without_baseline' and r.improvement_percent is None


@pytest.mark.parametrize('kwargs',[{'max_evaluations':0},{'max_evaluations':True},
    {'proposal_pool':0},{'exhaustive_limit':-1},{'allow_vacancies':1},{'explore_every':0}])
def test_invalid_budget(kwargs):
    with pytest.raises(ValueError):CompilerSearchConfig(**kwargs)


def test_real_ordered_adapter_keeps_absolute_terminal_and_replays(tmp_path):
    from neutral_atom_app.placement_execution import optimize_compiled_layout
    from neutral_atom_app.visualization.workbench import build_inputs
    from neutral_atom_env import NeutralAtomEnv
    raw=dict(atom_count=2,layout='row',seed=1,ez_policy='adaptive',
        aod_backend='row_column_orthogonal',aod_rows=1,aod_columns=2,
        compilation=dict(strategy='legacy',implementation='ordered_greedy',compile_timeout_s=30),
        gates=[dict(id='h',gate_type='H',qubit_ids=['Q000'],column=0),
               dict(id='cz',gate_type='CZ',qubit_ids=['Q000','Q001'],column=1),
               dict(id='t',gate_type='T',qubit_ids=['Q001'],column=2)])
    _,circuit,platform,mapping=build_inputs(raw)
    result=optimize_compiled_layout(circuit,platform,mapping,output=tmp_path,
        compiler_options=dict(compile_timeout_s=30),config=CompilerSearchConfig(max_evaluations=2))
    assert len(result.trials)==2
    assert all(t.evaluation.valid for t in result.trials)
    for t in result.trials:
        report=json.loads((tmp_path/f'trial-{t.index:04d}'/'result.json').read_text())
        assert report['replay_equal'] and report['effects_once'] and report['terminal_verified']
        final=NeutralAtomEnv.restore((tmp_path/f'trial-{t.index:04d}'/'final.json').read_text()).state
        assert {q:h.holder_id for q,h in final.placement.atom_to_holder.items()} == mapping
    assert result.selected.evaluation.total_time_us <= result.baseline.evaluation.total_time_us


def test_protocol_failure_cannot_win(tmp_path):
    from neutral_atom_app.placement_execution import optimize_compiled_layout
    from neutral_atom_app.visualization.workbench import build_inputs
    _,circuit,platform,mapping=build_inputs(dict(atom_count=1,layout='row',gates=[],
        aod_backend='row_column_orthogonal',aod_rows=1,aod_columns=1))
    r=optimize_compiled_layout(circuit,platform,mapping,verify_protocol=lambda s:False,output=tmp_path)
    assert r.status=='no_valid_execution' and 'Protocol verification' in r.baseline.evaluation.failure


def test_measurement_feedback_and_reset_are_kept_in_objective(tmp_path):
    from neutral_atom_app.placement_execution import optimize_compiled_layout
    from neutral_atom_app.visualization.workbench import build_inputs
    from neutral_atom_env.quantum.stabilizer import StabilizerState
    qs=('Q000','Q001')
    gates=[dict(id='h0',gate_type='H',qubit_ids=[qs[0]],column=0),
           dict(id='h1',gate_type='H',qubit_ids=[qs[1]],column=0),
           dict(id='cz',gate_type='CZ',qubit_ids=list(qs),column=1),
           dict(id='h2',gate_type='H',qubit_ids=[qs[1]],column=2),
           dict(id='m',gate_type='MEASURE',qubit_ids=[qs[0]],column=3),
           dict(id='x',gate_type='X',qubit_ids=[qs[1]],condition=[['m',1]],column=4),
           dict(id='r',gate_type='RESET',qubit_ids=[qs[0]],column=4)]
    _,_,platform,mapping=build_inputs(dict(atom_count=2,layout='row',seed=3,
        ez_policy='adaptive',aod_backend='row_column_orthogonal',aod_rows=1,aod_columns=2,
        compilation=dict(strategy='legacy',implementation='ordered_greedy'),gates=[]))
    # Workbench UI gates readout behind its QEC demo profile; the headless
    # PhysicalCircuit API itself must not acquire that UI-only restriction.
    circuit=PhysicalCircuit(tuple(PhysicalGate(**{k:v for k,v in g.items() if k!='column'}) for g in gates))
    def verify(state):
        return all(state.quantum_state.expectation({q:'Z'})==1 for q in qs)
    r=optimize_compiled_layout(circuit,platform,mapping,quantum_state=StabilizerState.zero(qs),
        seed=3,verify_protocol=verify,compiler_options=dict(compile_timeout_s=30),output=tmp_path,
        config=CompilerSearchConfig(max_evaluations=2))
    assert all(t.evaluation.valid for t in r.trials),[t.evaluation.failure for t in r.trials]
    assert r.selected.evaluation.total_time_us <= r.baseline.evaluation.total_time_us
