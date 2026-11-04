"""Explicit continuous-production limits and caller-owned delivery receipts.

No sink or physical transfer protocol is chosen here. Receipt validation checks
the shared ledger lifecycle; its evidence must separately justify delivery cost.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, replace
from math import isfinite
from typing import TYPE_CHECKING, Any, Protocol

from .protocol_intents import ProtocolFlow, WaitIntent
from .resources import ResourceLedger, ResourceToken

if TYPE_CHECKING:
    from .factory_process import FactoryProcess


@dataclass(frozen=True)
class ProductionPolicy:
    """Bound successful production cycles on one uninterrupted timeline.

    ``stop_at_us`` is an absolute requested horizon. A cycle already started is
    drained through terminal delivery/release or a validated reserved-resource
    handoff before stopping; no component is cut short. An explicitly retained
    surplus output or caller demand closure can stop production normally.
    Exhausting ``max_cycles`` before that horizon is an explicit failure.
    Without a horizon, completing exactly ``max_cycles`` is the requested goal.
    """

    max_cycles: int
    stop_at_us: float | None = None

    def __post_init__(self) -> None:
        if type(self.max_cycles) is not int or self.max_cycles < 1:
            raise ValueError("INVALID_PRODUCTION_CYCLE_BUDGET")
        if self.stop_at_us is not None and (
            type(self.stop_at_us) not in (int, float)
            or not isfinite(self.stop_at_us)
            or self.stop_at_us < 0
        ):
            raise ValueError("INVALID_PRODUCTION_HORIZON")


@dataclass(frozen=True)
class OutputDelivery:
    """Sink-supplied times and evidence, checked against the consumed resource."""

    token_id: str
    carrier_id: str
    consumer: str
    deliverable_at_us: float
    consumed_at_us: float
    released_at_us: float
    evidence: Mapping[str, Any]

    def validate(
        self, token: ResourceToken, ledger: ResourceLedger, now_us: float
    ) -> None:
        """Reject missing consumption/release or times inconsistent with the ledger."""
        times = (self.deliverable_at_us, self.consumed_at_us, self.released_at_us)
        current = ledger.token(token.token_id)
        carrier = ledger.carrier(token.carrier_id)
        if (
            self.token_id != token.token_id
            or self.carrier_id != token.carrier_id
            or not isinstance(self.consumer, str)
            or not self.consumer.strip()
            or any(type(t) not in (int, float) or not isfinite(t) for t in times)
            or not token.ready_at_us
            <= self.deliverable_at_us
            <= self.consumed_at_us
            <= self.released_at_us
            <= now_us
            or current.status != "consumed"
            or current.consumer != self.consumer
            or current.consumed_at_us != self.consumed_at_us
            or carrier.epoch != token.epoch
            or carrier.owner is not None
            or carrier.phase != "free"
            or carrier.last_at_us != self.released_at_us
            or carrier.safe_exit_at_us > self.released_at_us
        ):
            raise ValueError("INVALID_OUTPUT_DELIVERY_LIFECYCLE")
        if not isinstance(self.evidence, Mapping) or not self.evidence:
            raise ValueError("INVALID_OUTPUT_DELIVERY_EVIDENCE")
        json.dumps(dict(self.evidence), allow_nan=False)

    def to_dict(self) -> dict[str, Any]:
        """Return an independent serializable delivery record."""
        return {
            "token_id": self.token_id,
            "carrier_id": self.carrier_id,
            "consumer": self.consumer,
            "deliverable_at_us": self.deliverable_at_us,
            "consumed_at_us": self.consumed_at_us,
            "released_at_us": self.released_at_us,
            "evidence": deepcopy(dict(self.evidence)),
        }


@dataclass(frozen=True)
class OutputHandoff:
    """A reserved output handed onward while a free carrier replaces its role.

    The caller performs and validates physical delivery and role reassignment.
    This receipt checks only the current ledger and the declared role binding;
    its scoped trace reference is evidence supplied by the caller, not a claim
    that this validation inspected or replayed a physical trace. No token is
    consumed, released, copied or retagged by this receipt.
    """

    token_id: str
    carrier_id: str
    consumer: str
    handoff_at_us: float
    replacement_carrier_id: str
    replacement_ready_at_us: float
    evidence: Mapping[str, Any]

    def validate(
        self,
        token: ResourceToken,
        ledger: ResourceLedger,
        now_us: float,
        *,
        output_carrier_id: str,
        code_id: str,
        distance: int,
    ) -> None:
        """Verify unchanged reserved input, safe replacement and completed role binding.

        Args:
            token: Original offered token before the caller's handoff flow.
            ledger: Current shared ledger after delivery and reservation.
            now_us: Current execution time.
            output_carrier_id: Producer's already-rebound output role.
            code_id: Producer's declared code.
            distance: Producer's declared distance.

        Raises ValueError for incompatible identities, lifecycle, times or evidence.
        This method never mutates the ledger or verifies physical routing.
        """
        times = (self.handoff_at_us, self.replacement_ready_at_us, now_us)
        current = ledger.token(token.token_id)
        carrier = ledger.carrier(token.carrier_id)
        replacement = ledger.carrier(self.replacement_carrier_id)
        if (
            self.token_id != token.token_id
            or self.carrier_id != token.carrier_id
            or token.status != "offered"
            or not isinstance(self.consumer, str)
            or not self.consumer.strip()
            or any(type(t) not in (int, float) or not isfinite(t) for t in times)
            or current != replace(token, status="reserved", consumer=self.consumer)
            or carrier.epoch != token.epoch
            or carrier.owner != self.consumer
            or carrier.phase != "resource"
            or carrier.code_id != code_id
            or carrier.distance != distance
            or not max(
                token.ready_at_us,
                token.exit_at_us,
                carrier.safe_exit_at_us,
                carrier.last_at_us,
            )
            <= self.handoff_at_us
            <= now_us
            or self.replacement_carrier_id == token.carrier_id
            or output_carrier_id != self.replacement_carrier_id
            or replacement.owner is not None
            or replacement.phase != "free"
            or replacement.code_id != carrier.code_id
            or replacement.distance != carrier.distance
            or replacement.representation != carrier.representation
            or not max(replacement.safe_exit_at_us, replacement.last_at_us)
            <= self.replacement_ready_at_us
            <= now_us
        ):
            raise ValueError("INVALID_OUTPUT_HANDOFF_LIFECYCLE")
        if not isinstance(self.evidence, Mapping) or any(
            not isinstance(self.evidence.get(field), str)
            or not self.evidence[field].strip()
            for field in ("scope", "delivery_trace_ref")
        ):
            raise ValueError("INVALID_OUTPUT_HANDOFF_EVIDENCE")
        json.dumps(dict(self.evidence), allow_nan=False)

    def to_dict(self) -> dict[str, Any]:
        """Return an independent handoff record without terminal consumption times."""
        return {
            "token_id": self.token_id,
            "carrier_id": self.carrier_id,
            "consumer": self.consumer,
            "handoff_at_us": self.handoff_at_us,
            "replacement_carrier_id": self.replacement_carrier_id,
            "replacement_ready_at_us": self.replacement_ready_at_us,
            "validation_scope": "ledger_lifecycle_only",
            "evidence": deepcopy(dict(self.evidence)),
        }


@dataclass(frozen=True)
class OutputRetention:
    """Explicitly retain a safe, unused output when downstream demand has ended.

    Retention preserves the original offered token and its producer-owned
    carrier. It is terminal inventory, not delivery, consumption or release.
    The receipt only validates ledger state; it makes no physical-quality claim.
    """

    token_id: str
    carrier_id: str
    producer_owner: str
    retained_at_us: float
    reason: str
    evidence: Mapping[str, Any]

    def validate(
        self,
        token: ResourceToken,
        ledger: ResourceLedger,
        now_us: float,
        *,
        output_carrier_id: str,
        producer_owner: str,
        code_id: str,
        distance: int,
    ) -> None:
        """Check original identity, safe time and unchanged producer ownership.

        ``producer_owner`` is captured before the sink runs, and
        ``output_carrier_id`` is the producer's current output role. The method
        mutates nothing and rejects invalid lifecycle or evidence with ValueError.
        """
        current = ledger.token(token.token_id)
        carrier = ledger.carrier(token.carrier_id)
        if (
            self.token_id != token.token_id
            or self.carrier_id != token.carrier_id
            or output_carrier_id != token.carrier_id
            or token.status != "offered"
            or current != token
            or not isinstance(self.producer_owner, str)
            or not self.producer_owner.strip()
            or self.producer_owner != producer_owner
            or carrier.owner != producer_owner
            or carrier.phase != "resource"
            or carrier.epoch != token.epoch
            or carrier.code_id != code_id
            or carrier.distance != distance
            or any(
                type(time) not in (int, float) or not isfinite(time)
                for time in (self.retained_at_us, now_us)
            )
            or not max(
                token.ready_at_us,
                token.exit_at_us,
                carrier.safe_exit_at_us,
                carrier.last_at_us,
            )
            <= self.retained_at_us
            <= now_us
        ):
            raise ValueError("INVALID_OUTPUT_RETENTION_LIFECYCLE")
        if (
            not isinstance(self.reason, str)
            or not self.reason.strip()
            or not isinstance(self.evidence, Mapping)
            or not self.evidence
        ):
            raise ValueError("INVALID_OUTPUT_RETENTION_EVIDENCE")
        try:
            json.dumps(dict(self.evidence), allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ValueError("INVALID_OUTPUT_RETENTION_EVIDENCE") from error

    def to_dict(self) -> dict[str, Any]:
        """Export retained inventory without delivery or terminal-consumption times."""
        return {
            "token_id": self.token_id,
            "carrier_id": self.carrier_id,
            "producer_owner": self.producer_owner,
            "retained_at_us": self.retained_at_us,
            "reason": self.reason,
            "validation_scope": "ledger_retention_only",
            "evidence": deepcopy(dict(self.evidence)),
        }


class OutputSink(Protocol):
    """Caller-selected delivery, resource handoff or surplus-retention flow."""

    def __call__(self, process: FactoryProcess, token: ResourceToken) -> ProtocolFlow:
        """Return OutputDelivery, OutputHandoff or terminal OutputRetention."""
        ...


@dataclass(frozen=True)
class IdealExternalSink:
    """Explicit zero-cost external consumption assumption, never a physical route.

    Constructing this capability requires acknowledging excluded external costs.
    The output token is consumed once and its current carrier explicitly released;
    no token is copied and no timing is inferred for transport or a consumer.
    Factory preparation/reset operations in the next cycle remain in the recipe.
    """

    acknowledge_excluded_costs: bool
    consumer_id: str = "ideal_external"

    def __post_init__(self) -> None:
        if self.acknowledge_excluded_costs is not True:
            raise ValueError("IDEAL_EXTERNAL_EXCLUDED_COST_ACKNOWLEDGEMENT_REQUIRED")
        if (
            not isinstance(self.consumer_id, str)
            or not self.consumer_id.strip()
            or "/" in self.consumer_id
        ):
            raise ValueError("INVALID_IDEAL_EXTERNAL_CONSUMER_ID")

    def __call__(self, process: FactoryProcess, token: ResourceToken) -> ProtocolFlow:
        """Wait for the existing safe exit, then consume/release at zero added cost.

        The ResourceLedger enforces offered state, code/distance/kind,
        canonicalization, epoch and single-use ownership. This flow returns an
        OutputDelivery whose evidence explicitly excludes external physical work.
        """
        carrier = process.ledger.carrier(token.carrier_id)
        yield WaitIntent(
            max(
                process.execution.clock_us,
                token.ready_at_us,
                token.exit_at_us,
                carrier.safe_exit_at_us,
            ),
            "ideal_external_existing_safe_exit",
        )
        at_us = process.execution.clock_us
        consumer = (
            f"{process.factory_id}/cycle[{process.cycle_index}]/{self.consumer_id}"
        )
        process.ledger.reserve(
            token.token_id,
            consumer=consumer,
            at_us=at_us,
            expected_code=process.code,
            expected_kind=process.recipe.output_resource_kind,
            expected_canonicalization="canonical",
            expected_distance=process.distance,
        )
        process.ledger.consume(
            token.token_id,
            consumer=consumer,
            at_us=at_us,
            safe_exit_at_us=at_us,
        )
        process.ledger.complete_use(token.carrier_id, owner=consumer, at_us=at_us)
        return OutputDelivery(
            token.token_id,
            token.carrier_id,
            consumer,
            at_us,
            at_us,
            at_us,
            {
                "kind": "ideal_external",
                "physical_delivery": False,
                "acknowledge_excluded_costs": True,
                "assumptions": [
                    "External consumption irreversibly removes the output state at zero modeled time",
                    "No external transport, consumer operation or external reset is compiled",
                    "Carrier release is an explicit ideal consumption assumption, not physical delivery evidence",
                ],
                "excluded_costs_us": {
                    "external_transport": 0,
                    "external_consumer": 0,
                    "external_reset": 0,
                },
                "factory_reinitialization": "existing next-cycle preparation source remains counted",
            },
        )


def make_output_sink(configuration: Mapping[str, Any]) -> OutputSink:
    """Build only an explicitly selected supported sink; there is no default.

    The ideal external configuration requires kind='ideal_external' and the
    Boolean acknowledge_excluded_costs=True. consumer_id is optional. Unknown
    kinds or fields raise ValueError instead of silently changing cost semantics.
    """
    if not isinstance(configuration, Mapping):
        raise TypeError("OUTPUT_SINK_CONFIGURATION_REQUIRED")
    if set(configuration) - {"kind", "acknowledge_excluded_costs", "consumer_id"}:
        raise ValueError("UNKNOWN_OUTPUT_SINK_CONFIGURATION_FIELD")
    if configuration.get("kind") != "ideal_external":
        raise ValueError("EXPLICIT_SUPPORTED_OUTPUT_SINK_KIND_REQUIRED")
    acknowledgement = configuration.get("acknowledge_excluded_costs")
    if acknowledgement is not True:
        raise ValueError("IDEAL_EXTERNAL_EXCLUDED_COST_ACKNOWLEDGEMENT_REQUIRED")
    return IdealExternalSink(
        acknowledge_excluded_costs=acknowledgement,
        consumer_id=configuration.get("consumer_id", "ideal_external"),
    )
