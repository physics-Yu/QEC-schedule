"""Explicit code, shared hardware and synchronized production configuration."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from modules.logical_compiler.examples.factory_array import (
    DEFAULT_CONFIG,
    load_configuration,
    main,
    run_array,
)


def test_default_is_two_lines_one_aod_and_cohort_waiting():
    config = json.loads(DEFAULT_CONFIG.read_text("utf-8"))
    world, limits = load_configuration(config)
    assert world.factory_count == 2
    assert world.aod_id == "transport"
    assert world.shared_top_margin_um == 15
    assert world.readout_extra_height_um == 20
    assert limits.raw_attempts == 8 and limits.batches == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("code", "implicit"),
        ("coordination_policy", "run_ahead"),
        ("max_parallel", 1),
        ("mode", "serial"),
    ],
)
def test_configuration_rejects_implicit_code_or_wrong_coordination(field, value):
    config = deepcopy(json.loads(DEFAULT_CONFIG.read_text("utf-8")))
    config[field] = value
    with pytest.raises(ValueError):
        load_configuration(config)


def test_entry_requires_explicit_theory_p_before_creating_output(tmp_path):
    destination = tmp_path / "not-created"
    with pytest.raises(ValueError, match="input_z_error"):
        run_array(
            0,
            {},
            destination,
            configuration=json.loads(DEFAULT_CONFIG.read_text("utf-8")),
        )
    assert not destination.exists()


def test_cli_carries_theory_parameter_and_explicit_proxy_mode(monkeypatch, tmp_path):
    captured = []
    noise = tmp_path / "noise.json"
    noise.write_text("{}", encoding="utf-8")

    def run(seed, noise_params, output, **kwargs):
        captured.append(kwargs)
        return SimpleNamespace(
            case=SimpleNamespace(status="complete"),
            ledger={"counts": {}},
            manifest={"execution_completed": True},
        )

    monkeypatch.setattr(
        "modules.logical_compiler.examples.factory_array.run_array", run
    )
    shared = ["--noise-params", str(noise), "--output", str(tmp_path / "result")]
    assert main(shared + ["--input-z-error", "0.01"]) == 0
    assert captured[-1]["acceptance_model"] == "theory"
    assert captured[-1]["input_z_error"] == 0.01
    assert main(shared + ["--acceptance-model", "physical_no_fault_proxy"]) == 0
    assert captured[-1]["acceptance_model"] == "physical_no_fault_proxy"
    assert captured[-1]["input_z_error"] is None


def test_cli_rejects_missing_theory_p_and_proxy_with_p(tmp_path):
    shared = [
        "--noise-params",
        str(tmp_path / "noise.json"),
        "--output",
        str(tmp_path / "out"),
    ]
    with pytest.raises(SystemExit):
        main(shared)
    with pytest.raises(SystemExit):
        main(
            shared
            + [
                "--acceptance-model",
                "physical_no_fault_proxy",
                "--input-z-error",
                "0.01",
            ]
        )
