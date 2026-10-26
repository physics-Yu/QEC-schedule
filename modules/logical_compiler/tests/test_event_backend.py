"""Identity-stable coarse-event sampling using the shared probability contract."""

import json
import math
from dataclasses import FrozenInstanceError

import pytest

from modules.codes.contracts.event_probability import ProbabilityPort
from modules.logical_compiler.src.cases import backend as event_backend
from modules.logical_compiler.src.cases.backend import (
    EventResult,
    Occurrence,
    SeededEventBackend,
)


def fixture_document() -> dict:
    """Return explicitly synthetic probabilities, never a surface-code estimate."""
    return {
        "schema": "nadit.event_probability/1",
        "port_id": "test_fixture.joint",
        "protocol_id": "test_fixture.correlated_events",
        "protocol_version": "1",
        "model": {
            "id": "synthetic_half",
            "kind": "test_fixture",
            "assumptions": ["Synthetic joint outcomes for backend tests only"],
            "parameters": {},
            "evidence": {},
        },
        "outcomes": [
            {
                "key": "m0",
                "probability": 0.5,
                "values": {"left": 0, "right": 0},
                "branch_id": "continue_zero",
            },
            {
                "key": "m1",
                "probability": 0.5,
                "values": {"left": 1, "right": 1},
                "branch_id": "continue_one",
            },
        ],
        "branches": [
            {"key": "continue_zero", "transition": "continue", "steps": []},
            {"key": "continue_one", "transition": "continue", "steps": []},
        ],
    }


def occurrence(invocation_id: str = "invocation", attempt: int = 0) -> Occurrence:
    return Occurrence("case", invocation_id, attempt, "test_fixture.joint")


def test_repeat_returns_same_immutable_result_and_does_not_resample():
    port = ProbabilityPort.from_dict(fixture_document())
    backend = SeededEventBackend("case", seed=17)
    first = backend.sample(port, occurrence(), available_at_us=3.25)
    equivalent_port = ProbabilityPort.from_dict(port.to_dict())
    assert backend.sample(equivalent_port, occurrence(), available_at_us=3.25) is first
    assert backend.results == (first,)
    assert first.port_sha256 == port.content_sha256
    with pytest.raises(FrozenInstanceError):
        first.outcome_key = "changed"


def test_frontier_visitation_order_and_fresh_backend_preserve_each_outcome():
    port = ProbabilityPort.from_dict(fixture_document())
    forward = SeededEventBackend("case", seed=-121)
    reverse = SeededEventBackend("case", seed=-121)
    occurrences = [occurrence(f"factory-{i}") for i in range(100)]
    for item in occurrences:
        forward.sample(port, item, available_at_us=8.0)
    for item in reversed(occurrences):
        reverse.sample(port, item, available_at_us=8.0)
    assert forward.results == reverse.results
    assert {result.outcome_key for result in forward.results} == {"m0", "m1"}
    assert [result.occurrence for result in forward.results] == sorted(
        occurrences,
        key=lambda item: (item.case_id, item.invocation_id, item.attempt, item.port_id),
    )


def test_retry_attempt_is_an_independent_identity_without_mutating_previous_result():
    port = ProbabilityPort.from_dict(fixture_document())
    backend = SeededEventBackend("case", seed=8)
    results = [
        backend.sample(port, occurrence(attempt=i), available_at_us=float(i))
        for i in range(100)
    ]
    assert len(backend.results) == 100
    assert {result.outcome_key for result in results} == {"m0", "m1"}
    assert backend.sample(port, occurrence(), available_at_us=0) is results[0]


def test_different_seeds_produce_different_deterministic_case_samples():
    port = ProbabilityPort.from_dict(fixture_document())
    first = SeededEventBackend("case", seed=1)
    second = SeededEventBackend("case", seed=2)
    first_keys = []
    second_keys = []
    for index in range(100):
        item = occurrence(str(index))
        first_keys.append(first.sample(port, item, available_at_us=0).outcome_key)
        second_keys.append(second.sample(port, item, available_at_us=0).outcome_key)
    assert first_keys != second_keys


