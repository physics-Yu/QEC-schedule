"""Protocol-event expansion, causal timing and honest static-case evidence."""

import json

import pytest

from modules.codes.contracts.event_probability import ProbabilityPort
from modules.logical_compiler.src.cases import (
    AbstractComponent,
    CaseLimits,
    Invocation,
    compile_case,
)


def fixture_port(probability=1.0, transition="continue", steps=()):
    return ProbabilityPort.from_dict(
        {
            "schema": "nadit.event_probability/1",
            "port_id": "test_fixture.joint",
            "protocol_id": "test_fixture.protocol",
            "protocol_version": "1",
            "model": {
                "id": "test_fixture",
                "kind": "test_fixture",
                "assumptions": [
                    "Synthetic scheduling fixture, not a physical estimate"
                ],
                "parameters": {},
                "evidence": {},
            },
            "outcomes": [
                {
                    "key": "yes",
                    "probability": probability,
                    "values": {"accepted": True},
                    "branch_id": "yes_branch",
                },
                {
                    "key": "no",
                    "probability": 1 - probability,
                    "values": {"accepted": False},
                    "branch_id": "no_branch",
                },
            ],
            "branches": [
                {"key": "yes_branch", "transition": "deliver", "steps": []},
                {"key": "no_branch", "transition": transition, "steps": list(steps)},
            ],
        }
    )


def components(port, exit_after=5, ready_after=12):
    return (
        AbstractComponent("protocol", ("data",), exit_after, port, ready_after),
        AbstractComponent("s", ("target",), 3),
        AbstractComponent("cleanup", ("target",), 2),
        AbstractComponent("next", ("data",), 1),
    )


def test_branch_waits_for_both_result_and_exit_then_releases_successor():
    port = fixture_port(0, steps=[{"component_id": "s", "participant_roles": ["data"]}])
    result = compile_case(
        (
            Invocation("first", "protocol", (("data", "D"),)),
            Invocation("second", "next", (("data", "D"),), ("first",)),
        ),
        components=components(port),
        case_id="case",
        seed=0,
    )
    assert result.status == "complete"
    document = result.to_dict()
    assert document["artifact_kind"] == "abstract_case"
    assert document["execution_ready"] is False
    assert document["unresolved_invocations"] == []
    calls = document["calls"]
    first, correction, second = calls
    assert first["exit_at_us"] == 5
    assert first["event_available_at_us"] == 12
    assert correction["start_us"] == 12
    assert correction["bindings"] == {"target": "D"}
    assert second["start_us"] == 15
    assert document["duration_us"] == 16
    assert document["events"][0]["branch_id"] == "no_branch"
    assert document["events"][0]["transition"] == "continue"
    assert document["probability_models"][port.content_sha256] == port.to_dict()
    assert "syndrome" not in document["events"][0]["values"]
    assert document["frame_status"] == "unresolved"


def test_early_result_still_waits_for_exit():
    port = fixture_port(0, steps=[{"component_id": "s", "participant_roles": ["data"]}])
    result = compile_case(
        (Invocation("root", "protocol", (("data", "D"),)),),
        components=components(port, exit_after=20, ready_after=4),
        case_id="c",
        seed=1,
    ).to_dict()
    assert result["events"][0]["released_at_us"] == 20
    assert result["calls"][1]["start_us"] == 20


def test_retry_executes_cleanup_and_gets_fresh_attempt_until_budget_exhausted():
    port = fixture_port(
        0, "retry", [{"component_id": "cleanup", "participant_roles": ["data"]}]
    )
    result = compile_case(
        (Invocation("line", "protocol", (("data", "M"),), max_attempts=2),),
        components=components(port, exit_after=5, ready_after=8),
        case_id="c",
        seed=1,
    ).to_dict()
    assert result["status"] == "budget_exhausted"
    assert result["failure"]["code"] == "RETRY_BUDGET_EXHAUSTED"
    attempts = [call for call in result["calls"] if call["invocation_id"] == "line"]
    assert [call["attempt"] for call in attempts] == [0, 1]
    assert [call["start_us"] for call in attempts] == [0, 10]
    assert (
        len([call for call in result["calls"] if call["component_id"] == "cleanup"])
        == 2
    )
    assert result["duration_us"] == 20
    assert result["unresolved_invocations"] == ["line"]
    assert result["deliveries"] == []
    assert [event["occurrence"]["attempt"] for event in result["events"]] == [0, 1]


def test_deterministic_acceptance_delivers_without_retry_or_extra_steps():
    port = fixture_port()
    result = compile_case(
        (Invocation("line", "protocol", (("data", "M"),), max_attempts=5),),
        components=components(port),
        case_id="c",
        seed=99,
    ).to_dict()
    assert result["status"] == "complete"
    assert len(result["calls"]) == 1
    assert len(result["events"]) == 1
    assert result["deliveries"][0]["ready_at_us"] == 12
    assert result["deliveries"][0]["invocation_id"] == "line"


