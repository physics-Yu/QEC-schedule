"""Execution evidence shared by physical and calibrated logical protocol runs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from math import isfinite
from typing import Any, Literal

type Representation = Literal["physical", "logical_estimate"]


def _time(value: float) -> bool:
    return type(value) in (int, float) and isfinite(value) and value >= 0


@dataclass(frozen=True)
class ExecutionCarrier:
    """A carrier declaration; logical carriers have no invented atom footprint."""

    carrier_id: str
    representation: Representation
    atom_ids: tuple[str | int, ...] = ()

    def __post_init__(self) -> None:
        if not self.carrier_id or self.representation not in (
            "physical",
            "logical_estimate",
        ):
            raise ValueError("INVALID_EXECUTION_CARRIER")
        if (self.representation == "physical") != bool(self.atom_ids):
            raise ValueError("EXECUTION_CARRIER_FOOTPRINT_MISMATCH")


@dataclass(frozen=True)
class ComponentReceipt:
    """An actual or estimated interface completion, never an atom expansion.

    Logical result IDs identify abstract interface dependencies. They are not
    physical measurement records and contain no measured values. provenance_json
    is frozen JSON so profile/model evidence cannot change after publication.
    """

    invocation_id: str
    component_id: str
    participant_blocks: tuple[str, ...]
    start_us: float
    action_end_us: float
    results_ready_us: float
    result_availability: tuple[tuple[int, float], ...] = ()
    representation: Representation = "logical_estimate"
    provenance_json: str = "{}"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.invocation_id, str)
            or not self.invocation_id.strip()
            or not isinstance(self.component_id, str)
            or not self.component_id.strip()
            or not isinstance(self.participant_blocks, tuple)
            or not self.participant_blocks
            or len(set(self.participant_blocks)) != len(self.participant_blocks)
            or any(
                not isinstance(block, str) or not block.strip()
                for block in self.participant_blocks
            )
            or self.representation not in ("physical", "logical_estimate")
        ):
            raise ValueError("INVALID_COMPONENT_RECEIPT_IDENTITY")
        if (
            not all(
                _time(value)
                for value in (self.start_us, self.action_end_us, self.results_ready_us)
            )
            or not self.start_us <= self.action_end_us <= self.results_ready_us
        ):
            raise ValueError("INVALID_COMPONENT_RECEIPT_TIME")
        if not isinstance(self.result_availability, tuple) or any(
            not isinstance(pair, tuple)
            or len(pair) != 2
            or type(pair[0]) is not int
            or pair[0] < 0
            or not _time(pair[1])
            or not self.start_us <= pair[1] <= self.results_ready_us
            for pair in self.result_availability
        ):
            raise ValueError("INVALID_COMPONENT_RECEIPT_RESULTS")
        if len({result for result, _ in self.result_availability}) != len(
            self.result_availability
        ):
            raise ValueError("DUPLICATE_COMPONENT_RECEIPT_RESULT")
        provenance = json.loads(self.provenance_json)
        if not isinstance(provenance, dict):
            raise TypeError("INVALID_COMPONENT_RECEIPT_PROVENANCE")
        json.dumps(provenance, allow_nan=False)

    @property
    def provenance(self) -> dict[str, Any]:
        return dict(json.loads(self.provenance_json))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "nadit.component_receipt/1",
            "representation": self.representation,
            "invocation_id": self.invocation_id,
            "component_id": self.component_id,
            "participant_blocks": list(self.participant_blocks),
            "start_us": self.start_us,
            "action_end_us": self.action_end_us,
            "results_ready_us": self.results_ready_us,
            "result_availability": [
                {"result_id": result, "available_at_us": ready}
                for result, ready in self.result_availability
            ],
            "result_identity_kind": "logical_interface"
            if self.representation == "logical_estimate"
            else "physical_measurement",
            "provenance": self.provenance,
        }
