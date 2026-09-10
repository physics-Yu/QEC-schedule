"""Device separation applies to every trap, not just populated gate operands."""
from dataclasses import replace
from itertools import combinations
from math import hypot
import json
import pytest
from neutral_atom_env.domain.aod import AODConfiguration
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.operations import ExecuteGateBatchIntent
from neutral_atom_env.hardware import get_backend
from neutral_atom_env.motion.compiler import MotionCompiler
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.simulation.row_column_factory import make_row_column_state


@pytest.mark.parametrize('backend',['rigid','row_column'])
@pytest.mark.parametrize('gap',[1.0,1.01])
def test_initial_array_rejects_equal_or_smaller_spacing_even_when_empty(backend,gap):
    state=make_row_column_state(backend=backend)
    assert not state.placement.mobile_occupancy
    with pytest.raises(ValidationError,match='AOD_AXIS_SPACING'):
        replace(state,aod=replace(state.aod,spacing_um=gap))


@pytest.mark.parametrize('axis',['rows','columns'])
@pytest.mark.parametrize('gap',[1.0,1.01,1.010001])
def test_empty_moving_traps_obey_strict_threshold_on_both_axes(axis,gap):
    state=make_row_column_state();backend=get_backend(state.hardware)
    xs=(0,gap,5) if axis=='columns' else (0,5,10)
    ys=(0,gap) if axis=='rows' else (0,5)
    target=AODConfiguration(xs,ys);before=state.snapshot()
    if gap<=1.01:
        with pytest.raises(ValidationError,match='AOD_AXIS_SPACING'):backend.move(state,target)
    else:assert backend.move(state,target).aod.configuration()==target
    assert state.snapshot()==before


def test_configuration_cannot_weaken_the_floor_and_can_strengthen_it():
    state=make_row_column_state();backend=get_backend(state.hardware)
    weakened=replace(state,hardware=replace(state.hardware,minimum_axis_spacing_um=.1))
    with pytest.raises(ValidationError,match='AOD_AXIS_SPACING'):
        backend.move(weakened,AODConfiguration((0,1.01,5),(0,5)))
    stricter=replace(state,hardware=replace(state.hardware,minimum_axis_spacing_um=2))
    with pytest.raises(ValidationError,match='AOD_AXIS_SPACING'):
        backend.move(stricter,AODConfiguration((0,2,5),(0,5)))


def test_outer_pair_cannot_squeeze_an_empty_trap_into_a_two_micron_gate():
    state=make_row_column_state('outer_pair_blocked');before=state.snapshot()
    with pytest.raises(ValidationError,match='AOD_PAIR_SPACING_INFEASIBLE'):
        MotionCompiler().compile(ExecuteGateBatchIntent({'G000'}),state)
    # Generic backend also rejects an external planner's formerly accepted (4,5,6) target.
    with pytest.raises(ValidationError,match='AOD_AXIS_SPACING'):
        get_backend(state.hardware).move(state,AODConfiguration((4,5,6),(-25,-20)))
    assert state.snapshot()==before


def test_entire_cubic_deformation_keeps_all_cartesian_trap_pairs_separated():
    state=make_row_column_state();backend=get_backend(state.hardware)
    start=state.aod.configuration();end=AODConfiguration((0,1.02,3.05),(-25,-23.98))
    backend.validate_move(state,end)
    # Independent Cartesian point distances, rather than calling the axis-gap validator.
    for step in range(201):
        s=step/200;u=3*s*s-2*s*s*s
        xs=[a+u*(b-a) for a,b in zip(start.x_um,end.x_um)]
        ys=[a+u*(b-a) for a,b in zip(start.y_um,end.y_um)]
        points=[(x,y) for x in xs for y in ys]
        assert all(hypot(a[0]-b[0],a[1]-b[1])>1.01 for a,b in combinations(points,2))


def test_submit_and_restore_cannot_bypass_trap_spacing():
    state=make_row_column_state();plan=MotionCompiler().compile(ExecuteGateBatchIntent({'G000'}),state)
    ops=list(plan.operations);target=AODConfiguration((4,5,6),(-25,-20))
    duration=get_backend(state.hardware).move_duration(state.aod,target,state.hardware)
    ops[1]=replace(ops[1],target_configuration=target,duration_us=duration)
    damaged=replace(plan,operations=tuple(ops));before=state.snapshot()
    with pytest.raises(ValidationError,match='AOD_AXIS_SPACING'):Executor(state).submit(damaged)
    assert state.snapshot()==before
    saved=json.loads(before);saved['aod']['column_offsets_um']=[0,1,2]
    with pytest.raises(ValidationError,match='INVALID_CHECKPOINT'):SimulationState.restore(json.dumps(saved))
