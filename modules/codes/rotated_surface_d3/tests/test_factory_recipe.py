"""Recipe topology and independent small-state quantum semantics."""

from itertools import combinations, product

import numpy as np
import pytest

from modules.codes.rotated_surface_d3.protocols.factory import (
    factory_recipe,
    t_consumption_recipe,
)


def test_resource_boundaries_and_gate_count():
    recipe = factory_recipe()
    assert (
        recipe.work_roles == recipe.retry_work_roles == ("W1", "W2", "W3", "W4", "W5")
    )
    assert recipe.released_roles == ("W2", "W3", "W4", "W5", "R")
    assert recipe.output_role == "W1"
    assert [p.ownership for p in recipe.initial_preparations] == ["working"] + [
        "adopt"
    ] * 4
    expected = list(combinations(recipe.work_roles, 3)) + [recipe.work_roles]
    assert [r.support for r in recipe.rotations] == expected
    assert (
        sum(len(r.compute_calls) + 1 + len(r.uncompute_calls) for r in recipe.rotations)
        == 59
    )
    for rotation in recipe.rotations:
        assert rotation.preparation.role == "R"
        assert rotation.preparation.ownership == "reserve"
        assert rotation.consumption.cx_call.consumes_resource_role == "R"
        assert [c.participant_roles for c in rotation.uncompute_calls] == [
            c.participant_roles for c in rotation.compute_calls
        ][::-1]
        assert rotation.consumption.branches[1].calls[0].component_id == "logical_s"
    assert recipe.accepted_output_calls[0].component_id == "logical_x"
    assert len(recipe.final_event.dependency_call_keys) == 4


def test_injection_forbids_alias_and_declares_feedback_before_return():
    with pytest.raises(ValueError, match="distinct"):
        t_consumption_recipe("same", "same")
    recipe = t_consumption_recipe("data", "magic")
    assert recipe.cx_call.participant_roles == ("data", "magic")
    assert recipe.mz_call.participant_roles == ("magic",)
    assert recipe.event.dependency_call_keys == (recipe.mz_call.key,)
    assert not recipe.branches[0].calls
    assert recipe.branches[1].calls[0].participant_roles == ("data",)


def _cx(state, control, target):
    indices = np.arange(32)
    return state[indices ^ (((indices >> control) & 1) << target)]


def _rotation_branch(state, rotation, m):
    for call in rotation.compute_calls:
        state = _cx(
            state,
            int(call.participant_roles[0][1:]) - 1,
            int(call.participant_roles[1][1:]) - 1,
        )
    pivot = int(rotation.pivot[1:]) - 1
    bits = (np.arange(32) >> pivot) & 1
    # Derived directly by adding A, CX(pivot,A), and projecting MZ(A)=m.
    state = state * np.exp(1j * np.pi / 4 * (bits ^ m)) / np.sqrt(2)
    assert np.vdot(state, state).real == pytest.approx(0.5)
    if m:
        state *= np.exp(1j * np.pi / 2 * bits)
    state *= np.sqrt(2)
    for call in rotation.uncompute_calls:
        state = _cx(
            state,
            int(call.participant_roles[0][1:]) - 1,
            int(call.participant_roles[1][1:]) - 1,
        )
    return state


def test_all_2048_consumption_branches_prepare_a_dagger_then_x_gives_a():
    recipe = factory_recipe()
    indices = np.arange(32)
    initial = np.exp(
        1j * np.pi / 4 * sum((indices >> i) & 1 for i in range(1, 5))
    ) / np.sqrt(32)
    target = np.exp(-1j * np.pi / 4 * (indices & 1)) / np.sqrt(32)
    final = np.exp(1j * np.pi / 4 * (indices & 1)) / np.sqrt(32)
    for bits in product((0, 1), repeat=11):
        state = initial.copy()
        for rotation, m in zip(recipe.rotations, bits, strict=True):
            state = _rotation_branch(state, rotation, m)
        assert abs(np.vdot(target, state)) == pytest.approx(1)
        assert abs(np.vdot(final, state[indices ^ 1])) == pytest.approx(1)
