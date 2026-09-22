"""Independent expectations for placement legality, dependencies and selection."""
from dataclasses import asdict, replace
from itertools import permutations
import math

import pytest

from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate
from neutral_atom_strategies.placement import (Site, PlacementProblem, SearchConfig,
    PlacementCostModel, PhysicalEvaluation, circuit_layers, optimize_initial, select_physically)
from neutral_atom_app.placement import compile_layout


def problem():
    return PlacementProblem(
        PhysicalCircuit((PhysicalGate('g0', 'CZ', ('a', 'b')),)),
        ('a', 'b', 'idle'),
        (Site('s0', 0, 0), Site('s1', 10, 0), Site('s2', 0, 10), Site('s3', 10, 10)),
        (Site('ez', 0, 40),), (('a', 's0'), ('b', 's3'), ('idle', 's1')), aod_rows=2, aod_columns=2)


def test_proxy_exact_search_against_independent_exhaustion():
    p = problem(); config = SearchConfig(exact_limit=100, top_k=2)
    result = optimize_initial(p, config)
    # Independently score this one gate: col/row-compatible capture possible
    # iff the Cartesian closure of a,b does not contain idle. Otherwise 2 loads.
    h = p.hardware
    def travel(s):
        def t(d):
            return max(1.5*d/h.speed_um_per_us, math.sqrt(6*d/h.max_acceleration_um_per_us2),
                       (12*d/h.max_jerk_um_per_us3)**(1/3))
        return t(s.x_um) + t(40-s.y_um)
    scores = []
    for a, b, idle in permutations(p.storage, 3):
        conflict = idle.x_um in {a.x_um, b.x_um} and idle.y_um in {a.y_um, b.y_um}
        batches = 2 if conflict else 1
        movement = 2*(max(travel(a), travel(b)) if a.y_um == b.y_um else travel(a)+travel(b))
        scores.append(movement + batches*(h.load_duration_us+h.offload_duration_us))
    assert result.selected.cost.score_us == pytest.approx(min(scores))
    assert result.diagnostics['exact_proxy_optimum']
    assert result.selected.cost.score_us < result.baseline.cost.score_us
    assert result.baseline in result.candidates


def test_dependencies_include_1q_measurement_conditions_and_explicit_edges():
    circuit = PhysicalCircuit((PhysicalGate('h', 'H', ('a',)),
        PhysicalGate('m', 'MEASURE', ('b',)),
        PhysicalGate('x', 'X', ('c',), condition=(('m', 1),)),
        PhysicalGate('cz', 'CZ', ('a', 'c'), depends_on=('h',)),
        PhysicalGate('r', 'RESET', ('b',), depends_on=('cz',))))
    assert [[g.id for g in layer] for layer in circuit_layers(circuit)] == [['h','m'], ['x'], ['cz'], ['r']]


def test_seed_lock_injectivity_budget_and_input_unchanged():
    p = replace(problem(), locked=(('idle', 's1'),))
    before = asdict(p)
    config = SearchConfig(iterations=150, seed=30)
    a, b = optimize_initial(p, config), optimize_initial(p, config)
    assert a.selected == b.selected and a.candidates == b.candidates
    assert asdict(p) == before
    assert a.diagnostics['iterations'] == 150
    for c in a.candidates:
        assert dict(c.mapping)['idle'] == 's1'
        assert len(set(dict(c.mapping).values())) == len(p.qubits)
    assert a.selected.cost.score_us <= a.baseline.cost.score_us


def test_no_cz_keeps_mapping_including_idle_qubits():
    p = replace(problem(), circuit=PhysicalCircuit((PhysicalGate('h','H',('a',)),)))
    result = optimize_initial(p)
    assert result.selected.mapping == p.initial_mapping
    assert result.selected.cost.score_us == 0
    assert result.diagnostics['iterations'] == 0
    assert result.diagnostics['unscored_operations'] == ['H']


def test_capacity_and_irregular_grid_do_not_claim_parking_template():
    p = replace(problem(), aod_rows=1, aod_columns=1)
    detail = PlacementCostModel(p, SearchConfig()).estimate(p.initial_mapping).layer_details[0]
    assert not detail['parking_pattern_applicable']
    assert detail['axis'] == 'singleton_proxy' and detail['capture_batches'] == 2


def test_exported_details_cannot_poison_pattern_cache():
    p = problem(); model = PlacementCostModel(p,SearchConfig())
    first = model.estimate(p.initial_mapping)
    before = first.score_us
    first.layer_details[0]['compatibility']['row']['batches'] = 999
    second = model.estimate(p.initial_mapping)
    assert second.score_us == before
    assert second.layer_details[0]['compatibility']['row']['batches'] != 999


def test_wildcard_grouping_and_axis_choice_are_reported():
    # First three rows mutually conflict; last two wildcard rows can join.
    # Only two columns have targets, and those columns conflict with each other.
    mask = [[2,1],[1,2],[2,2],[2,0],[0,2]]
    sites = tuple(Site(f's{r}{c}',10*c,10*r) for r in range(5) for c in range(2))
    occupied = [(f'q{r}{c}',f's{r}{c}') for r in range(5) for c in range(2) if mask[r][c]]
    circuit = PhysicalCircuit((PhysicalGate('g0','CZ',('q00','q11')),
                               PhysicalGate('g1','CZ',('q20','q21')),
                               PhysicalGate('g2','CZ',('q30','q41'))))
    p = PlacementProblem(circuit,tuple(q for q,s in occupied),sites,(Site('ez',0,50),),tuple(occupied),
                         aod_rows=5,aod_columns=2)
    cost = PlacementCostModel(p,SearchConfig()).estimate(p.initial_mapping)
    d = cost.layer_details[0]
    assert d['compatibility']['row']['batches'] == 3
    assert d['compatibility']['column']['batches'] == 2
    assert d['axis'] == 'column'


