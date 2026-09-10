"""Routes have independent physical expectations; no golden compiler equivalence."""
from dataclasses import replace
import json
import pytest
from neutral_atom_env.domain.models import Position2D,StaticTrap,GridCoord
from neutral_atom_env.domain.aod import AODConfiguration
from neutral_atom_env.domain.operations import ExecuteGateBatchIntent,OperationType as K
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.motion.compiler import MotionCompiler,exact_validate
from neutral_atom_env.motion.planners import HalfGridPlanner,simplify_route
from neutral_atom_env.simulation.milestone1_factory import make_single_gate_state
from neutral_atom_env.simulation.row_column_factory import make_row_column_state
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.hardware import get_backend

INTENT=ExecuteGateBatchIntent({'G000'})


class DirectVerticalPlanner:
    id='external-vertical'
    def candidates(self,r):
        yield (r.start,r.start.translated(0,r.target.y_um[0]-r.start.y_um[0]),r.target)


def test_right_corridor_and_no_stop_in_middle_of_straight_leg():
    state=make_single_gate_state();before=state.snapshot()
    plan=MotionCompiler().compile(INTENT,state)
    targets=[o.target_pose for o in plan.operations[:4] if o.operation_type==K.AOD_MOVE]
    assert targets==[Position2D(2.5,0),Position2D(2.5,-25),Position2D(3,-25)]
    assert state.snapshot()==before


def test_different_legal_planners_submit_and_resume_without_default_recompilation(monkeypatch):
    left=MotionCompiler(HalfGridPlanner(sides=(-1,),id='left-only'))
    state=make_single_gate_state();plan=left.compile(INTENT,state)
    assert plan.operations[1].target_pose==Position2D(-2.5,0)
    assert plan.estimated_distance_um==66 # 2 * (2.5 + 25 + 5.5)
    monkeypatch.setattr(MotionCompiler,'compile',lambda *a,**kw:pytest.fail('Validator must not compile'))
    executor=Executor(state);executor.submit(plan)
    for _ in range(5):executor.step()
    resumed=SimulationState.restore(state.snapshot());Executor(resumed).run();executor.run()
    assert resumed.snapshot()==state.snapshot() and state.dag.completed


@pytest.mark.parametrize('enabled',[True,False])
def test_empty_enabled_trap_blocks_direct_route_but_candidate_dots_do_not(enabled):
    state=make_single_gate_state();traps=dict(state.world.traps)
    traps['EMPTY']=StaticTrap('EMPTY',GridCoord(0,-1),Position2D(0,-5),enabled=enabled)
    state=replace(state,world=replace(state.world,traps=traps));before=state.snapshot()
    if enabled:
        with pytest.raises(ValidationError,match='SLM_PATH_BLOCKED'):
            MotionCompiler(DirectVerticalPlanner()).compile(INTENT,state)
    else:exact_validate(MotionCompiler(DirectVerticalPlanner()).compile(INTENT,state),state)
    # Side corridor is clear even when the empty trap is enabled.
    exact_validate(MotionCompiler().compile(INTENT,state),state)
    assert state.snapshot()==before


def test_incidental_atom_is_also_checked_against_empty_slm():
    state=make_row_column_state('incidental');traps=dict(state.world.traps)
    traps['S002']=replace(traps['S002'],position=Position2D(10,5),grid=GridCoord(2,1))
    traps['EMPTY']=StaticTrap('EMPTY',GridCoord(2,-1),Position2D(10,-5))
    state=replace(state,world=replace(state.world,traps=traps))
    with pytest.raises(ValidationError,match='SLM_PATH_BLOCKED') as caught:
        MotionCompiler(DirectVerticalPlanner()).compile(INTENT,state)
    assert caught.value.violation.atom_ids==('Q002',)
    assert MotionCompiler().compile(INTENT,state).incidental_atom_ids==frozenset({'Q002'})


