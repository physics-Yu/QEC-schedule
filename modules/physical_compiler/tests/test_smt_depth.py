"""Small depth optima and independently detected illegal Cartesian motion."""

from dataclasses import replace

import pytest
from experiments.surface_smt.depth.model import DepthModel, Problem, Witness
from experiments.surface_smt.depth.validation import validate


def test_initially_idle_pair_needs_one_move():
    problem = Problem(2, (((0, 1),),), columns=2, rows=1)
    assert DepthModel(problem, 0).check(5)[0]["status"] == "unsat"
    report, witness = DepthModel(problem, 1).check(5)
    assert report["status"] == "sat"
    assert witness is not None and not validate(problem, witness)


def test_free_interacting_initial_layout_changes_lower_bound():
    problem = Problem(2, (((0, 1),),), columns=2, rows=1, initially_idle=False)
    report, witness = DepthModel(problem, 0).check(5)
    assert report["status"] == "sat"
    assert witness is not None and not validate(problem, witness)


def test_changed_matching_requires_another_move():
    problem = Problem(3, (((0, 1),), ((0, 2),)), columns=3, rows=1)
    assert DepthModel(problem, 1).check(5)[0]["status"] == "unsat"
    report, witness = DepthModel(problem, 2).check(5)
    assert report["status"] == "sat"
    assert witness is not None and not validate(problem, witness)


def test_cartesian_empty_corner_cannot_ignore_a_stationary_atom():
    problem = Problem(3, (), columns=4, rows=3)
    witness = Witness(
        (((0, 0), (2, 1), (0, 1)), ((2, 0), (4, 1), (0, 1))), ((0, 1),), ()
    )
    assert any("Cartesian_ghost" in item for item in validate(problem, witness))
    model = DepthModel(problem, 1)
    for t, points in enumerate(witness.positions):
        for q, (x, y) in enumerate(points):
            model.solver.add(model.x[t][q] == x, model.y[t][q] == y)
    for q in range(3):
        model.solver.add(model.carried[0][q] == (q in (0, 1)))
    assert model.check(5)[0]["status"] == "unsat"


def test_rigid_checks_physical_displacement_not_trap_index_delta():
    # x indices 0->1 and 1->2 both increment by one but move 2 vs 8 um.
    witness = Witness((((0, 0), (1, 1)), ((1, 0), (2, 1))), ((0, 1),), ())
    problem = Problem(2, (), columns=3, rows=2, motion="flexible")
    assert not validate(problem, witness)
    assert any(
        "rigid_translation" in s
        for s in validate(replace(problem, motion="rigid"), witness)
    )


@pytest.mark.slow
def test_d3_depth_four_certificate_lowers_to_original_nz_circuit():
    from experiments.surface_smt.depth.lowering import export
    from modules.codes.rotated_surface_d3.components.circuits import se_layers

    problem = Problem(17, se_layers())
    assert DepthModel(problem, 3).check(10)[0]["status"] == "unsat"
    report, witness = DepthModel(problem, 4).check(20)
    assert report["status"] == "sat" and witness is not None
    document, checks = export(problem, witness)
    assert checks["actual_geometry_clifford_tableau"]
    assert document["metrics"]["action_counts"]["Move"] == 4
    assert document["metrics"]["cz_gates_per_pulse"] == [6, 6, 6, 6]
