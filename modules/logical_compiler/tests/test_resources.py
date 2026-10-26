"""Carrier and resource lifecycle checks without inventory policy assumptions."""

import json
from dataclasses import FrozenInstanceError

import pytest

from modules.logical_compiler.src.protocols.resources import ResourceLedger


def offered(*, canonicalization="canonical", quality=None, provenance=None):
    ledger = ResourceLedger()
    carrier = ledger.register_carrier(
        "R", code_id="surface_d3", distance=3, atom_ids=(1, 2)
    )
    assert carrier.epoch == 0
    prepared = ledger.begin_preparation("R", owner="producer", at_us=0)
    ledger.offer(
        "raw",
        carrier_id="R",
        epoch=prepared.epoch,
        owner="producer",
        resource_kind="A",
        producer="raw-invocation",
        ready_at_us=5,
        exit_at_us=7,
        canonicalization=canonicalization,
        quality=quality,
        provenance=provenance,
    )
    return ledger


def reserve(ledger, *, at_us=7, consumer="factory", **expectations):
    required = {
        "expected_code": "surface_d3",
        "expected_kind": "A",
        "expected_canonicalization": "canonical",
    }
    required.update(expectations)
    return ledger.reserve("raw", consumer=consumer, at_us=at_us, **required)


def test_transaction_fork_isolates_both_branches_and_reuses_only_immutable_values():
    original = offered(quality={"model": {"assumptions": ["fixture"]}})
    branch = original.fork()
    initial = original.snapshot()
    assert branch.snapshot() == initial
    assert branch.carrier("R") is original.carrier("R")
    assert branch.token("raw") is original.token("raw")

    reserve(branch, consumer="staged")
    branch.consume("raw", consumer="staged", at_us=7, safe_exit_at_us=10)
    branch.register_carrier("staged_W", code_id="surface_d3", distance=3, atom_ids=(3,))
    assert original.snapshot() == initial
    staged = branch.snapshot()

    original.discard("raw", owner="producer", at_us=5, safe_exit_at_us=9)
    original.complete_use("R", owner="producer", at_us=9)
    original.begin_preparation("R", owner="new-producer", at_us=9)
    original.register_carrier(
        "original_W", code_id="surface_d3", distance=3, atom_ids=(3,)
    )
    assert branch.snapshot() == staged
    assert original.carrier("R").epoch == 2 and branch.carrier("R").epoch == 1
    assert original.token("raw").status == "discarded"
    assert branch.token("raw").status == "consumed"


def test_transaction_fork_invalid_mutations_and_export_edits_do_not_leak():
    original = offered(quality={"nested": ["original"]}, provenance={"nested": [1]})
    branch = original.fork()
    before = original.snapshot()
    with pytest.raises(ValueError, match="TOKEN_NOT_READY"):
        reserve(branch, at_us=4)
    with pytest.raises(ValueError, match="ATOM_OVERLAP"):
        original.register_carrier(
            "overlap", code_id="surface_d3", distance=3, atom_ids=(1,)
        )
    with pytest.raises(FrozenInstanceError):
        branch.token("raw").status = "consumed"
    with pytest.raises(FrozenInstanceError):
        branch.carrier("R").owner = "other"
    for ledger in (original, branch):
        exported = ledger.snapshot()
        exported["carriers"][0]["owner"] = "changed"
        exported["tokens"][0]["quality"]["nested"].append("changed")
        exported["audit"].clear()
        ledger.token("raw").provenance["nested"].append(2)
    assert original.snapshot() == branch.snapshot() == before


def test_carriers_cannot_reuse_atom_ids():
    ledger = offered()
    with pytest.raises(ValueError, match="ATOM_OVERLAP"):
        ledger.register_carrier("W", code_id="surface_d3", distance=3, atom_ids=(2, 3))
    with pytest.raises(ValueError, match="DUPLICATE_CARRIER"):
        ledger.register_carrier("R", code_id="surface_d3", distance=3, atom_ids=(4, 5))
    ledger.register_carrier("W", code_id="surface_d3", distance=3, atom_ids=(3, 4))


