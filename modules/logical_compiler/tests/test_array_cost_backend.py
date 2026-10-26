"""Each line pays for its own activity and peer waiting, not another line's work."""

from types import SimpleNamespace

import pytest

from modules.codes.rotated_surface_d3.protocols.factory_experiment import (
    FactoryExperimentModel,
)
from modules.logical_compiler.examples.array_backend import ArrayCostBackend


class CodeBackend:
    def preparation_event(self, *args):
        return None

    def preparation_quality_from_event(self, *args):
        return {}

    def factory_proxy_event(self, report, scope):
        self.received = report, scope
        return SimpleNamespace(content_sha256="port")


def setup_backend(model=None):
    code = CodeBackend()
    final_check = SimpleNamespace(
        invocation_id="factory0/batch[0]/mx", results_ready_us=35
    )
    physical = SimpleNamespace(
        clock_us=40,
        invocations=[
            SimpleNamespace(invocation_id="factory0/batch[0]/raw", start_us=0),
            SimpleNamespace(invocation_id="factory1/batch[0]/raw", start_us=10),
        ],
        finalize=lambda: "real-global-bundle",
        source=lambda identity: final_check,
        final_check=final_check,
    )
    backend = ArrayCostBackend(
        code,
        "factory0/W1",
        physical,
        factory_id="factory0",
        atom_ids=(0, 1),
        experiment_model=model
        or FactoryExperimentModel(mode="physical_no_fault_proxy"),
    )
    backend.raw_horizons = {
        "own": {"scope_id": "factory0/batch[0]", "start_us": 0, "results_ready_us": 10},
        "peer": {
            "scope_id": "factory1/batch[0]",
            "start_us": 10,
            "results_ready_us": 30,
        },
    }
    return backend, code


def test_theory_acceptance_is_joint_mx_and_cost_retains_raw_window(monkeypatch):
    backend, code = setup_backend(FactoryExperimentModel(input_z_error=0.01))
    captured = {}

    def evaluate(bundle, params, **kwargs):
        captured.update(bundle=bundle, params=params, **kwargs)
        return {
            "result_hash": "global-result",
            "metrics": {"no_fault_probability": 0.0001},
            "interval_selection": {
                "include_intervals": [[0, 40]],
                "selected_activity_sha256": "selected",
                "selected_event_indices": [1, 2, 3],
                "noise_profile": "independent_pauli_rates_v1",
                "exposure_partition": "absolute_intersections",
            },
            "participant_selection": {"owner_id": "factory0", "atom_ids": [0, 1]},
        }

    monkeypatch.setattr(
        "modules.logical_compiler.examples.array_backend.evaluate_participant_cost",
        evaluate,
    )
    port = backend.resolve_event_from_sources(
        "factory_mx",
        (backend.physical.final_check,),
        {"noise_model": "noise/v1", "noise_params": {}, "input_z_error": 0.01},
        event_id="factory0/batch[0]/final-check",
    )
    assert captured["include_intervals"] == ((0.0, 40.0),)
    assert captured["participant_atom_ids"] == (0, 1)
    assert port.outcome("mx_0000").probability == pytest.approx(0.860090333670424)
    assert all(
        dict(outcome.values)["accepted"]
        == all(dict(outcome.values)[f"m_w{i}"] == 0 for i in range(2, 6))
        for outcome in port.outcomes
    )
    assert not hasattr(code, "received")
    report = backend.factory_reports["factory0/batch[0]/final-check"]
    assert report["controls_factory_acceptance"] is False
    assert report["scope_evidence"]["excluded_raw_intervals_us"] == []
    assert report["scope_evidence"]["coverage"]["raw_physical_loss_included"] is True


