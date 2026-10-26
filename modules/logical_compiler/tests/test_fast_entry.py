"""The experimental CLI keeps explicit calibration and usable local artifacts."""

import json

import pytest

from modules.codes.rotated_surface_d3.protocols.fast_profile import FastProfile
from modules.logical_compiler.examples.factory_fast import main, run_fast, sweep
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
    result = sweep(
        FastProfile.from_dict(_complete_document()),
        code="rotated_surface_d3",
        acceptance_model="physical_no_fault_proxy",
        factory_counts=[1, 2],
        seeds=[0, 1],
        output=output,
    )
    assert result["all_runs_completed"]
    assert result["capacity_scales_with_factory_count"] is False
    assert result["statistics_unit"] == "independent_seed_trajectory"
    assert all(group["independent_seed_runs"] == 2 for group in result["groups"])
    assert len(result["sample_files"]) == 4
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