def test_early_reservation_and_incompatible_resource_do_not_mutate_ledger():
    ledger = offered()
    before = ledger.snapshot()
    with pytest.raises(ValueError, match="TOKEN_NOT_READY"):
        reserve(ledger, at_us=4)
    for invalid in (
        {"expected_code": "surface_d5"},
        {"expected_distance": 5},
        {"expected_kind": "A_dagger"},
        {"expected_canonicalization": "unresolved"},
    ):
        with pytest.raises(ValueError, match="INCOMPATIBLE_RESOURCE"):
            reserve(ledger, **invalid)
    assert ledger.snapshot() == before


def test_unresolved_canonicalization_is_not_promoted_by_reservation():
    ledger = offered(canonicalization="unresolved")
    with pytest.raises(ValueError, match="INCOMPATIBLE_RESOURCE"):
        reserve(ledger)
    assert (
        reserve(ledger, expected_canonicalization="unresolved").canonicalization
        == "unresolved"
    )


def test_reservation_can_precede_exit_but_irreversible_consumption_cannot():
    ledger = offered()
    assert reserve(ledger, at_us=5).status == "reserved"
    with pytest.raises(ValueError, match="CARRIER_NOT_SAFE"):
        ledger.consume("raw", consumer="factory", at_us=6, safe_exit_at_us=10)
    result = ledger.consume("raw", consumer="factory", at_us=7, safe_exit_at_us=10)
    assert result.status == "consumed"
    with pytest.raises(ValueError, match="TOKEN_ALREADY_CONSUMED"):
        ledger.consume("raw", consumer="factory", at_us=7, safe_exit_at_us=10)


def test_consumed_resource_stays_owned_until_explicit_safe_release():
    ledger = offered()
    reserve(ledger)
    ledger.consume("raw", consumer="factory", at_us=7, safe_exit_at_us=10)
    with pytest.raises(ValueError, match="CARRIER_OWNED"):
        ledger.begin_preparation("R", owner="factory", at_us=100)
    with pytest.raises(ValueError, match="CARRIER_NOT_SAFE"):
        ledger.complete_use("R", owner="factory", at_us=9)
    ledger.complete_use("R", owner="factory", at_us=10)
    assert ledger.begin_preparation("R", owner="producer", at_us=10).epoch == 2
    with pytest.raises(ValueError, match="STALE_TOKEN"):
        reserve(ledger, at_us=10)


def test_cross_owner_overwrite_reserve_consume_and_release_are_rejected():
    ledger = offered()
    with pytest.raises(ValueError, match="CARRIER_OWNED"):
        ledger.begin_preparation("R", owner="other", at_us=7)
    reserve(ledger)
    with pytest.raises(ValueError, match="TOKEN_NOT_AVAILABLE"):
        reserve(ledger, consumer="other")
    with pytest.raises(ValueError, match="OWNER_MISMATCH"):
        ledger.consume("raw", consumer="other", at_us=7, safe_exit_at_us=10)
    with pytest.raises(ValueError, match="OWNER_MISMATCH"):
        ledger.complete_use("R", owner="producer", at_us=10)


def test_adopted_work_carrier_can_offer_output_but_output_prevents_reset():
    ledger = offered()
    reserve(ledger)
    ledger.consume(
        "raw", consumer="factory", at_us=7, safe_exit_at_us=10, usage_kind="adopt"
    )
    assert ledger.carrier("R").owner == "factory"
    ledger.extend_use("R", owner="factory", at_us=10, safe_exit_at_us=15)
    ledger.offer(
        "distilled",
        carrier_id="R",
        epoch=1,
        owner="factory",
        resource_kind="A",
        producer="factory-invocation",
        ready_at_us=15,
        exit_at_us=15,
        canonicalization="canonical",
        quality={"verified": False},
    )
    with pytest.raises(ValueError, match="ACTIVE_TOKEN"):
        ledger.complete_use("R", owner="factory", at_us=20)
    with pytest.raises(ValueError, match="CARRIER_OWNED|ACTIVE_TOKEN"):
        ledger.begin_preparation("R", owner="factory", at_us=20)
    output = ledger.reserve(
        "distilled",
        consumer="algorithm",
        at_us=15,
        expected_code="surface_d3",
        expected_distance=3,
        expected_kind="A",
        expected_canonicalization="canonical",
    )
    assert output.carrier_id == "R"
    ledger.consume("distilled", consumer="algorithm", at_us=15, safe_exit_at_us=17)
    ledger.complete_use("R", owner="algorithm", at_us=17)
    assert ledger.begin_preparation("R", owner="producer", at_us=17).epoch == 2
    assert any(
        event.get("usage_kind") == "adopt" for event in ledger.snapshot()["audit"]
    )


