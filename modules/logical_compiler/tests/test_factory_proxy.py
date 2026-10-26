"""Physical proxy boundaries and honest terminal evidence."""

import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from modules.codes.contracts.event_probability import ProbabilityPort
from modules.logical_compiler.examples import factory_proxy as example
from modules.logical_compiler.src.protocols.experiment_ledger import build_ledger_record


def test_raw_horizon_exclusion_includes_each_attempt_readout_tail():
    assert example._included_intervals(10, 90, ((20, 35), (40, 60))) == (
        (10, 20),
        (35, 40),
        (60, 90),
    )
    assert example._included_intervals(10, 90, ((10, 35), (35, 60))) == ((60, 90),)


@pytest.mark.parametrize("horizons", [((9, 30),), ((20, 91),), ((20, 20),)])
def test_invalid_raw_horizons_fail_without_clamping(horizons):
    with pytest.raises(ValueError, match="INVALID_RAW_HORIZON"):
        example._included_intervals(10, 90, horizons)


def test_parallel_raw_horizons_are_excluded_once_by_union():
    # Different patch attempts can now occupy the same physical clock interval.
    assert example._included_intervals(
        10, 90, ((20, 40), (20, 40), (30, 50), (50, 60))
    ) == ((10, 20), (60, 90))
    assert example._raw_union(10, 90, ((20, 40), (20, 40), (30, 50))) == ((20, 50),)


def test_scope_binding_does_not_mix_factory_batches():
    assert example._batch_scope("factory/batch[1]/rotation[0]/raw/body") == (
        "factory/batch[1]"
    )
    with pytest.raises(ValueError, match="INVALID_FACTORY_SCOPE"):
        example._batch_scope("algorithm/output-consumption/mz")


def test_source_freeze_includes_the_new_proxy_entry_point():
    assert "modules/logical_compiler/examples/factory_proxy.py" in (
        example._source_hashes()
    )


def _port():
    return ProbabilityPort.from_dict(
        {
            "schema": "nadit.event_probability/1",
            "port_id": "test_fixture.proxy",
            "protocol_id": "test_fixture.proxy",
            "protocol_version": "1",
            "model": {
                "id": "test_fixture.proxy.routing",
                "kind": "test_fixture",
                "assumptions": ["Routing test only; no physical model claim"],
                "parameters": {},
                "evidence": {},
            },
            "outcomes": [
                {
                    "key": "proxy_success",
                    "probability": 1.0,
                    "values": {
                        "accepted": True,
                        "proxy_success": True,
                        "no_fault": True,
                    },
                    "branch_id": "continue",
                }
            ],
            "branches": [{"key": "continue", "transition": "continue", "steps": []}],
        }
    )


class _Backend:
    def __init__(self):
        self.port = _port()
        self.calls = []
        self.quality = {
            "status": "ideal_reference_for_proxy",
            "actual_quality": {"status": "unsupported"},
            "consumption_parameters": {"routing": "opaque-code-owned-reference"},
        }

    def preparation_event(self, preparation, source, parameters):
        self.calls.append((preparation, source, parameters))
        return self.port

    def preparation_quality_from_event(self, *args):
        return self.quality

    def factory_proxy_event(self, report, evidence):
        self.calls.append(("factory", report, evidence))
        return self.port

    def algorithm_proxy_event(self, report, evidence):
        self.calls.append(("algorithm", report, evidence))
        return self.port


def _report(intervals):
    return {
        "result_hash": "fixture-result-hash",
        "interval_selection": {
            "include_intervals": [list(pair) for pair in intervals],
            "selected_activity_sha256": "fixture-activity-hash",
            "selected_event_indices": [0, 4, 9],
            "noise_profile": "independent_pauli_rates_v1",
            "exposure_partition": (
                "original_activity_interval_intersections_with_merged_include_intervals"
            ),
        },
    }


