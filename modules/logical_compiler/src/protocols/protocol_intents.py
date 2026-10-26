"""Cooperative protocol requests; only the runtime writes the physical timeline."""

from __future__ import annotations

from collections.abc import Callable, Generator, Mapping
from dataclasses import dataclass
from typing import Any

from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.contracts.factory_recipe import ComponentCall

from .events import EventObservation
from .receipts import ComponentReceipt
from .resources import ResourceToken


@dataclass(frozen=True)
class CallIntent:
    """Declare a call now; bind and change resource ownership only on admission."""

    call: ComponentCall
    scope: str
    bound_factory: Callable[[], Any] | None = None
    token: ResourceToken | None = None
    events: tuple[EventObservation, ...] = ()
    begin_preparation_owner: str | None = None
    selection: Mapping[str, Any] | None = None

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
class BarrierIntent:
    """Join active factories in this batch at a stable recipe stage.

    A stage never contains a local raw attempt number. Finished or failed lines
    are absent from the cohort, and accepted outputs never re-enter a retry.
    """

    batch_index: int
    stage_key: str


@dataclass(frozen=True)
class ParallelPreparations:
    """Independent finite child flows, joined before their parent continues."""

    children: tuple[ProtocolFlow, ...]


type ProtocolIntent = (
    CallIntent | FeedbackIntent | WaitIntent | BarrierIntent | ParallelPreparations
)
type ProtocolFlow = Generator[ProtocolIntent, Any, Any]
