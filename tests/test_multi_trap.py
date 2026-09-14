"""Real multi-cell transport, unchanged physics, independent restore and limits."""
from dataclasses import replace
import json
import pytest
from neutral_atom_app.visualization.workbench import build_inputs, compile_input, validate_input
from neutral_atom_env.platform import initialize
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from neutral_atom_strategies.scheduling.m4 import run_m4
from neutral_atom_strategies.motion.multi_trap import MultiTrapGreedyCompiler, RigidArrayOrthogonalPlanner
from neutral_atom_strategies.motion.planners import RouteRequest
from neutral_atom_env.domain.aod import AODConfiguration
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware.dynamic_traps import switch_traps, trap_state
from neutral_atom_env.hardware import get_backend
from neutral_atom_env.domain.models import Position2D
from neutral_atom_env.domain.operations import CaptureBinding
from neutral_atom_env.domain.models import MobileCellIndex


def value(capacity=4,layout='row'):
    return {'compiler':'greedy','ez_policy':'adaptive','aod_traps':capacity,'atom_count':4,'layout':layout,'seed':13,
        'gates':[{'id':f'g{i}','gate_type':'CZ','qubit_ids':[f'Q{2*i:03d}',f'Q{2*i+1:03d}'],'parameters':[],'column':0} for i in range(2)]}


@pytest.mark.parametrize('capacity',[1,2,4])
def test_capacity_builds_one_array_and_explicit_space(capacity):
    _,_,p,_=build_inputs(value(capacity))
    assert p.aod.rows==1 and p.aod.columns==capacity
    assert not p.aod.active_cells
    assert p.world.bounds.upper.x_um==45+10*(capacity-1)
    assert p.world.zones[0].bounds.upper.x_um==45


@pytest.mark.parametrize('bad',[0,129,True,1.5])
def test_invalid_capacity_rejected(bad):
    with pytest.raises(ValueError):validate_input(value(bad))


def test_baseline_strategies_not_silently_converted():
    for mode in ('resident','returning','legacy'):
        with pytest.raises(ValueError,match='M4 strategy'):validate_input(value(4)|{'compiler':mode})
    with pytest.raises(ValueError,match='adaptive'):validate_input(value(4)|{'ez_policy':'pair'})
    raw=value(1);raw.pop('aod_traps');assert 'aod_traps' not in validate_input(raw)


@pytest.mark.parametrize('capacity',[2,4])
def test_joint_transport_uses_capacity_and_restores_full_terminal(capacity):
    r,state=compile_input(value(capacity))
    assert r['status']=='completed',r['diagnostics']
    frames=r['recording']['frames'];ops=r['recording']['operations']
    assert max(o['moving_count'] for o in ops)==capacity
    assert max(sum(f['aod']['enabled_rows'])*sum(f['aod']['enabled_columns']) for f in frames)==capacity
    assert not state.placement.mobile_occupancy and not state.aod.active_cells
    assert all(h.holder_id==f'S{int(q[1:]):03d}' for q,h in state.placement.atom_to_holder.items())
    assert all(not (f['movement'] and f['transfer']) for f in frames)
    # All axes follow the same displacement; both x and y never move in one segment.
    for f in frames:
        if not f['movement']:continue
        a,b=f['axes'],f['movement']['target_axes']
        dx=[v-u for u,v in zip(a['x_um'],b['x_um'])];dy=[v-u for u,v in zip(a['y_um'],b['y_um'])]
        assert len(set(round(x,8) for x in dx))==1 and (all(abs(x)<1e-8 for x in dx) or all(abs(y)<1e-8 for y in dy))


def test_joint_boundaries_restore_and_resume_compiler_without_dropping_atoms():
    raw,c,p,h=build_inputs(value(4));state=initialize(c,p,h,seed=raw['seed']);terminal=initial_terminal(state)
    choices,_,_=MultiTrapGreedyCompiler(adaptive_sites=True).alternatives('g0',state,site_limit=1)
    plan=min(choices,key=lambda c:c.cost).plan
    assert '/joint-4/' in plan.intent.task_id
    e=Executor(state);e.submit(plan);saved=[];loaded=None
    while state.event_queue:
        e.step();saved.append(state.snapshot())
        if len(state.placement.mobile_occupancy)==4 and not state.aod.is_moving and state.transfer is None:
            loaded=state.snapshot()
    for snapshot in saved:
        resumed=SimulationState.restore(snapshot);Executor(resumed).run()
        assert resumed.snapshot()==state.snapshot()
    assert loaded is not None
    mid=SimulationState.restore(loaded)
    # Shared row must not be disabled while any of its four atoms remains held.
    with pytest.raises(ValidationError,match='HOLDER_SUPPORT_DISABLED'):
        switch_traps(mid,replace(trap_state(mid),rows=(False,)))
    assert run_m4(mid,terminal=terminal,adaptive_sites=True).status=='completed'
    assert not mid.placement.mobile_occupancy


def test_array_planner_preserves_spacing_and_refuses_deformation():
    _,_,p,_=build_inputs(value(4));a=p.aod.configuration();b=a.translated(2.5,-25)
    request=RouteRequest(a,b,5,0,(),p.world,p.hardware)
    routes=list(RigidArrayOrthogonalPlanner().candidates(request));assert routes
    for route in routes:
        assert route[0]==a and route[-1]==b
        for axes in route:assert tuple(x-axes.x_um[0] for x in axes.x_um)==(0,10,20,30)
    assert not list(RigidArrayOrthogonalPlanner().candidates(replace(request,target=AODConfiguration((2.5,10,20,30),(-25,)))))


def test_budget_failure_preserves_actual_multi_atom_program():
    r,state=compile_input(value(4)|{'max_decisions':1})
    assert r['status']=='stalled' and r['failure_report']['code']=='DECISION_BUDGET_EXHAUSTED'
    assert max(o['moving_count'] for o in r['recording']['operations'])==4
    assert SimulationState.restore(state.snapshot()).snapshot()==state.snapshot()


@pytest.mark.parametrize('neighbor,allowed',[(5,True),(.5,False)])
def test_inactive_capacity_is_not_a_continuous_capture_surface(neighbor,allowed):
    raw,c,p,h=build_inputs(value(4));state=initialize(c,p,h)
    traps=dict(state.world.traps);traps['S001']=replace(traps['S001'],position=Position2D(neighbor,0))
    state=replace(state,world=replace(state.world,traps=traps,grid_spacing_um=.5))
    before=state.snapshot();binding=CaptureBinding('Q000',MobileCellIndex(0,0),'S000')
    if allowed:
        loaded=get_backend(state.hardware).load(state,(binding,))
        assert loaded.placement.mobile_occupancy=={MobileCellIndex(0,0):'Q000'}
        assert loaded.placement.atom_to_holder['Q001']==state.placement.atom_to_holder['Q001']
    else:
        with pytest.raises(ValidationError):get_backend(state.hardware).load(state,(binding,))
    assert state.snapshot()==before
