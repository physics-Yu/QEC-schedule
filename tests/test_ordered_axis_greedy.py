"""Order/closure negatives and independently checked physical execution."""
from dataclasses import replace
from time import perf_counter
import pytest

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.operations import OperationType as K
from neutral_atom_env.domain.aod import AODConfiguration, motion_target
from neutral_atom_env.hardware import get_backend
from neutral_atom_experiments.ordered_axis_comparison import demos,make_state,run_one
from neutral_atom_strategies.scheduling.ordered_greedy import build_batch,OrderedAxisGreedy,realize_batch


def stretch_assignments():
    return tuple((f'g{i:03}',f'Q{i+3:03}',f'Q{i:03}',x,30) for i,x in enumerate((-2,18,38)))


def test_joint_axis_assignment_and_translation_ablation():
    state=make_state(demos()['stretch']);assignments=stretch_assignments()
    b=build_batch(state,assignments)
    assert b.pickup.x_um==(0,10,20) and b.target.x_um==(-2,18,38)
    with pytest.raises(ValidationError,match='AXIS_TRANSLATION_ONLY'):
        build_batch(state,assignments,translation_only=True)
    planner=OrderedAxisGreedy()
    choices=planner.candidates(state,perf_counter()+10)
    assert max(len(c.gate_ids) for c in choices)==3


def test_reject_axis_crossing_shared_axis_disagreement_and_capacity():
    state=make_state(demos()['stretch']);a=list(stretch_assignments())
    a[1]=(*a[1][:3],-12,30)
    with pytest.raises(ValidationError,match='AXIS_ORDER'):build_batch(state,a)
    a=list(stretch_assignments());a[1]=(*a[1][:3],18,40)
    with pytest.raises(ValidationError,match='AXIS_SHARED_COORDINATE'):build_batch(state,a)
    spec=demos()['stretch'];spec['aod_columns']=2
    with pytest.raises(ValidationError,match='AXIS_CAPACITY'):build_batch(make_state(spec),stretch_assignments())


def test_cartesian_closure_not_diagonal_cell_selection():
    state=make_state(demos()['two_axes'])
    # Only the diagonal sources would enable both rows and both columns,
    # unintentionally also capturing the other two data atoms.
    a=(('g000','Q004','Q000',38,40),('g003','Q007','Q003',58,70))
    with pytest.raises(ValidationError,match='AXIS_CAPTURE_CLOSURE'):build_batch(state,a)


def test_real_deformation_orthogonal_extraction_backend_and_replay():
    state=make_state(demos()['stretch']);initial=state.snapshot()
    batch=build_batch(state,stretch_assignments())
    plan=realize_batch(state,batch,perf_counter()+20,128,[])
    assert state.snapshot()==initial
    work=state;deformed=False;load_seen=False;move_after_load=False
    from neutral_atom_env.program.builder import apply_operation
    for op in plan.operations:
        before=work.aod.configuration()
        if op.operation_type==K.AOD_LOAD:load_seen=True
        if op.operation_type==K.AOD_MOVE:
            after=motion_target(op)
            assert before.x_um==after.x_um or before.y_um==after.y_um
            if load_seen and not move_after_load:
                assert op.transfer_phase=='depart' and op.transfer_bindings==batch.bindings
                move_after_load=True
            if load_seen:
                deformed|=len({round(b-a,7) for a,b in zip(before.x_um,after.x_um)})>1
        work=apply_operation(work,op,None)
    assert deformed
    env=NeutralAtomEnv(state);env.submit(plan);env.run()
    assert env.state.dag.completed and env.state.placement==state.placement
    replay=NeutralAtomEnv.restore(initial);replay.submit(plan);replay.run()
    assert replay.snapshot()==env.snapshot()


def test_backend_rejects_safe_endpoints_with_illegal_mid_segment():
    state=make_state(demos()['stretch']);batch=build_batch(state,stretch_assignments())
    from neutral_atom_strategies.scheduling.ordered_greedy import new_builder,empty_reconfigure
    p=new_builder(state,batch.gate_ids);empty_reconfigure(p,batch.pickup)
    p.add(K.AOD_LOAD,'load',bindings=batch.bindings)
    p.add(K.AOD_MOVE,'extract',configuration=batch.pickup.translated(0,2.5),phase='depart',bindings=batch.bindings)
    # Passing straight through the static anchors at y=30 must be rejected,
    # even though the y=40 endpoint itself is clear.
    with pytest.raises(ValidationError):
        get_backend(p.state.hardware).move(p.state,AODConfiguration((0,10,20),(40,)))


def test_budget_failure_is_atomic_and_explicit():
    state=make_state(demos()['stretch']);initial=state.snapshot()
    with pytest.raises(TimeoutError):OrderedAxisGreedy().propose(state,perf_counter()-1)
    assert state.snapshot()==initial
    with pytest.raises(ValidationError,match='AXIS_ROUTE_EXHAUSTED'):
        realize_batch(state,build_batch(state,stretch_assignments()),perf_counter()+10,0,[])
    assert state.snapshot()==initial


def test_wider_beam_cannot_discard_existing_translation_incumbent(monkeypatch):
    original=OrderedAxisGreedy.candidates
    def no_wider_candidates(self,state,deadline):
        if self.translation_only:return original(self,state,deadline)
        self.log.append({'injected_wider_candidate_exhaustion':True})
        return []
    monkeypatch.setattr(OrderedAxisGreedy,'candidates',no_wider_candidates)
    # Remove the initial H layer so this checks a physical CZ proposal.
    spec=demos()['parallel'];spec['gates']=spec['gates'][8:];state=make_state(spec);initial=state.snapshot()
    planner=OrderedAxisGreedy();decision,plan=planner.propose(state,perf_counter()+20)
    assert len(decision['gate_ids'])==4 and plan is not None
    assert planner.log[0]['translation_incumbent']
    assert state.snapshot()==initial


def test_arbitrary_edited_gates_execute_and_same_hardware_comparison(tmp_path):
    spec=demos()['stretch'];spec['gates']=[dict(type='H',qubits=[i]) for i in range(3)]+spec['gates']+[dict(type='X',qubits=[0])]
    a=run_one(spec,'translation_greedy',tmp_path/'translation')
    b=run_one(spec,'ordered_greedy',tmp_path/'ordered')
    assert a['status']==b['status']=='completed'
    assert a['initial_sha256']==b['initial_sha256']
    assert all(r['effects_once'] and r['replay_equal'] and r['terminal_verified'] for r in (a,b))
    assert b['max_cz_batch']==3 and a['max_cz_batch']==1
    assert b['metrics']['simulation_time_us']<a['metrics']['simulation_time_us']
