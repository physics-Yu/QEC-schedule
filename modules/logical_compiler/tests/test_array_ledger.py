"""Dynamic line and resource accounting does not expose future decisions."""

from modules.logical_compiler.src.protocols.array_ledger import (
    build_array_ledger,
    resource_state_at,
)
from modules.logical_compiler.src.protocols.resources import ResourceLedger


def example():
    resources = ResourceLedger()
    resources.register_carrier("factory0/W1", code_id="test", distance=3, atom_ids=(0,))
    resources.begin_preparation("factory0/W1", owner="factory0/batch[0]", at_us=0)
    resources.extend_use(
        "factory0/W1", owner="factory0/batch[0]", at_us=0, safe_exit_at_us=5
    )
    resources.extend_use(
        "factory0/W1", owner="factory0/batch[0]", at_us=5, safe_exit_at_us=5
    )
    resources.offer(
        "factory0/batch[0]/output",
        carrier_id="factory0/W1",
        epoch=1,
        owner="factory0/batch[0]",
        resource_kind="A",
        producer="checks",
        ready_at_us=5,
        exit_at_us=5,
        canonicalization="canonical",
    )
    audit = resources.snapshot()
    lines = {}
    marks = []
    for i in range(2):
        identity = f"factory{i}"
        own = [
            {
                "kind": "line_state_changed",
                "factory_id": identity,
                "at_us": 0,
                "state": "running",
                "reason": "start",
            },
            {
                "kind": "line_state_changed",
                "factory_id": identity,
                "at_us": 2,
                "state": "waiting_peers" if i == 0 else "running",
                "reason": "raw join",
                "stage_key": "initial",
                "peers": ["factory0", "factory1"],
            },
            {
                "kind": "line_state_changed",
                "factory_id": identity,
                "at_us": 5,
                "state": "complete" if i == 0 else "failed",
                "reason": "terminal",
            },
            {
                "kind": "batch_decision",
                "factory_id": identity,
                "at_us": 5,
                "batch": 0,
                "accepted": i == 0,
            },
        ]
        lines[identity] = {
            "status": "complete" if i == 0 else "distillation_rejected",
            "failure": None if i == 0 else {"code": "distillation_rejected"},
            "calls": [],
            "milestones": own,
            "completed_at_us": 5,
            "output_token_id": "factory0/batch[0]/output" if i == 0 else None,
            "algorithm_consumed_token_id": None,
            "role_bindings": {"W1": identity + "/W1"},
        }
        marks.extend(own)
    return {
        "case_id": "array",
        "seed": 1,
        "status": "partial_failure",
        "duration_us": 5,
        "factories": lines,
        "calls": [],
        "events": [],
        "milestones": marks,
        "resources": audit,
        "component_schedule": {"admissions": []},
        "physical": {
            "device": {"aods": [{"id": "transport"}]},
            "validation": {"ok": True},
        },
        "coordination_policy": "cohort_stage_barriers",
    }


def test_line_acceptance_and_failure_remain_separate_from_array_status():
    record = build_array_ledger(example())
    assert record["counts"]["successful_lines"] == 1
    assert record["counts"]["failed_lines"] == 1
    assert record["lines"]["factory0"]["waiting_us"]["waiting_peers"] == 3
    assert record["lines"]["factory0"]["output_status"] == "offered"
    assert record["lines"]["factory1"]["factory_final_accepted"] is False
    assert record["logical_success"] is None


def test_resource_replay_never_shows_a_future_output():
    ledger = build_array_ledger(example())
    early = resource_state_at(ledger, 2)
    assert early["tokens"] == []
    assert early["carriers"][0]["phase"] == "preparing"
    assert resource_state_at(ledger, 5)["tokens"][0]["status"] == "offered"


def test_historical_offer_timestamp_cannot_make_a_future_token_ready():
    ledger = build_array_ledger(example())
    offer = next(
        item for item in ledger["resources"]["audit"] if item["action"] == "offer"
    )
    offer["at_us"] = 0
    assert resource_state_at(ledger, 2)["tokens"] == []
    assert len(resource_state_at(ledger, 5)["tokens"]) == 1