def test_discard_keeps_carrier_protected_until_its_cleanup_exit():
    ledger = offered()
    ledger.discard("raw", owner="producer", at_us=5, safe_exit_at_us=9)
    assert ledger.token("raw").status == "discarded"
    with pytest.raises(ValueError, match="CARRIER_NOT_SAFE"):
        ledger.complete_use("R", owner="producer", at_us=8)
    ledger.complete_use("R", owner="producer", at_us=9)
    ledger.begin_preparation("R", owner="producer", at_us=9)
    with pytest.raises(ValueError, match="STALE_EPOCH"):
        ledger.offer(
            "stale",
            carrier_id="R",
            epoch=1,
            owner="producer",
            resource_kind="A",
            producer="old",
            ready_at_us=10,
            exit_at_us=10,
            canonicalization="canonical",
        )


def test_only_one_active_output_exists_on_a_carrier_epoch():
    ledger = offered()
    with pytest.raises(ValueError, match="ACTIVE_TOKEN"):
        ledger.offer(
            "duplicate-state",
            carrier_id="R",
            epoch=1,
            owner="producer",
            resource_kind="A",
            producer="other",
            ready_at_us=7,
            exit_at_us=7,
            canonicalization="canonical",
        )
    with pytest.raises(ValueError, match="ACTIVE_TOKEN"):
        ledger.complete_use("R", owner="producer", at_us=7)


def test_safe_exit_can_extend_but_cannot_shrink_or_release_another_owner():
    ledger = offered()
    reserve(ledger)
    ledger.consume(
        "raw", consumer="factory", at_us=7, safe_exit_at_us=10, usage_kind="adopt"
    )
    ledger.extend_use("R", owner="factory", at_us=8, safe_exit_at_us=20)
    with pytest.raises(ValueError, match="INVALID_SAFE_EXIT"):
        ledger.extend_use("R", owner="factory", at_us=9, safe_exit_at_us=15)
    with pytest.raises(ValueError, match="CARRIER_NOT_SAFE"):
        ledger.complete_use("R", owner="factory", at_us=19)
    ledger.complete_use("R", owner="factory", at_us=20)


def test_failed_preparation_can_be_abandoned_only_after_declared_cleanup():
    ledger = ResourceLedger()
    ledger.register_carrier("R", code_id="surface_d3", distance=3, atom_ids=(1,))
    ledger.begin_preparation("R", owner="producer", at_us=0)
    ledger.extend_use("R", owner="producer", at_us=0, safe_exit_at_us=5)
    with pytest.raises(ValueError, match="CARRIER_NOT_SAFE"):
        ledger.complete_use("R", owner="producer", at_us=4)
    ledger.complete_use("R", owner="producer", at_us=5)
    assert ledger.begin_preparation("R", owner="producer", at_us=5).epoch == 2


def preparing_work_carrier():
    ledger = ResourceLedger()
    ledger.register_carrier("W", code_id="surface_d3", distance=3, atom_ids=(1,))
    ledger.begin_preparation("W", owner="algorithm", at_us=1)
    ledger.extend_use("W", owner="algorithm", at_us=1, safe_exit_at_us=5)
    return ledger


