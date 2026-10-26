"""Configuration and same-device policy binding for the parallel experiment."""

import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from modules.logical_compiler.examples import factory_parallel as entry


def configuration():
    return json.loads(entry.DEFAULT_CONFIG.read_text("utf-8"))


def test_explicit_code_and_device_allocation_are_validated():
    doc = configuration()
    doc["world"]["aod_ids"] = [f"transport{i}" for i in range(4)]
    doc["world"]["role_aod_ids"] = {f"W{i + 2}": f"transport{i}" for i in range(4)}
    world, maximum = entry.load_configuration(doc)
    assert maximum == 4
    assert len(set(dict(world.role_aod_ids).values())) == 4
    bad = deepcopy(doc)
    bad["code"] = "implicit-surface-code"
    with pytest.raises(ValueError, match="INVALID_PARALLEL_CONFIG"):
        entry.load_configuration(bad)
    bad = deepcopy(doc)
    bad["world"]["role_aod_ids"]["W2"] = "missing-device-resource"
    with pytest.raises(ValueError):
        entry.load_configuration(bad)


def test_default_parallel_experiment_uses_one_shared_aod():
    world, maximum = entry.load_configuration(configuration())
    assert world.aod_ids == ("transport",)
    assert maximum == 4
    assert set(dict(world.role_aod_ids).values()) == {"transport"}


def test_serial_parallel_use_identical_world_and_semantic_seed(monkeypatch, tmp_path):
    calls = []
    sentinel = SimpleNamespace(case="fixture")

    def collect(seed, noise_params, output, **kwargs):
        calls.append((seed, noise_params, output, kwargs))
        return sentinel

    monkeypatch.setattr(entry, "run_proxy_case", collect)
    config = configuration()
    for mode in ("serial", "parallel"):
        assert (
            entry.run_scheduled_case(
                12909,
                {"readout_flip": 0.001},
                tmp_path / mode,
                mode=mode,
                configuration=config,
            )
            is sentinel
        )
    assert calls[0][:2] == calls[1][:2]
    assert calls[0][3]["world"] == calls[1][3]["world"]
    assert calls[0][3]["backend"].device == calls[1][3]["backend"].device
    assert [call[3]["scheduler"].mode for call in calls] == ["serial", "parallel"]
    assert config == configuration()


@pytest.mark.parametrize("changed", ["device", "source"])
def test_comparison_rejects_changed_physical_inputs_or_source(
    monkeypatch, tmp_path, changed
):
    from modules.logical_compiler.examples import parallel_report

    monkeypatch.setattr(entry, "_source_hashes", lambda: {"fixture": "fixed"})
    monkeypatch.setattr(
        parallel_report, "write_parallel_comparison", lambda *a, **k: {}
    )

    def run(seed, params, output, *, mode, configuration):
        output.mkdir()
        doc = {
            "physical": {
                "device": {"aods": 4 if mode == "serial" or changed != "device" else 5},
                "entry_state": {},
            },
            "reference_parameters": {},
            "calls": [
                {
                    "component_id": "raw_t_postselection",
                    "invocation_id": f"factory/initial/W{i}/attempt[0]/body",
                    "start_us": 0,
                }
                for i in range(2, 6)
            ],
            "events": [
                {
                    "occurrence": {"invocation_id": "factory/initial/W2"},
                    "values": {"accepted": False},
                }
            ],
        }
        (output / "case.json").write_text(json.dumps(doc))
        return SimpleNamespace(
            case=SimpleNamespace(
                status="complete",
                to_dict=lambda: doc,
                physical=SimpleNamespace(validation={"ok": True}),
            ),
            evaluation={},
            manifest={"source_stable": changed != "source"},
        )

    monkeypatch.setattr(entry, "run_scheduled_case", run)
    with pytest.raises(
        ValueError, match="COMPARISON_PHYSICAL_INPUT_MISMATCH|EXPERIMENT_SOURCE_CHANGED"
    ):
        entry.run_comparison(
            12909, {}, tmp_path / "comparison", configuration=configuration()
        )
