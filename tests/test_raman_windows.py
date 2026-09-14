"""Independent geometric expectations for usable pieces of a MOVE interval."""
from dataclasses import replace
from math import sqrt

import pytest

from test_aod_raman import loaded
from neutral_atom_env.domain.models import Position2D
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget, OperationType as K
from neutral_atom_env.hardware.raman import validate_rotation_sweep
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.motion.program import ProgramBuilder
from neutral_atom_env.simulation.raman_windows import safe_rotation_fractions
from neutral_atom_env.simulation.m4 import fill_raman
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState


def test_departing_neighbor_opens_half_move_and_approaching_closes_half():
    state = loaded([('H', (0,))], 2.5)
    assert safe_rotation_fractions(state, 'g0', Position2D(7.5, 0)) == ((.5, 1.),)
    state = loaded([('H', (0,))], 7.5)
    assert safe_rotation_fractions(state, 'g0', Position2D(2.5, 0)) == ((0., .5),)


def test_crossing_neighbor_has_two_safe_windows_and_tangency_is_allowed():
    state = loaded([('H', (0,))], 10)
    state = replace(state, aod=replace(state.aod, pose=Position2D(-10, 2.5)))
    # For a radius-five circle, the intersections on y=2.5 are ±sqrt(18.75).
    edges = safe_rotation_fractions(state, 'g0', Position2D(10, 2.5))
    assert edges[0] == pytest.approx((0, (10-sqrt(18.75))/20))
    assert edges[1] == pytest.approx(((10+sqrt(18.75))/20, 1))
    state = replace(state, aod=replace(state.aod, pose=Position2D(-10, 5)))
    assert safe_rotation_fractions(state, 'g0', Position2D(10, 5)) == ((0., 1.),)


def test_stationary_near_neighbor_and_moving_target_have_no_window():
    state = loaded([('H', (0,)), ('H', (1,))], 2.5)
    assert safe_rotation_fractions(state, 'g0') == ()
    assert safe_rotation_fractions(state, 'g1', Position2D(7.5, 0)) == ()


def test_fill_starts_at_five_um_inside_move_and_restores_inflight():
    state = loaded([('H', (0,))], 2.5)
    target = Position2D(7.5, 0)
    builder = ProgramBuilder(state, TaskIntent('depart', TaskTarget(
        aod_configuration=replace(state.aod.configuration(), x_um=(7.5,)))))
    builder.add(K.AOD_MOVE, 'Separate neighbor', target=target)
    base = builder.finish('safe-window-test')
    duration = base.operations[0].duration_us
    plan, slots = fill_raman(base, state)
    assert slots == [('g0', duration/2)]
    assert plan.estimated_duration_us == duration
    with pytest.raises(ValidationError, match='RAMAN_NEIGHBOR_TOO_CLOSE'):
        validate_rotation_sweep(state, 'g0', target, .5-1/duration, .5)
    validate_rotation_sweep(state, 'g0', target, .5, .5+1/duration)
    executor = Executor(state)
    executor.submit(plan)
    snapshots = []
    while state.event_queue:
        executor.step()
        snapshots.append(state.snapshot())
    assert state.dag.completed
    for snapshot in snapshots:
        restored = SimulationState.restore(snapshot)
        Executor(restored).run()
        assert restored.snapshot() == state.snapshot()
