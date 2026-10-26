"""Consume a real surface-code probability artifact in abstract static cases.

The probability document is copied from the producer, with provenance beside it.
Component durations below are synthetic fixture values. They establish causal
branch release and role binding, not physical T/S execution or scheduling.
"""

import json
from pathlib import Path

import pytest

from modules.codes.contracts.event_probability import ProbabilityPort
from modules.logical_compiler.src.cases import (
    AbstractComponent,
    Invocation,
    compile_case,
)

_FIXTURES = Path(__file__).parent / "fixtures" / "event_probability"
_PORT_SHA256 = "027a1520ac29d3ebb4381518b8119c3d503ee9067abb8c285aa9ac7478e6371f"
_RAW_PORT_SHA256 = "67473fdb73d402200402db983ed05d3ec942ddadb30c20d04edbfc351ab8aede"
_RAW_VALIDATION_SHA256 = (
    "62a4b122a740cbd2861b720c8bdbac47cf84017cc4757b7c5c4afed6bb59639a"
)
_CASE_ID = "producer-t-injection"
_INVOCATION_ID = "inject-t"
_T_COMPONENT = "rotated_surface_d3/t_injection"
_S_COMPONENT = "rotated_surface_d3/logical_s"


@pytest.fixture
def injection_port() -> ProbabilityPort:
    """Load the frozen producer document through the shared contract validator."""
    document = json.loads((_FIXTURES / "t_injection.ideal.json").read_text("utf-8"))
    return ProbabilityPort.from_dict(document)


def test_real_producer_fixture_retains_fingerprint_and_provenance(
    injection_port: ProbabilityPort,
) -> None:
    provenance = json.loads(
        (_FIXTURES / "t_injection.ideal.provenance.json").read_text("utf-8")
    )
    assert injection_port.content_sha256 == _PORT_SHA256
    assert provenance["content_sha256"] == _PORT_SHA256
    assert provenance["producer_arguments"] == {}
    assert provenance["producer_callable"].endswith(".t_injection.t_injection_port")
    document = injection_port.to_dict()
    assert document["model"]["kind"] == "ideal_exact"
    assert document["model"]["evidence"]["scope"] == "logical_branch_statistics_only"
    assert {
        outcome.key: outcome.probability for outcome in injection_port.outcomes
    } == {
        "m0": 0.5,
        "m1": 0.5,
    }


