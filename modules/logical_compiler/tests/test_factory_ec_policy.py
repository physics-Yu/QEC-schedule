"""Explicit factory assumptions and EC control flow; no atom compilation."""

from dataclasses import replace

import pytest
from test_factory_execution import CODE, FixtureBound, toy_recipe
from test_scheduled_factory import BatchedPhysical, DeclaredBackend

from modules.codes.contracts.factory_recipe import ComponentCall
from modules.codes.rotated_surface.factory_assumptions import (
    ECPolicy,
    TransversalSAssumption,
    assumed_factory_recipe,
)
from modules.logical_compiler.src.protocols.factory import (
    FactoryExecutor,
    _validate_recipe,
)


def test_s_configuration_is_explicit_immutable_and_identified():
    first = TransversalSAssumption((0.001, 0.002, 0.003))
    assert first.duration_us == 1
    assert first.identity == TransversalSAssumption((0.001, 0.002, 0.003)).identity
    assert first.identity != replace(first, duration_us=2).identity
    assert first.identity != replace(first, pauli_error=(0.001, 0.002, 0.004)).identity
    assert first.to_dict()["physical_logical_implementation_verified"] is False
    assert first.to_dict()["noise"]["scope"] == "independent_per_data_atom"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"duration_us": 0},
        {"duration_us": float("inf")},
        {"duration_us": True},
        {"pauli_error": (-0.1, 0, 0)},
        {"pauli_error": (0.5, 0.5, 0.1)},
        {"pauli_error": (0, float("nan"), 0)},
        {"pauli_error": [0, 0, 0]},
        {"pauli_error": (0, 0)},
    ],
)
def test_invalid_s_assumptions_are_rejected(kwargs):
    with pytest.raises(ValueError):
        TransversalSAssumption(**{"pauli_error": (0, 0, 0), **kwargs})


@pytest.mark.parametrize(
    "mode,rounds",
    [
        ("unknown", 0),
        ("preparation_only", 1),
        ("after_rotation", 0),
        ("after_rotation", True),
        ("after_rotation", -1),
    ],
)
def test_invalid_ec_policies_are_rejected(mode, rounds):
    with pytest.raises(ValueError):
        ECPolicy(mode, rounds)


@pytest.mark.parametrize("roles", [("R",), ("missing",), ("W1", "W1")])
def test_ec_cannot_touch_consumed_or_unknown_carriers(roles):
    original = toy_recipe()
    rotation = replace(
        original.rotations[0],
        post_rotation_rounds=((ComponentCall("ec", "toy.se", roles),),),
    )
    with pytest.raises(ValueError, match="distinct work roles"):
        _validate_recipe(replace(original, rotations=(rotation,)), {"W1", "W2", "R"})


def test_ec_key_cannot_alias_final_measurement():
    original = toy_recipe()
    rotation = replace(
        original.rotations[0],
        post_rotation_rounds=((ComponentCall("final/mx", "toy.se", ("W1",)),),),
    )
    with pytest.raises(ValueError, match="unique keys"):
        _validate_recipe(replace(original, rotations=(rotation,)), {"W1", "W2", "R"})


@pytest.mark.parametrize("distance", [3, 5, 7])
def test_surface_recipe_retains_circuit_and_adds_independent_ec(distance):
    assumption = TransversalSAssumption((0.0001, 0.0001, 0.0001))
    ec = ECPolicy("after_rotation", "distance")
    recipe = assumed_factory_recipe(distance, s=assumption, ec=ec)
    assert len(recipe.rotations) == 11
    assert (
        sum(len(r.compute_calls) + len(r.uncompute_calls) + 1 for r in recipe.rotations)
        == 59
    )
    assert [p.role for p in recipe.initial_preparations] == list(recipe.work_roles)
    for rotation in recipe.rotations:
        assert len(rotation.post_rotation_rounds) == distance
        assert all(
            tuple(c.participant_roles[0] for c in group) == recipe.work_roles
            for group in rotation.post_rotation_rounds
        )
        assert all(
            c.component_id == "se_round"
            for group in rotation.post_rotation_rounds
            for c in group
        )
        assert rotation.consumption.branches[0].calls == ()
        s_call = rotation.consumption.branches[1].calls[0]
        assert s_call.component_id == "assumed_transversal_s"
        assert dict(s_call.parameters) == {"assumption_id": assumption.identity}
    old = assumed_factory_recipe(distance, s=assumption, ec=ECPolicy())
    assert all(r.post_rotation_rounds == () for r in old.rotations)
    assert old.protocol_id != recipe.protocol_id
    assert ec.to_dict(distance)["waiting_maintenance"] == "omitted"
    assert ec.to_dict(distance)["syndrome_interpretation"] == "unobserved_cost_only"


def _ec_case(outcome):
    """Use the existing clock/result harness, which generates no atom actions."""
    original = toy_recipe()
    rounds = tuple(
        tuple(
            ComponentCall(f"rotation/ec[{i}]/{role}", "toy.se", (role,))
            for role in original.work_roles
        )
        for i in range(2)
    )
    recipe = replace(
        original,
        rotations=(replace(original.rotations[0], post_rotation_rounds=rounds),),
    )

    class Backend(DeclaredBackend):
        def describe_execution(self, component_id, participants, parameters=()):
            result = super().describe_execution(component_id, participants, parameters)
            if component_id == "toy.se":
                return replace(
                    result,
                    waveform_key="toy.se",
                    parallel_mode="independent_aods_lockstep",
                    result_count=1,
                )
            return result

        def bind_call(self, component_id, participant_bindings, parameters=()):
            if component_id == "toy.se":
                return FixtureBound(component_id, participant_bindings, 1)
            return super().bind_call(component_id, participant_bindings, parameters)

    clock = BatchedPhysical()
    result = (
        FactoryExecutor(
            code=CODE,
            recipe=recipe,
            backend=Backend({"t:rotation": (outcome,)}),
            physical=clock,
            role_bindings={r: r for r in clock.bindings},
            distance=1,
            case_id="ec-policy-fixture",
            seed=17,
        )
        .run()
        .to_dict()
    )
    return result, clock


@pytest.mark.parametrize("outcome", ["m0", "m1"])
def test_ec_runs_after_uncompute_on_both_feedback_branches_and_joins_results(outcome):
    result, _ = _ec_case(outcome)
    assert result["status"] == "complete"
    calls = result["calls"]
    ec = [c for c in calls if c["component_id"] == "toy.se"]
    assert len(ec) == 4
    uncompute = next(c for c in calls if c["component_id"] == "toy.uncompute")
    measurement = next(c for c in calls if c["component_id"] == "toy.mx")
    groups = {}
    for call in ec:
        groups.setdefault(call["batch_id"], []).append(call)
        assert call["start_us"] >= uncompute["end_us"]
    waves = list(groups.values())
    assert [len(wave) for wave in waves] == [2, 2]
    assert waves[1][0]["start_us"] >= waves[0][0]["end_us"] + 3
    assert measurement["start_us"] >= waves[1][0]["end_us"] + 3
    assert sum(c["component_id"] == "toy.s" for c in calls) == int(outcome == "m1")
    completed = [m for m in result["milestones"] if m["kind"] == "ec_round_complete"]
    assert len(completed) == 2
    assert all(
        mark["at_us"] >= wave[0]["end_us"] + 3
        and mark["syndrome_interpretation"] == "unobserved_cost_only"
        for mark, wave in zip(completed, waves, strict=True)
    )