def test_frontier_input_order_does_not_change_artifact():
    port = fixture_port(
        0.5, steps=[{"component_id": "s", "participant_roles": ["data"]}]
    )
    roots = tuple(
        Invocation(name, "protocol", (("data", name),)) for name in ("a", "b", "c")
    )
    args = {"components": components(port), "case_id": "case", "seed": 91}
    forward = compile_case(roots, **args).to_json()
    reverse = compile_case(tuple(reversed(roots)), **args).to_json()
    assert forward == reverse
    assert json.loads(forward)["status"] == "complete"


def test_unknown_selected_continuation_is_a_capability_failure():
    port = fixture_port(
        0, steps=[{"component_id": "unimplemented_s", "participant_roles": ["data"]}]
    )
    result = compile_case(
        (Invocation("root", "protocol", (("data", "D"),)),),
        components=components(port),
        case_id="case",
        seed=4,
    ).to_dict()
    assert result["status"] == "failed"
    assert result["failure"]["code"] == "UNSUPPORTED_COMPONENT"
    assert result["events"][0]["transition"] == "continue"
    assert result["unresolved_invocations"] == ["root"]


def test_unselected_unsupported_branch_is_not_instantiated():
    port = fixture_port(
        1, steps=[{"component_id": "missing", "participant_roles": ["data"]}]
    )
    result = compile_case(
        (Invocation("root", "protocol", (("data", "D"),)),),
        components=components(port),
        case_id="case",
        seed=4,
    )
    assert result.status == "complete"


def test_multiple_seeds_exercise_both_branches_without_unresolved_probabilities():
    port = fixture_port(
        0.5, steps=[{"component_id": "s", "participant_roles": ["data"]}]
    )
    outcomes = set()
    for seed in range(32):
        doc = compile_case(
            (Invocation("root", "protocol", (("data", "D"),)),),
            components=components(port),
            case_id="c",
            seed=seed,
        ).to_dict()
        event = doc["events"][0]
        outcomes.add(event["outcome_key"])
        assert doc["status"] == "complete"
        assert doc["unresolved_invocations"] == []
        assert sum(call["component_id"] == "s" for call in doc["calls"]) == (
            event["outcome_key"] == "no"
        )
    assert outcomes == {"yes", "no"}


def test_dynamic_step_can_itself_produce_an_event():
    child = fixture_port(1)
    parent_doc = fixture_port(
        0, steps=[{"component_id": "child", "participant_roles": ["data"]}]
    ).to_dict()
    parent_doc["port_id"] = "test_fixture.parent"
    parent = ProbabilityPort.from_dict(parent_doc)
    catalog = components(parent) + (
        AbstractComponent("child", ("target",), 2, child, 5),
    )
    doc = compile_case(
        (Invocation("root", "protocol", (("data", "D"),)),),
        components=catalog,
        case_id="c",
        seed=3,
    ).to_dict()
    assert doc["status"] == "complete"
    assert len(doc["events"]) == 2
    assert doc["duration_us"] == 17
    assert doc["events"][1]["released_at_us"] == 17


def test_expansion_budget_bounds_recursive_continuations():
    port = fixture_port(
        0, steps=[{"component_id": "protocol", "participant_roles": ["data"]}]
    )
    doc = compile_case(
        (Invocation("root", "protocol", (("data", "D"),)),),
        components=components(port),
        case_id="c",
        seed=1,
        limits=CaseLimits(max_expansions=3),
    ).to_dict()
    assert doc["status"] == "budget_exhausted"
    assert doc["failure"]["code"] == "EXPANSION_BUDGET_EXHAUSTED"
    assert len(doc["calls"]) == 3


def test_invalid_dependency_graph_is_rejected_without_sampling():
    with pytest.raises(ValueError, match="DEPENDENCY"):
        compile_case(
            (
                Invocation("a", "next", (("data", "A"),), ("b",)),
                Invocation("b", "next", (("data", "B"),), ("a",)),
            ),
            components=components(fixture_port()),
            case_id="c",
            seed=1,
        )


def test_atom_and_decoder_modes_are_explicitly_unsupported():
    kwargs = {"components": components(fixture_port()), "case_id": "c", "seed": 0}
    with pytest.raises(ValueError, match="UNSUPPORTED"):
        compile_case((), mode="atom", **kwargs)
    with pytest.raises(ValueError, match="UNSUPPORTED"):
        compile_case((), backend_kind="syndrome_decoder", **kwargs)


def test_ordered_steps_and_join_depend_on_whole_invocation_completion():
    port = fixture_port(
        0,
        steps=[
            {"component_id": "s", "participant_roles": ["data"]},
            {"component_id": "cleanup", "participant_roles": ["data"]},
        ],
    )
    catalog = components(port) + (AbstractComponent("long", ("data",), 20),)
    doc = compile_case(
        (
            Invocation("a", "protocol", (("data", "A"),)),
            Invocation("b", "long", (("data", "B"),)),
            Invocation("join", "next", (("data", "A"),), ("a", "b")),
        ),
        components=catalog,
        case_id="join-case",
        seed=0,
    ).to_dict()
    calls = doc["calls"]
    assert [(call["component_id"], call["start_us"]) for call in calls] == [
        ("protocol", 0),
        ("long", 0),
        ("s", 12),
        ("cleanup", 15),
        ("next", 20),
    ]
    assert calls[0]["invocation_completed_at_us"] == 17
    assert set(calls[-1]["after_calls"]) == {calls[1]["call_id"], calls[3]["call_id"]}
    assert calls[3]["after_calls"] == [calls[2]["call_id"]]
    assert doc["duration_us"] == 21


