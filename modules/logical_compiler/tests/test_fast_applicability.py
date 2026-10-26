"""Fast execution requires applicable saved records, not fresh atom compilation."""

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from pathlib import Path

import pytest

from modules.codes.rotated_surface_d3.protocols.fast_context import component_context
from modules.codes.rotated_surface_d3.protocols.fast_profile import (
    FastProfile,
    make_fast_layout,
)
from modules.codes.rotated_surface_d3.tests.test_fast_profile import profile_document
from modules.logical_compiler.src.estimation.calibration import (
    CalibrationCache,
    CalibrationRecord,
    MissingCalibration,
)
from modules.logical_compiler.src.estimation.kernel import ProfileExecutionKernel


def recorded_profile(component="logical_x"):
    document = profile_document()
    source = "modules/codes/rotated_surface_d3/definition.py"
    root = Path(__file__).resolve().parents[3]
    document["provenance"] = {
        "kind": "offline_physical_calibration",
        "source_hashes": {source: sha256((root / source).read_bytes()).hexdigest()},
    }
    profile = FastProfile.from_dict(document)
    layout = make_fast_layout(profile, 1)
    entry = document["entries"][component]
    context = component_context(
        document, layout.placement_plan, ("factory0/W1",), entry, layout.budget
    )
    document["applicability"] = {
        "schema": "nadit.fast_surface_applicability/1",
        "records": [
            CalibrationRecord(
                context, entry, {"kind": "unit_fixture_model", "variant_key": component}
            ).to_dict()
        ],
    }
    return FastProfile.from_dict(document)


def test_existing_record_reuses_across_more_far_factories_without_compilation(
    monkeypatch,
):
    from nadit_physical_compiler import compiler

    monkeypatch.setattr(
        compiler,
        "compile_physical",
        lambda *a, **k: pytest.fail("no physical compilation"),
    )
    profile = recorded_profile()
    cache = CalibrationCache()
    first = ProfileExecutionKernel(
        profile, make_fast_layout(profile, 1), calibration_cache=cache
    )
    second = ProfileExecutionKernel(
        profile, make_fast_layout(profile, 3), calibration_cache=cache
    )
    a, b = (
        first.layout.factories[0].bindings["W1"],
        second.layout.factories[2].bindings["W1"],
    )
    assert first.profile.lookup("logical_x", (a,)) == second.profile.lookup(
        "logical_x", (b,)
    )
    assert len(cache.to_dict()["records"]) == 1
    assert (
        first.layout.placement_plan.geometry_fingerprint
        != second.layout.placement_plan.geometry_fingerprint
    )
    assert first.profile.calibration_key(
        "logical_x", (a,)
    ) == second.profile.calibration_key("logical_x", (b,))


def test_readout_geometry_change_produces_structured_missing_calibration():
    profile = recorded_profile("logical_mz")
    layout = make_fast_layout(profile, 1)
    budget = deepcopy(layout.budget)
    budget["readout_bounds_um"][1] += 5
    kernel = ProfileExecutionKernel(profile, replace(layout, budget=budget))
    with pytest.raises(MissingCalibration) as error:
        kernel.profile.lookup("logical_mz", (layout.factories[0].bindings["W1"],))
    assert error.value.missing.reason == "not_calibrated"
    assert (
        kernel.snapshot()["calibration"]["missing"][0]["key_fingerprint"]
        == error.value.missing.key.fingerprint
    )
    assert kernel.clock_us == 0 and not kernel.used


def test_changed_component_sources_and_legacy_missing_context_are_rejected():
    document = recorded_profile().to_dict()
    source = next(iter(document["provenance"]["source_hashes"]))
    document["provenance"]["source_hashes"][source] = "0" * 64
    profile = FastProfile.from_dict(document)
    with pytest.raises(ValueError, match="CHANGED_CALIBRATION_IMPLEMENTATION"):
        ProfileExecutionKernel(profile, make_fast_layout(profile, 1))
    original = recorded_profile().to_dict()
    original.pop("applicability")
    profile = FastProfile.from_dict(original)
    with pytest.raises(ValueError, match="UNCALIBRATED_PROFILE_CONTEXT"):
        ProfileExecutionKernel(profile, make_fast_layout(profile, 1))


def test_profile_binding_checks_actual_storage_region_once():
    profile = recorded_profile()
    layout = make_fast_layout(profile, 1)
    budget = {**layout.budget, "shared_bounds_um": [0, 0, 100, 10]}
    with pytest.raises(ValueError, match="PLACEMENT_OUTSIDE_DEVICE_REGION"):
        ProfileExecutionKernel(profile, replace(layout, budget=budget))


def test_budget_mutation_cannot_reuse_a_memoized_context():
    profile = recorded_profile()
    layout = make_fast_layout(profile, 1)
    kernel = ProfileExecutionKernel(profile, layout)
    participants = (layout.factories[0].bindings["W1"],)
    kernel.profile.lookup("logical_x", participants)
    layout.budget["readout_bounds_um"][1] += 10
    with pytest.raises(ValueError, match="DEVICE_CONTEXT_CHANGED"):
        kernel.profile.lookup("logical_x", participants)


def test_production_lookup_rejects_explicit_fixture_evidence():
    document = recorded_profile().to_dict()
    document["applicability"]["records"][0]["evidence"]["kind"] = "test_fixture"
    profile = FastProfile.from_dict(document)
    layout = make_fast_layout(profile, 1)
    kernel = ProfileExecutionKernel(profile, layout)
    with pytest.raises(ValueError, match="TEST_FIXTURE_IS_NOT_PHYSICAL"):
        kernel.profile.lookup("logical_x", (layout.factories[0].bindings["W1"],))


def test_mismatched_carrier_coordinates_cannot_borrow_plan_cache_identity():
    from nadit_physical_compiler.device import Position

    profile = recorded_profile()
    layout = make_fast_layout(profile, 1)
    factory = layout.factories[0]
    patch = replace(factory.patches[0], origin=Position(20, 0))
    altered = replace(
        layout, factories=(replace(factory, patches=(patch, *factory.patches[1:])),)
    )
    with pytest.raises(ValueError, match="PLACEMENT_CARRIER_BINDINGS_MISMATCH"):
        ProfileExecutionKernel(profile, altered)


def test_permuted_roles_cannot_reuse_relative_slot_activity():
    from modules.codes.rotated_surface_d3.protocols.fast_layout import layout_from_plan
    from modules.logical_compiler.src.placement import (
        ExplicitPlacement,
        PlacementRequest,
        place,
    )

    document = profile_document()
    document["entries"]["logical_x"]["busy"].append([1, 0, 0, 1, "Rotation", "slm"])
    document["entries"]["logical_x"]["claim"]["spaces"][0][2] = 160
    profile = FastProfile.from_dict(document)
    original = make_fast_layout(profile, 1)
    plan = original.placement_plan
    positions = dict(plan.placements)
    positions["factory0/W2"], positions["factory0/W3"] = (
        positions["factory0/W3"],
        positions["factory0/W2"],
    )
    permuted = place(
        PlacementRequest(plan.blocks, plan.geometries, positions=positions),
        ExplicitPlacement(),
    )
    layout = layout_from_plan(
        permuted,
        **{
            key: original.budget[key]
            for key in (
                "shared_bounds_um",
                "readout_bounds_um",
                "aod_workspace_bounds_um",
            )
        },
    )
    kernel = ProfileExecutionKernel(profile, layout)
    with pytest.raises(ValueError, match="UNCALIBRATED_ACTIVITY_ROLE_LAYOUT"):
        kernel.profile.lookup("logical_x", (layout.factories[0].bindings["W1"],))
