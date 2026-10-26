"""Center-model integration against saved references, without atom execution."""

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import replace
from itertools import accumulate
from pathlib import Path

import pytest

from experiments.msd.center_metrics import summarize_center_case
from experiments.msd.fast_guard import no_atom_execution
from modules.codes.rotated_surface.assumed_s_profile import AssumedSProfile
from modules.codes.rotated_surface.center_costs import (
    center_component_cost,
    load_center_references,
)
from modules.codes.rotated_surface.center_profile import (
    CenterSurfaceFactoryProfile,
    center_factory_plan,
)
from modules.codes.rotated_surface.factory_assumptions import (
    ECPolicy,
    TransversalSAssumption,
    assumed_factory_recipe,
)
from modules.codes.rotated_surface_d3.protocols.factory_experiment import (
    FactoryExperimentModel,
)
from modules.logical_compiler.examples.surface_factory_fast import run_surface_factory
from modules.logical_compiler.src.protocols.production import (
    ProductionPolicy,
    make_output_sink,
)
from modules.logical_compiler.src.scheduling.compatibility import compatible_specs

REFERENCE = (
    Path(__file__).resolve().parents[4] / "experiments/msd/center-reference-costs.json"
)


@pytest.fixture(scope="module")
def references():
    return load_center_references(REFERENCE)


def _participants(profile, factory, *roles):
    return tuple(
        profile.layout().bindings[f"factory{factory}/{role}"] for role in roles
    )


@pytest.mark.parametrize("distance", [3, 5, 7])
@pytest.mark.parametrize("count", [1, 2, 4, 8])
def test_readout_translation_preserves_rows_and_clears_upper_halfplane(
    references, distance, count
):
    with no_atom_execution() as audit:
        profile = CenterSurfaceFactoryProfile(references, distance, count)
        origins = [
            profile.plan.placements[f"factory{i}/W1"].origin for i in range(count)
        ]
        targets = [(p.x, p.y + profile.translation_y_um) for p in origins]
        assert min(y for _, y in targets) == 50
        assert all(
            x == p.x and y - p.y == profile.translation_y_um
            for p, (x, y) in zip(origins, targets, strict=True)
        )
        assert all(
            targets[i][1] - targets[i + 1][1] == 20 * distance + 40
            for i in range(count - 1)
        )
        assert profile.layout().budget["aod_count"] == 1
    assert audit.to_dict()["passed"]


@pytest.mark.parametrize("distance", [3, 5, 7])
@pytest.mark.parametrize(
    "component",
    [
        "se_round",
        "raw_t_postselection",
        "raw_t_postselection/canonicalize",
        "transversal_cnot",
        "logical_mx",
    ],
)
def test_phase_compression_preserves_cost_integrals_counts_and_result_availability(
    references, distance, component
):
    with no_atom_execution() as audit:
        profile = CenterSurfaceFactoryProfile(references, distance, 2)
        roles = ("W1", "W2") if component == "transversal_cnot" else ("R",)
        participants = _participants(profile, 0, *roles)
        centers = tuple(
            (p.origin.x + 10 * distance, p.origin.y + 10 * distance)
            for p in participants
        )
        original = center_component_cost(
            references,
            distance=distance,
            component_id=component,
            centers=centers,
            readout_center=(centers[0][0], centers[0][1] + profile.translation_y_um),
            movement_us_per_um=1,
        )
        entry = profile.lookup(
            component,
            participants,
            parameters={"injection_rounds": 3}
            if component == "raw_t_postselection"
            else {},
        )
        segments = entry.claim["estimate_segments"]
        assert sum(entry.phase_durations_us) == pytest.approx(original["duration_us"])
        assert sum(
            s["end_offset_us"] - s["start_offset_us"] for s in segments
        ) == pytest.approx(original["duration_us"])
        assert sum(s["busy_atom_us"] for s in segments) == pytest.approx(
            original["busy_atom_us"]
        )
        assert sum(s["movement_distance_atom_um"] for s in segments) == pytest.approx(
            original["movement_distance_atom_um"]
        )
        primitives = Counter()
        for segment in segments:
            primitives.update(segment["primitive_counts"])
        assert (
            dict(primitives) == entry.primitive_counts == original["primitive_counts"]
        )
        old_ends = list(accumulate(original["phase_durations_us"]))
        assert entry.result_ready_offsets_us == pytest.approx(
            tuple(
                old_ends[i] + latency for i, latency in original["measurement_phases"]
            )
        )
        compressed_ends = list(accumulate(entry.phase_durations_us))
        assert tuple(
            compressed_ends[i] + latency for i, latency in entry.measurement_phases
        ) == pytest.approx(entry.result_ready_offsets_us)
        categories = {s["category"] for s in segments}
        for category in categories:
            expected = sum(
                s["busy_atom_us"]
                for s in original["segments"]
                if s["category"] == category
            )
            observed = sum(
                s["busy_atom_us"] for s in segments if s["category"] == category
            )
            assert observed == pytest.approx(expected)
        assert len(segments) <= len(original["segments"])
    assert audit.to_dict()["passed"]


def test_cnot_admission_uses_signed_relative_geometry_and_order(references):
    profile = CenterSurfaceFactoryProfile(references, 3, 2)
    budget = profile.layout().budget

    def spec(factory, control, target):
        return profile.describe(
            "transversal_cnot",
            _participants(profile, factory, control, target),
            budget=budget,
        )

    left, matching = spec(0, "W1", "W2"), spec(1, "W1", "W2")
    shifted = spec(1, "W3", "W4")
    assert (
        left.estimate_batch_key
        == matching.estimate_batch_key
        == shifted.estimate_batch_key
    )
    assert compatible_specs((left, matching))
    assert compatible_specs((left, shifted))
    assert not compatible_specs((left, spec(1, "W1", "W3")))
    assert not compatible_specs((left, spec(1, "W2", "W1")))


