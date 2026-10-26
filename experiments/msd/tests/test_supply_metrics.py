"""Hand-verifiable supply occupancy and residence-age integration."""

from copy import deepcopy

import pytest

from experiments.msd import supply_metrics
from modules.logical_compiler.src.protocols.resources import ResourceLedger
from modules.logical_compiler.src.protocols.supply import TokenBuffer


def fixture(*, remove_b=True, pending=False, abort_safe=12):
    """Actual inventory/ledger bookkeeping; no physical preparation is implied."""
    ledger = ResourceLedger()
    for token, ready in (("A", 2), ("B", 4)):
        ledger.register_logical_carrier(token, code_id="fixture", distance=3)
        ledger.begin_preparation(token, owner="producer", at_us=0)
        ledger.offer(
            token,
            carrier_id=token,
            epoch=1,
            owner="producer",
            resource_kind="A",
            producer="fixture",
            ready_at_us=ready,
            exit_at_us=ready,
            canonicalization="canonical",
        )
    buffer = TokenBuffer("fixture-buffer", 2)
    buffer.reserve_capacity("rA", owner="producer", at_us=1)
    buffer.publish("rA", "A", ledger=ledger, at_us=2)
    buffer.reserve_capacity("rB", owner="producer", at_us=3)
    buffer.publish("rB", "B", ledger=ledger, at_us=4)
    buffer.claim(
        "A",
        ledger=ledger,
        consumer="consumer",
        at_us=5,
        expected_code="fixture",
        expected_distance=3,
        expected_kind="A",
    )
    # The real factory consumes through the shared ledger, not TokenBuffer.consume.
    ledger.consume("A", consumer="consumer", at_us=7, safe_exit_at_us=8)
    buffer.remove("A", ledger=ledger, at_us=8)
    buffer.abort_token(
        "B", ledger=ledger, owner="producer", at_us=11, safe_exit_at_us=abort_safe
    )
    if remove_b:
        buffer.remove("B", ledger=ledger, at_us=12)
    if pending:
        buffer.reserve_capacity("rC", owner="producer", at_us=13)
    buffer.close(at_us=14)
    return {
        "level1_factories": ["L1"],
        "supply": {
            "buffer": buffer.snapshot(ledger=ledger),
            "waiting_producer_outputs": [],
            "retained_outputs": [],
        },
        "case": {
            "duration_us": 20,
            "resources": ledger.snapshot(),
            "factories": {
                "L1": {
                    "outputs": [
                        {"token_id": "A", "ready_at_us": 2},
                        {"token_id": "B", "ready_at_us": 4},
                    ],
                    "completed_at_us": 20,
                    "milestones": [
                        {
                            "kind": "line_state_changed",
                            "at_us": 0,
                            "state": "running",
                            "reason": "fixture",
                        },
                        {
                            "kind": "line_state_changed",
                            "at_us": 20,
                            "state": "complete",
                            "reason": "fixture",
                        },
                    ],
                },
                "L2": {
                    "outputs": [],
                    "completed_at_us": 20,
                    "milestones": [
                        {
                            "kind": "line_state_changed",
                            "at_us": 0,
                            "state": "running",
                            "reason": "fixture",
                        },
                        {
                            "kind": "line_state_changed",
                            "at_us": 20,
                            "state": "complete",
                            "reason": "fixture",
                        },
                    ],
                },
            },
        },
    }


def test_hand_calculated_window_integrates_inventory_and_age():
    result = fixture()
    before = deepcopy(result)
    metrics = supply_metrics.summarize_supply_window(result, warmup_us=5, stop_us=10)
    buffer = metrics["buffer"]
    assert buffer["status"] == "known"
    assert buffer["occupied_slot_time_us"] == buffer["published_token_time_us"] == 8
    assert buffer["peak_occupied_slots"] == buffer["peak_published_tokens"] == 2
    assert buffer["mean_occupied_slots"] == buffer["mean_published_tokens"] == 1.6
    assert buffer["residence_age_integral_us2"] == 31
    assert buffer["token_time_weighted_mean_age_us"] == 3.875
    assert buffer["maximum_residence_age_us"] == 6
    assert buffer["completed_residences"] == {"count": 1, "mean_us": 6}
    assert buffer["completed_claim_waits"] == {"count": 1, "mean_us": 3}
    assert result == before


