"""Seeded sampling of code-owned coarse probability events.

This backend binds an event outcome but does not release feedback dependencies.
The case engine must respect the bound availability and physical exit times.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from modules.codes.contracts.event_probability import ProbabilityPort


_RANDOM_BITS = 53
_HASH_BITS = 256
_RANDOM_DOMAIN = "nadit.coarse_event/1"


class EventBackendError(ValueError):
    """Reject an invalid event identity, input binding or probability draw."""


def _validate_name(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise EventBackendError(
            f"INVALID_EVENT_IDENTITY: {field} must be a nonempty string"
        )


def _validate_time(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EventBackendError(
            "INVALID_EVENT_TIME: available_at_us must be a finite number"
        )
    try:
        converted = float(value)
    except OverflowError as exc:
        raise EventBackendError(
            "INVALID_EVENT_TIME: available_at_us is too large"
        ) from exc
    if not math.isfinite(converted) or converted < 0:
        raise EventBackendError(
            "INVALID_EVENT_TIME: available_at_us must be finite and nonnegative"
        )
    return converted


@dataclass(frozen=True)
class Occurrence:
    """Identify one protocol event in one invocation attempt.

    Args:
        case_id: Owning case identifier.
        invocation_id: Stable invocation identifier within the case.
        attempt: Nonnegative retry index; booleans are not valid indices.
        port_id: The exact code-owned probability port identifier.

    Raises:
        ValueError: An identifier is empty or the attempt is not a nonnegative integer.
    """

    case_id: str
    invocation_id: str
    attempt: int
    port_id: str

    def __post_init__(self) -> None:
        for field in ("case_id", "invocation_id", "port_id"):
            _validate_name(getattr(self, field), field)
        if (
            isinstance(self.attempt, bool)
            or not isinstance(self.attempt, int)
            or self.attempt < 0
        ):
            raise EventBackendError(
                "INVALID_EVENT_IDENTITY: attempt must be a nonnegative integer"
            )

    def to_dict(self) -> dict[str, str | int]:
        """Return a fresh JSON-compatible occurrence identity."""
        return {
            "case_id": self.case_id,
            "invocation_id": self.invocation_id,
            "attempt": self.attempt,
            "port_id": self.port_id,
        }


@dataclass(frozen=True)
class EventResult:
    """Store the selected joint outcome with its immutable input binding.

    Args:
        occurrence: The sampled event identity.
        port_sha256: Fingerprint of the complete shared probability document.
        available_at_us: Earliest result-ready time; not a feedback release itself.
        outcome_key: A whole joint outcome in that document.
        evidence_kind: Always ``coarse_probability``; no syndrome is generated.

    Raises:
        ValueError: The evidence kind attempts to claim detailed measurement data.
    """

    occurrence: Occurrence
    port_sha256: str
    available_at_us: float
    outcome_key: str
    evidence_kind: str = "coarse_probability"

    def __post_init__(self) -> None:
        if self.evidence_kind != "coarse_probability":
            raise EventBackendError(
                "UNSUPPORTED_EVENT_EVIDENCE: only coarse_probability is implemented"
            )

    def to_dict(self) -> dict[str, object]:
        """Return a fresh result record referencing the complete model by its hash."""
        return {
            "occurrence": self.occurrence.to_dict(),
            "port_sha256": self.port_sha256,
            "available_at_us": self.available_at_us,
            "outcome_key": self.outcome_key,
            "evidence_kind": self.evidence_kind,
        }


def _uniform_draw(seed: int, occurrence: Occurrence) -> float:
    payload = json.dumps(
        [_RANDOM_DOMAIN, seed, occurrence.to_dict()],
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = int.from_bytes(hashlib.sha256(payload).digest(), "big")
    # Taking 53 bits avoids rounding the maximum draw up to 1.0.
    return (digest >> (_HASH_BITS - _RANDOM_BITS)) / (1 << _RANDOM_BITS)


def _select_outcome(port: ProbabilityPort, draw: float) -> str:
    probabilities: list[float] = []
    for outcome in port.outcomes:
        probabilities.append(outcome.probability)
        if outcome.probability > 0 and draw < math.fsum(probabilities):
            return outcome.key
    # Shared validation tolerates tiny sum roundoff. A sampled gap must remain
    # explicit rather than silently rescaling the code-owned distribution.
    raise EventBackendError(
        "EVENT_PROBABILITY_GAP: draw lies outside declared probability mass"
    )


class SeededEventBackend:
    """Sample once per occurrence, independently of frontier visitation order.

    Args:
        case_id: Case that owns every sampled occurrence.
        seed: Integer seed, including negative integers; booleans are rejected.
        backend_kind: Only ``coarse_probability`` is currently supported.

    Raises:
        ValueError: The case identifier or seed is invalid.
        NotImplementedError: A detailed syndrome/decoder or unknown backend is requested.
    """

    def __init__(
        self, case_id: str, seed: int, *, backend_kind: str = "coarse_probability"
    ) -> None:
        _validate_name(case_id, "case_id")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise EventBackendError(
                "INVALID_EVENT_SEED: seed must be an integer, not a boolean"
            )
        if backend_kind != "coarse_probability":
            raise NotImplementedError(
                f"UNSUPPORTED_EVENT_BACKEND: {backend_kind!r}; only coarse_probability is implemented"
            )
        self._case_id = case_id
        self._seed = seed
        self._results: dict[Occurrence, EventResult] = {}

    @property
    def results(self) -> tuple[EventResult, ...]:
        """Return immutable results in case/invocation/attempt/port identity order."""
        identities = sorted(
            self._results,
            key=lambda item: (
                item.case_id,
                item.invocation_id,
                item.attempt,
                item.port_id,
            ),
        )
        return tuple(self._results[identity] for identity in identities)

    def sample(
        self, port: ProbabilityPort, occurrence: Occurrence, *, available_at_us: float
    ) -> EventResult:
        """Return the one sampled outcome for this bound occurrence.

        Args:
            port: Validated immutable shared probability port.
            occurrence: Stable identity, with a fresh attempt for each retry.
            available_at_us: Bound finite nonnegative result-ready time.

        Returns:
            The stored result, including the same object on repeated access.

        Raises:
            ValueError: Case/port identity differs, time is invalid, a previous
                binding changes, or a draw falls outside declared probability mass.
        """
        ready_time = _validate_time(available_at_us)
        port_id = port.to_dict()["port_id"]
        if occurrence.case_id != self._case_id or occurrence.port_id != port_id:
            raise EventBackendError(
                f"EVENT_IDENTITY_MISMATCH: {occurrence!r} does not match case {self._case_id!r}"
                f" and port {port_id!r}"
            )
        port_hash = port.content_sha256
        previous = self._results.get(occurrence)
        if previous is not None:
            if (
                previous.port_sha256 != port_hash
                or previous.available_at_us != ready_time
            ):
                raise EventBackendError(
                    f"EVENT_BINDING_CONFLICT: probability port or ready time changed for {occurrence!r}"
                )
            return previous
        outcome_key = _select_outcome(port, _uniform_draw(self._seed, occurrence))
        result = EventResult(occurrence, port_hash, ready_time, outcome_key)
        self._results[occurrence] = result
        return result
