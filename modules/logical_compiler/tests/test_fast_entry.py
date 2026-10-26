"""The experimental CLI keeps explicit calibration and usable local artifacts."""

import json
from dataclasses import replace

import pytest

from modules.codes.rotated_surface_d3.protocols.fast_profile import FastProfile
from modules.logical_compiler.examples.factory_fast import main, run_fast, sweep
from modules.logical_compiler.src.estimation.calibration import CalibrationCache
from modules.logical_compiler.tests.test_fast_experiment_review import (
    _complete_document,
)


def test_cli_exports_only_logical_artifacts_and_requires_explicit_profile(tmp_path):
    profile_path = tmp_path / "profile.json"
    profile_path.write_text(json.dumps(_complete_document()), encoding="utf-8")
    output = tmp_path / "run"
    assert (
        main(
            [
                "run",
                "--acceptance-model",
                "physical_no_fault_proxy",
                "--code",
                "rotated_surface_d3",
                "--profile",
                str(profile_path),
                "--output",
                str(output),
                "--seed",
                "1",
            ]
        )
        == 0
    )
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    assert summary["physical_validation"] == "not_run"
    assert summary["physical_validation_ok"] is None
    assert summary["outputs"] == 2
    assert summary["accounting"]["resource_sum_is_elapsed"] is False
    assert (output / "resource-events.jsonl").read_text(encoding="utf-8").strip()
    page = (output / "index.html").read_text(encoding="utf-8")
    assert "Logical estimates" in page and "atom-replay" not in page
    assert not (output / "atom-program.json").exists()
    with pytest.raises(FileNotFoundError):
        main(
            [
                "run",
                "--acceptance-model",
                "physical_no_fault_proxy",
                "--code",
                "rotated_surface_d3",
                "--profile",
                str(tmp_path / "missing.json"),
                "--output",
                str(tmp_path / "missing-run"),
            ]
        )
    assert not (tmp_path / "missing-run").exists()


def test_sweep_retains_fixed_capacity_and_all_seed_line_ledgers(tmp_path):
    output = tmp_path / "sweep"
    cache = CalibrationCache()
    result = sweep(
        FastProfile.from_dict(_complete_document()),
        code="rotated_surface_d3",
        acceptance_model="physical_no_fault_proxy",
        factory_counts=[1, 2],
        seeds=[0, 1],
        output=output,
        calibration_cache=cache,
    )
    assert result["all_runs_completed"]
    assert result["capacity_scales_with_factory_count"] is False
    assert result["statistics_unit"] == "independent_seed_trajectory"
    assert all(group["independent_seed_runs"] == 2 for group in result["groups"])
    assert len(result["sample_files"]) == 4
    restored = CalibrationCache.load(output / result["calibration_cache_file"])
    assert restored.to_dict() == cache.to_dict()
    assert restored.to_dict()["records"]
    for name in result["sample_files"]:
        sample = json.loads((output / name).read_text(encoding="utf-8"))
        assert len(sample["lines"]) == sample["factory_count"]
        assert sample["configuration"]["device_budget"]["aod_max_columns"] == 48
        assert sample["configuration"]["device_budget"]["max_readout_atoms"] == 96
    assert "Uncertainty" in (output / "index.html").read_text(encoding="utf-8")


def test_fast_entry_rejects_implicit_or_wrong_code_and_invalid_sweep(tmp_path):
    profile = FastProfile.from_dict(_complete_document())
    with pytest.raises(ValueError, match="EXPLICIT_SUPPORTED_CODE"):
        run_fast(profile, code="unknown", seed=0)
    with pytest.raises(ValueError, match="DISTINCT"):
        sweep(
            profile,
            code="rotated_surface_d3",
            acceptance_model="physical_no_fault_proxy",
            factory_counts=[1],
            seeds=[1, 1],
            output=tmp_path / "invalid",
        )


@pytest.mark.parametrize("command", ["run", "sweep"])
def test_cli_rejects_serial_throttling_before_loading_a_profile(command, tmp_path):
    with pytest.raises(SystemExit) as error:
        main(
            [
                command,
                "--code",
                "rotated_surface_d3",
                "--profile",
                str(tmp_path / "unused-profile.json"),
                "--output",
                str(tmp_path / "unused-output"),
                "--input-z-error",
                "0.01",
                "--max-parallel",
                "1",
            ]
        )
    assert error.value.code == 2
    assert not (tmp_path / "unused-output").exists()


def test_fast_api_has_no_artificial_parallelism_limit(tmp_path):
    profile = FastProfile.from_dict(_complete_document())
    with pytest.raises(TypeError, match="max_parallel"):
        run_fast(
            profile,
            code="rotated_surface_d3",
            seed=0,
            input_z_error=0.01,
            max_parallel=1,
        )
    with pytest.raises(TypeError, match="max_parallel"):
        sweep(
            profile,
            code="rotated_surface_d3",
            factory_counts=[2],
            seeds=[0],
            output=tmp_path / "unused-sweep",
            input_z_error=0.01,
            max_parallel=1,
        )
    assert not (tmp_path / "unused-sweep").exists()


