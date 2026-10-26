"""Noise routing, frozen studies and one real unsupported-quality prefix."""

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.codes.contracts.event_probability import ProbabilityPort
from modules.logical_compiler.examples import factory_noise as example
from modules.logical_compiler.src.protocols.experiment_ledger import build_ledger_record


def _port():
    return ProbabilityPort.from_dict(
        {
            "schema": "nadit.event_probability/1",
            "port_id": "test_fixture.noise",
            "protocol_id": "test_fixture.noise",
            "protocol_version": "1",
            "model": {
                "id": "test_fixture.routing",
                "kind": "test_fixture",
                "assumptions": ["Routing only; no physical probability claim"],
                "parameters": {},
                "evidence": {},
            },
            "outcomes": [
                {
                    "key": "accepted",
                    "probability": 1.0,
                    "values": {"accepted": True, "byproduct_class": 0},
                    "branch_id": "continue",
                }
            ],
            "branches": [{"key": "continue", "transition": "continue", "steps": []}],
        }
    )


class HookBackend:
    def __init__(self, device=None):
        self.device = device
        self.calls = []
        self.port = _port()
        self.quality = {"status": "unsupported", "consumption_parameters": None}

    def preparation_event(self, preparation, source, parameters):
        self.calls.append(("event", preparation, source, parameters))
        return self.port

    def preparation_quality_from_event(
        self, preparation, source, port, values, parameters
    ):
        self.calls.append(("quality", preparation, source, parameters))
        assert port is self.port
        return self.quality


def test_noise_routes_only_to_raw_and_never_adds_reference_input_error():
    backend = HookBackend()
    adapter = example.CostNoiseBackend(backend, "W1")
    source = object()
    parameters = {"noise_model": "noise/v1", "noise_params": {"readout_flip": 0.1}}
    adapter.preparation_event("initialize_plus", source, parameters)
    port = adapter.preparation_event("raw_t_postselection", source, parameters)
    quality = adapter.preparation_quality_from_event(
        "raw_t_postselection",
        source,
        port,
        {"accepted": True, "byproduct_class": 0},
        parameters,
    )
    assert backend.calls[0][3] == {}
    assert backend.calls[1][3] == parameters
    assert backend.calls[1][3] is not parameters
    assert backend.calls[1][3]["noise_params"] is not parameters["noise_params"]
    assert all(call[2] is source for call in backend.calls)
    assert quality is backend.quality
    assert quality["status"] == "unsupported"
    assert quality["consumption_parameters"] is None
    assert "input_z_error" not in json.dumps(backend.calls, default=str)
    with pytest.raises(ValueError, match="RAW_COST_PARAMETERS_REQUIRED"):
        adapter.preparation_event("raw_t_postselection", source, {})


def test_missing_source_hooks_never_fall_back_to_ideal():
    with pytest.raises(NotImplementedError, match="preparation_event"):
        example.CostNoiseBackend(SimpleNamespace(), "W1")


def test_source_freeze_hashes_the_imported_physical_runtime():
    root = example._physical_runtime_root()
    sources = example._source_hashes()
    key = "runtime-physical:" + (root / "__init__.py").as_posix()
    assert (
        sources[key] == hashlib.sha256((root / "__init__.py").read_bytes()).hexdigest()
    )
    assert any(
        key.startswith("runtime-physical:") and "/cost/noise/" in key for key in sources
    )


def test_source_change_stops_cohort_and_invalidates_comparison(monkeypatch, tmp_path):
    device = object()
    world = SimpleNamespace(
        device=device, bindings={"W1": SimpleNamespace(block_id="W1")}
    )
    monkeypatch.setattr(example, "make_factory_world", lambda: world)
    monkeypatch.setattr(example, "SurfaceFactoryBackend", HookBackend)
    versions = iter(({"source": "before"}, {"source": "before"}, {"source": "after"}))
    monkeypatch.setattr(example, "_source_hashes", lambda: next(versions))
    invoked = []

    def fake_run(seed, params, output, **kwargs):
        invoked.append((seed, params, kwargs["source_snapshot"]))
        output.mkdir()
        (output / "manifest.json").write_text("{}", encoding="utf-8")
        document = {
            "schema": "nadit.factory_case/1",
            "case_id": example.CASE_ID,
            "seed": seed,
            "code": "test_fixture",
            "status": "unsupported_resource_quality",
            "recipe": {"protocol_id": "test_fixture", "version": "1"},
            "calls": [],
            "events": [],
            "milestones": [],
            "resources": {"tokens": []},
        }
        return SimpleNamespace(
            case=SimpleNamespace(status="unsupported_resource_quality"),
            ledger_record=build_ledger_record(document),
            output=output,
            manifest={
                "duration_us": 0,
                "counts": {"raw_preparation_attempts": 0},
                "physical_validation": None,
                "cost_profile": {"status": "unavailable"},
                "source_stable": False,
            },
        )

    monkeypatch.setattr(example, "run_noise_case", fake_run)
    summary = example.run_noise_cohort({"readout_flip": 0.1}, tmp_path / "cohort")
    assert summary["seeds_requested"] == list(range(16))
    assert summary["seeds_completed"] == [0]
    assert len(invoked) == 1
    assert summary["status"] == "source_changed"
    assert summary["comparison_valid"] is False
    assert summary["logical_success"] is None
    assert json.loads((tmp_path / "cohort" / "noise-params.json").read_text()) == {
        "readout_flip": 0.1
    }
    assert Path(summary["ledger_files"]["jsonl"]).is_file()


