"""Declaration-only component scheduling and independent feedback chains."""

from dataclasses import FrozenInstanceError, replace

import pytest
from nadit_physical_compiler.device import Region

from modules.codes.contracts.parallel import ComponentExecutionSpec, SpaceClaim
from modules.logical_compiler.src.scheduling import (
    Admission,
    ComponentNode,
    ComponentScheduler,
)


def node(
    identity,
    block=None,
    *,
    x=0,
    aod=None,
    waveform="raw/v1",
    mode="independent_aods_lockstep",
    **kwargs,
):
    block = block or identity
    spec = ComponentExecutionSpec(
        code_id="test_code",
        component_id="raw",
        waveform_key=waveform,
        participant_blocks=(block,),
        spaces=(SpaceClaim(Region(x, 0, x + 1, 1), "workspace"),),
        exclusive_resources=("aod:" + (aod or identity),),
        parallel_mode=mode,
        result_count=1,
    )
    return ComponentNode(identity, spec, **kwargs)


def admit(scheduler, time=0, snapshot="world-0"):
    return scheduler.admit(time, snapshot_id=snapshot)


def finish(scheduler, admission, time):
    scheduler.commit_admission(admission)
    for member in admission.nodes:
        scheduler.mark_completed(member.id, time)


def test_four_roots_share_one_pure_deterministic_admission():
    scheduler = ComponentScheduler(mode="parallel")
    roots = [node(f"raw-{i}", x=3 * i) for i in range(4)]
    scheduler.add(*reversed(roots))
    first = admit(scheduler)
    assert first.node_ids == ("raw-0", "raw-1", "raw-2", "raw-3")
    assert first == admit(scheduler)
    assert first.start_us == 0 and first.snapshot_id == "world-0"
    assert first.to_dict()["nodes"][0]["spec"]["participant_blocks"] == ["raw-0"]
    with pytest.raises(FrozenInstanceError):
        first.start_us = 7
    scheduler.commit_admission(first)
    assert admit(scheduler) is None
    scheduler.mark_completed("raw-0", 10)
    assert admit(scheduler, 10) is None


def test_selection_is_invariant_to_independent_input_order():
    roots = [node("b", x=3), node("a")]
    one, two = ComponentScheduler(), ComponentScheduler()
    one.add(*roots)
    two.add(*reversed(roots))
    assert admit(one) == admit(two)


def test_ready_correction_priority_precedes_unrelated_preparation():
    scheduler = ComponentScheduler()
    scheduler.add(
        node("a-preparation"),
        node(
            "z-correction",
            x=3,
            mode="exclusive",
            priority=-1,
            event_dependencies=("m",),
        ),
    )
    assert admit(scheduler).node_ids == ("a-preparation",)
    scheduler.release_event("m", 5)
    assert tuple(n.id for n in scheduler.frontier(5)) == (
        "z-correction",
        "a-preparation",
    )
    correction = admit(scheduler, 5)
    assert correction.node_ids == ("z-correction",)
    assert correction.to_dict()["nodes"][0]["priority"] == -1


def test_snapshot_records_only_committed_admissions_and_is_independent():
    scheduler = ComponentScheduler(mode="parallel", max_parallel=2)
    scheduler.add(node("a"), node("b", x=3, priority=2))
    proposal = admit(scheduler)
    assert scheduler.snapshot()["admissions"] == []
    scheduler.commit_admission(proposal)
    scheduler.mark_completed("a", 3)
    scheduler.release_event("m", 4)
    scheduler.release_token("resource", 4)
    snapshot = scheduler.snapshot()
    assert snapshot["schema"] == "nadit.component_schedule/1"
    assert snapshot["policy"] == {"mode": "parallel", "max_parallel": 2}
    assert snapshot["admissions"] == [proposal.to_dict()]
    assert snapshot["completed"] == {"a": 3}
    assert snapshot["running"] == {"b": 0}
    assert snapshot["event_releases"] == {"m": 4}
    assert snapshot["token_releases"] == {"resource": 4}
    snapshot["nodes"][0]["spec"]["participant_blocks"].append("other")
    snapshot["completed"]["a"] = 99
    assert scheduler.snapshot()["completed"] == {"a": 3}
    assert scheduler.snapshot()["nodes"][0]["spec"]["participant_blocks"] == ["a"]