def test_finish_preparation_records_work_phase_without_releasing_or_issuing_quality():
    ledger = preparing_work_carrier()
    previous = ledger.carrier("W")
    result = ledger.finish_preparation("W", owner="algorithm", at_us=5)
    assert result.phase == "work"
    assert result.owner == "algorithm"
    assert result.epoch == previous.epoch == 1
    assert result.safe_exit_at_us == 5
    assert result.last_at_us == 5
    assert previous.phase == "preparing"
    assert ledger.snapshot()["tokens"] == []
    assert ledger.snapshot()["audit"][-1] == {
        "sequence": 3,
        "action": "finish_preparation",
        "at_us": 5.0,
        "carrier_id": "W",
        "epoch": 1,
        "owner": "algorithm",
    }
    with pytest.raises(ValueError, match="CARRIER_OWNED"):
        ledger.begin_preparation("W", owner="algorithm", at_us=6)


@pytest.mark.parametrize(
    ("owner", "at_us", "error"),
    [
        ("other", 5, "OWNER_MISMATCH"),
        ("algorithm", 4, "CARRIER_NOT_SAFE"),
        ("algorithm", 0, "TIME_REVERSED"),
        ("algorithm", float("nan"), "INVALID_TIME"),
    ],
)
def test_finish_preparation_rejects_invalid_owner_or_time_atomically(
    owner, at_us, error
):
    ledger = preparing_work_carrier()
    before = ledger.snapshot()
    with pytest.raises(ValueError, match=error):
        ledger.finish_preparation("W", owner=owner, at_us=at_us)
    assert ledger.snapshot() == before


def test_finish_preparation_cannot_overwrite_active_resource_token():
    ledger = offered()
    before = ledger.snapshot()
    with pytest.raises(ValueError, match="ACTIVE_TOKEN"):
        ledger.finish_preparation("R", owner="producer", at_us=7)
    assert ledger.snapshot() == before


def test_finish_preparation_requires_preparing_phase_and_is_not_repeatable():
    ledger = preparing_work_carrier()
    ledger.finish_preparation("W", owner="algorithm", at_us=5)
    before = ledger.snapshot()
    with pytest.raises(ValueError, match="INVALID_PREPARATION_STATE"):
        ledger.finish_preparation("W", owner="algorithm", at_us=6)
    assert ledger.snapshot() == before


def test_discard_reservation_requires_current_consumer_and_does_not_consume_twice():
    ledger = offered()
    reserve(ledger)
    with pytest.raises(ValueError, match="OWNER_MISMATCH"):
        ledger.discard("raw", owner="producer", at_us=7)
    ledger.discard("raw", owner="factory", at_us=7)
    with pytest.raises(ValueError, match="TOKEN_NOT_RESERVED"):
        ledger.consume("raw", consumer="factory", at_us=7, safe_exit_at_us=8)
    ledger.complete_use("R", owner="factory", at_us=7)


def test_unknown_usage_kind_and_backdated_transitions_leave_state_unchanged():
    ledger = offered()
    reserve(ledger)
    before = ledger.snapshot()
    with pytest.raises(ValueError, match="INVALID_USAGE_KIND"):
        ledger.consume(
            "raw", consumer="factory", at_us=7, safe_exit_at_us=9, usage_kind="measure"
        )
    with pytest.raises(ValueError, match="TIME_REVERSED"):
        ledger.discard("raw", owner="factory", at_us=6)
    assert ledger.snapshot() == before


@pytest.mark.parametrize("distance", [True, 3.0])
def test_expected_distance_requires_an_integer(distance):
    ledger = offered()
    with pytest.raises(ValueError, match="INCOMPATIBLE_RESOURCE"):
        reserve(ledger, expected_distance=distance)