def test_raw_supply_reference_is_fixed_across_n_and_separate_from_input_quality(
    references,
):
    small, large = (
        CenterSurfaceFactoryProfile(references, 3, count) for count in (1, 8)
    )
    first, second = (
        profile.preparation_port("raw_t_postselection", "factory0/R")
        for profile in (small, large)
    )
    recorded = references["payload"]["distances"]["3"]["raw_acceptance"]["R"]
    assert (
        first.outcome("accepted").probability
        == second.outcome("accepted").probability
        == recorded["probability"]
    )
    evidence = first.to_dict()["model"]["evidence"]
    assert evidence["geometry_noise_recomputed"] is False
    assert evidence["source_port_sha256"] == recorded["port_sha256"]
    assert (
        evidence["scope"]
        == "archived_singleton_supply_reference_held_fixed_across_geometry"
    )
    quality = FactoryExperimentModel("theory", 0.01).reference_quality(
        "raw_t_postselection"
    )
    assert quality["consumption_parameters"]["input_z_error"] == 0.01
    assert recorded["probability"] != 0.01


def test_profile_rejects_changed_placement_parameters_and_device(references):
    profile = CenterSurfaceFactoryProfile(references, 3, 2)
    patch = _participants(profile, 0, "W1")[0]
    with pytest.raises(ValueError, match="PLACEMENT_CHANGED"):
        profile.layout(placement_plan=center_factory_plan(3, 2, gap_um=60))
    with pytest.raises(ValueError, match="POSITION"):
        profile.lookup(
            "se_round",
            (replace(patch, origin=replace(patch.origin, x=patch.origin.x + 1)),),
        )
    with pytest.raises(ValueError, match="PARAMETERS_CHANGED"):
        profile.lookup(
            "raw_t_postselection", (patch,), parameters={"injection_rounds": 1}
        )
    with pytest.raises(ValueError, match="DEVICE_CHANGED"):
        profile.describe(
            "se_round", (patch,), budget={**profile.layout().budget, "aod_count": 2}
        )


def test_reference_and_noise_views_cannot_change_profile_identity_or_cost(references):
    tampered = deepcopy(references)
    tampered["payload"]["distances"]["3"]["components"]["se_round"]["segments"][0][
        "duration_us"
    ] += 1
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        CenterSurfaceFactoryProfile(tampered, 3, 2)
    profile = CenterSurfaceFactoryProfile(references, 3, 2)
    identity = profile.profile_sha256
    original = profile.lookup("se_round", _participants(profile, 0, "W1"))
    changed = profile.references
    changed["payload"]["distances"]["3"]["components"]["se_round"]["segments"][0][
        "duration_us"
    ] += 100
    noise = profile.noise_params
    noise["readout_flip"] = 0.9
    later = profile.lookup("se_round", _participants(profile, 1, "W1"))
    assert later.phase_durations_us == original.phase_durations_us
    assert later.primitive_counts == original.primitive_counts
    assert profile.profile_sha256 == identity
    assert (
        profile.noise_params["readout_flip"]
        == references["payload"]["noise_params"]["readout_flip"]
    )
    with pytest.raises(AttributeError):
        profile.translation_y_um = 0


def test_small_center_factory_completes_with_retries_s_and_ec_without_atoms(references):
    with no_atom_execution() as audit:
        base = CenterSurfaceFactoryProfile(references, 3, 2)
        assumption = TransversalSAssumption((0.0001, 0.0001, 0.0001))
        profile = AssumedSProfile(base, assumption)
        result = run_surface_factory(
            profile,
            seed=0,
            input_z_error=0.01,
            raw_attempts=32,
            batches=4,
            recipe=assumed_factory_recipe(
                3, s=assumption, ec=ECPolicy("after_rotation", "distance")
            ),
            production_policy=ProductionPolicy(1),
            output_sink=make_output_sink(
                {"kind": "ideal_external", "acknowledge_excluded_costs": True}
            ),
        )
        metrics = summarize_center_case(result["case"], base.plan)
    assert audit.to_dict()["passed"]
    assert result["case"]["physical"] is None
    assert result["case"]["status"] == "complete"
    counts = result["ledger"]["counts"]
    assert counts["accepted_outputs"] == counts["delivered_outputs"] == 2
    assert counts["raw_rejections"] > 0
    assert counts["s_calls"] > 0
    decisions = [
        m for m in result["case"]["milestones"] if m["kind"] == "batch_decision"
    ]
    assert counts["se_calls"] == len(decisions) * 11 * 3 * 5
    assert counts["raw_attempts"] == len(decisions) * 15 + counts["raw_rejections"]
    grouped = defaultdict(list)
    for call in result["case"]["calls"]:
        if call["component_id"] == "se_round":
            grouped[call["batch_id"]].append(call)
    assert any(len(group) == 10 for group in grouped.values())
    assert metrics["configured_atoms"] == 204
    assert metrics["configured_atom_time_us"] == pytest.approx(
        metrics["busy_atom_time_us"] + metrics["idle_atom_time_us"]
    )
    assert metrics["movement_distance_atom_um"] > 0
    assert (
        metrics["atom_time_status"]
        == "component_cost_estimate_not_native_order_timeline"
    )
    assert metrics["actual_output_error"] is None