def test_coherent_translation_escapes_single_atom_pair_split():
    sites = tuple(Site(f's{r}{c}',10*c,10*r) for r in range(10) for c in range(10))
    p = PlacementProblem(PhysicalCircuit((PhysicalGate('g','CZ',('a','b')),)),('a','b'),
                         sites,(Site('ez',0,120),),(('a','s00'),('b','s01')),
                         aod_rows=2,aod_columns=2)
    result = optimize_initial(p,SearchConfig(iterations=1))
    assert dict(result.selected.mapping) == {'a':'s90','b':'s91'}
    assert result.selected.cost.score_us < result.baseline.cost.score_us


def test_unknown_gate_qubit_and_unsupported_backend_fail_closed():
    from neutral_atom_env.domain.operations import HardwareConfig
    with pytest.raises(ValueError,match='unknown qubit'):
        replace(problem(),qubits=('other','b','idle'))
    # Backend restriction belongs to this proxy, not to the mapping domain.
    p = replace(problem(),hardware=HardwareConfig())
    with pytest.raises(ValueError,match='row_column_orthogonal'):
        PlacementCostModel(p,SearchConfig())


def test_physical_reranking_can_reject_proxy_winner_and_keep_baseline():
    result = optimize_initial(problem(), SearchConfig(exact_limit=100))
    seen = []
    def evaluate(c):
        seen.append(c.mapping)
        if c.mapping == result.baseline.mapping:
            return PhysicalEvaluation(True, 100)
        raise RuntimeError('bounded route failure')
    winner, records = select_physically(result, evaluate)
    assert winner == result.baseline
    assert len(seen) == len(result.candidates)
    assert any(not e.valid and 'bounded route failure' in e.failure for _,e in records)
    winner, records = select_physically(result, lambda c: PhysicalEvaluation(False, failure='no route'))
    assert winner is None


@pytest.mark.parametrize('change', [
    {'initial_mapping': (('a','s0'),('b','s0'),('idle','s1'))},
    {'locked': (('a','s3'),)}, {'qubits': ('a','a','idle')},
    {'aod_rows': True}, {'storage': (Site('one',0,0),)},
    {'interaction_sites': ()},
])
def test_invalid_problem_rejected(change):
    with pytest.raises(ValueError):
        replace(problem(), **change)


@pytest.mark.parametrize('change', [{'iterations':-1}, {'decay':float('nan')}, {'top_k':0},
                                  {'exact_limit':100001}, {'objective':'magic'}, {'seed':True}])
def test_invalid_budget_rejected(change):
    with pytest.raises(ValueError): SearchConfig(**change)


def test_custom_json_roundtrip_preserves_circuit_and_dependencies():
    p = problem()
    raw = dict(schema='initial-placement/1', qubits=list(p.qubits),
        gates=[asdict(g) for g in p.circuit.gates], storage=[asdict(s) for s in p.storage],
        interaction_sites=[asdict(s) for s in p.interaction_sites], initial_mapping=dict(p.initial_mapping),
        aod=dict(rows=2,columns=2), search=dict(iterations=20,seed=9))
    output = compile_layout(raw)
    assert output['status'] == 'estimated'
    assert output['circuit']['gates'] == tuple(raw['gates'])
    assert output['input'] == raw
    assert output['diagnostics']['physical_validation'] == 'not_run'
    with pytest.raises(ValueError, match='Unknown placement fields'):
        compile_layout(dict(raw, typo=1))


def test_existing_platform_adapter_compiles_mixed_custom_circuit_and_replays():
    from neutral_atom_app.placement import compile_platform_layout
    from neutral_atom_app.visualization.workbench import build_inputs
    from neutral_atom_env import NeutralAtomEnv
    from neutral_atom_strategies.api import make_strategy
    from neutral_atom_env.program.task_validation import validate_target
    from neutral_atom_strategies.scheduling.m3 import initial_terminal
    raw = dict(atom_count=2,layout='row',seed=1,ez_policy='adaptive',
        aod_backend='row_column_orthogonal',aod_rows=1,aod_columns=2,
        compilation=dict(strategy='legacy',implementation='ordered_greedy',compile_timeout_s=30),
        gates=[dict(id='prepare',gate_type='H',qubit_ids=['Q000'],column=0),
               dict(id='entangle',gate_type='CZ',qubit_ids=['Q000','Q001'],column=1),
               dict(id='finish',gate_type='T',qubit_ids=['Q001'],column=2)])
    _,circuit,platform,mapping = build_inputs(raw)
    result = compile_platform_layout(circuit,platform,mapping,config=SearchConfig(exact_limit=10))
    env = NeutralAtomEnv.create(circuit,platform,dict(result.selected.mapping))
    initial = env.snapshot(); terminal = initial_terminal(env.state)
    plans = []; submit = env.submit
    def capture(plan):
        submit(plan); plans.append(plan)
    env.submit = capture
    execution = make_strategy('ordered_greedy',compile_timeout_s=30).run(env)
    assert execution.status == 'completed', execution.diagnostics
    validate_target(terminal,env.state)
    replay = NeutralAtomEnv.restore(initial)
    for plan in plans:
        replay.submit(plan); replay.run()
    assert replay.snapshot() == env.snapshot()
    assert env.state.dag.circuit == circuit
    assert env.state.metrics()['completed_gate_count'] == 3