def test_raw_horizons_and_proxy_quality_are_code_owned():
    backend = _Backend()
    adapter = example.CostProxyBackend(backend, "W1", object())
    source = SimpleNamespace(
        parts=(
            SimpleNamespace(invocation_id="factory/batch[0]/raw/part0", start_us=10),
        ),
        results_ready_us=35,
    )
    params = {"noise_model": "noise/v1", "noise_params": {"readout_flip": 0.1}}
    port = adapter.preparation_event("raw_t_postselection", source, params)
    quality = adapter.preparation_quality_from_event(
        "raw_t_postselection", source, port, {"accepted": True}, params
    )
    assert quality is backend.quality
    assert quality["actual_quality"]["status"] == "unsupported"
    assert quality["consumption_parameters"] == {
        "routing": "opaque-code-owned-reference"
    }
    assert adapter.raw_horizons["factory/batch[0]/raw/part0"]["results_ready_us"] == 35
    assert backend.calls[0][2] == params


def test_factory_proxy_cost_is_ready_and_scoped_without_other_batches(monkeypatch):
    backend = _Backend()
    bundle = object()
    context = SimpleNamespace(
        clock_us=90,
        invocations=(
            SimpleNamespace(invocation_id="factory/batch[0]/a", start_us=0),
            SimpleNamespace(invocation_id="factory/batch[1]/a", start_us=10),
        ),
        finalize=lambda: bundle,
    )
    adapter = example.CostProxyBackend(backend, "W1", context)
    adapter.raw_horizons = {
        "old": {"scope_id": "factory/batch[0]", "start_us": 1, "results_ready_us": 8},
        "first": {
            "scope_id": "factory/batch[1]",
            "start_us": 20,
            "results_ready_us": 35,
        },
        "retry": {
            "scope_id": "factory/batch[1]",
            "start_us": 40,
            "results_ready_us": 60,
        },
    }
    captured = []

    def evaluate(source, params, *, include_intervals):
        captured.append((source, params, include_intervals))
        return _report(include_intervals)

    monkeypatch.setattr(
        example.cost, "evaluate_physical_cost_intervals", evaluate, raising=False
    )
    part = SimpleNamespace(results_ready_us=90)
    port = adapter.resolve_event_from_sources(
        "factory_cost_proxy",
        (part,),
        {"noise_params": {"readout_flip": 0.1}},
        event_id="factory/batch[1]/final/event",
    )
    assert port is backend.port
    assert captured == [(bundle, {"readout_flip": 0.1}, ((10, 20), (35, 40), (60, 90)))]
    evidence = backend.calls[-1][2]
    assert evidence["window_us"] == [10, 90]
    assert evidence["excluded_raw_intervals_us"] == [[20, 35], [40, 60]]
    assert evidence["full_trace_probability_equivalence_claimed"] is False
    context.clock_us = 89
    with pytest.raises(ValueError, match="FACTORY_PROXY_BEFORE_RESULTS_READY"):
        adapter.resolve_event_from_sources(
            "factory_cost_proxy",
            (part,),
            {"noise_params": {}},
            event_id="factory/batch[1]/final/event",
        )
    assert len(captured) == 1