@pytest.mark.parametrize(
    ("seed", "outcome", "branch", "logical_m", "has_correction"),
    [(1, "m0", "no_correction", 0, False), (0, "m1", "apply_s", 1, True)],
)
@pytest.mark.parametrize(("exit_after", "ready_after"), [(5, 12), (20, 4)])
def test_real_t_producer_expands_both_fixed_seed_cases(
    injection_port: ProbabilityPort,
    seed: int,
    outcome: str,
    branch: str,
    logical_m: int,
    has_correction: bool,
    exit_after: float,
    ready_after: float,
    tmp_path: Path,
) -> None:
    # These declarations are abstract adapters, not certified physical components.
    catalog = (
        AbstractComponent(
            _T_COMPONENT, ("data", "magic"), exit_after, injection_port, ready_after
        ),
        AbstractComponent(_S_COMPONENT, ("patch",), 3),
        AbstractComponent("test_fixture/successor", ("data",), 2),
    )
    roots = (
        Invocation(
            _INVOCATION_ID,
            _T_COMPONENT,
            (("data", "data-patch"), ("magic", "magic-patch")),
        ),
        Invocation(
            "successor",
            "test_fixture/successor",
            (("data", "data-patch"),),
            (_INVOCATION_ID,),
        ),
    )
    result = compile_case(roots, components=catalog, case_id=_CASE_ID, seed=seed)
    document = result.to_dict()
    assert result.status == "complete"
    assert document["artifact_kind"] == "abstract_case"
    assert document["execution_ready"] is False
    assert document["physical_validation"] == "not_run"
    assert document["resource_scheduling"] == "not_performed"
    assert document["frame_status"] == "unresolved"
    assert document["unresolved_invocations"] == []
    assert document["probability_models"] == {_PORT_SHA256: injection_port.to_dict()}
    assert document["probability_models_usage"] == "evidence_only"
    assert len(document["events"]) == 1
    event = document["events"][0]
    assert event["occurrence"] == {
        "case_id": _CASE_ID,
        "invocation_id": _INVOCATION_ID,
        "attempt": 0,
        "port_id": injection_port.port_id,
    }
    assert event["port_sha256"] == _PORT_SHA256
    assert event["evidence_kind"] == "coarse_probability"
    assert event["outcome_key"] == outcome
    assert event["branch_id"] == branch
    assert event["values"] == {"logical_m": logical_m}
    assert event["transition"] == "continue"
    assert event["available_at_us"] == ready_after
    released_at = max(exit_after, ready_after)
    assert event["released_at_us"] == released_at

    calls = document["calls"]
    expected_components = [_T_COMPONENT]
    if has_correction:
        expected_components.append(_S_COMPONENT)
    expected_components.append("test_fixture/successor")
    assert [call["component_id"] for call in calls] == expected_components
    assert calls[0]["bindings"] == {"data": "data-patch", "magic": "magic-patch"}
    assert calls[0]["exit_at_us"] == exit_after
    assert calls[0]["event_available_at_us"] == ready_after
    assert calls[0]["after_calls"] == []
    if has_correction:
        assert calls[1]["bindings"] == {"patch": "data-patch"}
        assert calls[1]["start_us"] == released_at
        assert calls[1]["exit_at_us"] == released_at + 3
        assert calls[1]["after_calls"] == [calls[0]["call_id"]]
        assert event["expanded_step_invocations"] == [calls[1]["invocation_id"]]
    else:
        assert event["expanded_step_invocations"] == []
    successor_start = released_at + (3 if has_correction else 0)
    assert calls[-1]["start_us"] == successor_start
    assert calls[-1]["after_calls"] == [calls[-2]["call_id"]]
    assert calls[0]["invocation_completed_at_us"] == successor_start
    assert document["duration_us"] == successor_start + 2
    assert document["deliveries"] == []
    assert (
        result.to_json()
        == compile_case(
            roots, components=catalog, case_id=_CASE_ID, seed=seed
        ).to_json()
    )
    artifact = tmp_path / f"t_injection.{outcome}.abstract_case.json"
    artifact.write_text(result.to_json(), encoding="utf-8")
    assert json.loads(artifact.read_text("utf-8")) == document


def test_real_raw_t_acceptance_delivers_once_without_resolving_bulk_frame(
    tmp_path: Path,
) -> None:
    """Raw acceptance is a separate case, not proof of canonical T consumption."""
    port = ProbabilityPort.from_dict(
        json.loads((_FIXTURES / "raw_t_postselection.ideal.json").read_text("utf-8"))
    )
    provenance = json.loads(
        (_FIXTURES / "raw_t_postselection.ideal.provenance.json").read_text("utf-8")
    )
    assert port.content_sha256 == _RAW_PORT_SHA256
    assert provenance["content_sha256"] == _RAW_PORT_SHA256
    model = port.to_dict()["model"]
    assert model["kind"] == "ideal_exact"
    assert model["parameters"]["extra_rounds"] == 1
    assert model["evidence"]["detector_count"] == 12
    assert model["evidence"]["logical_error_rate_claimed"] is False
    assert {outcome.key: outcome.probability for outcome in port.outcomes} == {
        "accepted": 1.0,
        "rejected": 0.0,
    }
    component_id = "rotated_surface_d3/raw_t_postselection"
    catalog = (AbstractComponent(component_id, ("magic",), 11, port, 13),)
    roots = (
        Invocation("prepare-raw-t", component_id, (("magic", "M"),), max_attempts=3),
    )
    result = compile_case(roots, components=catalog, case_id="producer-raw-t", seed=7)
    document = result.to_dict()
    assert result.status == "complete"
    assert document["artifact_kind"] == "abstract_case"
    assert document["execution_ready"] is False
    assert document["physical_validation"] == "not_run"
    assert document["resource_scheduling"] == "not_performed"
    assert document["frame_status"] == "unresolved"
    assert document["unresolved_invocations"] == []
    assert document["probability_models"] == {_RAW_PORT_SHA256: port.to_dict()}
    assert len(document["calls"]) == 1
    assert len(document["events"]) == 1
    event = document["events"][0]
    assert event["occurrence"]["attempt"] == 0
    assert event["port_sha256"] == _RAW_PORT_SHA256
    assert event["outcome_key"] == "accepted"
    assert event["values"] == {"accepted": True}
    assert event["branch_id"] == event["transition"] == "deliver"
    assert event["released_at_us"] == 13
    assert len(document["deliveries"]) == 1
    assert document["deliveries"][0]["invocation_id"] == "prepare-raw-t"
    assert document["deliveries"][0]["ready_at_us"] == 13
    assert document["deliveries"][0]["quality_verified"] is False
    assert document["duration_us"] == 13
    artifact = tmp_path / "raw_t.accepted.abstract_case.json"
    artifact.write_text(result.to_json(), encoding="utf-8")
    assert json.loads(artifact.read_text("utf-8")) == document
    assert (
        result.to_json()
        == compile_case(
            roots, components=catalog, case_id="producer-raw-t", seed=7
        ).to_json()
    )


