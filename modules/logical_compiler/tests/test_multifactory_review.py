"""Independent failure-isolation and synchronized multi-factory regressions."""

import pytest
from test_factory_process import _run
from test_scheduled_factory import DeclaredBackend

from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.contracts.parallel import ComponentExecutionSpec
from modules.logical_compiler.src.protocols.factory import FactoryLimits
from modules.logical_compiler.src.scheduling import ComponentNode, ComponentScheduler


def _node(identity, patch, *, after=()):
    return ComponentNode(
        identity,
        ComponentExecutionSpec(
            code_id="review_code",
            component_id="local",
            waveform_key="local/v1",
            participant_blocks=(patch,),
            spaces=(),
            exclusive_resources=(),
            parallel_mode="independent_aods_lockstep",
            result_count=0,
        ),
        after_calls=after,
    )


def test_cancellation_does_not_release_successors_or_cancel_other_factory():
    scheduler = ComponentScheduler()
    scheduler.add(
        _node("line-a/raw", "a"),
        _node("line-a/next", "a", after=("line-a/raw",)),
        _node("line-b/raw", "b"),
    )

    scheduler.cancel_pending(("line-a/raw",), reason="input_supply_exhausted")

    assert tuple(node.id for node in scheduler.frontier(100)) == ("line-b/raw",)
    state = scheduler.snapshot()
    assert state["completed"] == {}
    assert state["cancelled"] == {"line-a/raw": "input_supply_exhausted"}
    assert len(state["nodes"]) == 3


def test_cancelling_a_wave_member_invalidates_the_whole_uncommitted_admission():
    scheduler = ComponentScheduler()
    scheduler.add(_node("line-a/raw", "a"), _node("line-b/raw", "b"))
    previous = scheduler.admit(0, snapshot_id="unchanged-physical-world")
    assert previous.node_ids == ("line-a/raw", "line-b/raw")

    scheduler.cancel_pending(("line-a/raw",), reason="line_stopped")
    with pytest.raises(ValueError, match="STALE_ADMISSION"):
        scheduler.commit_admission(previous)

    assert scheduler.snapshot()["running"] == {}
    current = scheduler.admit(0, snapshot_id="unchanged-physical-world")
    assert current.node_ids == ("line-b/raw",)


@pytest.mark.parametrize("started_state", ["running", "completed"])
def test_started_and_pending_mixed_cancellation_is_atomic(started_state):
    scheduler = ComponentScheduler(mode="serial")
    scheduler.add(_node("line-a/started", "a"), _node("line-b/pending", "b"))
    admission = scheduler.admit(0, snapshot_id="world")
    scheduler.commit_admission(admission)
    if started_state == "completed":
        scheduler.mark_completed("line-a/started", 1)
    before = scheduler.snapshot()

    with pytest.raises(ValueError, match="CANNOT_CANCEL_STARTED_NODE"):
        scheduler.cancel_pending(
            ("line-b/pending", "line-a/started"), reason="line_stopped"
        )

    assert scheduler.snapshot() == before


def test_unknown_or_changed_cancellation_does_not_partially_change_other_line():
    scheduler = ComponentScheduler()
    scheduler.add(_node("line-a/raw", "a"), _node("line-b/raw", "b"))
    before = scheduler.snapshot()
    with pytest.raises(ValueError, match="UNKNOWN_CANCELLATION_NODE"):
        scheduler.cancel_pending(("line-b/raw", "missing"), reason="line_stopped")
    assert scheduler.snapshot() == before

    scheduler.cancel_pending(("line-a/raw",), reason="line_stopped")
    before = scheduler.snapshot()
    scheduler.cancel_pending(("line-a/raw",), reason="line_stopped")
    assert scheduler.snapshot() == before
    with pytest.raises(ValueError, match="CANCELLATION_CHANGED"):
        scheduler.cancel_pending(
            ("line-b/raw", "line-a/raw"), reason="different_failure"
        )
    assert scheduler.snapshot() == before


def _barrier_records(case, stage):
    return [
        item
        for item in case["milestones"]
        if item["kind"] == "cohort_barrier_released" and item["stage_key"] == stage
    ]


@pytest.mark.parametrize(
    ("role", "stage", "next_call"),
    [
        ("W1", "initial_preparations_ready", "prepare/R/attempt[0]/body"),
        ("R", "rotation[0]/raw_prepared", "rotation/compute"),
    ],
)
def test_successful_raw_holds_without_repreparation_until_retry_peer_arrives(
    role, stage, next_call
):
    case, _ = _run(({"prep:" + role: ("rejected", "accepted")}, {}))
    assert case["status"] == "complete"
    stage = "batch[0]/" + stage
    waiting = next(
        item
        for item in case["milestones"]
        if item["kind"] == "line_state_changed"
        and item["state"] == "waiting_peers"
        and item["factory_id"] == "line-1"
        and item["stage_key"] == stage
    )
    releases = _barrier_records(case, stage)
    assert {item["factory_id"] for item in releases} == {"line-0", "line-1"}
    assert len({item["at_us"] for item in releases}) == 1
    release = releases[0]["at_us"]
    assert release - waiting["at_us"] == 10
    assert waiting["peers"] == ["line-0", "line-1"]
    assert all(item["peers"] == waiting["peers"] for item in releases)
    assert not any(
        call["factory_id"] == "line-1"
        and waiting["at_us"] <= call["start_us"] < release
        for call in case["calls"]
    )
    for line in ("line-0", "line-1"):
        successor = next(
            c
            for c in case["calls"]
            if c["invocation_id"] == f"{line}/batch[0]/{next_call}"
        )
        assert successor["start_us"] >= release
    epochs = [
        item["epoch"]
        for item in case["resources"]["audit"]
        if item["action"] == "begin_preparation"
        and item["carrier_id"] == "line-1/" + role
    ]
    assert epochs == [1]
    retry = next(
        c
        for c in case["calls"]
        if c["invocation_id"] == f"line-0/batch[0]/prepare/{role}/attempt[1]/body"
    )
    assert waiting["at_us"] <= retry["start_us"] < retry["end_us"] < release