def test_records_and_evidence_are_immutable_and_snapshot_is_deterministic():
    quality = {"assumptions": ["test_fixture"], "verified": False}
    provenance = {"model": {"kind": "test_fixture"}}
    ledger = offered(quality=quality, provenance=provenance)
    reference = ledger.snapshot()
    quality["assumptions"].append("mutation")
    provenance["model"]["kind"] = "changed"
    with pytest.raises(FrozenInstanceError):
        ledger.carrier("R").owner = "changed"
    with pytest.raises(FrozenInstanceError):
        ledger.token("raw").epoch = 99
    snapshot = ledger.snapshot()
    snapshot["tokens"][0]["quality"]["assumptions"].append("external")
    assert ledger.snapshot() == reference
    equivalent = offered(
        quality={"assumptions": ["test_fixture"], "verified": False},
        provenance={"model": {"kind": "test_fixture"}},
    )
    assert json.dumps(ledger.snapshot(), sort_keys=True) == json.dumps(
        equivalent.snapshot(), sort_keys=True
    )


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), {"not_json"}])
def test_nonfinite_or_non_json_evidence_is_rejected(invalid):
    with pytest.raises(ValueError, match="INVALID_EVIDENCE"):
        offered(quality={"bad": invalid})


@pytest.mark.parametrize("time", [-1, True, float("nan"), float("inf")])
def test_invalid_times_are_rejected(time):
    ledger = offered()
    with pytest.raises(ValueError, match="INVALID_TIME"):
        reserve(ledger, at_us=time)


def transport_evidence():
    """Synthetic reference hashes; ledger tests do not execute physical motion."""
    return {
        "trace_sha256": "1" * 64,
        "entry_world_sha256": "2" * 64,
        "exit_world_sha256": "3" * 64,
        "entry_binding_sha256": "4" * 64,
        "exit_binding_sha256": "5" * 64,
    }


def logical_offered():
    ledger = ResourceLedger()
    ledger.register_logical_carrier("R", code_id="surface_d3", distance=3)
    prepared = ledger.begin_preparation("R", owner="producer", at_us=0)
    ledger.offer(
        "raw",
        carrier_id="R",
        epoch=prepared.epoch,
        owner="producer",
        resource_kind="A",
        producer="raw-invocation",
        ready_at_us=5,
        exit_at_us=7,
        canonicalization="canonical",
        quality={"status": "fixture"},
    )
    return ledger


@pytest.mark.parametrize("logical", (False, True))
@pytest.mark.parametrize("reserved", (False, True))
def test_transport_keeps_resource_identity_evidence_and_representation(
    logical, reserved
):
    ledger = logical_offered() if logical else offered(quality={"status": "fixture"})
    if reserved:
        reserve(ledger)
    owner = "factory" if reserved else "producer"
    token, before = ledger.token("raw"), ledger.carrier("R")
    evidence = transport_evidence()
    carrier = ledger.record_transport(
        "R", owner=owner, at_us=7, safe_exit_at_us=12, evidence=evidence
    )
    assert ledger.token("raw") is token
    assert carrier.carrier_id == before.carrier_id
    assert carrier.atom_ids == before.atom_ids == (() if logical else (1, 2))
    assert carrier.epoch == before.epoch == 1
    assert carrier.owner == owner and carrier.phase == before.phase
    assert carrier.representation == before.representation
    assert carrier.last_at_us == 7 and carrier.safe_exit_at_us == 12
    audit = ledger.snapshot()["audit"][-1]
    assert audit["action"] == "record_transport"
    assert audit["at_us"] == 7 and audit["safe_exit_at_us"] == 12
    assert audit["token_id"] == token.token_id and audit["epoch"] == token.epoch
    assert audit["representation"] == before.representation
    assert audit["resource_time_basis"] == (
        "logical_estimated_us" if logical else "physical_us"
    )
    assert audit["verification_scope"] == "ledger_reference_only"
    assert audit["evidence"] == evidence
    evidence["trace_sha256"] = "6" * 64
    audit["evidence"]["trace_sha256"] = "7" * 64
    assert ledger.snapshot()["audit"][-1]["evidence"] == transport_evidence()


def test_transport_blocks_reservation_until_arrival_without_changing_old_rule():
    ledger = offered()
    ledger.record_transport(
        "R",
        owner="producer",
        at_us=7,
        safe_exit_at_us=12,
        evidence=transport_evidence(),
    )
    before = ledger.snapshot()
    with pytest.raises(ValueError, match="TRANSPORT_NOT_COMPLETE"):
        reserve(ledger, at_us=11)
    assert ledger.snapshot() == before
    assert reserve(ledger, at_us=12).carrier_id == "R"
    assert reserve(offered(), at_us=5).status == "reserved"