def test_patch_edges_do_not_create_a_global_last_call_chain():
    scheduler = ComponentScheduler()
    scheduler.add(node("a", block="A"), node("b", block="B", x=3))
    added = scheduler.add(node("a-next", block="A"))[0]
    assert added.after_calls == ("a",)
    assert tuple(n.id for n in scheduler.frontier(0)) == ("a", "b")
    finish(scheduler, admit(scheduler), 5)
    assert admit(scheduler, 5).node_ids == ("a-next",)


def test_explicit_event_token_and_time_readiness_are_separate():
    scheduler = ComponentScheduler()
    scheduler.add(
        node(
            "use", event_dependencies=("m",), token_dependencies=("A",), not_before_us=7
        )
    )
    assert admit(scheduler, 20) is None
    scheduler.release_event("m", 5)
    assert admit(scheduler, 20) is None
    scheduler.release_token("A", 6)
    assert admit(scheduler, 6) is None
    assert admit(scheduler, 7).node_ids == ("use",)
    scheduler.release_event("m", 5)
    with pytest.raises(ValueError, match="READINESS_CHANGED"):
        scheduler.release_event("m", 9)


def test_rejected_chain_retries_without_an_unrelated_event_dependency():
    scheduler = ComponentScheduler()
    scheduler.add(node("A/attempt[0]"), node("B/attempt[0]", x=3))
    finish(scheduler, admit(scheduler), 10)
    scheduler.add(
        node("A/attempt[1]", block="A/attempt[0]", event_dependencies=("A/reject",))
    )
    assert admit(scheduler, 10) is None
    scheduler.release_event("A/reject", 12)
    retry = admit(scheduler, 12)
    assert retry.node_ids == ("A/attempt[1]",)
    assert retry.nodes[0].after_calls == ("A/attempt[0]",)
    assert retry.nodes[0].event_dependencies == ("A/reject",)


@pytest.mark.parametrize(
    "second", [node("b", x=3, aod="a"), node("b", x=1), node("b", x=0.5)]
)
def test_resource_or_closed_space_overlap_prevents_batching(second):
    scheduler = ComponentScheduler()
    scheduler.add(node("a"), second)
    assert admit(scheduler).node_ids == ("a",)


@pytest.mark.parametrize(
    "second",
    [
        node("b", x=3, waveform="different"),
        node("b", x=3, waveform=None, mode="exclusive"),
        node("b", x=3, mode="exclusive"),
    ],
)
def test_unknown_exclusive_or_different_waveforms_are_not_grouped(second):
    scheduler = ComponentScheduler()
    scheduler.add(node("a"), second)
    first = admit(scheduler)
    assert first.node_ids == ("a",)
    finish(scheduler, first, 3)
    assert admit(scheduler, 3).node_ids == ("b",)


def test_different_codes_cannot_share_a_waveform_group():
    scheduler = ComponentScheduler()
    other = node("b", x=3)
    scheduler.add(
        node("a"), replace(other, spec=replace(other.spec, code_id="other_code"))
    )
    assert admit(scheduler).node_ids == ("a",)


def test_different_components_with_the_same_waveform_do_not_group():
    scheduler = ComponentScheduler()
    other = node("b", x=3)
    scheduler.add(
        node("a"), replace(other, spec=replace(other.spec, component_id="other"))
    )
    assert admit(scheduler).node_ids == ("a",)


@pytest.mark.parametrize("multi_patch_id", ["a", "b"])
def test_mismatched_participant_counts_do_not_join_a_batch(multi_patch_id):
    scheduler = ComponentScheduler()
    roots = [node("a"), node("b", x=3)]
    roots = [
        replace(item, spec=replace(item.spec, participant_blocks=(item.id, "extra")))
        if item.id == multi_patch_id
        else item
        for item in roots
    ]
    scheduler.add(*roots)
    first = admit(scheduler)
    assert first.node_ids == ("a",)
    finish(scheduler, first, 5)
    assert admit(scheduler, 5).node_ids == ("b",)


def test_serial_and_capacity_policies_preserve_the_same_graph():
    roots = [node(str(i), x=3 * i) for i in range(4)]
    serial = ComponentScheduler(mode="serial")
    parallel = ComponentScheduler(mode="parallel", max_parallel=2)
    assert serial.add(*roots) == parallel.add(*roots)
    assert admit(serial).node_ids == ("0",)
    assert admit(parallel).node_ids == ("0", "1")


