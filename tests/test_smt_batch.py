"""Independent subset oracle, actual execution and explicit budget failures."""
from itertools import combinations
from math import hypot
import pytest

pytest.importorskip('z3')
from neutral_atom_experiments.smt_comparison import demos, make_state, realize, run_one
from neutral_atom_strategies.scheduling.smt_batch import SMTBatchPlanner
from neutral_atom_strategies.motion.patch_array import PatchArrayCompiler
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_strategies.scheduling.m3 import initial_terminal


def independent_batch_masks(spec):
    """Exhaustive fixed-geometry CZ subset oracle, no SMT/compiler helpers."""
    points=spec['positions'];gates=spec['gates'];shifts={}
    for i,g in enumerate(gates):
        a,b=g['qubits']
        for anchor,mobile in ((a,b),(b,a)):
            for dx,dy in ((2,0),(-2,0),(0,2),(0,-2)):
                delta=(points[anchor][0]+dx-points[mobile][0],points[anchor][1]+dy-points[mobile][1])
                shifts.setdefault(delta,[]).append((i,anchor,mobile))
    feasible=set()
    for shift,opts in shifts.items():
        for size in range(1,len(opts)+1):
            for subset in combinations(opts,size):
                ids=[i for i,_,_ in subset];used=[q for _,a,b in subset for q in (a,b)]
                if len(set(ids))!=len(ids) or len(set(used))!=len(used):continue
                moving={b for _,_,b in subset}
                xs={points[q][0] for q in moving};ys={points[q][1] for q in moving}
                if max(xs)-min(xs)>10*(spec['aod_columns']-1) or max(ys)-min(ys)>10*(spec['aod_rows']-1):continue
                captured={q for q,(x,y) in enumerate(points) if x in xs and y in ys}
                if captured!=moving:continue
                end=[(x+shift[0],y+shift[1]) if q in moving else (x,y) for q,(x,y) in enumerate(points)]
                actual={frozenset((a,b)) for a,b in combinations(range(len(points)),2) if hypot(end[a][0]-end[b][0],end[a][1]-end[b][1])<=2+1e-9}
                if actual!={frozenset((a,b)) for _,a,b in subset}:continue
                feasible.add(sum(1<<i for i in ids))
    return feasible


def test_smt_finds_omitted_combination_and_matches_exhaustive_oracle():
    spec=demos()['closure'];state=make_state(spec);snapshot=state.snapshot()
    masks=independent_batch_masks(spec)
    planner=SMTBatchPlanner()
    proposal=next(planner.proposals(state))
    assert len(proposal[0].gate_ids)==max(m.bit_count() for m in masks)==5
    assert state.snapshot()==snapshot
    plan=realize(state,proposal,PatchArrayCompiler())
    assert state.snapshot()==snapshot
    env=NeutralAtomEnv(state);env.submit(plan);env.run()
    assert env.state.metrics()['completed_gate_count']==5


def test_multi_horizon_matches_independent_cover_lower_bound_and_executes():
    spec=demos()['closure'];state=make_state(spec);masks=independent_batch_masks(spec)
    all_bits=(1<<len(spec['gates']))-1
    reachable={0}
    for depth in range(1,len(spec['gates'])+1):
        reachable|={done|batch for done in tuple(reachable) for batch in masks if not done&batch}
        if all_bits in reachable:break
    planner=SMTBatchPlanner(mode='multi')
    proposal=next(planner.proposals(state))
    assert len(proposal)==depth==2
    env=NeutralAtomEnv(state);terminal=initial_terminal(state)
    env.submit(realize(state,proposal,PatchArrayCompiler(),terminal));env.run()
    assert env.state.dag.completed
    validate_target(terminal,env.state)
    assert planner.log[0]['status']=='UNSAT'


def test_mixed_gates_dependencies_and_no_live_mutation():
    state=make_state(demos()['mixed']);initial=state.snapshot()
    proposal=next(SMTBatchPlanner(mode='multi').proposals(state))
    stage={g:i for i,b in enumerate(proposal) for g in b.gate_ids}
    for g,node in state.dag.nodes.items():
        for child in node.successors:assert stage[g]<stage[child]
    for batch in proposal:
        assert len({state.dag.nodes[g].gate.gate_type for g in batch.gate_ids})==1
    assert state.snapshot()==initial


def test_route_rejection_is_reported_and_not_called_physical_unsat(monkeypatch,tmp_path):
    from neutral_atom_experiments import smt_comparison as module
    def fail(*args,**kwargs):raise ValidationError('TEST_ROUTE_BUDGET','Forced route budget exhaustion')
    monkeypatch.setattr(module,'realize',fail)
    spec=demos()['parallel']|{'model_budget':1}
    result=run_one(spec,'smt_single',tmp_path)
    assert result['status']=='failed' and result['replay_equal']
    assert result['metrics']['completed_gate_count']==0
    assert result['rejection_count']==1
    assert result['solver_log'][-1]['reason']=='model_budget'


def test_expired_deadline_is_unknown():
    planner=SMTBatchPlanner()
    assert list(planner.proposals(make_state(demos()['parallel']),deadline=1))==[]
    assert planner.log[-1]['status']=='UNKNOWN'


def test_unsupported_spacing_is_not_silently_reinterpreted():
    spec=demos()['parallel'];spec['positions'][0]=[-5,0]
    with pytest.raises(ValidationError,match='SMT_FAMILY'):make_state(spec)


def test_execution_exact_replay_and_atom_statistics(tmp_path):
    result=run_one(demos()['parallel'],'smt_multi',tmp_path)
    assert result['status']=='completed' and result['replay_equal'] and result['effects_once']
    assert result['cz_batch_sizes']==[4] and result['terminal_verified']
    assert (tmp_path/'atom_statistics.json').exists()