def test_existing_output_refused_before_work(tmp_path, monkeypatch):
    def forbidden():
        raise AssertionError(
            "existing output must be rejected before world construction"
        )

    monkeypatch.setattr(example, "make_factory_world", forbidden)
    with pytest.raises(FileExistsError):
        example.run_noise_case(0, {}, tmp_path)
    with pytest.raises(FileExistsError):
        example.run_noise_cohort({}, tmp_path)


def test_invalid_seed_list_is_rejected_before_cohort_creation(tmp_path):
    for seeds in ((), (1, 1), (True,)):
        with pytest.raises(ValueError, match="seeds"):
            example.run_noise_cohort({}, tmp_path / "invalid", seeds=seeds)
    assert not (tmp_path / "invalid").exists()


def test_real_cost_noise_stops_after_canonicalized_unsupported_resource(tmp_path):
    parameter_file = (
        Path(__file__).resolve().parents[2]
        / "physical_compiler/cost_params/noise_illustrative.json"
    )
    params = json.loads(parameter_file.read_text("utf-8"))
    configured = os.environ.get("NADIT_FACTORY_NOISE_TEST_OUTPUT")
    output = Path(configured) if configured else tmp_path / "seed-0"
    run = example.run_noise_case(0, params, output)
    document = run.case.to_dict()
    assert document["status"] == "unsupported_resource_quality"
    assert document["output_token_id"] is None
    assert document["algorithm_consumed_token_id"] is None
    assert not any(
        call["component_id"] == "transversal_cnot" for call in document["calls"]
    )
    assert not any(
        call["invocation_id"].startswith("algorithm/") for call in document["calls"]
    )
    assert document["calls"][-1]["component_id"] == "raw_t_postselection/canonicalize"
    tokens = document["resources"]["tokens"]
    assert len(tokens) == 1 and tokens[0]["status"] == "offered"
    assert tokens[0]["canonicalization"] == "canonical"
    assert tokens[0]["quality"]["status"] == "unsupported"
    assert tokens[0]["quality"]["consumption_parameters"] is None
    physical = document["physical"]
    assert physical["validation"]["ok"] is True
    assert all(output["value"] is None for output in physical["pending_measurements"])
    assert run.manifest["input_z_error"] is None
    assert run.manifest["input_quality_status"] == "unsupported"
    assert run.manifest["scopes"]["event_fixture"] is False
    raw_events = [
        event
        for event in document["events"]
        if "raw_t_postselection" in event["occurrence"]["port_id"]
    ]
    assert [event["outcome_key"] for event in raw_events] == ["rejected", "accepted_2"]
    assert [event["occurrence"]["attempt"] for event in raw_events] == [0, 1]
    assert all(
        document["probability_models"][event["port_sha256"]]["model"]["kind"]
        != "test_fixture"
        for event in raw_events
    )
    carrier = next(
        item
        for item in document["resources"]["carriers"]
        if item["carrier_id"] == "factory/W2"
    )
    assert carrier["epoch"] == 2
    data_atoms = set(carrier["atom_ids"][:9])
    for call in document["calls"]:
        if call["component_id"] != "raw_t_postselection":
            continue
        reset_atoms = set()
        for step in physical["program"]["steps"]:
            for action in step["actions"]:
                if action["kind"] == "Reset" and any(
                    physical["source_id_map"][str(source)]["invocation_id"]
                    in call["part_invocations"]
                    for source in action["source_ids"]
                ):
                    reset_atoms.update(action["atoms"])
        assert data_atoms <= reset_atoms
    assert run.cost_report is not None
    assert run.cost_report["logical_success"] is None
    assert run.cost_report["measurement_evidence"] == "unobserved"
    assert run.ledger_record["logical_success"] is None
    assert run.ledger_record["factory_output_ready"] is False
    assert run.ledger_record["algorithm_complete"] is False
    assert run.ledger_record["counts"]["raw_accepted_resources"] == 1
    assert run.manifest["limits"]["raw_attempts"] == 8
    assert run.manifest["limits"]["batches"] == 1
    for name, digest in run.manifest["files_sha256"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    assert json.loads((output / "noise-params.json").read_text()) == params
    assert json.loads((output / "case.json").read_text()) == document
    assert (output / "index.html").is_file()