def test_half_open_boundary_completions_and_empty_inventory():
    result = fixture()
    buffer = supply_metrics.summarize_supply_window(result, warmup_us=8, stop_us=12)[
        "buffer"
    ]
    assert buffer["published_token_time_us"] == 4
    assert buffer["peak_published_tokens"] == 1
    assert buffer["residence_age_integral_us2"] == 24
    assert buffer["maximum_residence_age_us"] == 8
    assert buffer["completed_residences"] == {"count": 1, "mean_us": 6}
    assert buffer["completed_claim_waits"] == {"count": 0, "mean_us": None}
    empty = supply_metrics.summarize_supply_window(result, warmup_us=12, stop_us=14)[
        "buffer"
    ]
    assert empty["published_token_time_us"] == empty["peak_published_tokens"] == 0
    assert empty["residence_age_integral_us2"] == 0
    assert (
        empty["token_time_weighted_mean_age_us"]
        is empty["maximum_residence_age_us"]
        is None
    )
    assert empty["completed_residences"] == {"count": 1, "mean_us": 8}


def test_pending_reservations_occupy_slots_without_inventing_token_ages():
    buffer = supply_metrics.summarize_supply_window(
        fixture(pending=True), warmup_us=15, stop_us=20
    )["buffer"]
    assert buffer["occupied_slot_time_us"] == 5
    assert buffer["published_token_time_us"] == 0
    assert buffer["peak_occupied_slots"] == 1
    assert buffer["maximum_residence_age_us"] is None


def test_live_discarded_item_stays_occupied_until_explicit_remove():
    buffer = supply_metrics.summarize_supply_window(
        fixture(remove_b=False), warmup_us=12, stop_us=20
    )["buffer"]
    assert buffer["occupied_slot_time_us"] == buffer["published_token_time_us"] == 8
    assert buffer["maximum_residence_age_us"] == 16
    assert buffer["completed_residences"]["count"] == 0


@pytest.mark.parametrize("legacy", ("audit", "time", "null"))
def test_legacy_missing_inventory_time_is_unknown_without_erasing_other_evidence(
    legacy,
):
    result = fixture()
    buffer = result["supply"]["buffer"]
    if legacy == "audit":
        del buffer["audit"]
    elif legacy == "time":
        del buffer["audit"][0]["at_us"]
    else:
        buffer["audit"][0]["at_us"] = None
    metrics = supply_metrics.summarize_supply_window(result, warmup_us=5, stop_us=10)
    assert metrics["buffer"]["status"] == "unknown"
    assert metrics["buffer"]["peak_occupied_slots"] is None
    assert metrics["buffer"]["occupied_slot_time_us"] is None
    assert metrics["waits"]["status"] == "known"
    if legacy != "audit":
        assert metrics["source_backlog"]["status"] == "known"


@pytest.mark.parametrize(
    "damage",
    (
        "order",
        "publish",
        "capacity",
        "occupied",
        "pending",
        "closed",
        "early_remove",
        "duplicate_claim",
    ),
)
def test_invalid_audit_or_terminal_snapshot_fails_closed(damage):
    result = fixture()
    buffer = result["supply"]["buffer"]
    audit = buffer["audit"]
    if damage == "order":
        audit[1]["at_us"] = 0
    elif damage == "publish":
        audit.insert(2, deepcopy(audit[1]))
    elif damage == "capacity":
        buffer["capacity"] = 1
    elif damage == "occupied":
        buffer["occupied"] = 1
    elif damage == "pending":
        buffer["pending"] = {"unrecorded": "producer"}
        buffer["occupied"] = 1
    elif damage == "closed":
        buffer["closed"] = False
    elif damage == "early_remove":
        audit[5]["at_us"] = 6
    else:
        audit.insert(5, deepcopy(audit[4]))
    with pytest.raises(ValueError):
        supply_metrics.summarize_supply_window(result, warmup_us=5, stop_us=10)


def test_repeated_close_is_valid_idempotent_runtime_bookkeeping():
    result = fixture()
    result["supply"]["buffer"]["audit"].append({"action": "close", "at_us": 15})
    assert (
        supply_metrics.summarize_supply_window(result, warmup_us=5, stop_us=10)[
            "buffer"
        ]["status"]
        == "known"
    )


def test_source_backlog_uses_each_ready_output_until_publish_retention_or_current_wait():
    result = fixture()
    outputs = result["case"]["factories"]["L1"]["outputs"]
    outputs[0]["ready_at_us"] = 1
    outputs.append(
        {
            "token_id": "C",
            "ready_at_us": 4,
            "retained_at_us": 9,
            "retention": {"token_id": "C", "retained_at_us": 9},
        }
    )
    outputs.append({"token_id": "D", "ready_at_us": 6})
    result["supply"]["retained_outputs"] = ["C"]
    result["supply"]["waiting_producer_outputs"] = ["D"]
    backlog = supply_metrics.summarize_supply_window(result, warmup_us=5, stop_us=10)[
        "source_backlog"
    ]
    assert backlog["status"] == "known"
    assert backlog["token_time_us"] == 8
    assert backlog["peak_tokens"] == 2
    assert backlog["age_integral_us2"] == 20
    assert backlog["maximum_age_us"] == 5


