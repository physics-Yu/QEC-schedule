"""Cancelled work remains distinct from completed physical execution."""

import pytest

from modules.logical_compiler.src.scheduling import ComponentNode, ComponentScheduler
from modules.logical_compiler.tests.test_shared_aod_scheduler import declaration


def test_cancel_one_line_keeps_other_line_ready_and_blocks_cancelled_dependents():
    scheduler = ComponentScheduler()
    scheduler.add(
        ComponentNode("line-a/prepare", declaration(0)),
        ComponentNode("line-a/next", declaration(1), after_calls=("line-a/prepare",)),
        ComponentNode("line-b/prepare", declaration(2)),
    )
    scheduler.cancel_pending(("line-a/prepare",), reason="local_supply_exhausted")
    assert [node.id for node in scheduler.frontier(0)] == ["line-b/prepare"]
    snapshot = scheduler.snapshot()
    assert snapshot["cancelled"] == {"line-a/prepare": "local_supply_exhausted"}
    assert snapshot["completed"] == {}
    scheduler.cancel_pending(("line-a/prepare",), reason="local_supply_exhausted")
    assert scheduler.snapshot() == snapshot


@pytest.mark.parametrize("invalid", ["unknown", "running", "completed"])
def test_cancel_transaction_rejects_unknown_or_started_nodes(invalid):
    scheduler = ComponentScheduler(mode="serial")
    scheduler.add(
        ComponentNode("a", declaration(0)), ComponentNode("b", declaration(1))
    )
    if invalid != "unknown":
        scheduler.commit_admission(scheduler.admit(0, snapshot_id="world"))
        if invalid == "completed":
            scheduler.mark_completed("a", 1)
    before = scheduler.snapshot()
    with pytest.raises(ValueError):
        scheduler.cancel_pending(
            ("b", "missing" if invalid == "unknown" else "a"), reason="stop"
        )
    assert scheduler.snapshot() == before


def test_cancellation_invalidates_an_uncommitted_admission():
    scheduler = ComponentScheduler()
    scheduler.add(
        ComponentNode("a", declaration(0)), ComponentNode("b", declaration(1))
    )
    proposal = scheduler.admit(0, snapshot_id="world")
    scheduler.cancel_pending(("a",), reason="line_failed")
    with pytest.raises(ValueError, match="STALE_ADMISSION"):
        scheduler.commit_admission(proposal)
