from dataclasses import replace
from types import SimpleNamespace
from time import perf_counter
import pytest
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import ZoneType
from neutral_atom_env.domain.operations import OperationType as K
from neutral_atom_experiments.qec_ordered_comparison import demos,make_state
from neutral_atom_strategies.scheduling.qec import readout_service
from neutral_atom_strategies.scheduling.patch_greedy import patch_assignment
from neutral_atom_strategies.scheduling.ordered_greedy import new_builder,finish
from neutral_atom_strategies.motion.ordered_transfer import OrderedTransfer
from neutral_atom_strategies.scheduling.readout_placement import ReadoutPlacementPolicy


@pytest.fixture(scope='module')
def staged():
    spec=demos()['qec_ghz2']
    atoms=('Q019','Q020','Q027','Q028')
    spec['gates']=[dict(id=f'm{i}',gate_type='MEASURE',qubit_ids=[q]) for i,q in enumerate(atoms)]+[
        dict(id=f'r{i}',gate_type='RESET',qubit_ids=[q]) for i,q in enumerate(atoms)]
    env=NeutralAtomEnv(make_state(spec));p=new_builder(env.state)
    OrderedTransfer().transfer_group(p,patch_assignment(env.state))
    env.submit(finish(p));env.run()
    return env.snapshot()


def inputs(staged):
    state=NeutralAtomEnv.restore(staged).state
    return state,tuple(state.dag.nodes[f'm{i}'].gate for i in range(4))


def test_candidates_include_aod_boundary_and_nonrigid_shapes(staged):
    state,gates=inputs(staged);atoms=tuple(g.qubit_ids[0] for g in gates)
    candidates=ReadoutPlacementPolicy().candidates(state,atoms)
    assert {c.support for c in candidates}=={'aod','slm'}
    zone=next(z.bounds for z in state.world.zones if z.zone_type==ZoneType.MEASUREMENT)
    assert any(max(y for q,(x,y) in c.positions)==zone.upper.y_um for c in candidates if c.support=='aod')
    assert any(max(y for q,(x,y) in c.positions)-min(y for q,(x,y) in c.positions)<20 for c in candidates if c.support=='aod')
    for c in candidates:
        for _,(x,y) in c.positions:
            assert zone.lower.x_um<=x<=zone.upper.x_um and zone.lower.y_um<=y<=zone.upper.y_um


@pytest.mark.parametrize('mode,loads',[('adaptive',1),('slm_only',2)])
def test_support_selection_real_execution_and_replay(staged,mode,loads):
    state,gates=inputs(staged);policy=ReadoutPlacementPolicy(mode=mode)
    plan,resets=readout_service(state,OrderedTransfer(),gates,placement_policy=policy)
    assert state.snapshot()==staged and resets==4
    assert sum(o.operation_type==K.AOD_LOAD for o in plan.operations)==loads
    assert sum(o.operation_type==K.AOD_OFFLOAD for o in plan.operations)==loads
    assert policy.log[-1]['selected']['support']==('aod' if mode=='adaptive' else 'slm')
    run=NeutralAtomEnv.restore(staged);run.submit(plan);run.run()
    assert run.state.dag.completed and run.state.placement==state.placement
    replay=NeutralAtomEnv.restore(staged);replay.submit(plan);replay.run()
    assert replay.snapshot()==run.snapshot()


def test_aod_readout_reduces_service_time_with_same_results(staged):
    state,gates=inputs(staged)
    plans=[readout_service(state,OrderedTransfer(),gates,placement_policy=ReadoutPlacementPolicy(mode=m))[0]
           for m in ('aod_only','slm_only')]
    states=[]
    for p in plans:
        e=NeutralAtomEnv.restore(staged);e.submit(p);e.run();states.append(e.state)
    assert plans[0].estimated_duration_us<plans[1].estimated_duration_us
    assert states[0].measurement_results==states[1].measurement_results
    assert states[0].quantum_state==states[1].quantum_state
    assert states[0].placement==states[1].placement


def test_failed_aod_candidates_fall_back_to_slm_without_mutating_origin(staged,monkeypatch):
    state,gates=inputs(staged);policy=ReadoutPlacementPolicy(candidate_budget=4)
    realize=policy.realize
    def reject_aod(state,compiler,gates,resets,target):
        if target.support=='aod':raise ValidationError('TEST_OBSTACLE','Injected blocked AOD endpoint')
        return realize(state,compiler,gates,resets,target)
    monkeypatch.setattr(policy,'realize',reject_aod)
    readout_service(state,OrderedTransfer(),gates,placement_policy=policy)
    assert state.snapshot()==staged
    assert policy.log[-1]['selected']['support']=='slm'
    assert any(c.get('code')=='TEST_OBSTACLE' for c in policy.log[-1]['candidates'])


def test_actual_cost_feedback_can_reject_first_legal_target(staged,monkeypatch):
    state,gates=inputs(staged);policy=ReadoutPlacementPolicy(top_k=2)
    count=[]
    def realize(*args):
        count.append(1)
        return SimpleNamespace(estimated_duration_us=100 if len(count)==1 else 50,estimated_distance_um=0)
    monkeypatch.setattr(policy,'realize',realize)
    plan,_=readout_service(state,OrderedTransfer(),gates,placement_policy=policy)
    assert plan.estimated_duration_us==50 and len(count)==2
    assert policy.log[-1]['selected']['actual_us']==50


def test_exhaustion_and_deadline_leave_state_unchanged(staged,monkeypatch):
    state,gates=inputs(staged)
    with pytest.raises(TimeoutError):
        readout_service(state,OrderedTransfer(deadline=perf_counter()-1),gates,placement_policy=ReadoutPlacementPolicy())
    assert state.snapshot()==staged
    policy=ReadoutPlacementPolicy()
    monkeypatch.setattr(policy,'candidates',lambda state,atoms:[])
    with pytest.raises(ValidationError,match='READOUT_TARGETS_EXHAUSTED'):
        readout_service(state,OrderedTransfer(),gates,placement_policy=policy)
    assert state.snapshot()==staged


def test_already_supported_in_mz_does_not_force_aod_visit(staged):
    from neutral_atom_strategies.scheduling.qec import measurement_destinations
    state,gates=inputs(staged);dest=measurement_destinations(state,tuple(g.qubit_ids[0] for g in gates))[0]
    p=new_builder(state);OrderedTransfer().transfer_group(p,dest)
    env=NeutralAtomEnv.restore(staged);env.submit(finish(p));env.run()
    policy=ReadoutPlacementPolicy();plan,_=readout_service(env.state,OrderedTransfer(),gates,placement_policy=policy)
    assert [o.operation_type for o in plan.operations]==[K.MEASUREMENT,K.RESET]
    assert policy.log[-1]['selected']['support']=='slm'
