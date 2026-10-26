"""Protocol events bound to explicit physical or logical interface dependencies.

Only code-owned coarse events are sampled. Physical measurement outputs remain
untouched: timing dependencies do not imply invented syndrome or measured bits.
Logical receipts retain their estimated time basis and logical result identities.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from modules.codes.contracts.event_probability import ProbabilityPort

from ..cases.backend import EventResult, Occurrence, SeededEventBackend
from .receipts import ComponentReceipt, Representation

if TYPE_CHECKING:
    from modules.codes.contracts.component import ComponentExpansion


class EventJournalError(ValueError):
    """Reject malformed source dependencies or unavailable feedback."""


def _finite_time(value: float, field: str, code: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EventJournalError(f"{code}: {field} must be a finite nonnegative time")
    try:
        result = float(value)
    except OverflowError as exc:
        raise EventJournalError(f"{code}: {field} is too large") from exc
    if not math.isfinite(result) or result < 0:
        raise EventJournalError(f"{code}: {field} must be a finite nonnegative time")
    return result


class ClockContext(Protocol):
    """Minimal shared physical-clock interface required to release feedback."""

    @property
    def clock_us(self) -> float:
        """Return the current global case clock."""
        ...

    def wait_until(self, time_us: float, *, reason: str) -> None:
        """Advance to at least time_us while recording why the wait is required."""
        ...


@dataclass(frozen=True)
class EventDependency:
    """Preserve one physical source's exit and global result-ready times.

    A source may have no measurement outputs when only its physical exit is
    required. The whole event dependency set must include a measured result.
    Malformed identities, duplicates and invalid times raise EventJournalError.
    """

    invocation_id: str
    exit_at_us: float
    results: tuple[tuple[int, float], ...]
    representation: Representation = "physical"

    def __post_init__(self) -> None:
        if self.representation not in ("physical", "logical_estimate"):
            raise EventJournalError("INVALID_EVENT_REPRESENTATION")
        if not isinstance(self.invocation_id, str) or not self.invocation_id.strip():
            raise EventJournalError("INVALID_EVENT_DEPENDENCY: empty source invocation")
        exit_time = _finite_time(
            self.exit_at_us, "exit_at_us", "INVALID_EVENT_DEPENDENCY"
        )
        normalized: list[tuple[int, float]] = []
        try:
            pairs = tuple(tuple(pair) for pair in self.results)
        except TypeError as exc:
            raise EventJournalError(
                "INVALID_EVENT_DEPENDENCY: expected result/time pairs"
            ) from exc
        for pair in pairs:
            if len(pair) != 2:
                raise EventJournalError(
                    "INVALID_EVENT_DEPENDENCY: expected result/time pairs"
                )
            result_id, ready = pair
            if (
                isinstance(result_id, bool)
                or not isinstance(result_id, int)
                or result_id < 0
            ):
                raise EventJournalError(
                    "INVALID_EVENT_DEPENDENCY: result IDs must be nonnegative integers"
                )
            normalized.append(
                (
                    result_id,
                    _finite_time(ready, "available_at_us", "INVALID_EVENT_DEPENDENCY"),
                )
            )
        if len({result_id for result_id, _ in normalized}) != len(normalized):
            raise EventJournalError(
                "DUPLICATE_RESULT: source repeats a global result ID"
            )
        object.__setattr__(self, "exit_at_us", exit_time)
        object.__setattr__(self, "results", tuple(sorted(normalized)))

    @classmethod
    def from_expansion(cls, expansion: ComponentExpansion) -> EventDependency:
        """Read component identities and availability without reading bits.

        Raises EventJournalError if a measurement claims another invocation.
        This conversion does not perform physical validation of the expansion.
        """
        if any(
            result.invocation_id != expansion.invocation_id
            for result in expansion.measurements
        ):
            raise EventJournalError(
                "INVALID_EVENT_DEPENDENCY: result source differs from expansion"
            )
        return cls(
            expansion.invocation_id,
            expansion.action_end_us,
            tuple(
                (result.result.measurement_id, result.available_at_us)
                for result in expansion.measurements
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        """Return a fresh dependency record containing no physical result values."""
        return {
            "invocation_id": self.invocation_id,
            "exit_at_us": self.exit_at_us,
            "results": [
                {"result_id": result_id, "available_at_us": ready}
                for result_id, ready in self.results
            ],
            **(
                {
                    "representation": "logical_estimate",
                    "time_basis": "logical_estimated_us",
                    "result_identity_kind": "logical_interface",
                }
                if self.representation == "logical_estimate"
                else {}
            ),
        }

    @classmethod
    def from_receipt(cls, receipt: ComponentReceipt) -> EventDependency:
        """Keep receipt dependency identities and their explicit evidence scope."""
        return cls(
            receipt.invocation_id,
            receipt.action_end_us,
            receipt.result_availability,
            receipt.representation,
        )


@dataclass(frozen=True)
class EventObservation:
    """Immutable chosen coarse event and the physical dependencies permitting it."""

    result: EventResult
    _values_json: str
    branch_id: str
    transition: str
    dependencies: tuple[EventDependency, ...]
    released_at_us: float

    @property
    def values(self) -> dict[str, Any]:
        """Return a fresh copy of the selected joint protocol values."""
        return dict(json.loads(self._values_json))

    def to_dict(self) -> dict[str, Any]:
        """Return event, timing and provenance without physical measurement bits."""
        return {
            **self.result.to_dict(),
            "values": self.values,
            "branch_id": self.branch_id,
            "transition": self.transition,
            "dependencies": [dependency.to_dict() for dependency in self.dependencies],
            "released_at_us": self.released_at_us,
        }


def _dependencies(sources: Iterable[EventDependency]) -> tuple[EventDependency, ...]:
    dependencies = tuple(sources)
    if not dependencies or any(
        not isinstance(source, EventDependency) for source in dependencies
    ):
        raise EventJournalError(
            "INVALID_EVENT_DEPENDENCY: at least one physical source is required"
        )
    if len({source.invocation_id for source in dependencies}) != len(dependencies):
        raise EventJournalError("DUPLICATE_SOURCE: repeated physical source invocation")
    if len({source.representation for source in dependencies}) != 1:
        raise EventJournalError("MIXED_EVENT_REPRESENTATIONS")
    result_ids = [
        result_id for source in dependencies for result_id, _ in source.results
    ]
    if not result_ids:
        raise EventJournalError(
            "INVALID_EVENT_DEPENDENCY: at least one measured result is required"
        )
    if len(set(result_ids)) != len(result_ids):
        raise EventJournalError("DUPLICATE_RESULT: sources share a global result ID")
    return tuple(sorted(dependencies, key=lambda source: source.invocation_id))


def _wait(context: ClockContext, until: float, reason: str) -> float:
    current = _finite_time(context.clock_us, "clock_us", "INVALID_EVENT_CLOCK")
    if current < until:
        context.wait_until(until, reason=reason)
    released = _finite_time(context.clock_us, "clock_us", "INVALID_EVENT_CLOCK")
    if released < max(until, current):
        raise EventJournalError(
            "CLOCK_NOT_READY: context did not reach the feedback release time"
        )
    return released


class EventJournal:
    """Sample coarse events only after source results and physical exits are ready.

    Args:
        case_id: Stable owning case identity.
        seed: Seed passed unchanged to SeededEventBackend.

    Invalid seeds/identities preserve the backend's validation errors. Successful
    observations retain actual resolution order; input dependency order is normalized.
    """

    def __init__(self, case_id: str, seed: int) -> None:
        self._case_id = case_id
        self._backend = SeededEventBackend(case_id, seed)
        self._observations: dict[Occurrence, EventObservation] = {}
        self._models: dict[str, str] = {}

    def sample(
        self,
        port: ProbabilityPort,
        *,
        invocation_id: str,
        attempt: int,
        dependencies: Iterable[EventDependency],
        context: ClockContext,
    ) -> EventObservation:
        """Wait, sample once, and journal the exact source/result dependency binding.

        Returns the same observation for a repeated unchanged occurrence. Changed
        probability hashes/readiness retain backend binding errors; changed source
        dependencies raise EventJournalError. No event is published if the clock
        cannot reach the required release time.
        """
        sources = _dependencies(dependencies)
        available = max(ready for source in sources for _, ready in source.results)
        occurrence = Occurrence(
            self._case_id, invocation_id, attempt, port.to_dict()["port_id"]
        )
        previous = self._observations.get(occurrence)
        reason = f"protocol_event:{invocation_id}:{attempt}:{occurrence.port_id}"
        if previous is not None:
            if (
                previous.result.port_sha256 != port.content_sha256
                or previous.result.available_at_us != available
            ):
                # Delegate changed hash/time validation to the existing backend.
                self._backend.sample(port, occurrence, available_at_us=available)
            if previous.dependencies != sources:
                raise EventJournalError(
                    "EVENT_DEPENDENCY_CONFLICT: occurrence source dependencies changed"
                )
            _wait(context, previous.released_at_us, reason)
            return previous
        release = max(available, *(source.exit_at_us for source in sources))
        released = _wait(context, release, reason)
        result = self._backend.sample(port, occurrence, available_at_us=available)
        outcome = port.outcome(result.outcome_key)
        branch = port.branch(outcome.branch_id)
        observation = EventObservation(
            result,
            json.dumps(
                dict(outcome.values),
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ),
            branch.key,
            branch.transition,
            sources,
            released,
        )
        self._observations[occurrence] = observation
        self._models[port.content_sha256] = json.dumps(
            port.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        return observation

    def snapshot(self) -> dict[str, Any]:
        """Return resolved events and complete immutable model snapshots."""
        return {
            "events": [
                observation.to_dict() for observation in self._observations.values()
            ],
            "probability_models": {
                key: json.loads(self._models[key]) for key in sorted(self._models)
            },
        }