def test_waits_are_clipped_factory_sums_and_unions_not_snapshot_peaks():
    result = fixture()

    def states(start, end, reason, state):
        return [
            {
                "kind": "line_state_changed",
                "at_us": 0,
                "state": "running",
                "reason": "fixture",
            },
            {
                "kind": "line_state_changed",
                "at_us": start,
                "state": state,
                "reason": reason,
            },
            {
                "kind": "line_state_changed",
                "at_us": end,
                "state": "running",
                "reason": "fixture",
            },
        ]

    lines = result["case"]["factories"]
    lines["L1"]["milestones"] = states(
        1, 6, "producer_buffer_backpressure", "waiting_buffer"
    )
    lines["L2"]["milestones"] = states(
        2, 8, "consumer_waiting_for_accepted_input", "waiting_supply"
    )
    lines["L3"] = {
        "outputs": [],
        "completed_at_us": 20,
        "milestones": states(
            5, 12, "consumer_waiting_for_accepted_input", "waiting_supply"
        ),
    }
    waits = supply_metrics.summarize_supply_window(result, warmup_us=5, stop_us=10)[
        "waits"
    ]
    assert waits["status"] == "known"
    assert waits["consumer_starvation"]["factory_sum_us"] == 8
    assert waits["consumer_starvation"]["union_us"] == 5
    assert waits["producer_backpressure"]["factory_sum_us"] == 1
    assert waits["producer_backpressure"]["union_us"] == 1


def test_out_of_order_line_states_are_not_silently_sorted():
    result = fixture()
    result["case"]["factories"]["L1"]["milestones"].reverse()
    with pytest.raises(ValueError, match="SUPPLY_WAIT"):
        supply_metrics.summarize_supply_window(result, warmup_us=5, stop_us=10)


def test_discard_after_previous_safe_exit_is_legal_and_still_occupies_until_remove():
    result = fixture(abort_safe=None)
    metrics = supply_metrics.summarize_supply_window(result, warmup_us=10, stop_us=12)
    assert metrics["buffer"]["published_token_time_us"] == 2
    assert metrics["buffer"]["maximum_residence_age_us"] == 8


def test_missing_wait_reason_is_unknown_instead_of_zero_starvation():
    result = fixture()
    result["case"]["factories"]["L2"]["milestones"][0]["state"] = "waiting_supply"
    del result["case"]["factories"]["L2"]["milestones"][0]["reason"]
    metrics = supply_metrics.summarize_supply_window(result, warmup_us=5, stop_us=10)
    assert metrics["buffer"]["status"] == "known"
    assert metrics["waits"]["status"] == "unknown"
    assert metrics["waits"]["consumer_starvation"]["factory_sum_us"] is None


def test_published_token_cannot_also_be_reported_as_unpublished_source_backlog():
    result = fixture()
    result["supply"]["waiting_producer_outputs"] = ["A"]
    with pytest.raises(ValueError, match="SOURCE_INVENTORY"):
        supply_metrics.summarize_supply_window(result, warmup_us=5, stop_us=10)


def output_lifetime_fixture(*, retained=False):
    """One real ledger token: use at 8 differs from capacity release at 12."""
    ledger = ResourceLedger()
    ledger.register_logical_carrier("A", code_id="fixture", distance=3)
    ledger.begin_preparation("A", owner="producer", at_us=0)
    ledger.offer(
        "A",
        carrier_id="A",
        epoch=1,
        owner="producer",
        resource_kind="A",
        producer="fixture",
        ready_at_us=2,
        exit_at_us=2,
        canonicalization="canonical",
    )
    buffer = TokenBuffer("fixture-buffer", 1)
    output = {"token_id": "A", "carrier_id": "A", "epoch": 1, "ready_at_us": 2}
    if retained:
        output.update(
            retained_at_us=6, retention={"token_id": "A", "retained_at_us": 6}
        )
    else:
        buffer.reserve_capacity("rA", owner="producer", at_us=1)
        buffer.publish("rA", "A", ledger=ledger, at_us=2)
        buffer.claim(
            "A",
            ledger=ledger,
            consumer="consumer",
            at_us=5,
            expected_code="fixture",
            expected_distance=3,
            expected_kind="A",
        )
        ledger.consume("A", consumer="consumer", at_us=8, safe_exit_at_us=10)
        buffer.remove("A", ledger=ledger, at_us=12)
    buffer.close(at_us=14)
    return {
        "level1_factories": ["L1"],
        "case": {
            "duration_us": 20,
            "resources": ledger.snapshot(),
            "factories": {"L1": {"outputs": [output], "milestones": []}},
        },
        "supply": {
            "buffer": buffer.snapshot(ledger=ledger),
            "waiting_producer_outputs": [],
            "retained_outputs": ["A"] if retained else [],
        },
    }


