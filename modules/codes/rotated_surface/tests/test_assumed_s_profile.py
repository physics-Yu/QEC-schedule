"""Synthetic S/EC integration only; unit costs are not experiment evidence."""

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import replace

import pytest

from experiments.msd.fast_guard import no_atom_execution
from modules.codes.rotated_surface.assumed_s_profile import AssumedSProfile
from modules.codes.rotated_surface.factory_assumptions import (
    ECPolicy,
    TransversalSAssumption,
    assumed_factory_recipe,
)
from modules.codes.rotated_surface.fast_factory import acceptance_port, entry_key
from modules.codes.rotated_surface.joint_factory_profile import (
    JointSurfaceFactoryProfile,
    MissingJointCalibration,
)
from modules.codes.rotated_surface.tests.test_generic_fast_factory import (
    fixture_profile,
)
from modules.codes.rotated_surface.tests.test_joint_factory_profile import (
    SyntheticJointProfile,
)
from modules.logical_compiler.examples.surface_factory_fast import run_surface_factory
from modules.logical_compiler.src.protocols.production import (
    ProductionPolicy,
    make_output_sink,
)


class RejectionFixture(SyntheticJointProfile):
    """Unit-control group generator with explicit synthetic raw rejection."""

    def group(self, members):
        group = super().group(members)
        for member in group["raw_ports"]:
            group["raw_ports"][member] = acceptance_port(
                0.75,
                preparation="raw_t_postselection",
                evidence={"test_fixture": True, "physical_calibration": False},
                kind="test_fixture",
            ).to_dict()
        return group


def _fixture_document(distance=3, count=2):
    document = fixture_profile(distance, count).to_dict()
    document["joint_calibration"] = {"family": "synthetic-s-ec", "limits": {}}
    document["metadata"] = {
        "evidence_kind": "synthetic_unit_costs",
        "physical_calibration": False,
    }
    for factory in range(count):
        for role in ("W1", "W2", "W3", "W4", "W5"):
            document["entries"][
                entry_key("se_round", (f"factory{factory}/{role}",))
            ] = {
                "component_id": "se_round",
                "phase_durations_us": [7],
                "measurement_phases": [[0, 0]] * (distance**2 - 1),
                "uses_aod": True,
                "cost_segments": [],
                "primitive_counts": {},
            }
    return document


def _assumption(duration=2):
    return TransversalSAssumption((0.0001, 0.0002, 0.0003), duration)


def _run(base, *, seed=17):
    s = _assumption()
    profile = AssumedSProfile(base, s)
    return run_surface_factory(
        profile,
        seed=seed,
        input_z_error=0.01,
        raw_attempts=32,
        batches=4,
        recipe=assumed_factory_recipe(
            profile.distance, s=s, ec=ECPolicy("after_rotation", "distance")
        ),
        production_policy=ProductionPolicy(2),
        output_sink=make_output_sink(
            {"kind": "ideal_external", "acknowledge_excluded_costs": True}
        ),
    )


def test_s_lookup_has_declared_duration_noise_identity_and_no_results_or_aod():
    with no_atom_execution() as audit:
        base = JointSurfaceFactoryProfile(_fixture_document())
        s = _assumption(2.5)
        profile = AssumedSProfile(base, s)
        layout = profile.layout()
        patch = layout.factories[0].patches[0]
        arguments = {"parameters": {"assumption_id": s.identity}}
        entry = profile.lookup("assumed_transversal_s", (patch,), **arguments)
        declaration = profile.describe(
            "assumed_transversal_s", (patch,), budget=layout.budget, **arguments
        )
        assert entry.phase_durations_us == (2.5,)
        assert entry.measurement_phases == entry.result_ready_offsets_us == ()
        assert entry.claim["result_count"] == declaration.result_count == 0
        assert entry.claim["uses_aod"] is False
        assert declaration.shared_aod is None
        assert declaration.exclusive_resources == ()
        assert declaration.parallel_mode == "local_parallel"
        assert entry.primitive_counts == {"assumed_S": 9}
        assert layout.budget["assumed_transversal_s"] == s.to_dict()
        assert (
            profile.profile_sha256
            != AssumedSProfile(base, replace(s, duration_us=3)).profile_sha256
        )
        assert profile.to_dict()["base"] == base.to_dict()
    assert audit.to_dict()["passed"]