def test_joint_outcome_is_selected_whole_without_independent_marginal_sampling():
    port = ProbabilityPort.from_dict(fixture_document())
    backend = SeededEventBackend("case", seed=2026)
    for index in range(100):
        result = backend.sample(port, occurrence(str(index)), available_at_us=0)
        values = dict(port.outcome(result.outcome_key).values)
        assert values["left"] == values["right"]
        assert result.evidence_kind == "coarse_probability"
        assert "syndrome" not in result.to_dict()


@pytest.mark.parametrize("zero_index", [0, 1])
def test_zero_probability_is_never_selected(zero_index):
    document = fixture_document()
    document["outcomes"][zero_index]["probability"] = 0.0
    document["outcomes"][1 - zero_index]["probability"] = 1.0
    port = ProbabilityPort.from_dict(document)
    backend = SeededEventBackend("case", seed=0)
    assert {
        backend.sample(port, occurrence(str(index)), available_at_us=0).outcome_key
        for index in range(100)
    } == {f"m{1 - zero_index}"}


@pytest.mark.parametrize(
    ("draw", "expected"), [(0.0, "m0"), (0.5, "m1"), (math.nextafter(1.0, 0.0), "m1")]
)
def test_probability_intervals_handle_exact_boundaries(monkeypatch, draw, expected):
    monkeypatch.setattr(event_backend, "_uniform_draw", lambda *_: draw)
    result = SeededEventBackend("case", seed=0).sample(
        ProbabilityPort.from_dict(fixture_document()), occurrence(), available_at_us=0
    )
    assert result.outcome_key == expected


def test_zero_probability_is_skipped_even_at_zero_draw(monkeypatch):
    document = fixture_document()
    document["outcomes"][0]["probability"] = 0.0
    document["outcomes"][1]["probability"] = 1.0
    monkeypatch.setattr(event_backend, "_uniform_draw", lambda *_: 0.0)
    result = SeededEventBackend("case", seed=0).sample(
        ProbabilityPort.from_dict(document), occurrence(), available_at_us=0
    )
    assert result.outcome_key == "m1"


def test_tolerated_probability_sum_gap_is_not_silently_normalized(monkeypatch):
    document = fixture_document()
    document["outcomes"][1]["probability"] -= 5e-13
    port = ProbabilityPort.from_dict(document)
    monkeypatch.setattr(
        event_backend, "_uniform_draw", lambda *_: math.nextafter(1.0, 0.0)
    )
    backend = SeededEventBackend("case", seed=0)
    with pytest.raises(ValueError, match="EVENT_PROBABILITY_GAP"):
        backend.sample(port, occurrence(), available_at_us=0)
    assert backend.results == ()


@pytest.mark.parametrize("change", ["probability", "evidence", "branch"])
def test_changed_complete_port_document_is_rejected_for_bound_occurrence(change):
    document = fixture_document()
    backend = SeededEventBackend("case", seed=0)
    original = backend.sample(
        ProbabilityPort.from_dict(document), occurrence(), available_at_us=4
    )
    if change == "probability":
        document["outcomes"][0]["probability"] = 0.25
        document["outcomes"][1]["probability"] = 0.75
    elif change == "evidence":
        document["model"]["evidence"]["revision"] = "different"
    else:
        document["branches"][0]["transition"] = "deliver"
    with pytest.raises(ValueError, match="EVENT_BINDING_CONFLICT"):
        backend.sample(
            ProbabilityPort.from_dict(document), occurrence(), available_at_us=4
        )
    assert backend.results == (original,)


def test_changed_result_ready_time_is_rejected_for_bound_occurrence():
    port = ProbabilityPort.from_dict(fixture_document())
    backend = SeededEventBackend("case", seed=0)
    original = backend.sample(port, occurrence(), available_at_us=4)
    with pytest.raises(ValueError, match="EVENT_BINDING_CONFLICT"):
        backend.sample(port, occurrence(), available_at_us=4.000001)
    assert backend.results == (original,)