def test_no_terminal_sample_for_incomplete_algorithm(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("An incomplete algorithm must not sample a terminal event")

    monkeypatch.setattr(example, "SeededEventBackend", forbidden)
    case = SimpleNamespace(
        to_dict=lambda: {
            "case_id": example.CASE_ID,
            "seed": 0,
            "status": "distillation_rejected",
            "milestones": [],
        }
    )
    evaluation, report = example._algorithm_evaluation(case, None, {})
    assert report is None
    assert evaluation["status"] == "not_evaluated"
    assert evaluation["proxy_success"] is None
    assert evaluation["logical_success"] is None


def test_terminal_sampling_uses_accepted_decision_to_algorithm_exit(monkeypatch):
    backend = _Backend()
    adapter = SimpleNamespace(
        proxy_backend=backend, factory_reports={"factory/batch[1]/final/event": {}}
    )
    document = {
        "case_id": example.CASE_ID,
        "seed": 23,
        "status": "complete",
        "milestones": [{"kind": "algorithm_t_complete"}],
        "duration_us": 120,
        "output_token_id": "factory/batch[1]/output",
        "resources": {
            "tokens": [
                {
                    "token_id": "factory/batch[1]/output",
                    "quality": {"delivery_assessment": {"start_us": 90}},
                }
            ]
        },
        "events": [
            {
                "occurrence": {"invocation_id": "factory/batch[1]/final/event"},
                "values": {"accepted": True},
                "released_at_us": 90,
            }
        ],
    }
    bundle = object()
    case = SimpleNamespace(to_dict=lambda: document, physical=bundle)
    intervals = []

    def evaluate(source, params, *, include_intervals):
        assert source is bundle
        intervals.append(include_intervals)
        return _report(include_intervals)

    monkeypatch.setattr(
        example.cost, "evaluate_physical_cost_intervals", evaluate, raising=False
    )
    result, _ = example._algorithm_evaluation(case, adapter, {})
    repeated, _ = example._algorithm_evaluation(case, adapter, {})
    assert result == repeated
    assert intervals == [((90, 120),), ((90, 120),)]
    assert result["event"]["occurrence"]["invocation_id"] == "algorithm/terminal-proxy"
    assert result["event"]["available_at_us"] == 120
    assert result["proxy_success"] is True
    assert result["logical_success"] is None
    assert result["feeds_back_into_compilation"] is False
    assert result["physical_measurement_values"] == "unobserved"
    document["resources"]["tokens"][0]["quality"]["delivery_assessment"]["start_us"] = (
        91
    )
    with pytest.raises(ValueError, match="DELIVERY_BOUNDARY_MISMATCH"):
        example._algorithm_evaluation(case, adapter, {})


def test_existing_outputs_and_invalid_witness_lists_fail_before_compilation(tmp_path):
    with pytest.raises(FileExistsError):
        example.run_proxy_case(0, {}, tmp_path)
    with pytest.raises(FileExistsError):
        example.run_proxy_cohort({}, tmp_path)
    with pytest.raises(ValueError, match="disjoint"):
        example.run_proxy_cohort({}, tmp_path / "new", seeds=(0,), witness_seeds=(0,))


def test_cohort_witnesses_have_separate_ledger_and_explicit_seed_lists(
    monkeypatch, tmp_path
):
    world = SimpleNamespace(device=object())
    monkeypatch.setattr(example, "make_factory_world", lambda: world)
    monkeypatch.setitem(
        sys.modules,
        "modules.codes.rotated_surface_d3.protocols.cost_proxy",
        SimpleNamespace(SurfaceCostProxyBackend=lambda device: object()),
    )
    monkeypatch.setattr(example, "_source_hashes", lambda: {"source": "frozen"})
    seen = []

    def fake_run(seed, params, output, **kwargs):
        seen.append((seed, kwargs["sampling_role"]))
        output.mkdir()
        (output / "manifest.json").write_text("{}", encoding="utf-8")
        document = {
            "schema": "nadit.factory_case/1",
            "case_id": example.CASE_ID,
            "seed": seed,
            "code": "test_fixture",
            "status": "distillation_rejected",
            "recipe": {"protocol_id": "test_fixture", "version": "1"},
            "calls": [],
            "events": [],
            "milestones": [],
            "resources": {"tokens": []},
        }
        record = build_ledger_record(
            document, {"sampling_role": kwargs["sampling_role"]}
        )
        return SimpleNamespace(
            case=SimpleNamespace(status=document["status"]),
            output=output,
            ledger_record=record,
            evaluation={"status": "not_evaluated", "proxy_success": None},
            manifest={
                "duration_us": 0,
                "counts": {},
                "physical_validation": None,
                "source_stable": True,
            },
        )

    monkeypatch.setattr(example, "run_proxy_case", fake_run)
    output = tmp_path / "cohort"
    summary = example.run_proxy_cohort({}, output, seeds=(0, 1), witness_seeds=(99,))
    assert seen == [(0, "unbiased_cohort"), (1, "unbiased_cohort"), (99, "witness")]
    assert summary["seeds_requested"] == [0, 1]
    assert summary["witness_seeds_requested"] == [99]
    assert [item["seed"] for item in summary["runs"]] == [0, 1]
    assert [item["seed"] for item in summary["witness_runs"]] == [99]
    assert summary["witnesses_included_in_unbiased_statistics"] is False
    assert summary["comparison_valid"] is True
    unbiased = (output / "ledger/ledger.jsonl").read_text().splitlines()
    witness = (output / "witness-ledger/ledger.jsonl").read_text().splitlines()
    assert [json.loads(item)["seed"] for item in unbiased] == [0, 1]
    assert [json.loads(item)["seed"] for item in witness] == [99]


def test_real_proxy_pipeline_retains_physical_and_model_evidence(tmp_path):
    """Compile by default; an explicit smoke artifact may be verified without rerun."""
    retained = os.environ.get("NADIT_FACTORY_PROXY_VERIFY_ARTIFACT")
    output = Path(retained) if retained else tmp_path / "seed-0"
    if retained is None:
        parameter_file = (
            Path(__file__).resolve().parents[2]
            / "physical_compiler/cost_params/noise_illustrative.json"
        )
        params = json.loads(parameter_file.read_text("utf-8"))
        example.run_proxy_case(0, params, output)
    document = json.loads((output / "case.json").read_text("utf-8"))
    manifest = json.loads((output / "manifest.json").read_text("utf-8"))
    evaluation = json.loads((output / "evaluation.json").read_text("utf-8"))
    reports = json.loads((output / "proxy-costs.json").read_text("utf-8"))
    ledger = json.loads((output / "experiment.json").read_text("utf-8"))
    assert document["case_id"] == example.CASE_ID and document["seed"] == 0
    assert document["limits"]["batches"] == 2
    assert document["limits"]["raw_attempts"] == 8
    assert document["status"] in ("complete", "distillation_rejected")
    assert document["physical"]["validation"]["ok"] is True
    assert all(
        item["value"] is None for item in document["physical"]["pending_measurements"]
    )
    assert manifest["input_z_error"] is None
    assert manifest["whole_pipeline_no_fault_probability"] is None
    assert evaluation["logical_success"] is None
    assert ledger["logical_success"] is None
    assert ledger["algorithm_evaluation"] == evaluation
    assert all(
        model["model"]["kind"] != "test_fixture"
        for model in document["probability_models"].values()
    )
    raw_calls = [
        call
        for call in document["calls"]
        if call["component_id"] == "raw_t_postselection"
    ]
    assert len(raw_calls) == len(reports["raw_horizons"])
    assert raw_calls
    for token in document["resources"]["tokens"]:
        quality = token["quality"]
        assert quality["status"] == "cost_proxy_routing"
        assert quality["actual_quality"]["status"] == "unsupported"
        assert (
            quality["consumption_parameters"]["routing_reference"]
            == "ideal_cost_proxy.v1"
        )
    events = {
        event["occurrence"]["invocation_id"]: event
        for event in document["events"]
        if event["occurrence"]["port_id"]
        == "rotated_surface_d3.factory_15_to_1.cost_proxy"
    }
    assert events and events.keys() == reports["factory"].keys()
    for identity, event in events.items():
        evidence = reports["factory"][identity]
        scope = evidence["scope_evidence"]
        report = evidence["report"]
        model = document["probability_models"][event["port_sha256"]]
        port = ProbabilityPort.from_dict(model)
        assert port.content_sha256 == evidence["port_sha256"]
        assert (
            report["metrics"]["no_fault_probability"]
            == port.outcome("accepted").probability
        )
        assert report["logical_success"] is None
        assert scope["window_us"][1] == event["released_at_us"]
        assert scope["full_trace_probability_equivalence_claimed"] is False
        batch = example._batch_scope(identity)
        horizons = [
            [item["start_us"], item["results_ready_us"]]
            for item in reports["raw_horizons"]
            if item["scope_id"] == batch
        ]
        # Original attempts remain distinct; adjacent/overlapping clock exposure
        # is now excluded once, including serial rejection immediately retried.
        assert scope["raw_attempt_intervals_us"] == horizons
        assert scope["excluded_raw_intervals_us"] == [
            list(pair) for pair in example._raw_union(*scope["window_us"], horizons)
        ]
        assert all(
            max(a, c) >= min(b, d)
            for a, b in scope["included_intervals_us"]
            for c, d in horizons
        )
    if document["status"] == "complete":
        assert evaluation["status"] == "evaluated"
        assert type(evaluation["proxy_success"]) is bool
    else:
        assert len(events) == 2
        assert all(event["values"]["accepted"] is False for event in events.values())
        assert evaluation["status"] == "not_evaluated"
        assert evaluation["proxy_success"] is None
    for name, digest in manifest["files_sha256"].items():
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
