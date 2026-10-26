"""Cooperative protocol requests; only the runtime writes the physical timeline."""

from __future__ import annotations

from collections.abc import Callable, Generator, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from modules.codes.contracts.component import ComponentBinding
from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.contracts.factory_recipe import ComponentCall

from .events import EventObservation
from .receipts import ComponentReceipt
from .resources import ResourceToken

RESOURCE_WAIT_KINDS = ("supply", "buffer")
RESOURCE_WAIT_INSTRUMENTATION_SCHEMA = "nadit.resource_wait_instrumentation/1"


@dataclass(frozen=True)
class CallIntent:
    """Declare a call now; bind and change resource ownership only on admission.

    transport_owner explicitly requests a mechanical block_translation. It does
    not authorize resource consumption or preparation and requires committed native
    transport evidence from the execution kernel. Ordinary calls leave it unset.
    """

    call: ComponentCall
    scope: str
    bound_factory: Callable[[], Any] | None = None
    token: ResourceToken | None = None
    events: tuple[EventObservation, ...] = ()
    begin_preparation_owner: str | None = None
    selection: Mapping[str, Any] | None = None
    transport_owner: str | None = None

    def __post_init__(self) -> None:
        if self.transport_owner is None:
            if self.call.component_id == "block_translation":
                raise ValueError("TRANSPORT_CALL_OWNER_REQUIRED")
            return
        if (
            not isinstance(self.transport_owner, str)
            or not self.transport_owner.strip()
            or self.call.component_id != "block_translation"
            or len(self.call.participant_roles) != 1
            or self.begin_preparation_owner is not None
            or self.call.consumes_resource_role is not None
            or self.selection is not None
        ):
            raise ValueError("INVALID_TRANSPORT_CALL")

    @property
    def invocation_id(self) -> str:
        return f"{self.scope}/{self.call.key}"


@dataclass(frozen=True)
class FeedbackIntent:
    """Resolve a model and sample only after all original sources are ready."""

    identity: str
    attempt: int
    parts: tuple[ComponentReceipt, ...]
    resolve_port: Callable[[], ProbabilityPort]
    participant_roles: tuple[str, ...] = ()

    @property
    def ready_at_us(self) -> float:
        return max(part.results_ready_us for part in self.parts)


@dataclass(frozen=True)
class WaitIntent:
    """Block one flow on a deadline without blocking another factory's frontier."""

    until_us: float
    reason: str


@dataclass(frozen=True)
class ResourceWaitIntent:
    """Wait on caller-owned inventory while other producers continue scheduling.

    Predicates must be read-only and return bool. Exhaustion is explicit; absent
    a future producer action/deadline or a ready predicate, runtime reports a
    deadlock rather than inventing an arrival time or an accepted input.
    """

    resource_id: str
    reason: str
    ready: Callable[[], bool]
    exhausted: Callable[[], bool] | None = None
    wait_kind: Literal["supply", "buffer"] = "supply"

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (self.resource_id, self.reason)
        ):
            raise ValueError("INVALID_RESOURCE_WAIT_IDENTITY")
        if not callable(self.ready) or (
            self.exhausted is not None and not callable(self.exhausted)
        ):
            raise TypeError("INVALID_RESOURCE_WAIT_PREDICATE")
        if self.wait_kind not in RESOURCE_WAIT_KINDS:
            raise ValueError("INVALID_RESOURCE_WAIT_KIND")


@dataclass(frozen=True)
class RoleHandoffIntent:
    """Exchange two roles after an already committed same-carrier delivery.

    The source token must already be reserved by consumer_owner; replacement is
    free. Receipts and exact exit bindings are checked by the execution kernel,
    not accepted as caller assertions of physical delivery. This intent neither
    transports atoms nor changes token/carrier identities or resource quality.
    """

    producer_id: str
    consumer_id: str
    producer_role: str
    consumer_role: str
    token_id: str
    consumer_owner: str
    source_carrier_id: str
    replacement_carrier_id: str
    transport_receipts: tuple[ComponentReceipt, ...]
    expected_snapshot_id: str
    expected_bindings: tuple[ComponentBinding, ...]

    def __post_init__(self) -> None:
        if (
            any(
                not isinstance(value, str) or not value.strip()
                for value in (
                    self.producer_id,
                    self.consumer_id,
                    self.producer_role,
                    self.consumer_role,
                    self.token_id,
                    self.consumer_owner,
                    self.source_carrier_id,
                    self.replacement_carrier_id,
                    self.expected_snapshot_id,
                )
            )
            or self.producer_id == self.consumer_id
            or self.source_carrier_id == self.replacement_carrier_id
        ):
            raise ValueError("INVALID_ROLE_HANDOFF_IDENTITY")
        if (
            not isinstance(self.transport_receipts, tuple)
            or not self.transport_receipts
            or any(
                not isinstance(receipt, ComponentReceipt)
                for receipt in self.transport_receipts
            )
            or len({r.invocation_id for r in self.transport_receipts})
            != len(self.transport_receipts)
            or not isinstance(self.expected_bindings, tuple)
            or len(self.expected_bindings) != 2
            or any(
                not isinstance(binding, ComponentBinding)
                for binding in self.expected_bindings
            )
            or {binding.block_id for binding in self.expected_bindings}
            != {self.source_carrier_id, self.replacement_carrier_id}
        ):
            raise ValueError("INVALID_ROLE_HANDOFF_EVIDENCE")


@dataclass(frozen=True)
class BarrierIntent:
    """Join active factories in this batch at a stable recipe stage.

    A stage never contains a local raw attempt number. Finished or failed lines
    are absent from the cohort, and accepted outputs never re-enter a retry.
    ``cycle_index`` separates continuous cycles. A None batch joins every live
    line in that cycle, including peers still finishing a different retry batch.
    """

    batch_index: int | None
    stage_key: str
    cycle_index: int | None = None


@dataclass(frozen=True)
class ParallelFlows:
    """Expose child calls together and join before the parent continues.

    Readiness does not imply compatibility: the scheduler retains same-patch
    dependencies and device constraints when grouping the children's calls.
    """

    children: tuple[ProtocolFlow, ...]


type ProtocolIntent = (
    CallIntent
    | FeedbackIntent
    | WaitIntent
    | ResourceWaitIntent
    | RoleHandoffIntent
    | BarrierIntent
    | ParallelFlows
)
type ProtocolFlow = Generator[ProtocolIntent, Any, Any]