def test_result_export_is_immutable_and_empty_case_is_complete():
    result = compile_case((), components=(), case_id="empty", seed=0)
    doc = result.to_dict()
    doc["calls"].append({"component_id": "mutated"})
    assert result.to_dict()["calls"] == []
    assert result.status == "complete"
    assert result.to_dict()["duration_us"] == 0


def test_unused_catalog_model_fingerprints_have_complete_snapshots():
    port = fixture_port()
    doc = compile_case((), components=components(port), case_id="c", seed=0).to_dict()
    assert doc["probability_models"][port.content_sha256] == port.to_dict()
    assert doc["events"] == []
    assert doc["calls"] == []
    assert doc["probability_models_usage"] == "evidence_only"


def test_rejection_cleanup_then_acceptance_releases_successor_once():
    port = fixture_port(
        0.5, "retry", [{"component_id": "cleanup", "participant_roles": ["data"]}]
    )
    roots = (
        Invocation("line", "protocol", (("data", "M"),), max_attempts=3),
        Invocation("consumer", "next", (("data", "M"),), ("line",)),
    )
    args = {
        "components": components(port, exit_after=5, ready_after=8),
        "case_id": "retry-success",
        "seed": 0,
    }
    result = compile_case(roots, **args)
    doc = result.to_dict()
    assert doc["status"] == "complete"
    assert [event["outcome_key"] for event in doc["events"]] == ["no", "yes"]
    assert [event["occurrence"]["attempt"] for event in doc["events"]] == [0, 1]
    assert [(call["component_id"], call["start_us"]) for call in doc["calls"]] == [
        ("protocol", 0),
        ("cleanup", 8),
        ("protocol", 10),
        ("next", 18),
    ]
    assert len(doc["deliveries"]) == 1
    assert doc["deliveries"][0]["ready_at_us"] == 18
    assert doc["duration_us"] == 19
    assert result.to_json() == compile_case(tuple(reversed(roots)), **args).to_json()


@pytest.mark.parametrize("budget", [0, -1, True, 1.2])
def test_invalid_budgets_are_rejected(budget):
    with pytest.raises(ValueError, match="positive integer"):
        CaseLimits(max_expansions=budget)
    with pytest.raises(ValueError, match="positive integer"):
        Invocation("a", "next", (), max_attempts=budget)


@pytest.mark.parametrize("duration", [-1, float("nan"), float("inf"), True])
def test_invalid_body_times_are_rejected(duration):
    with pytest.raises(ValueError, match="finite and nonnegative"):
        AbstractComponent("a", (), duration)


def test_event_requires_explicit_ready_offset_and_unique_roles():
    with pytest.raises(ValueError, match="required together"):
        AbstractComponent("a", (), 1, fixture_port())
    with pytest.raises(ValueError, match="required together"):
        AbstractComponent("a", (), 1, result_ready_after_us=2)
    with pytest.raises(ValueError, match="duplicate participant"):
        AbstractComponent("a", ("data", "data"), 1)


def test_missing_dependency_and_reserved_ids_are_input_errors():
    with pytest.raises(ValueError, match="DEPENDENCY"):
        compile_case(
            (Invocation("a", "next", (), ("missing",)),),
            components=(),
            case_id="c",
            seed=0,
        )
    with pytest.raises(ValueError, match="reserved"):
        compile_case(
            (Invocation("@internal", "next", ()),), components=(), case_id="c", seed=0
        )


def test_invalid_selected_role_is_failure_with_event_retained():
    port = fixture_port(
        0, steps=[{"component_id": "s", "participant_roles": ["missing"]}]
    )
    doc = compile_case(
        (Invocation("root", "protocol", (("data", "D"),)),),
        components=components(port),
        case_id="c",
        seed=0,
    ).to_dict()
    assert doc["status"] == "failed"
    assert doc["failure"]["code"] == "INVALID_PARTICIPANT_BINDING"
    assert len(doc["events"]) == 1
    assert len(doc["calls"]) == 1


def test_time_overflow_is_failure_without_nonfinite_json():
    doc = compile_case(
        (Invocation("a", "long", ()), Invocation("b", "long", (), ("a",))),
        components=(AbstractComponent("long", (), 1e308),),
        case_id="c",
        seed=0,
    ).to_dict()
    assert doc["status"] == "failed"
    assert doc["failure"]["code"] == "INVALID_CASE_TIME"
    assert len(doc["calls"]) == 1
