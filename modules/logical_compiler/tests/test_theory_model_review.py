"""Independent review of reference feedback, diagnostic isolation and boundaries."""

import json
from copy import deepcopy

import pytest

from modules.codes.contracts.factory_recipe import ComponentCall
from modules.codes.rotated_surface_d3.protocols import fast_backend
from modules.codes.rotated_surface_d3.protocols.factory_experiment import (
    FactoryExperimentModel,
)
from modules.codes.rotated_surface_d3.protocols.fast_backend import FastCostBackend
from modules.codes.rotated_surface_d3.protocols.fast_profile import (
    FastProfile,
    make_fast_layout,
)
from modules.logical_compiler.examples import factory_fast
from modules.logical_compiler.examples.factory_fast import run_fast
from modules.logical_compiler.src.cases.backend import EventResult, Occurrence
from modules.logical_compiler.src.estimation.kernel import ProfileExecutionKernel
from modules.logical_compiler.src.protocols.events import (
    EventDependency,
    EventObservation,
)
from modules.logical_compiler.src.protocols.execution_kernel import ExecutionRequest
from modules.logical_compiler.src.scheduling import ComponentNode, ComponentScheduler
from modules.logical_compiler.tests.test_fast_experiment_review import (
    _complete_document,
    no_physical,  # noqa: F401 - register the shared pytest fixture
)

pytestmark = pytest.mark.usefixtures("no_physical")


def _decisions(run):
    return [
        (
            event["occurrence"],
            event["outcome_key"],
            event["values"],
            event["port_sha256"],
        )
        for event in run.case["events"]
    ]


def test_theory_never_uses_legacy_consumption_or_factory_proxy(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Theory attempted to obtain a legacy cost-proxy probability port")

    monkeypatch.setattr(FastProfile, "consumption_port", forbidden)
    monkeypatch.setattr(fast_backend, "factory_probability_port", forbidden)
    profile = FastProfile.from_dict(_complete_document())
    run = run_fast(profile, code="rotated_surface_d3", seed=0, input_z_error=0.0)
    assert run.summary["execution_completed"]
    assert run.summary["outputs"] == 2
    assert run.ledger["physical_validation_ok"] is None
    assert run.case.get("physical") is None
    assert all(
        p == [1.0] for p in run.summary["factory_acceptance_probabilities"].values()
    )
    final = [event for event in run.case["events"] if "m_w2" in event["values"]]
    assert len(final) == 2
    assert all(event["outcome_key"] == "mx_0000" for event in final)


def test_diagnostic_metric_changes_cannot_change_seeded_theory(monkeypatch):
    profile = FastProfile.from_dict(_complete_document())
    baseline = run_fast(profile, code="rotated_surface_d3", seed=0, input_z_error=0.01)
    original = fast_backend.evaluate_factory_cost

    def zero_diagnostic(*args, **kwargs):
        report = deepcopy(original(*args, **kwargs))
        report["metrics"]["no_fault_probability"] = 0.0
        return report

    monkeypatch.setattr(fast_backend, "evaluate_factory_cost", zero_diagnostic)
    changed = run_fast(profile, code="rotated_surface_d3", seed=0, input_z_error=0.01)
    assert _decisions(changed) == _decisions(baseline)
    assert changed.case["calls"] == baseline.case["calls"]
    assert changed.case["resources"] == baseline.case["resources"]
    assert changed.ledger["counts"] == baseline.ledger["counts"]
    assert changed.summary["outputs"] > 0
    assert all(
        p == [0.0] for p in changed.summary["physical_no_fault_diagnostics"].values()
    )
    assert all(
        p == [1.0] for p in baseline.summary["physical_no_fault_diagnostics"].values()
    )


def test_cli_rejects_missing_or_mixed_model_before_reading_profile(
    tmp_path, monkeypatch
):
    def forbidden(*args, **kwargs):
        pytest.fail("Invalid model configuration reached profile loading")

    monkeypatch.setattr(factory_fast, "load_fast_profile", forbidden)
    base = [
        "run",
        "--code",
        "rotated_surface_d3",
        "--profile",
        "unused.json",
        "--output",
        str(tmp_path / "unused"),
    ]
    for suffix in (
        [],
        ["--acceptance-model", "physical_no_fault_proxy", "--input-z-error", "0.01"],
    ):
        with pytest.raises(SystemExit) as error:
            factory_fast.main(base + suffix)
        assert error.value.code == 2
    assert not (tmp_path / "unused").exists()


def _impossible_source():
    document = _complete_document()
    document["preparation_ports"]["raw_t_postselection"]["outcomes"].append(
        {
            "key": "impossible",
            "probability": 0,
            "values": {"accepted": True, "byproduct_class": 7},
            "branch_id": "keep",
        }
    )
    profile = FastProfile.from_dict(document)
    kernel = ProfileExecutionKernel(profile, make_fast_layout(profile, 1))
    model = FactoryExperimentModel(input_z_error=0.01)
    backend = FastCostBackend(
        profile, kernel, factory_id="factory0", experiment_model=model
    )
    identity = "factory0/batch[0]/raw/attempt[0]/body"
    call = ComponentCall("body", "raw_t_postselection", ("W2",))
    request = ExecutionRequest(identity, backend, call, ("factory0/W2",))
    scheduler = ComponentScheduler()
    scheduler.add(
        ComponentNode(
            identity, kernel.describe(backend, call, request.participant_blocks)
        )
    )
    admission = scheduler.admit(0, snapshot_id=kernel.snapshot_id)
    source = kernel.execute(admission, (request,))[identity][0]
    kernel.wait_until(source.results_ready_us, reason="review")
    parameters = model.parameters(profile.noise_params)
    port = backend.preparation_event("raw_t_postselection", source, parameters)
    return kernel, backend, source, parameters, port


def test_zero_probability_preparation_cannot_acquire_reference_quality():
    _, backend, source, parameters, port = _impossible_source()
    with pytest.raises(ValueError, match="ACCEPTED_PREPARATION"):
        backend.preparation_quality_from_event(
            "raw_t_postselection",
            source,
            port,
            {"accepted": True, "byproduct_class": 7},
            parameters,
        )


def test_zero_probability_preparation_cannot_select_correction():
    kernel, backend, source, _, port = _impossible_source()
    observation = EventObservation(
        EventResult(
            Occurrence("review", "factory0/batch[0]/raw", 0, port.port_id),
            port.content_sha256,
            source.results_ready_us,
            "impossible",
        ),
        json.dumps({"accepted": True, "byproduct_class": 7}),
        "keep",
        "deliver",
        (EventDependency.from_receipt(source),),
        source.results_ready_us,
    )
    with pytest.raises(ValueError, match="INVALID_ESTIMATE_CORRECTION_EVENT"):
        kernel.correction_plan(
            backend,
            "raw_t_postselection",
            source,
            port,
            observation,
            event_id="factory0/batch[0]/raw/event[0]",
        )