def test_resource_age_ends_at_actual_use_not_safe_exit_or_inventory_removal():
    result = output_lifetime_fixture()
    before = deepcopy(result)
    metrics = supply_metrics.summarize_supply_window(result, warmup_us=0, stop_us=20)
    inventory, resource = metrics["buffer"], metrics["unconsumed_outputs"]
    assert inventory["published_token_time_us"] == 10
    assert inventory["residence_age_integral_us2"] == 50
    assert inventory["maximum_residence_age_us"] == 10
    assert resource["status"] == "known"
    assert resource["token_time_us"] == 6
    assert resource["age_integral_us2"] == 18
    assert resource["token_time_weighted_mean_age_us"] == 3
    assert resource["maximum_age_us"] == 6
    assert resource["completed_use_ages"] == {
        "count": 1,
        "mean_us": 6,
        "samples": [{"token_id": "A", "at_us": 8, "age_us": 6}],
    }
    assert resource["completed_discard_ages"]["count"] == 0
    assert result == before


def test_retained_resource_continues_aging_past_retention_and_factory_stop():
    metrics = supply_metrics.summarize_supply_window(
        output_lifetime_fixture(retained=True), warmup_us=0, stop_us=20
    )
    resource = metrics["unconsumed_outputs"]
    assert metrics["buffer"]["published_token_time_us"] == 0
    assert metrics["source_backlog"]["token_time_us"] == 4
    assert resource["token_time_us"] == 18
    assert resource["age_integral_us2"] == 162
    assert resource["maximum_age_us"] == 18
    assert resource["token_time_weighted_mean_age_us"] == 9
    assert resource["completed_use_ages"]["count"] == 0
    assert resource["completed_discard_ages"]["count"] == 0


def test_output_use_samples_follow_half_open_boundary_even_after_lifetime_ends():
    result = output_lifetime_fixture()
    before = supply_metrics.summarize_supply_window(result, warmup_us=0, stop_us=8)[
        "unconsumed_outputs"
    ]
    assert before["token_time_us"] == 6 and before["completed_use_ages"]["count"] == 0
    after = supply_metrics.summarize_supply_window(result, warmup_us=8, stop_us=12)[
        "unconsumed_outputs"
    ]
    assert after["token_time_us"] == after["age_integral_us2"] == 0
    assert after["maximum_age_us"] is None
    assert after["completed_use_ages"]["count"] == 1
    assert after["completed_use_ages"]["mean_us"] == 6


def test_output_discard_age_ends_at_discard_event_and_ledger_index_is_shared(
    monkeypatch,
):
    calls = []
    original = supply_metrics._ledger

    def counted(case):
        calls.append(case)
        return original(case)

    monkeypatch.setattr(supply_metrics, "_ledger", counted)
    result = supply_metrics.summarize_supply_window(fixture(), warmup_us=5, stop_us=12)
    assert len(calls) == 1
    domain = result["unconsumed_outputs"]
    assert domain["token_time_us"] == 8  # A: 5..7; B: 5..11.
    assert domain["age_integral_us2"] == 32  # A: 8; B: 24.
    assert domain["maximum_age_us"] == 7
    assert domain["completed_discard_ages"]["samples"] == [
        {"token_id": "B", "at_us": 11, "age_us": 7}
    ]


@pytest.mark.parametrize(
    "missing", ("resources", "audit", "tokens", "null_resources", "null_audit")
)
def test_missing_ledger_evidence_yields_unknown_resource_lifetime(missing):
    result = output_lifetime_fixture(retained=True)
    if missing == "resources":
        del result["case"]["resources"]
    elif missing == "null_resources":
        result["case"]["resources"] = None
    elif missing == "null_audit":
        result["case"]["resources"]["audit"] = None
    else:
        del result["case"]["resources"][missing]
    domain = supply_metrics.summarize_supply_window(result, warmup_us=0, stop_us=20)[
        "unconsumed_outputs"
    ]
    assert domain["status"] == "unknown"
    assert domain["token_time_us"] is domain["maximum_age_us"] is None


def test_missing_ledger_time_does_not_become_zero_resource_age():
    result = output_lifetime_fixture()
    event = next(
        e for e in result["case"]["resources"]["audit"] if e["action"] == "consume"
    )
    event["at_us"] = None
    domain = supply_metrics.summarize_supply_window(result, warmup_us=0, stop_us=20)[
        "unconsumed_outputs"
    ]
    assert domain["status"] == "unknown" and domain["age_integral_us2"] is None