def test_reserved_resource_can_move_but_cannot_be_consumed_in_transit():
    ledger = offered()
    reserve(ledger)
    ledger.record_transport(
        "R",
        owner="factory",
        at_us=7,
        safe_exit_at_us=12,
        evidence=transport_evidence(),
    )
    before = ledger.snapshot()
    with pytest.raises(ValueError, match="CARRIER_NOT_SAFE"):
        ledger.consume("raw", consumer="factory", at_us=11, safe_exit_at_us=13)
    assert ledger.snapshot() == before
    ledger.consume("raw", consumer="factory", at_us=12, safe_exit_at_us=13)
    ledger.complete_use("R", owner="factory", at_us=13)
    assert ledger.begin_preparation("R", owner="producer", at_us=13).epoch == 2


@pytest.mark.parametrize(
    ("owner", "start", "end", "error"),
    [
        ("other", 7, 12, "OWNER_MISMATCH"),
        ("producer", 6, 12, "CARRIER_NOT_SAFE"),
        ("producer", 7, 7, "INVALID_TRANSPORT_INTERVAL"),
        ("producer", 7, 6, "INVALID_TRANSPORT_INTERVAL"),
        ("producer", float("nan"), 12, "INVALID_TIME"),
        ("producer", 7, float("inf"), "INVALID_TIME"),
    ],
)
def test_transport_rejects_invalid_owner_and_interval_atomically(
    owner, start, end, error
):
    ledger = offered()
    before = ledger.snapshot()
    with pytest.raises(ValueError, match=error):
        ledger.record_transport(
            "R",
            owner=owner,
            at_us=start,
            safe_exit_at_us=end,
            evidence=transport_evidence(),
        )
    assert ledger.snapshot() == before


@pytest.mark.parametrize("damage", ("missing", "label", "digest", "world", "binding"))
def test_transport_requires_reviewable_nontrivial_reference_evidence(damage):
    ledger = offered()
    evidence = transport_evidence()
    if damage == "missing":
        del evidence["trace_sha256"]
    elif damage == "label":
        evidence = {"physical_delivery": True}
    elif damage == "digest":
        evidence["trace_sha256"] = "not-a-trace-hash"
    elif damage == "world":
        evidence["exit_world_sha256"] = evidence["entry_world_sha256"]
    else:
        evidence["exit_binding_sha256"] = evidence["entry_binding_sha256"]
    before = ledger.snapshot()
    with pytest.raises(ValueError, match="INVALID_TRANSPORT_EVIDENCE"):
        ledger.record_transport(
            "R", owner="producer", at_us=7, safe_exit_at_us=12, evidence=evidence
        )
    assert ledger.snapshot() == before


def test_transport_respects_token_readiness_and_does_not_acquire_free_carriers():
    ledger = ResourceLedger()
    ledger.register_carrier("R", code_id="surface_d3", distance=3, atom_ids=(1, 2))
    with pytest.raises(ValueError, match="OWNER_MISMATCH"):
        ledger.record_transport(
            "R",
            owner="producer",
            at_us=0,
            safe_exit_at_us=5,
            evidence=transport_evidence(),
        )
    ledger.begin_preparation("R", owner="producer", at_us=0)
    ledger.offer(
        "raw",
        carrier_id="R",
        epoch=1,
        owner="producer",
        resource_kind="A",
        producer="raw-invocation",
        ready_at_us=12,
        exit_at_us=7,
        canonicalization="canonical",
    )
    before = ledger.snapshot()
    with pytest.raises(ValueError, match="TOKEN_NOT_READY"):
        ledger.record_transport(
            "R",
            owner="producer",
            at_us=7,
            safe_exit_at_us=15,
            evidence=transport_evidence(),
        )
    assert ledger.snapshot() == before


