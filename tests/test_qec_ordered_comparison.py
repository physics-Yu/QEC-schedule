from dataclasses import replace
from time import perf_counter
import pytest
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.operations import OperationType as K
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_experiments.ordered_axis_comparison import demos as small_demos,make_state as small_state
from neutral_atom_experiments.qec_ordered_comparison import demos,make_state,run_one
from neutral_atom_experiments.surface_qec import simulate_ideal
from neutral_atom_strategies.scheduling.smt_ordered import SMTOrderedAxisPlanner
from neutral_atom_strategies.scheduling.ordered_greedy import new_builder,finish
from neutral_atom_strategies.scheduling.patch_greedy import patch_assignment
from neutral_atom_strategies.motion.ordered_transfer import OrderedTransfer


def test_full_protocol_keeps_real_ancilla_measurements_and_recovers_y():
    spec=demos()['qec_ghz2'];state=make_state(spec)
    assert len(state.atoms)==34 and state.quantum_state is not None
    assert sum(g['gate_type']=='MEASURE' for g in spec['gates'])==32
    assert sum(g['gate_type']=='RESET' for g in spec['gates'])==32
    assert sum(g['gate_type']=='CZ' for g in spec['gates'])==105
    assert any(g.get('condition') for g in spec['gates'])
    _,report=simulate_ideal(spec['gates'])
    assert report['verified_logical_ghz2'] and report['measurement_protocol_complete']


@pytest.mark.parametrize('name,size',[('stretch',3),('two_axes',4)])
def test_smt_independently_constructs_nonuniform_batch(name,size):
    state=small_state(small_demos()[name]);initial=state.snapshot()
    planner=SMTOrderedAxisPlanner(timeout_ms=10000)
    decision,plan=planner.propose(state,perf_counter()+30)
    assert len(decision['gate_ids'])==size
    assert state.snapshot()==initial
    env=NeutralAtomEnv(state);env.submit(plan);env.run()
    assert env.state.dag.completed
    assert env.state.placement.mobile_occupancy=={}
    assert planner.log[0]['models'][-1]['physical_accepted']


def test_group_transfer_preserves_source_support_and_explicit_terminal():
    state=make_state(demos()['qec_ghz2']);initial=state.snapshot()
    p=new_builder(state);dest=patch_assignment(state);OrderedTransfer().transfer_group(p,dest)
    plan=finish(p)
    assert len([op for op in plan.operations if op.operation_type==K.AOD_LOAD])==1
    moves=[op for op in plan.operations if op.operation_type==K.AOD_MOVE]
    assert len(moves)==1 and moves[0].transfer_phase=='depart'
    assert state.snapshot()==initial
    env=NeutralAtomEnv(state);env.submit(plan);env.run()
    assert all(env.state.placement.atom_to_holder[q].holder_id==t for q,t in dest.items())


def test_unknown_is_reported_without_mutating_state(monkeypatch):
    import z3
    state=small_state(small_demos()['stretch']);initial=state.snapshot()
    monkeypatch.setattr(z3.Optimize,'check',lambda self,*args:z3.unknown)
    with pytest.raises(ValidationError,match='SMT_UNKNOWN'):SMTOrderedAxisPlanner().propose(state,perf_counter()+10)
    assert state.snapshot()==initial


def test_arbitrary_edit_measure_reset_same_inputs_and_real_replay(tmp_path):
    spec=demos()['qec_ghz2'];spec['gates']=[
        {'id':'h','gate_type':'H','qubit_ids':['Q018']},
        {'id':'m','gate_type':'MEASURE','qubit_ids':['Q018']},
        {'id':'r','gate_type':'RESET','qubit_ids':['Q018']},
        {'id':'x','gate_type':'X','qubit_ids':['Q000'],'condition':[['m',1]],'depends_on':['m']}]
    results=[run_one(spec,s,tmp_path/s) for s in ('ordered_greedy','smt_ordered')]
    assert results[0]['initial_sha256']==results[1]['initial_sha256']
    for result in results:
        assert result['status']=='completed'
        assert result['effects_once'] and result['replay_equal'] and result['terminal_verified']
        assert not result['quantum']['measurement_protocol_complete']