@pytest.mark.parametrize("parameters", [{}, {"assumption_id": "wrong"}])
def test_s_assumption_mismatch_is_rejected(parameters):
    with no_atom_execution() as audit:
        profile = AssumedSProfile(
            JointSurfaceFactoryProfile(_fixture_document()), _assumption()
        )
        patch = profile.layout().factories[0].patches[0]
        with pytest.raises(ValueError, match="TRANSVERSAL_S_ASSUMPTION_MISMATCH"):
            profile.lookup("assumed_transversal_s", (patch,), parameters=parameters)
    assert audit.to_dict()["passed"]


def test_overlay_does_not_create_missing_joint_calibration():
    with no_atom_execution() as audit:
        base = JointSurfaceFactoryProfile(_fixture_document())
        with pytest.raises(MissingJointCalibration) as missing:
            _run(base)
        assert not base.groups
        assert "initialize_plus:factory0/W1" in missing.value.members
        assert "raw_t_postselection:factory1/W2" in missing.value.members
    assert audit.to_dict()["passed"]


def test_recipe_profile_code_mismatch_is_rejected():
    with no_atom_execution() as audit:
        profile = AssumedSProfile(
            JointSurfaceFactoryProfile(_fixture_document()), _assumption()
        )
        wrong = assumed_factory_recipe(5, s=_assumption(), ec=ECPolicy())
        with pytest.raises(ValueError, match="FACTORY_RECIPE_PROFILE_CODE_MISMATCH"):
            run_surface_factory(profile, seed=17, input_z_error=0.01, recipe=wrong)
    assert audit.to_dict()["passed"]


def test_two_cycle_joint_fixture_replays_with_local_retries_ec_and_s_ledger():
    """Exercise the real logical runtime over synthetic, explicitly frozen costs."""
    with no_atom_execution() as audit:
        fixture = RejectionFixture(_fixture_document())
        _run(fixture)
        frozen = fixture.to_dict()
        first = _run(JointSurfaceFactoryProfile(deepcopy(frozen)))
        second = _run(JointSurfaceFactoryProfile(deepcopy(frozen)))
    assert audit.to_dict()["passed"]
    assert first["case"] == second["case"]
    assert first["ledger"] == second["ledger"]
    case, ledger = first["case"], first["ledger"]
    assert case["status"] == "complete", case.get("errors")
    assert case["physical"] is None
    assert ledger["counts"]["accepted_outputs"] == 4
    assert ledger["counts"]["delivered_outputs"] == 4
    assert ledger["counts"]["raw_rejections"] > 0
    calls = case["calls"]
    s_calls = [c for c in calls if c["component_id"] == "assumed_transversal_s"]
    assert s_calls
    assert ledger["counts"]["s_calls"] == len(s_calls)
    assert not any(c["component_id"] == "logical_s" for c in calls)
    assert all(c["end_us"] - c["start_us"] == 2 for c in s_calls)

    decisions = [m for m in case["milestones"] if m["kind"] == "batch_decision"]
    ec_calls = [c for c in calls if c["component_id"] == "se_round"]
    assert len(ec_calls) == len(decisions) * 11 * 3 * 5
    assert ledger["counts"]["se_calls"] == len(ec_calls)
    grouped = defaultdict(list)
    for call in ec_calls:
        grouped[call["batch_id"]].append(call)
    assert any(len(group) == 10 for group in grouped.values())
    assert all(len(group) in (5, 10) for group in grouped.values())
    assert all(len({c["start_us"] for c in group}) == 1 for group in grouped.values())
    for group in grouped.values():
        per_line = Counter(c["factory_id"] for c in group)
        assert all(count == 5 for count in per_line.values())

    raw_calls = [c for c in calls if c["component_id"] == "raw_t_postselection"]
    attempts = Counter(c["invocation_id"].split("/attempt[")[0] for c in raw_calls)
    assert max(attempts.values()) > 1
    assert min(attempts.values()) == 1
    for line in case["factories"].values():
        assert len(line["outputs"]) == 2
        assert len({r["token_id"] for r in line["outputs"]}) == 2
    tokens = {r["token_id"]: r for r in case["resources"]["tokens"]}
    assert all(
        tokens[row["token_id"]]["status"] == "consumed"
        for line in case["factories"].values()
        for row in line["outputs"]
    )
