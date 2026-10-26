"""Center-distance cost changes preserve archived intrinsic stages and results."""

import json
from pathlib import Path

import pytest

from experiments.msd.fast_guard import no_atom_execution
from modules.codes.rotated_surface.center_costs import (
    center_component_cost,
    load_center_references,
)

REFERENCE = (
    Path(__file__).resolve().parents[4] / "experiments/msd/center-reference-costs.json"
)


@pytest.mark.parametrize("distance", (3, 5, 7))
def test_readout_center_changes_only_explicit_legs_and_keeps_result_phases(distance):
    with no_atom_execution() as audit:
        references = load_center_references(REFERENCE)
        arguments = {
            "distance": distance,
            "component_id": "raw_t_postselection",
            "centers": ((0.0, 0.0),),
            "movement_us_per_um": 1.0,
        }
        near = center_component_cost(
            references, readout_center=(0.0, 100.0), **arguments
        )
        far = center_component_cost(
            references, readout_center=(0.0, 150.0), **arguments
        )
    assert audit.to_dict()["passed"]
    legs = 0
    for left, right in zip(near["segments"], far["segments"], strict=True):
        if left["travel_kind"] == "readout":
            legs += 1
            assert right["duration_us"] - left["duration_us"] == 50.0
            assert (
                right["movement_distance_atom_um"] - left["movement_distance_atom_um"]
                == 50 * left["atom_count"]
            )
        else:
            assert right["duration_us"] == left["duration_us"]
            assert (
                right["movement_distance_atom_um"] == left["movement_distance_atom_um"]
            )
    assert legs == (6 if distance == 3 else 18)
    assert far["duration_us"] - near["duration_us"] == pytest.approx(50 * legs)
    assert near["measurement_phases"] == far["measurement_phases"]
    assert len(near["measurement_phases"]) == 24
    assert near["primitive_counts"] == far["primitive_counts"]


def test_cnot_uses_ordered_control_to_target_offset_and_two_legs():
    references = load_center_references(REFERENCE)
    result = center_component_cost(
        references,
        distance=3,
        component_id="transversal_cnot",
        centers=((0.0, 0.0), (3.0, 4.0)),
        readout_center=(0.0, 50.0),
        movement_us_per_um=2.0,
        cnot_target_offset_um=(0.0, 0.0),
    )
    movement = [s for s in result["segments"] if s["travel_kind"] == "cnot"]
    assert [s["duration_us"] for s in movement] == [10.0, 10.0]
    assert [s["movement_distance_atom_um"] for s in movement] == [45.0, 45.0]
    assert result["duration_us"] == pytest.approx(64.5)
    assert result["primitive_counts"]["cz"] == 9
    assert result["measurement_phases"] == []


@pytest.mark.parametrize("distance", (3, 5, 7))
def test_se_reference_is_one_ordinary_round_and_init_has_unchanged_prefix(distance):
    references = load_center_references(REFERENCE)
    components = references["payload"]["distances"][str(distance)]["components"]
    se, init = components["se_round"], components["initialize_plus"]
    assert len(se["measurement_phases"]) == distance**2 - 1
    assert init["segments"][3:] == se["segments"]
    assert [s["duration_us"] for s in init["segments"][:3]] == [5, 1, 1]
    assert sum(
        s["primitive_counts"].get("cz", 0) for s in se["segments"]
    ) == 4 * distance * (distance - 1)
    assert sum(s["travel_kind"] == "readout" for s in se["segments"]) == 2


def test_modified_bundle_is_rejected(tmp_path):
    document = json.loads(REFERENCE.read_text(encoding="utf-8"))
    document["payload"]["distances"]["3"]["components"]["se_round"]["segments"][0][
        "duration_us"
    ] += 1
    path = tmp_path / "modified.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="HASH_MISMATCH"):
        load_center_references(path)


@pytest.mark.parametrize("point,timing", (((float("nan"), 0), 1), ((0, 0), -1)))
def test_invalid_geometry_and_timing_fail_closed(point, timing):
    references = load_center_references(REFERENCE)
    with pytest.raises(ValueError):
        center_component_cost(
            references,
            distance=3,
            component_id="se_round",
            centers=(point,),
            readout_center=(0.0, 100.0),
            movement_us_per_um=timing,
        )
