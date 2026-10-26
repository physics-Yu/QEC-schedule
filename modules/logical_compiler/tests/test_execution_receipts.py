"""Typed logical evidence must not impersonate atom expansions or carriers."""

import pytest

from modules.logical_compiler.src.protocols.events import EventDependency
from modules.logical_compiler.src.protocols.receipts import (
    ComponentReceipt,
    ExecutionCarrier,
)
from modules.logical_compiler.src.protocols.resources import ResourceLedger


def test_logical_receipt_has_only_estimated_interface_results():
    receipt = ComponentReceipt("line/raw", "raw", ("line/P",), 2, 7, 10, ((0, 10),))
    assert receipt.representation == "logical_estimate"
    assert not hasattr(receipt, "program") and not hasattr(receipt, "measurements")
    dependency = EventDependency.from_receipt(receipt).to_dict()
    assert dependency["representation"] == "logical_estimate"
    assert dependency["results"] == [{"result_id": 0, "available_at_us": 10}]


def test_logical_carrier_needs_no_atom_ids_and_uses_same_epoch_and_token_lifecycle():
    declaration = ExecutionCarrier("line/P", "logical_estimate")
    assert declaration.atom_ids == ()
    ledger = ResourceLedger()
    ledger.register_logical_carrier("line/P", code_id="test", distance=3)
    carrier = ledger.begin_preparation("line/P", owner="line", at_us=1)
    token = ledger.offer(
        "token",
        carrier_id="line/P",
        epoch=carrier.epoch,
        owner="line",
        resource_kind="A",
        producer="raw",
        ready_at_us=2,
        exit_at_us=2,
        canonicalization="canonical",
    )
    ledger.reserve(
        token.token_id,
        consumer="use",
        at_us=2,
        expected_code="test",
        expected_kind="A",
        expected_canonicalization="canonical",
    )
    ledger.consume(token.token_id, consumer="use", at_us=2, safe_exit_at_us=3)
    ledger.complete_use("line/P", owner="use", at_us=3)
    snapshot = ledger.snapshot()
    assert snapshot["schema"] == "nadit.resource_ledger/2"
    assert snapshot["resource_time_basis"] == "logical_estimated_us"
    assert "atom_ids" not in snapshot["carriers"][0]
    assert snapshot["carriers"][0]["epoch"] == 1
    assert snapshot["tokens"][0]["status"] == "consumed"


def test_physical_carrier_and_dependency_keep_original_serialization():
    ledger = ResourceLedger()
    ledger.register_carrier("P", code_id="test", distance=3, atom_ids=(1, 2))
    assert ledger.snapshot()["schema"] == "nadit.resource_ledger/1"
    assert "resource_time_basis" not in ledger.snapshot()
    assert "representation" not in ledger.snapshot()["carriers"][0]
    receipt = ComponentReceipt(
        "physical", "measure", ("P",), 0, 1, 2, ((0, 2),), representation="physical"
    )
    assert (
        EventDependency.from_receipt(receipt).to_dict()
        == EventDependency("physical", 1, ((0, 2),)).to_dict()
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"representation": "logical_estimate", "atom_ids": (1,)},
        {"representation": "physical", "atom_ids": ()},
    ],
)
def test_carrier_representations_cannot_fake_physical_footprints(kwargs):
    with pytest.raises(ValueError):
        ExecutionCarrier("P", **kwargs)
