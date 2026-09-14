"""Compiler-controlled EZ supports use actual switch cost and safe routes."""
from dataclasses import replace
import pytest
from test_m4 import make, execute
from neutral_atom_env.domain.models import HolderRef, HolderType as H, MobileCellIndex
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget, OperationType as K
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_strategies.motion.persistent import PersistentTargetCompiler
from neutral_atom_strategies.motion.greedy import GreedyCompiler
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.simulation import Executor


def origin(switch_cost=1,occupied=False):
    state=make([])
    state=replace(state,hardware=replace(state.hardware,switch_duration_us=switch_cost))
    axes=replace(state.aod.configuration(),x_um=(0.,),y_um=(-35.,))
    holders=(('Q000',HolderRef(H.MOBILE,MobileCellIndex(0,0))),)
    if occupied:holders+=(('Q001',HolderRef(H.STATIC,'EZ0')),)
    execute(state,PersistentTargetCompiler().compile(TaskIntent('origin',TaskTarget(holders,axes)),state))
    return state


@pytest.mark.parametrize('cost',[1,100])
def test_corridors_avoid_potential_sites_even_when_switching_is_cheap(cost):
    state=origin(cost);before=state.snapshot()
    axes=replace(state.aod.configuration(),x_um=(10.,))
    plan=GreedyCompiler().compile(TaskIntent('cross-ez',TaskTarget(aod_configuration=axes)),state)
    assert state.snapshot()==before
    assert not any(o.operation_type==K.TRAP_SWITCH for o in plan.operations)
    assert plan.estimated_duration_us==30 # 2.5 + 10 + 2.5 um; no 10 um row shortcut.
    e=Executor(state);e.submit(plan);saved=[state.snapshot()]
    while state.event_queue:e.step();saved.append(state.snapshot())
    assert state.slm_enabled['EZ0']
    for snapshot in saved:
        restored=SimulationState.restore(snapshot);Executor(restored).run()
        assert restored.snapshot()==state.snapshot()


def test_occupied_ez_is_never_disabled_to_shortcut_route():
    state=origin(occupied=True);before=state.snapshot()
    axes=replace(state.aod.configuration(),x_um=(10.,))
    plan=GreedyCompiler().compile(TaskIntent('avoid-resident',TaskTarget(aod_configuration=axes)),state)
    assert dict(plan.predicted_traps.slm)['EZ0'] is True
    assert plan.estimated_duration_us>20
    masks=replace(trap_state(state),slm=tuple((k,False if k=='EZ0' else v) for k,v in trap_state(state).slm))
    with pytest.raises(ValidationError):GreedyCompiler().compile(TaskIntent('unsafe-disable',TaskTarget(traps=masks)),state)
    assert state.snapshot()==before
    execute(state,plan)
    assert state.placement.atom_to_holder['Q001']==HolderRef(H.STATIC,'EZ0')
