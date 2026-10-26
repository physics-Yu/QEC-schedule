"""Finite transport constraints, checked with independently fixed snapshots."""

import pytest
import z3

from nadit_physical_compiler.device import (
    AOD,
    Device,
    Position,
    Region,
    SLMSite,
    Timing,
)
from nadit_physical_compiler.smt.contracts import Domain
from nadit_physical_compiler.smt.transport import TransportModel
from nadit_physical_compiler.state import AtomLayout, AtomState, SLMHolder


def _model(
    positions=((0, 0), (2, 2)),
    *,
    motion="flexible",
    horizon=4,
    capacity=None,
    spacing=1,
):
    coords = tuple(float(i) for i in range(5))
    sites = tuple(SLMSite(f"s{x}_{y}", Position(x, y)) for x in coords for y in coords)
    entry = AtomLayout(
        tuple(
            AtomState(q, Position(x, y), SLMHolder(f"s{float(x)}_{float(y)}"))
            for q, (x, y) in enumerate(positions)
        ),
        qubit_to_atom=tuple(range(len(positions))),
    )
    device = Device(
        "test",
        (),
        sites,
        (AOD("a", Region(0, 0, 4, 4), spacing, capacity, capacity, motion),),
        Timing(1, 1, 1),
    )
    solver = z3.Solver()
    model = TransportModel(solver, device, "a", entry, Domain(coords, coords, horizon))
    return solver, model


def _lines(solver, model, state, columns, rows):
    solver.add(
        *[flag == (i in columns) for i, flag in enumerate(model.columns[state])],
        *[flag == (i in rows) for i, flag in enumerate(model.rows[state])],
    )


def _position(solver, model, state, atom, x, y):
    solver.add(model.x[state][atom] == x, model.y[state][atom] == y)


@pytest.mark.parametrize("motion,expected", [("flexible", z3.sat), ("rigid", z3.unsat)])
def test_spacing_change_is_flexible_only(motion, expected):
    solver, model = _model(motion=motion)
    solver.add(*[k == v for k, v in zip(model.kind, (1, 2, 2, 3), strict=True)])
    _lines(solver, model, 1, (0, 2), (0, 2))
    _lines(solver, model, 2, (1, 4), (1, 3))
    _lines(solver, model, 3, (0, 2), (0, 2))
    _position(solver, model, 2, 0, 1, 1)
    _position(solver, model, 2, 1, 4, 3)
    assert solver.check() == expected


def test_rigid_uniform_translation_round_trip_has_home_and_empty_grid():
    solver, model = _model(motion="rigid")
    solver.add(*[k == v for k, v in zip(model.kind, (1, 2, 2, 3), strict=True)])
    _lines(solver, model, 1, (0, 2), (0, 2))
    _lines(solver, model, 2, (1, 3), (1, 3))
    _lines(solver, model, 3, (0, 2), (0, 2))
    _position(solver, model, 2, 0, 1, 1)
    _position(solver, model, 2, 1, 3, 3)
    assert solver.check() == z3.sat
    assignment = solver.model()
    assert model.snapshot(assignment, 4).positions == (Position(0, 0), Position(2, 2))
    assert model.snapshot(assignment, 4).carried == (False, False)
    assert model.snapshot(assignment, 4).columns == ()
    assert model.snapshot(assignment, 4).rows == ()
    assert model.transition_names(assignment) == ("load", "move", "move", "store")


@pytest.mark.parametrize("motion", ["flexible", "rigid"])
def test_partial_store_retains_other_atom_and_can_store_it_later(motion):
    solver, model = _model(motion=motion, horizon=3)
    solver.add(*[k == v for k, v in zip(model.kind, (1, 3, 3), strict=True)])
    _lines(solver, model, 1, (0, 2), (0, 2))
    _lines(solver, model, 2, (2,), (2,))
    solver.add(z3.Not(model.carried[2][0]), model.carried[2][1])
    assert solver.check() == z3.sat
    assignment = solver.model()
    assert z3.is_true(assignment.eval(model.touched(1, 0)))
    assert z3.is_false(assignment.eval(model.touched(1, 1)))