@pytest.mark.parametrize("ready", [-1, float("nan"), float("inf"), True, "1"])
def test_invalid_ready_times_are_rejected_without_recording_result(ready):
    port = ProbabilityPort.from_dict(fixture_document())
    backend = SeededEventBackend("case", seed=0)
    with pytest.raises(ValueError, match="INVALID_EVENT_TIME"):
        backend.sample(port, occurrence(), available_at_us=ready)
    assert backend.results == ()


@pytest.mark.parametrize(
    "item",
    [
        Occurrence("other-case", "invocation", 0, "test_fixture.joint"),
        Occurrence("case", "invocation", 0, "other-port"),
    ],
)
def test_wrong_case_or_port_identity_is_rejected(item):
    backend = SeededEventBackend("case", seed=0)
    with pytest.raises(ValueError, match="EVENT_IDENTITY_MISMATCH"):
        backend.sample(
            ProbabilityPort.from_dict(fixture_document()), item, available_at_us=0
        )
    assert backend.results == ()


@pytest.mark.parametrize("attempt", [-1, True, 0.5, "0"])
def test_occurrence_requires_nonnegative_integer_attempt(attempt):
    with pytest.raises(ValueError, match="INVALID_EVENT_IDENTITY"):
        occurrence(attempt=attempt)


@pytest.mark.parametrize("field", ["case_id", "invocation_id", "port_id"])
@pytest.mark.parametrize("value", ["", None, 1])
def test_occurrence_requires_nonempty_string_identity_fields(field, value):
    fields = {
        "case_id": "case",
        "invocation_id": "invocation",
        "attempt": 0,
        "port_id": "test_fixture.joint",
    }
    fields[field] = value
    with pytest.raises(ValueError, match="INVALID_EVENT_IDENTITY"):
        Occurrence(**fields)


@pytest.mark.parametrize("seed", [True, 1.5, "3", None])
def test_backend_requires_integer_seed(seed):
    with pytest.raises(ValueError, match="INVALID_EVENT_SEED"):
        SeededEventBackend("case", seed=seed)


@pytest.mark.parametrize("case_id", ["", None, 1])
def test_backend_requires_nonempty_case_id(case_id):
    with pytest.raises(ValueError, match="INVALID_EVENT_IDENTITY"):
        SeededEventBackend(case_id, seed=3)


@pytest.mark.parametrize("mode", ["syndrome_decoder", "detailed_syndrome", "unknown"])
def test_detailed_or_unknown_backends_are_explicitly_unsupported(mode):
    with pytest.raises(NotImplementedError, match="UNSUPPORTED_EVENT_BACKEND"):
        SeededEventBackend("case", seed=1, backend_kind=mode)


def test_serialized_result_contains_bound_identity_and_hash_but_no_synthetic_bits():
    port = ProbabilityPort.from_dict(fixture_document())
    result = SeededEventBackend("case", seed=2).sample(
        port, occurrence("named", 3), available_at_us=7
    )
    document = result.to_dict()
    assert document == {
        "occurrence": {
            "case_id": "case",
            "invocation_id": "named",
            "attempt": 3,
            "port_id": "test_fixture.joint",
        },
        "port_sha256": port.content_sha256,
        "available_at_us": 7.0,
        "outcome_key": result.outcome_key,
        "evidence_kind": "coarse_probability",
    }
    assert json.loads(json.dumps(document)) == document
    document["occurrence"]["attempt"] = 999
    assert result.occurrence.attempt == 3


def test_result_cannot_claim_detailed_measurement_evidence():
    with pytest.raises(ValueError, match="UNSUPPORTED_EVENT_EVIDENCE"):
        EventResult(occurrence(), "0" * 64, 0, "m0", evidence_kind="syndrome")
