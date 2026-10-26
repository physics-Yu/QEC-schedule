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
