"""Carrier and resource lifecycle checks without inventory policy assumptions."""

import pytest

from modules.logical_compiler.src.protocols.resources import ResourceLedger


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