@pytest.mark.parametrize("motion,expected", [("flexible", z3.sat), ("rigid", z3.unsat)])
def test_adding_lines_while_carrying_is_flexible_only(motion, expected):
    solver, model = _model(motion=motion)
    solver.add(*[k == v for k, v in zip(model.kind, (1, 3, 1, 3), strict=True)])
    _lines(solver, model, 1, (0, 2), (0, 2))
    _lines(solver, model, 2, (2,), (2,))
    _lines(solver, model, 3, (0, 2), (0, 2))
    assert solver.check() == expected


def test_load_must_pick_every_occupied_cartesian_intersection():
    solver, model = _model(((0, 0), (2, 2), (0, 2)), horizon=2)
    solver.add(model.kind[0] == 1, model.kind[1] == 3)
    solver.add(model.carried[1][0], model.carried[1][1], z3.Not(model.carried[1][2]))
    assert solver.check() == z3.unsat


@pytest.mark.parametrize("motion,expected", [("flexible", z3.sat), ("rigid", z3.unsat)])
def test_empty_active_line_participates_in_rigid_translation(motion, expected):
    solver, model = _model(((0, 0),), motion=motion)
    solver.add(*[k == v for k, v in zip(model.kind, (1, 2, 2, 3), strict=True)])
    _lines(solver, model, 1, (0, 2), (0,))
    _lines(solver, model, 2, (1, 4), (0,))
    _lines(solver, model, 3, (0, 2), (0,))
    _position(solver, model, 2, 0, 1, 0)
    assert solver.check() == expected


def test_flexible_move_cannot_reverse_carried_column_order():
    solver, model = _model()
    solver.add(*[k == v for k, v in zip(model.kind, (1, 2, 2, 3), strict=True)])
    _lines(solver, model, 1, (0, 2), (0, 2))
    _lines(solver, model, 2, (0, 2), (0, 2))
    _position(solver, model, 2, 0, 2, 0)
    _position(solver, model, 2, 1, 0, 2)
    assert solver.check() == z3.unsat


def test_move_cannot_occupy_a_stationary_slm_atom():
    solver, model = _model(((0, 0), (1, 0)))
    solver.add(*[k == v for k, v in zip(model.kind, (1, 2, 2, 3), strict=True)])
    _lines(solver, model, 1, (0,), (0,))
    _lines(solver, model, 2, (1,), (0,))
    _position(solver, model, 2, 0, 1, 0)
    assert solver.check() == z3.unsat


def test_empty_intersection_cannot_move_onto_stationary_slm_atom():
    solver, model = _model(((0, 0), (3, 0)))
    solver.add(*[k == v for k, v in zip(model.kind, (1, 2, 2, 3), strict=True)])
    _lines(solver, model, 1, (0, 2), (0,))
    _lines(solver, model, 2, (1, 3), (0,))
    _position(solver, model, 2, 0, 1, 0)
    assert solver.check() == z3.unsat


def test_store_cannot_release_atom_whose_intersection_stays_active():
    solver, model = _model(horizon=3)
    solver.add(*[k == v for k, v in zip(model.kind, (1, 3, 3), strict=True)])
    _lines(solver, model, 1, (0, 2), (0, 2))
    _lines(solver, model, 2, (0, 2), (0, 2))
    solver.add(z3.Not(model.carried[2][0]))
    assert solver.check() == z3.unsat


def test_one_axis_grid_without_atoms_is_permitted():
    solver, model = _model((), horizon=2)
    solver.add(model.kind[0] == 1, model.kind[1] == 3)
    _lines(solver, model, 1, (), (0, 2))
    assert solver.check() == z3.sat


@pytest.mark.parametrize("capacity,spacing", [(1, 1), (None, 3)])
def test_capacity_and_minimum_line_spacing_are_enforced(capacity, spacing):
    solver, model = _model(capacity=capacity, spacing=spacing, horizon=2)
    solver.add(model.kind[0] == 1, model.kind[1] == 3)
    solver.add(*model.carried[1])
    assert solver.check() == z3.unsat


def test_move_touches_stationary_carried_atom_too():
    solver, model = _model(((0, 0),), horizon=3)
    solver.add(*[k == v for k, v in zip(model.kind, (1, 2, 3), strict=True)])
    _lines(solver, model, 1, (0,), (0,))
    _lines(solver, model, 2, (0,), (0,))
    assert solver.check() == z3.sat
    assert z3.is_true(solver.model().eval(model.touched(1, 0)))
