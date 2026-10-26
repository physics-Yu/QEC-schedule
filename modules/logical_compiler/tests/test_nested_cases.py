"""Nested continuation and fan-in regression checks with synthetic events."""

from modules.codes.contracts.event_probability import ProbabilityPort
from modules.logical_compiler.src.cases import (
    AbstractComponent,
    Invocation,
    compile_case,
)
from modules.logical_compiler.tests.test_cases import fixture_port


def _nested_components(
    child_accept_probability: float,
) -> tuple[AbstractComponent, ...]:
    child_document = fixture_port(
        child_accept_probability,
        "retry",
        [{"component_id": "cleanup", "participant_roles": ["target"]}],
    ).to_dict()
    child_document["port_id"] = "test_fixture.child"
    child = ProbabilityPort.from_dict(child_document)
    parent_document = fixture_port(
        0,
        "continue",
        [
            {"component_id": "child", "participant_roles": ["data"]},
            {"component_id": "tail", "participant_roles": ["data"]},
        ],
    ).to_dict()
    parent_document["port_id"] = "test_fixture.parent"
    parent = ProbabilityPort.from_dict(parent_document)
    return (
        AbstractComponent("parent", ("data",), 2, parent, 3),
        AbstractComponent("child", ("target",), 4, child, 1),
        AbstractComponent("cleanup", ("target",), 2),
        AbstractComponent("tail", ("target",), 5),
        AbstractComponent("successor", ("data",), 1),
    )


def _roots(max_attempts: int) -> tuple[Invocation, ...]:
    return (
        Invocation("root", "parent", (("data", "D"),), max_attempts=max_attempts),
        Invocation("next", "successor", (("data", "D"),), after=("root",)),
    )


def test_nested_retry_finishes_before_next_step_and_root_successor():
    components = _nested_components(0.5)
    roots = _roots(3)
    # This stable fixture seed selects reject then accept for the child.
    document = compile_case(
        roots, components=components, case_id="review", seed=0
    ).to_dict()
    assert document["status"] == "complete"
    assert document["unresolved_invocations"] == []
    assert document["duration_us"] == 19
    assert [
        (call["component_id"], call["attempt"], call["start_us"])
        for call in document["calls"]
    ] == [
        ("parent", 0, 0),
        ("child", 0, 3),
        ("cleanup", 0, 7),
        ("child", 1, 9),
        ("tail", 0, 13),
        ("successor", 0, 18),
    ]
    parent, child_first, cleanup, child_second, tail, successor = document["calls"]
    assert child_first["invocation_id"] == child_second["invocation_id"]
    assert child_second["after_calls"] == [cleanup["call_id"]]
    assert tail["after_calls"] == [child_second["call_id"]]
    assert successor["after_calls"] == [tail["call_id"]]
    assert parent["invocation_completed_at_us"] == 18
    assert child_second["invocation_completed_at_us"] == 13
    assert [event["outcome_key"] for event in document["events"]] == ["no", "no", "yes"]
    assert (
        document
        == compile_case(
            reversed(roots), components=reversed(components), case_id="review", seed=0
        ).to_dict()
    )


def test_nested_retry_exhaustion_preserves_parent_and_child_as_unresolved():
    document = compile_case(
        _roots(2), components=_nested_components(0), case_id="nested-fail", seed=0
    ).to_dict()
    assert document["status"] == "budget_exhausted"
    assert document["failure"]["code"] == "RETRY_BUDGET_EXHAUSTED"
    calls = document["calls"]
    assert [call["component_id"] for call in calls] == [
        "parent",
        "child",
        "cleanup",
        "child",
        "cleanup",
    ]
    child_id = calls[1]["invocation_id"]
    assert document["failure"]["invocation_id"] == child_id
    assert document["failure"]["attempt"] == 1
    assert set(document["unresolved_invocations"]) == {"root", child_id, "next"}
    assert document["processed_until_us"] == 15
    assert calls[-1]["invocation_completed_at_us"] == 15
    assert "invocation_completed_at_us" not in calls[0]
    assert document["deliveries"] == []
    assert [event["occurrence"]["attempt"] for event in document["events"][1:]] == [
        0,
        1,
    ]


def test_zero_duration_fanin_starts_successor_exactly_once():
    component = AbstractComponent("plain", ("data",), 0)
    roots = (
        Invocation("a", "plain", (("data", "A"),)),
        Invocation("b", "plain", (("data", "B"),)),
        Invocation("join", "plain", (("data", "J"),), after=("a", "b")),
    )
    document = compile_case(
        roots, components=(component,), case_id="zero", seed=0
    ).to_dict()
    assert document["status"] == "complete"
    assert document["duration_us"] == 0
    assert document["unresolved_invocations"] == []
    assert len(document["calls"]) == 3
    predecessors = [
        call for call in document["calls"] if call["invocation_id"] in ("a", "b")
    ]
    joins = [call for call in document["calls"] if call["invocation_id"] == "join"]
    assert len(joins) == 1
    assert joins[0]["after_calls"] == sorted(call["call_id"] for call in predecessors)
    assert all(call["invocation_completed_at_us"] == 0 for call in document["calls"])
    assert (
        document
        == compile_case(
            reversed(roots), components=(component,), case_id="zero", seed=0
        ).to_dict()
    )
