"""Bounded token-ID inventory; physical placement and delivery remain code-owned.

The buffer never copies a ResourceToken, moves atoms or changes code/distance.
Callers supply the current ledger on every operation because execution waves
commit transaction forks. Capacity is not proof of a vacant physical destination.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING, Any, Protocol

from modules.codes.contracts.factory_recipe import ResourcePreparation

from .protocol_intents import ProtocolFlow
from .resources import Carrier, ResourceError, ResourceLedger, ResourceToken

if TYPE_CHECKING:
    from .factory_process import FactoryProcess


class PreparationSupplier(Protocol):
    """Provide an existing reserved token after separately validated delivery."""

    def __call__(
        self,
        process: FactoryProcess,
        preparation: ResourcePreparation,
        identity: str,
        owner: str,
        /,
    ) -> ProtocolFlow:
        """Yield existing intents and return a token on the requested current carrier."""
        ...


def _name(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ResourceError("INVALID_SUPPLY_IDENTITY")


def _time(value: float) -> None:
    if type(value) not in (int, float) or not isfinite(value) or value < 0:
        raise ResourceError("INVALID_SUPPLY_TIME")


@dataclass(frozen=True)
class _Entry:
    reservation_id: str
    token_id: str
    producer: str
    queued_at_us: float


class TokenBuffer:
    """Finite reservations and token IDs with explicit ownership and removal.

    Claim and consumption do not free capacity. The caller removes an item only
    after its irreversible consumption/discard and declared safe exit. Releasing
    inventory capacity does not release the underlying carrier or move its state.
    """

    def __init__(self, buffer_id: str, capacity: int) -> None:
        _name(buffer_id)
        if type(capacity) is not int or capacity < 1:
            raise ResourceError("INVALID_BUFFER_CAPACITY")
        self.buffer_id, self.capacity = buffer_id, capacity
        self._pending: dict[str, str] = {}
        self._entries: dict[str, _Entry] = {}
        self._claims: dict[str, str] = {}
        self._reservation_ids: set[str] = set()
        self._token_ids: set[str] = set()
        self._closed = False
        self._audit: list[dict[str, Any]] = []

    @property
    def occupied(self) -> int:
        """Return reserved plus published slots, including in-progress consumers."""
        return len(self._pending) + len(self._entries)

    @property
    def closed(self) -> bool:
        """Return the explicit producer-side closure state without modifying it."""
        return self._closed

    @property
    def available_capacity(self) -> int:
        """Expose a read-only backpressure predicate; closed buffers accept no work."""
        return 0 if self._closed else self.capacity - self.occupied

    @property
    def exhausted(self) -> bool:
        """Return true only when explicitly closed and all reserved work is removed."""
        return self._closed and self.occupied == 0

    def _record(self, action: str, at_us: float | None, **details: Any) -> None:
        self._audit.append({"action": action, "at_us": at_us, **details})

    def reserve_capacity(
        self, reservation_id: str, *, owner: str, at_us: float | None = None
    ) -> bool:
        """Reserve one slot or report backpressure/closure without modifying state.

        Reservation identities are single-use, including after explicit abort.
        Omitted reservation time remains null rather than inventing a timestamp.
        """
        _name(reservation_id)
        _name(owner)
        if at_us is not None:
            _time(at_us)
        if reservation_id in self._reservation_ids:
            raise ResourceError("DUPLICATE_BUFFER_RESERVATION")
        if self._closed or self.occupied >= self.capacity:
            return False
        self._pending[reservation_id] = owner
        self._reservation_ids.add(reservation_id)
        self._record(
            "reserve_capacity", at_us, reservation_id=reservation_id, owner=owner
        )
        return True

    def publish(
        self,
        reservation_id: str,
        token_id: str,
        *,
        ledger: ResourceLedger,
        at_us: float,
    ) -> None:
        """Publish a ready, offered token owned by this reservation's producer."""
        _time(at_us)
        if reservation_id not in self._pending:
            raise ResourceError("UNKNOWN_BUFFER_RESERVATION")
        if token_id in self._token_ids:
            raise ResourceError("DUPLICATE_BUFFER_TOKEN")
        token = ledger.token(token_id)
        carrier = ledger.carrier(token.carrier_id)
        owner = self._pending[reservation_id]
        if token.epoch != carrier.epoch:
            raise ResourceError("STALE_BUFFER_TOKEN")
        if (
            token.status != "offered"
            or carrier.owner != owner
            or carrier.phase != "resource"
        ):
            raise ResourceError("BUFFER_TOKEN_OWNER_OR_STATUS_MISMATCH")
        if at_us < max(
            token.ready_at_us,
            token.exit_at_us,
            carrier.safe_exit_at_us,
            carrier.last_at_us,
        ):
            raise ResourceError("BUFFER_TOKEN_NOT_READY")
        del self._pending[reservation_id]
        self._entries[token_id] = _Entry(reservation_id, token_id, owner, at_us)
        self._token_ids.add(token_id)
        self._record("publish", at_us, reservation_id=reservation_id, token_id=token_id)

    def _current(
        self, token_id: str, ledger: ResourceLedger
    ) -> tuple[ResourceToken, Carrier]:
        if token_id not in self._entries:
            raise ResourceError("UNKNOWN_BUFFER_TOKEN")
        token = ledger.token(token_id)
        carrier = ledger.carrier(token.carrier_id)
        if token.epoch != carrier.epoch:
            raise ResourceError("STALE_BUFFER_TOKEN")
        if token.status == "offered":
            if carrier.owner != self._entries[token_id].producer:
                raise ResourceError("BUFFER_TOKEN_OWNERSHIP_CHANGED")
        elif token.status in ("reserved", "consumed"):
            if token.consumer != self._claims.get(token_id) or (
                token.status == "reserved" and carrier.owner != token.consumer
            ):
                raise ResourceError("BUFFER_TOKEN_OWNERSHIP_CHANGED")
        elif token.status != "discarded":
            raise ResourceError("BUFFER_TOKEN_STATUS_CHANGED")
        return token, carrier

    def available(self, *, ledger: ResourceLedger, at_us: float) -> tuple[str, ...]:
        """Return ready offered IDs in publication order; reject stale inventory."""
        _time(at_us)
        result = []
        for token_id, entry in self._entries.items():
            token, carrier = self._current(token_id, ledger)
            if token.status == "offered" and at_us >= max(
                entry.queued_at_us,
                token.ready_at_us,
                token.exit_at_us,
                carrier.safe_exit_at_us,
            ):
                result.append(token_id)
        return tuple(result)

    def claim(
        self,
        token_id: str,
        *,
        ledger: ResourceLedger,
        consumer: str,
        at_us: float,
        expected_code: str,
        expected_kind: str,
        expected_distance: int,
        expected_canonicalization: str = "canonical",
    ) -> ResourceToken:
        """Reserve one existing compatible token; retain its occupied buffer slot."""
        _time(at_us)
        self._current(token_id, ledger)
        if at_us < self._entries[token_id].queued_at_us:
            raise ResourceError("BUFFER_TOKEN_NOT_READY")
        token = ledger.reserve(
            token_id,
            consumer=consumer,
            at_us=at_us,
            expected_code=expected_code,
            expected_kind=expected_kind,
            expected_distance=expected_distance,
            expected_canonicalization=expected_canonicalization,
        )
        self._claims[token_id] = consumer
        self._record("claim", at_us, token_id=token_id, consumer=consumer)
        return token

    def consume(
        self,
        token_id: str,
        *,
        ledger: ResourceLedger,
        consumer: str,
        at_us: float,
        safe_exit_at_us: float,
        usage_kind: str = "consume",
    ) -> ResourceToken:
        """Record irreversible use through the ledger; removal remains explicit."""
        self._current(token_id, ledger)
        token = ledger.consume(
            token_id,
            consumer=consumer,
            at_us=at_us,
            safe_exit_at_us=safe_exit_at_us,
            usage_kind=usage_kind,
        )
        self._record("consume", at_us, token_id=token_id, consumer=consumer)
        return token

    def remove(self, token_id: str, *, ledger: ResourceLedger, at_us: float) -> None:
        """Release capacity after consumption/discard and safe exit, not the carrier."""
        _time(at_us)
        token, carrier = self._current(token_id, ledger)
        if token.status not in ("consumed", "discarded"):
            raise ResourceError("BUFFER_TOKEN_NOT_CONSUMED_OR_DISCARDED")
        if at_us < max(
            self._entries[token_id].queued_at_us,
            carrier.safe_exit_at_us,
            carrier.last_at_us,
        ):
            raise ResourceError("BUFFER_TOKEN_NOT_SAFE")
        del self._entries[token_id]
        self._claims.pop(token_id, None)
        self._record("remove", at_us, token_id=token_id)

    def abort_reservation(
        self, reservation_id: str, *, owner: str, at_us: float | None = None
    ) -> None:
        """Cancel an unpublished reservation owned by this producer."""
        _name(reservation_id)
        _name(owner)
        if at_us is not None:
            _time(at_us)
        if self._pending.get(reservation_id) != owner:
            raise ResourceError("BUFFER_RESERVATION_OWNER_MISMATCH")
        del self._pending[reservation_id]
        self._record(
            "abort_reservation", at_us, reservation_id=reservation_id, owner=owner
        )

    def abort_token(
        self,
        token_id: str,
        *,
        ledger: ResourceLedger,
        owner: str,
        at_us: float,
        safe_exit_at_us: float | None = None,
    ) -> ResourceToken:
        """Explicitly discard an unconsumed item without prematurely freeing its slot."""
        _time(at_us)
        self._current(token_id, ledger)
        if at_us < self._entries[token_id].queued_at_us:
            raise ResourceError("BUFFER_TOKEN_NOT_READY")
        token = ledger.discard(
            token_id, owner=owner, at_us=at_us, safe_exit_at_us=safe_exit_at_us
        )
        self._record("abort_token", at_us, token_id=token_id, owner=owner)
        return token

    def close(self, *, at_us: float | None = None) -> None:
        """Forbid new reservations while allowing previously reserved work to finish."""
        if at_us is not None:
            _time(at_us)
        self._closed = True
        self._record("close", at_us)

    def snapshot(self, *, ledger: ResourceLedger) -> dict[str, Any]:
        """Export current inventory and bookkeeping; no physical-delivery assertion."""
        items = []
        for token_id, entry in self._entries.items():
            token, carrier = self._current(token_id, ledger)
            items.append(
                {
                    "token_id": token_id,
                    "reservation_id": entry.reservation_id,
                    "queued_at_us": entry.queued_at_us,
                    "status": token.status,
                    "carrier_id": token.carrier_id,
                    "epoch": token.epoch,
                    "code": carrier.code_id,
                    "distance": carrier.distance,
                }
            )
        return {
            "schema": "nadit.token_buffer/1",
            "buffer_id": self.buffer_id,
            "capacity": self.capacity,
            "occupied": self.occupied,
            "closed": self._closed,
            "pending": dict(self._pending),
            "items": items,
            "audit": [dict(item) for item in self._audit],
            "physical_delivery": False,
        }