def test_missing_dependency_duplicate_and_cycle_are_transactional():
    scheduler = ComponentScheduler()
    with pytest.raises(ValueError, match="UNKNOWN_DEPENDENCY"):
        scheduler.add(node("a", after_calls=("missing",)))
    assert scheduler.frontier(0) == ()
    with pytest.raises(ValueError, match="DEPENDENCY_CYCLE"):
        scheduler.add(node("a", after_calls=("b",)), node("b", x=3, after_calls=("a",)))
    assert scheduler.frontier(0) == ()
    scheduler.add(node("a"))
    with pytest.raises(ValueError, match="DUPLICATE_NODE"):
        scheduler.add(node("a"))
    assert admit(scheduler).node_ids == ("a",)


def test_stale_or_modified_admission_does_not_commit():
    scheduler = ComponentScheduler()
    scheduler.add(node("a"))
    proposal = admit(scheduler)
    with pytest.raises(ValueError, match="INVALID_ADMISSION"):
        scheduler.commit_admission(replace(proposal, batch_id="forged"))
    scheduler.add(node("b", x=3))
    with pytest.raises(ValueError, match="STALE_ADMISSION"):
        scheduler.commit_admission(proposal)
    assert admit(scheduler).node_ids == ("a", "b")


def test_admission_requires_immutable_members_and_snapshot_identity():
    with pytest.raises(ValueError, match="INVALID_ADMISSION"):
        Admission("batch", [node("a")], 0, "world")
    with pytest.raises(ValueError, match="INVALID_ADMISSION"):
        Admission("batch", (), 0, "world")
    with pytest.raises(ValueError, match="snapshot ID"):
        admit(ComponentScheduler(), snapshot="")


def test_admission_snapshot_changes_certificate_without_changing_graph():
    scheduler = ComponentScheduler()
    scheduler.add(node("a"))
    first, second = admit(scheduler), admit(scheduler, snapshot="world-1")
    assert first.node_ids == second.node_ids
    assert first.batch_id != second.batch_id
    exported = first.to_dict()
    exported["nodes"][0]["spec"]["participant_blocks"].append("other")
    assert first.nodes[0].spec.participant_blocks == ("a",)


def test_explicit_call_dependency_waits_for_real_completion():
    scheduler = ComponentScheduler()
    scheduler.add(node("a"), node("b", x=3, after_calls=("a",)))
    assert admit(scheduler).node_ids == ("a",)
    finish(scheduler, admit(scheduler), 10)
    assert scheduler.frontier(9) == ()
    assert admit(scheduler, 10).node_ids == ("b",)
    with pytest.raises(ValueError, match="TIME_REVERSED"):
        admit(scheduler, 9)


def test_completion_requires_a_committed_node_and_valid_time():
    scheduler = ComponentScheduler()
    scheduler.add(node("a", not_before_us=5))
    with pytest.raises(ValueError, match="NOT_RUNNING"):
        scheduler.mark_completed("a", 5)
    scheduler.commit_admission(admit(scheduler, 5))
    with pytest.raises(ValueError, match="COMPLETION_BEFORE_START"):
        scheduler.mark_completed("a", 4)
    scheduler.mark_completed("a", 8)
    scheduler.mark_completed("a", 8)
    with pytest.raises(ValueError, match="COMPLETION_CHANGED"):
        scheduler.mark_completed("a", 9)
    assert admit(scheduler, 8) is None


def test_wrong_record_types_are_rejected_without_mutation():
    scheduler = ComponentScheduler()
    with pytest.raises(TypeError, match="INVALID_COMPONENT_NODE"):
        scheduler.add("not a component node")
    with pytest.raises(TypeError, match="INVALID_ADMISSION"):
        scheduler.commit_admission("not an admission")
    with pytest.raises(TypeError, match="INVALID_COMPONENT_SPEC"):
        ComponentNode("a", None)
    with pytest.raises(TypeError, match="must be a tuple"):
        node("a", after_calls=["b"])
    assert scheduler.frontier(0) == ()


@pytest.mark.parametrize(
    "kwargs",
    [
        {"mode": "unknown"},
        {"max_parallel": 0},
        {"max_parallel": True},
        {"max_parallel": 1.5},
    ],
)
def test_invalid_policy(kwargs):
    with pytest.raises(ValueError):
        ComponentScheduler(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"not_before_us": -1},
        {"not_before_us": float("nan")},
        {"after_calls": ("a", "a")},
        {"event_dependencies": ("",)},
        {"priority": True},
        {"priority": 0.5},
    ],
)
def test_invalid_node_inputs(kwargs):
    with pytest.raises(ValueError):
        node("a", **kwargs)


@pytest.mark.parametrize("time", [-1, float("inf"), True, 10**400])
def test_invalid_admission_time(time):
    with pytest.raises(ValueError):
        admit(ComponentScheduler(), time)