def test_transport_rejects_overlap_and_work_until_complete_without_resetting_epoch():
    ledger = preparing_work_carrier()
    ledger.finish_preparation("W", owner="algorithm", at_us=5)
    ledger.record_transport(
        "W",
        owner="algorithm",
        at_us=5,
        safe_exit_at_us=10,
        evidence=transport_evidence(),
    )
    before = ledger.snapshot()
    for start in (5, 9):
        with pytest.raises(ValueError, match="CARRIER_NOT_SAFE"):
            ledger.record_transport(
                "W",
                owner="algorithm",
                at_us=start,
                safe_exit_at_us=15,
                evidence=transport_evidence(),
            )
    with pytest.raises(ValueError, match="TRANSPORT_NOT_COMPLETE"):
        ledger.extend_use("W", owner="algorithm", at_us=9, safe_exit_at_us=15)
    with pytest.raises(ValueError, match="CARRIER_NOT_SAFE"):
        ledger.complete_use("W", owner="algorithm", at_us=9)
    assert ledger.snapshot() == before
    ledger.extend_use("W", owner="algorithm", at_us=10, safe_exit_at_us=11)
    assert ledger.carrier("W").epoch == 1


def test_transport_pending_state_is_copied_and_isolated_by_transaction_forks():
    original = offered()
    branch = original.fork()
    branch.record_transport(
        "R",
        owner="producer",
        at_us=7,
        safe_exit_at_us=12,
        evidence=transport_evidence(),
    )
    child = branch.fork()
    assert reserve(original, at_us=8).status == "reserved"
    with pytest.raises(ValueError, match="TRANSPORT_NOT_COMPLETE"):
        reserve(child, at_us=8)
    branch.record_transport(
        "R",
        owner="producer",
        at_us=12,
        safe_exit_at_us=17,
        evidence=transport_evidence(),
    )
    assert reserve(child, at_us=12).status == "reserved"
    with pytest.raises(ValueError, match="TRANSPORT_NOT_COMPLETE"):
        reserve(branch, at_us=12)


def test_free_carrier_transport_lease_preserves_epoch_and_needs_recorded_motion():
    ledger = offered()
    reserve(ledger)
    ledger.consume("raw", consumer="factory", at_us=7, safe_exit_at_us=8)
    ledger.complete_use("R", owner="factory", at_us=8)
    token = ledger.token("raw")
    before = ledger.carrier("R")
    acquired = ledger.acquire_transport("R", owner="router", at_us=9)
    assert acquired.epoch == before.epoch == 1
    assert acquired.atom_ids == before.atom_ids
    assert acquired.phase == "transport" and acquired.owner == "router"
    assert acquired.safe_exit_at_us == before.safe_exit_at_us == 8
    assert acquired.last_at_us == 9
    assert ledger.token("raw") is token
    audit = ledger.snapshot()["audit"][-1]
    assert audit["action"] == "acquire_transport"
    assert audit["physical_action"] is False
    ledger.record_transport(
        "R",
        owner="router",
        at_us=9,
        safe_exit_at_us=14,
        evidence=transport_evidence(),
    )
    with pytest.raises(ValueError, match="CARRIER_NOT_SAFE"):
        ledger.complete_use("R", owner="router", at_us=13)
    ledger.complete_use("R", owner="router", at_us=14)
    assert ledger.begin_preparation("R", owner="producer", at_us=14).epoch == 2


def test_transport_lease_rejects_owned_resource_and_forks_do_not_leak():
    original = offered()
    before = original.snapshot()
    with pytest.raises(ValueError, match="CARRIER_OWNED|ACTIVE_TOKEN"):
        original.acquire_transport("R", owner="router", at_us=7)
    assert original.snapshot() == before
    original.discard("raw", owner="producer", at_us=7)
    original.complete_use("R", owner="producer", at_us=7)
    before = original.snapshot()
    branch = original.fork()
    branch.acquire_transport("R", owner="router", at_us=7)
    with pytest.raises(ValueError, match="CARRIER_OWNED"):
        branch.acquire_transport("R", owner="other", at_us=7)
    assert original.snapshot() == before
    original.acquire_transport("R", owner="other", at_us=7)
    assert branch.carrier("R").owner == "router"
    with pytest.raises(ValueError, match="TIME_REVERSED"):
        branch.complete_use("R", owner="router", at_us=6)