@pytest.mark.parametrize('damage',['missing_depart','fake_depart','binding','resources','time','distance','placement','operands'])
def test_plan_validation_rejects_semantic_corruption_atomically(damage):
    state=make_single_gate_state();plan=MotionCompiler().compile(INTENT,state);ops=list(plan.operations)
    if damage=='missing_depart':ops[1]=replace(ops[1],transfer_phase=None);plan=replace(plan,operations=tuple(ops))
    elif damage=='fake_depart':ops[2]=replace(ops[2],transfer_phase='depart');plan=replace(plan,operations=tuple(ops))
    elif damage=='binding':plan=replace(plan,bindings=(replace(plan.bindings[0],static_trap_id='S002'),))
    elif damage=='resources':plan=replace(plan,resources=plan.resources[:-1])
    elif damage=='time':ops[2]=replace(ops[2],duration_us=1);plan=replace(plan,operations=tuple(ops))
    elif damage=='distance':plan=replace(plan,estimated_distance_um=0)
    elif damage=='placement':plan=replace(plan,predicted_placement=())
    elif damage=='operands':plan=replace(plan,requested_atom_ids=frozenset({'Q003'}))
    before=state.snapshot()
    with pytest.raises(ValidationError):Executor(state).submit(plan)
    assert state.snapshot()==before


def test_backend_departure_is_not_an_arbitrary_overlap_exemption():
    state=make_single_gate_state();backend=get_backend(state.hardware);bindings=backend.capture_closure(state,state.aod.pose)
    state=backend.load(state,bindings)
    with pytest.raises(ValidationError,match='SLM_PATH_BLOCKED'):backend.move(state,Position2D(2.5,0))
    with pytest.raises(ValidationError,match='INVALID_TRANSFER_PATH'):
        backend.move(state,Position2D(.5,0),transfer='depart',bindings=bindings)
    moved=backend.move(state,Position2D(2.5,0),transfer='depart',bindings=bindings)
    with pytest.raises(ValidationError,match='INVALID_TRANSFER_PATH'):
        backend.move(moved,Position2D(2.5,-25),transfer='depart',bindings=bindings)


def test_collinear_simplification_uses_full_axes_and_keeps_turns_and_reversals():
    a=AODConfiguration((0,5),(0,5));b=a.translated(2.5,0);c=a.translated(5,0);d=c.translated(0,-25)
    assert simplify_route((a,a,b,c,d))==(a,c,d)
    assert simplify_route((a,b,a))==(a,b,a)
    shaped=AODConfiguration((5,9),(0,5))
    assert simplify_route((a,b,shaped))==(a,b,shaped)


def test_upper_layer_can_choose_another_legal_interaction_layout():
    state=make_row_column_state();target=AODConfiguration((4,6,8),(-24,-19))
    plan=MotionCompiler().compile(INTENT,state,target_configuration=target)
    executor=Executor(state);executor.submit(plan)
    while state.dag.nodes['G000'].status.value!='running':executor.step()
    assert state.aod.configuration()==target
    executor.run();assert state.dag.completed


def test_scheduler_uses_injected_policy_compiler():
    from neutral_atom_env.planning.eager_baseline import EagerBaseline
    from neutral_atom_env.simulation.scheduler import EagerScheduler
    state=make_single_gate_state()
    policy=EagerBaseline(compiler=MotionCompiler(HalfGridPlanner(sides=(-1,),id='left-only')))
    assert EagerScheduler(state,policy=policy).run().status=='completed'
    plans=[json.loads(r)['event']['plan'] for r in state.trace.records if json.loads(r)['event']['event_type']=='plan_started']
    assert plans[0]['planner_id']=='left-only' and state.metrics()['total_aod_distance_um']==66


def test_restore_reaudits_plan_even_when_trace_is_modified_consistently():
    state=make_single_gate_state();executor=Executor(state)
    executor.submit(MotionCompiler().compile(INTENT,state))
    for _ in range(4):executor.step()
    saved=json.loads(state.snapshot())
    saved['active_plan']['plan']['operations'][2]['transfer_phase']='depart'
    first=json.loads(saved['trace'][0]);first['event']['plan']=saved['active_plan']['plan']
    saved['trace'][0]=json.dumps(first)
    with pytest.raises(ValidationError,match='INVALID_CHECKPOINT'):SimulationState.restore(json.dumps(saved))


def test_schema_six_cannot_silently_bypass_new_slm_semantics():
    state=make_single_gate_state();saved=json.loads(state.snapshot());assert saved['schema_version']>=7
    saved['schema_version']=6
    with pytest.raises(ValidationError,match='INVALID_CHECKPOINT'):SimulationState.restore(json.dumps(saved))