def test_real_raw_t_validation_model_retries_then_accepts_with_finite_budget(
    tmp_path: Path,
) -> None:
    """Exercise a validation-only distribution without selecting production noise."""
    port = ProbabilityPort.from_dict(
        json.loads(
            (_FIXTURES / "raw_t_postselection.readout_validation.json").read_text(
                "utf-8"
            )
        )
    )
    provenance = json.loads(
        (
            _FIXTURES / "raw_t_postselection.readout_validation.provenance.json"
        ).read_text("utf-8")
    )
    assert port.content_sha256 == _RAW_VALIDATION_SHA256
    assert provenance["content_sha256"] == _RAW_VALIDATION_SHA256
    assert provenance["validation_only"] is True
    assert provenance["production_noise_selected"] is False
    model = port.to_dict()["model"]
    assert model["kind"] == "pauli_exact"
    assert model["parameters"]["noise"]["readout_flip"] == 0.1
    assert model["evidence"]["scope"] == "pauli_readout_only"
    assert model["evidence"]["logical_error_rate_claimed"] is False
    assert port.outcome("accepted").probability == 0.1946235926074897

    component_id = "rotated_surface_d3/raw_t_postselection"
    # Deliberately use declared abstract offsets, not producer activity duration.
    catalog = (AbstractComponent(component_id, ("magic",), 11, port, 13),)
    roots = (
        Invocation("prepare-raw-t", component_id, (("magic", "M"),), max_attempts=2),
    )
    result = compile_case(
        roots, components=catalog, case_id="producer-raw-t-retry", seed=3
    )
    document = result.to_dict()
    assert result.status == "complete"
    assert document["artifact_kind"] == "abstract_case"
    assert document["execution_ready"] is False
    assert document["physical_validation"] == "not_run"
    assert document["resource_scheduling"] == "not_performed"
    assert document["frame_status"] == "unresolved"
    assert document["unresolved_invocations"] == []
    assert document["probability_models"] == {_RAW_VALIDATION_SHA256: port.to_dict()}
    assert document["probability_models_usage"] == "evidence_only"
    assert document["roots"][0]["max_attempts"] == 2
    assert document["failure"] is None
    events = document["events"]
    assert [event["outcome_key"] for event in events] == ["rejected", "accepted"]
    assert [event["transition"] for event in events] == ["retry", "deliver"]
    assert [event["occurrence"]["attempt"] for event in events] == [0, 1]
    assert [event["values"] for event in events] == [
        {"accepted": False},
        {"accepted": True},
    ]
    assert [event["released_at_us"] for event in events] == [13, 26]
    assert all(event["port_sha256"] == _RAW_VALIDATION_SHA256 for event in events)
    assert all(event["evidence_kind"] == "coarse_probability" for event in events)
    calls = document["calls"]
    assert len(calls) == 2
    assert [call["attempt"] for call in calls] == [0, 1]
    assert [call["start_us"] for call in calls] == [0, 13]
    assert [call["exit_at_us"] for call in calls] == [11, 24]
    assert calls[1]["after_calls"] == [calls[0]["call_id"]]
    assert len(document["deliveries"]) == 1
    assert document["deliveries"][0]["attempt"] == 1
    assert document["deliveries"][0]["ready_at_us"] == 26
    assert document["deliveries"][0]["quality_verified"] is False
    assert document["duration_us"] == 26
    artifact = tmp_path / "raw_t.validation_retry.abstract_case.json"
    artifact.write_text(result.to_json(), encoding="utf-8")
    assert json.loads(artifact.read_text("utf-8")) == document
    assert (
        result.to_json()
        == compile_case(
            roots, components=catalog, case_id="producer-raw-t-retry", seed=3
        ).to_json()
    )