def test_theory_raw_quality_and_consumption_use_explicit_input_reference():
    backend, _ = setup_backend(FactoryExperimentModel(input_z_error=0.01))
    port = SimpleNamespace(content_sha256="a" * 64)
    quality = backend.preparation_quality_from_event(
        "raw_t_postselection",
        None,
        port,
        {"accepted": True, "byproduct_class": 3},
        {"noise_model": "noise/v1", "noise_params": {}, "input_z_error": 0.01},
    )
    assert quality["status"] == "assumed_reference"
    assert quality["consumption_parameters"] == {"input_z_error": 0.01}
    event = backend.resolve_event("t_consumption", quality["consumption_parameters"])
    assert [outcome.probability for outcome in event.outcomes] == [0.5, 0.5]
    with pytest.raises(ValueError, match="ACCEPTED"):
        backend.preparation_quality_from_event(
            "raw_t_postselection",
            None,
            port,
            {"accepted": False, "byproduct_class": None},
            {"noise_model": "noise/v1", "noise_params": {}, "input_z_error": 0.01},
        )


def test_theory_strips_reference_p_before_raw_cost_event():
    backend, _ = setup_backend(FactoryExperimentModel(input_z_error=0.01))
    assert backend._event_parameters(
        "raw_t_postselection",
        {
            "noise_model": "noise/v1",
            "noise_params": {"example": 1},
            "input_z_error": 0.01,
        },
    ) == {"noise_model": "noise/v1", "noise_params": {"example": 1}}
    assert (
        backend._event_parameters(
            "initialize_plus",
            {"noise_model": "noise/v1", "noise_params": {}, "input_z_error": 0.01},
        )
        == {}
    )


def test_theory_selector_cannot_silently_request_legacy_proxy():
    backend, _ = setup_backend(FactoryExperimentModel(input_z_error=0.01))
    with pytest.raises(ValueError, match="MODEL_SELECTOR"):
        backend.resolve_event_from_sources(
            "factory_cost_proxy", (), {}, event_id="factory0/batch[0]/final-check"
        )


def test_factory_cost_keeps_own_wait_for_peer_and_scopes_atoms(monkeypatch):
    backend, code = setup_backend()
    captured = {}

    def evaluate(bundle, params, **kwargs):
        captured.update(bundle=bundle, params=params, **kwargs)
        return {
            "result_hash": "global-result",
            "interval_selection": {
                "include_intervals": [[10, 40]],
                "selected_activity_sha256": "selected",
                "selected_event_indices": [1, 3],
                "noise_profile": "independent_pauli_rates_v1",
                "exposure_partition": "absolute_intersections",
            },
            "participant_selection": {"owner_id": "factory0", "atom_ids": [0, 1]},
        }

    monkeypatch.setattr(
        "modules.logical_compiler.examples.array_backend.evaluate_participant_cost",
        evaluate,
    )
    backend.resolve_event_from_sources(
        "factory_cost_proxy",
        (backend.physical.final_check,),
        {"noise_params": {"test": "params"}},
        event_id="factory0/batch[0]/final-check",
    )
    assert captured["bundle"] == "real-global-bundle"
    assert captured["participant_atom_ids"] == (0, 1)
    assert captured["include_intervals"] == ((10.0, 40.0),)
    assert captured["owner_id"] == "factory0"
    assert code.received[1]["excluded_raw_intervals_us"] == [[0.0, 10.0]]
    assert code.received[1]["participant_selection"]["atom_ids"] == [0, 1]


@pytest.mark.parametrize(
    "identity",
    ["factory1/batch[0]/final", "factory00/batch[0]/final", "factory0/other/final"],
)
def test_factory_scope_never_borrows_another_line(identity):
    backend, _ = setup_backend()
    with pytest.raises(ValueError, match="FACTORY_SCOPE"):
        backend.resolve_event_from_sources(
            "factory_cost_proxy",
            (backend.physical.final_check,),
            {"noise_params": {}},
            event_id=identity,
        )


def test_theory_final_check_rejects_foreign_or_uncommitted_sources():
    backend, _ = setup_backend(FactoryExperimentModel(input_z_error=0.01))
    for source, message in (
        (
            SimpleNamespace(invocation_id="factory1/batch[0]/mx", results_ready_us=35),
            "SOURCE_SCOPE",
        ),
        (
            SimpleNamespace(invocation_id="factory0/batch[0]/mx", results_ready_us=35),
            "NOT_COMMITTED",
        ),
    ):
        with pytest.raises(ValueError, match=message):
            backend.resolve_event_from_sources(
                "factory_mx", (source,), {}, event_id="factory0/batch[0]/final-check"
            )