def test_explicit_factory_plan_is_used_without_layout_generation_or_physical_work(
    monkeypatch,
):
    from modules.codes.rotated_surface_d3.protocols.factory_backend import (
        SurfaceFactoryBackend,
    )
    from modules.codes.rotated_surface_d3.protocols.factory_experiment import (
        FactoryExperimentModel,
    )
    from modules.codes.rotated_surface_d3.protocols.fast_layout import (
        legacy_factory_plan,
    )
    from modules.logical_compiler.examples import factory_fast as entry

    plan = legacy_factory_plan(3)
    profile = FastProfile.from_dict(_complete_document())

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "Explicit logical compilation must not regenerate placement or bind atoms"
        )

    monkeypatch.setattr(entry, "make_fast_layout", forbidden)
    monkeypatch.setattr(SurfaceFactoryBackend, "bind_call", forbidden)
    recipe = FactoryExperimentModel("physical_no_fault_proxy").recipe()
    first = run_fast(
        profile,
        code="rotated_surface_d3",
        seed=1,
        acceptance_model="physical_no_fault_proxy",
        placement_plan=plan,
        recipe=recipe,
    )
    replay = run_fast(
        profile,
        code="rotated_surface_d3",
        seed=1,
        acceptance_model="physical_no_fault_proxy",
        placement_plan=plan,
        recipe=recipe,
    )
    assert first.case == replay.case
    assert first.case["physical"] is None
    assert first.case["placement"] == plan.to_dict()
    assert first.summary["factory_count"] == 3
    assert first.summary["geometry_fingerprint"] == plan.geometry_fingerprint
    assert (
        first.ledger["device_budget"]["geometry_fingerprint"]
        == plan.geometry_fingerprint
    )
    assert first.summary["execution_completed"] is True
    assert first.summary["parallel_wave_count"] > 0


def test_explicit_plan_count_and_recipe_cannot_change_model_semantics():
    from modules.codes.rotated_surface_d3.protocols.factory import factory_recipe
    from modules.codes.rotated_surface_d3.protocols.fast_layout import (
        legacy_factory_plan,
    )

    profile = FastProfile.from_dict(_complete_document())
    with pytest.raises(ValueError, match="PLACEMENT_FACTORY_COUNT_MISMATCH"):
        run_fast(
            profile,
            code="rotated_surface_d3",
            seed=0,
            input_z_error=0.01,
            factory_count=2,
            placement_plan=legacy_factory_plan(3),
        )
    with pytest.raises(ValueError, match="UNSUPPORTED_FACTORY_RECIPE"):
        run_fast(
            profile,
            code="rotated_surface_d3",
            seed=0,
            input_z_error=0.01,
            recipe=replace(factory_recipe(), rotations=()),
        )


def test_fast_layout_adapter_preserves_coordinates_slots_and_device_regions():
    from nadit_physical_compiler.device import Position

    from modules.codes.rotated_surface_d3.protocols.fast_layout import (
        layout_from_plan,
        legacy_factory_plan,
        legacy_regions,
    )

    plan = legacy_factory_plan(3, origin=Position(10, -5))
    shared, readout = legacy_regions(plan)
    layout = layout_from_plan(plan, shared_bounds_um=shared, readout_bounds_um=readout)
    assert layout.placement_plan is plan
    for i, factory in enumerate(layout.factories):
        for slot, patch in enumerate(factory.patches):
            assert patch.origin == Position(10 + i * 620 + slot * 100, -5)
            assert patch.slot == slot
    assert layout.budget["shared_bounds_um"] == [-12, -7, 1835, 75]
    assert layout.budget["readout_bounds_um"] == [-10, 85, 1835, 125]
    assert layout.budget["atom_count_estimate"] == 306
    assert layout.budget["aod_max_columns"] == 48
    assert layout.budget["max_readout_atoms"] == 96
    untranslated = layout_from_plan(legacy_factory_plan(3))
    assert untranslated.budget["aod_workspace_bounds_um"] == [-25, -5, 1830, 135]
    assert layout.budget["aod_workspace_bounds_um"] is None


@pytest.mark.parametrize("count", [1, 3])
def test_vertical_plan_metadata_never_invents_readout_or_changes_positions(count):
    from modules.codes.rotated_surface_d3.protocols.factory import factory_recipe
    from modules.codes.rotated_surface_d3.protocols.fast_layout import (
        layout_from_plan,
        legacy_factory_plan,
    )
    from modules.logical_compiler.src.placement import (
        PlacementRequest,
        VerticalFactoryPlacement,
        place,
    )

    seed = legacy_factory_plan(count)
    recipe = factory_recipe()
    plan = place(
        PlacementRequest(blocks=seed.blocks, geometries=seed.geometries),
        VerticalFactoryPlacement(role_order=(*recipe.work_roles, recipe.resource_role)),
    )
    layout = layout_from_plan(plan)
    assert layout.budget["shared_bounds_um"] is None
    assert layout.budget["readout_bounds_um"] is None
    assert layout.budget["aod_workspace_bounds_um"] is None
    assert len(layout.factories) == count
    assert all(
        patch.origin == plan.placements[patch.block_id].origin
        for patch in layout.bindings.values()
    )
    explicit = layout_from_plan(
        plan,
        shared_bounds_um=[-20, -280, 600, 0],
        readout_bounds_um=[-20, 50, 600, 200],
        aod_workspace_bounds_um=[-20, -280, 600, 200],
    )
    assert explicit.budget["readout_bounds_um"] == [-20, 50, 600, 200]
    assert explicit.budget["aod_workspace_bounds_um"] == [-20, -280, 600, 200]
    assert explicit.budget["geometry_fingerprint"] == plan.geometry_fingerprint
