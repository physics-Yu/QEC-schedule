"""Abstract layouts and fail-closed calibrated component lookup."""

from copy import deepcopy

import pytest

from modules.codes.rotated_surface_d3.protocols.fast_profile import (
    FastProfile,
    make_fast_layout,
)


def profile_document():
    """Provide a small explicit test calibration, without physical evidence claims."""
    base = {
        "component_id": "logical_x",
        "geometry": [],
        "selection_class": None,
        "waveform_key": "local-test",
        "phase_durations_us": [1.0],
        "measurement_phases": [],
        "result_ready_offsets_us": [],
        "cost_segments": [
            {
                "start_offset_us": 0,
                "end_offset_us": 1,
                "category": "gate",
                "resource": "local",
            }
        ],
        "primitive_counts": {"rotation_targets": 1},
        "events": [
            {
                "offset_us": 0,
                "duration_us": 1,
                "kind": "Rotation",
                "log_survival": -0.01,
            }
        ],
        "busy": [[0, 0, 0, 1, "Rotation", "slm"]],
        "claim": {
            "parallel_mode": "local_parallel",
            "result_count": 0,
            "spaces": [[0, 0, 60, 60, "local_addressing"]],
            "shared": None,
        },
    }
    entries = {"logical_x": deepcopy(base)}
    for prep in ("initialize_plus", "raw_t_postselection"):
        for value in range(16):
            item = deepcopy(base)
            item["component_id"] = prep + "/canonicalize"
            item["selection_class"] = value
            if value == 0:
                for key in ("phase_durations_us", "cost_segments", "events", "busy"):
                    item[key] = []
            entries[f"{prep}/canonicalize:{value}"] = item
    measurement = deepcopy(base)
    measurement.update(
        component_id="logical_mz",
        waveform_key="mz-test",
        phase_durations_us=[20, 10, 20],
        measurement_phases=[[1, 500]] * 9,
        result_ready_offsets_us=[530] * 9,
        events=[],
        busy=[],
        cost_segments=[],
        primitive_counts={},
    )
    measurement["claim"] = {
        "parallel_mode": "shared_aod_lockstep",
        "result_count": 9,
        "spaces": [[-5, -5, 70, 115, "measurement"]],
        "shared": {"band": [0, 62], "rows": 3, "columns": 3, "readout_atoms": 9},
    }
    entries["logical_mz"] = measurement
    return {
        "schema": "nadit.fast_surface_factory_profile/1",
        "code_id": "rotated_surface_d3",
        "distance": 3,
        "control": {
            "aod": {"motion": "flexible", "min_spacing": 1},
            "readout": {"channel": "camera"},
        },
        "noise_params": {
            "exposure": {
                "slm_t2_us": None,
                "aod_t2_us": None,
                "include_transport": True,
            },
            "transport": {"slm_loss_per_us": 0, "aod_loss_per_us": 0},
        },
        "provenance": {"kind": "test_fixture"},
        "entries": entries,
        "preparation_ports": {},
        "consumption_port": {},
    }


def test_layout_has_only_patches_and_fixed_shared_capacity():
    profile = FastProfile.from_dict(profile_document())
    layout = make_fast_layout(profile, 100)
    assert len(layout.bindings) == 600
    assert layout.budget["aod_max_columns"] == 48
    assert layout.budget["max_readout_atoms"] == 96
    assert layout.factories[1].bindings["W1"].origin.x == 620
    assert not hasattr(layout.factories[0].bindings["W1"], "atom_ids")
    assert not hasattr(layout, "world_state")
    patch = layout.factories[0].bindings["W1"]
    entry = profile.lookup("logical_mz", (patch,))
    assert entry.action_duration_us == 50
    assert entry.results_ready_offset_us == 530
    spec = profile.describe("logical_mz", (patch,), budget=layout.budget)
    assert spec.shared_aod.max_columns == 48
    assert spec.shared_aod.peak_readout_atoms == 9


def test_lookup_requires_covered_parameters_and_selected_correction():
    profile = FastProfile.from_dict(profile_document())
    layout = make_fast_layout(profile, 2)
    patch = layout.factories[0].bindings["W1"]
    with pytest.raises(ValueError, match="UNCALIBRATED"):
        profile.lookup("logical_s", (patch,))
    with pytest.raises(ValueError, match="CORRECTION"):
        profile.lookup("initialize_plus/canonicalize", (patch,))
    with pytest.raises(ValueError, match="PARAMETERS"):
        profile.lookup("logical_x", (patch,), parameters=(("extra_rounds", 2),))
    zero = profile.lookup(
        "initialize_plus/canonicalize",
        (patch,),
        {"accepted": True, "byproduct_class": 0},
    )
    assert zero.action_duration_us == 0
    assert zero.events == zero.busy == ()


def test_capacity_override_is_used_and_cannot_understate_demand():
    profile = FastProfile.from_dict(profile_document())
    layout = make_fast_layout(profile, 2, aod_max_columns=9, max_readout_atoms=18)
    patch = layout.factories[0].bindings["W1"]
    spec = profile.describe("logical_mz", (patch,), budget=layout.budget)
    assert spec.shared_aod.max_columns == 9
    assert spec.shared_aod.max_readout_atoms == 18
    with pytest.raises(ValueError, match="CAPACITY"):
        profile.describe(
            "logical_mz", (patch,), budget=layout.budget | {"max_readout_atoms": 8}
        )


def test_profile_rejects_missing_correction_classes():
    document = profile_document()
    del document["entries"]["raw_t_postselection/canonicalize:7"]
    with pytest.raises(ValueError, match="CORRECTION_COVERAGE"):
        FastProfile.from_dict(document)


@pytest.mark.parametrize(
    "invalid", ("result_offset", "phase_index", "segment_end", "category", "resource")
)
def test_profile_rejects_inconsistent_timing_or_cost_segments_on_load(invalid):
    document = profile_document()
    if invalid == "result_offset":
        document["entries"]["logical_mz"]["result_ready_offsets_us"][0] = 531
    elif invalid == "phase_index":
        document["entries"]["logical_mz"]["measurement_phases"][0][0] = True
    else:
        segment = document["entries"]["logical_x"]["cost_segments"][0]
        segment[
            {
                "segment_end": "end_offset_us",
                "category": "category",
                "resource": "resource",
            }[invalid]
        ] = 2 if invalid == "segment_end" else "unknown"
    with pytest.raises(ValueError, match="FAST_PROFILE"):
        FastProfile.from_dict(document)


def test_runtime_profile_cannot_mutate_without_changing_its_recorded_document():
    profile = FastProfile.from_dict(profile_document())
    original = profile.to_dict()
    profile.noise_params["exposure"]["slm_t2_us"] = 1
    profile.control["aod"]["min_spacing"] = 2
    assert profile.noise_params == original["noise_params"]
    assert profile.control == original["control"]
    entry = profile.entries["logical_x"]
    with pytest.raises(TypeError):
        entry.events[0]["log_survival"] = -1
    with pytest.raises(TypeError):
        entry.claim["spaces"][0][0] = 1
    with pytest.raises(TypeError):
        profile.entries["logical_x"] = entry
    assert profile.to_dict() == original
