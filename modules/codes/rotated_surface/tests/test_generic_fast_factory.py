"""Generic factory admission, code identity and accepted-only growth regression."""

from dataclasses import replace

import pytest

from modules.codes.rotated_surface.fast_factory import (
    SurfaceFactoryProfile,
    factory_recipe,
)
from modules.logical_compiler.examples.surface_factory_fast import run_surface_factory


def fixture_profile(distance=5, count=1):
    """Synthetic timings for control tests only; never experimental evidence."""
    from modules.codes.rotated_surface.fast_factory import (
        ROLES,
        SCHEMA,
        acceptance_port,
        entry_key,
        required_variants,
    )

    patches, entries, ports = [], {}, {}
    for i in range(count):
        for slot, role in enumerate(ROLES):
            block = f"factory{i}/{role}"
            patches.append(
                {
                    "block_id": block,
                    "factory_id": f"factory{i}",
                    "role": role,
                    "slot": slot,
                    "origin": [100 * slot, -100 * i],
                }
            )
            ports[block] = acceptance_port(
                1,
                preparation="raw_t_postselection",
                evidence={"test_fixture": True},
                kind="test_fixture",
            ).to_dict()
        for component, roles in required_variants(distance):
            blocks = tuple(f"factory{i}/{r}" for r in roles)
            measured = (
                4
                if component == "raw_t_postselection"
                else 1
                if component in ("initialize_plus", "logical_mx", "logical_mz")
                else 0
            )
            duration = 1 if component.endswith("/canonicalize") else 10 + i
            entries[entry_key(component, blocks)] = {
                "component_id": component,
                "phase_durations_us": [duration],
                "measurement_phases": [[0, 0]] * measured,
                "uses_aod": not component.endswith("/canonicalize"),
                "cost_segments": [
                    {
                        "start_offset_us": 0,
                        "end_offset_us": duration,
                        "category": "movement",
                        "resource": "aod",
                    }
                ],
                "primitive_counts": {},
            }
    return SurfaceFactoryProfile(
        {
            "schema": SCHEMA,
            "distance": distance,
            "factory_count": count,
            "noise_params": {},
            "patches": patches,
            "entries": entries,
            "raw_ports": ports,
        }
    )


@pytest.mark.parametrize("distance", (3, 5, 7, 9))
def test_recipe_retains_fifteen_inputs_and_small_seed_policy(distance):
    recipe = factory_recipe(distance)
    assert recipe.code_id == f"rotated_surface_d{distance}"
    assert len(recipe.rotations) == 11
    assert len([p for p in recipe.initial_preparations if p.resource_kind]) == 4
    for preparation in (
        *recipe.initial_preparations[1:],
        *(r.preparation for r in recipe.rotations),
    ):
        assert dict(preparation.parameters) == {"injection_rounds": 3}
        assert preparation.resource_kind == f"rotated_surface_d{distance}/A"


@pytest.mark.parametrize("count", (1, 3, 7))
def test_arbitrary_module_count_shared_runtime_and_no_physical_fallback(
    count, monkeypatch
):
    import nadit_physical_compiler.compiler as physical

    def forbidden(*args, **kwargs):
        raise AssertionError("fast execution called a physical compiler")

    monkeypatch.setattr(physical, "compile_physical", forbidden)
    profile = fixture_profile(5, count)
    result = run_surface_factory(profile, seed=0, input_z_error=0)
    assert result["summary"]["outputs"] == count
    assert result["summary"]["raw_attempts"] == 15 * count
    assert result["summary"]["growth_calls"] == 15 * count
    assert result["case"]["physical"] is None
    calls = result["case"]["calls"]
    reservations = [c for c in calls if c.get("reserved_resources")]
    intervals = sorted((c["start_us"], c["action_end_us"]) for c in reservations)
    assert all(
        a[1] <= b[0] + 1e-8 for a, b in zip(intervals, intervals[1:], strict=False)
    )


def test_independent_aod_control_allows_real_temporal_overlap():
    result = run_surface_factory(
        fixture_profile(7, 3),
        seed=0,
        input_z_error=0,
        hardware="independent_aod_control",
    )
    calls = result["case"]["calls"]
    assert any(len(w["invocations"]) > 1 for w in result["case"]["execution"]["waves"])
    assert result["summary"]["hardware"]["aod_count"] == 3
    assert result["summary"]["outputs"] == 3
    assert any(
        a["start_us"] == b["start_us"] for a, b in zip(calls, calls[1:], strict=False)
    )


def test_missing_calibration_fails_closed():
    profile = fixture_profile()
    patch = profile.layout().factories[0].patches[0]
    with pytest.raises(ValueError, match="UNCALIBRATED"):
        profile.lookup("new_component", (patch,))
    with pytest.raises(ValueError, match="UNCALIBRATED"):
        profile.lookup(
            "initialize_plus",
            (replace(patch, origin=replace(patch.origin, y=patch.origin.y - 10)),),
        )


def test_zero_acceptance_never_grows_and_exhausts_only_raw_supply():
    doc = fixture_profile().to_dict()
    for port in doc["raw_ports"].values():
        port["outcomes"][0]["probability"] = 0
        port["outcomes"][1]["probability"] = 1
    result = run_surface_factory(SurfaceFactoryProfile(doc), seed=1, input_z_error=0)
    assert result["summary"]["outputs"] == 0
    assert result["summary"]["growth_calls"] == 0