def test_empty_t_branch_waits_for_peer_s_before_uncompute():
    case, _ = _run(({"t:rotation": ("m0",)}, {"t:rotation": ("m1",)}))
    corrections = [c for c in case["calls"] if c["component_id"] == "toy.s"]
    assert len(corrections) == 1 and corrections[0]["factory_id"] == "line-1"
    releases = _barrier_records(case, "batch[0]/rotation[0]/consumption_complete")
    assert len(releases) == 2
    assert {item["at_us"] for item in releases} == {corrections[0]["end_us"]}
    uncompute = [c for c in case["calls"] if c["component_id"] == "toy.uncompute"]
    assert len(uncompute) == 2
    assert all(c["start_us"] >= corrections[0]["end_us"] for c in uncompute)


def test_waiting_peer_is_released_when_retrying_line_exhausts_its_budget():
    case, _ = _run(
        ({"prep:R": ("rejected", "rejected")}, {}),
        limits=FactoryLimits(raw_attempts=2),
    )
    failed = case["factories"]["line-0"]
    assert failed["status"] == "input_supply_exhausted"
    assert case["factories"]["line-1"]["status"] == "complete"
    waiting = next(
        item
        for item in case["milestones"]
        if item["kind"] == "line_state_changed"
        and item["state"] == "waiting_peers"
        and item["factory_id"] == "line-1"
        and item["stage_key"] == "batch[0]/rotation[0]/raw_prepared"
    )
    assert waiting["at_us"] < failed["completed_at_us"]
    releases = _barrier_records(case, "batch[0]/rotation[0]/raw_prepared")
    assert len(releases) == 1
    assert releases[0]["factory_id"] == "line-1"
    assert releases[0]["peers"] == ["line-1"]
    assert releases[0]["at_us"] == failed["completed_at_us"]
    token = next(
        t
        for t in case["resources"]["tokens"]
        if t["token_id"] == "line-1/batch[0]/prepare/R/attempt[0]/resource"
    )
    assert token["status"] == "consumed" and token["epoch"] == 1
    assert (
        sum(
            a["action"] == "consume" and a.get("token_id") == token["token_id"]
            for a in case["resources"]["audit"]
        )
        == 1
    )
    assert not any(
        c["factory_id"] == "line-0" and c["component_id"] == "toy.compute"
        for c in case["calls"]
    )


def test_completed_output_stays_offered_during_other_lines_outer_retry():
    case, _ = _run(
        ({"final": ("rejected", "accepted")}, {}), limits=FactoryLimits(batches=2)
    )
    assert case["status"] == "complete"
    output = next(
        t
        for t in case["resources"]["tokens"]
        if t["token_id"] == "line-1/batch[0]/output"
    )
    assert output["status"] == "offered" and output["consumed_at_us"] is None
    assert output["ready_at_us"] < case["duration_us"]
    assert not any(
        c["factory_id"] == "line-1" and "/batch[1]/" in c["invocation_id"]
        for c in case["calls"]
    )
    second_batch = [
        m
        for m in case["milestones"]
        if m["kind"] == "cohort_barrier_released"
        and m["stage_key"].startswith("batch[1]/")
    ]
    assert second_batch and all(m["peers"] == ["line-0"] for m in second_batch)
    assert not any(
        a["action"] in ("discard", "consume")
        and a.get("token_id") == output["token_id"]
        for a in case["resources"]["audit"]
    )


def test_cross_line_wave_is_real_admission_but_two_patch_calls_stay_singletons():
    case, _ = _run()
    calls = {c["invocation_id"]: c for c in case["calls"]}
    admissions = case["component_schedule"]["admissions"]
    initial = admissions[0]
    assert len(initial["nodes"]) == 4
    assert {calls[node["id"]]["factory_id"] for node in initial["nodes"]} == {
        "line-0",
        "line-1",
    }
    for admission in admissions:
        if any(
            len(calls[node["id"]]["participant_roles"]) > 1
            for node in admission["nodes"]
        ):
            assert len(admission["nodes"]) == 1


def test_line_namespaced_fair_t_events_replay_across_serial_and_parallel():
    class FairTBackend(DeclaredBackend):
        def resolve_event(self, selector, parameters=None):
            port = super().resolve_event(selector, parameters)
            if not selector.startswith("t:"):
                return port
            payload = port.to_dict()
            for outcome in payload["outcomes"]:
                outcome["probability"] = 0.5
            return ProbabilityPort.from_dict(payload)

    results = []
    for mode in ("serial", "parallel"):
        case, _ = _run(
            mode=mode,
            backend_factory=lambda line, script, physical: FairTBackend(script),
        )
        assert case["status"] == "complete"
        results.append(
            {
                event["occurrence"]["invocation_id"]: event["outcome_key"]
                for event in case["events"]
                if event["occurrence"]["port_id"] == "test_fixture.t:rotation"
            }
        )
    # Known fixture uniforms: line-0 = .6173912998, line-1 = .0617254147.
    assert (
        results
        == [
            {
                "line-0/batch[0]/rotation/event": "m1",
                "line-1/batch[0]/rotation/event": "m0",
            }
        ]
        * 2
    )
