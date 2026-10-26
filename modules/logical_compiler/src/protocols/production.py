"""First-level continuous production and explicit ideal external delivery.

Selected from 85f5479; second-level handoff/retention capabilities are deferred.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING, Any, Protocol

from .protocol_intents import ProtocolFlow, WaitIntent
from .resources import ResourceLedger, ResourceToken

if TYPE_CHECKING:
    from .factory_process import FactoryProcess


class OutputSink(Protocol):
    """Caller-selected output delivery flow."""

    def __call__(
        self, process: FactoryProcess, token: ResourceToken
    ) -> ProtocolFlow: ...


@dataclass(frozen=True)
class ProductionPolicy:
    """Bound accepted outputs or attempted rounds on one uninterrupted timeline.

    ``stop_at_us`` is an absolute requested horizon. A cycle already started is
    drained through terminal delivery/release or a validated reserved-resource
    handoff before stopping; no component is cut short. An explicitly retained
    surplus output or caller demand closure can stop production normally.
    Exhausting ``max_cycles`` before that horizon is an explicit failure.
    Without a horizon, completing exactly ``max_cycles`` is the requested goal.
    ``completion_basis='production_rounds'`` counts every final decision, including
    rejection. It never retries a final rejection inside the same cycle; the next
    cycle prepares a new batch. Raw-resource retries remain internal to a round.
    """

    max_cycles: int
    stop_at_us: float | None = None
    completion_basis: str = "accepted_outputs"

    def __post_init__(self) -> None:
        if self.completion_basis not in ("accepted_outputs", "production_rounds"):
            raise ValueError("INVALID_PRODUCTION_COMPLETION_BASIS")
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
                    (
                        "External consumption irreversibly removes the output "
                        "state at zero modeled time"
                    ),
                    (
                        "No external transport, consumer operation or external "
                        "reset is compiled"
                    ),
                    (
                        "Carrier release is an explicit ideal consumption "
                        "assumption, not physical delivery evidence"
                    ),
                ],
                "excluded_costs_us": {
                    "external_transport": 0,
                    "external_consumer": 0,
                    "external_reset": 0,
                },
                "factory_reinitialization": "existing next-cycle preparation "
                "source remains counted",
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
