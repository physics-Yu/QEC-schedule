"""Explicit carrier ownership and single-use resource accounting.

This ledger records caller-supplied physical exits and quantum evidence. It does
not estimate quality, schedule operations, maintain inventory or request SE.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any


class ResourceError(ValueError):
    """Reject an invalid carrier or resource lifecycle transition."""


def _name(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ResourceError(
            f"INVALID_RESOURCE_INPUT: {field} must be a nonempty string"
        )


def _time(value: float, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResourceError(f"INVALID_TIME: {field} must be finite and nonnegative")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ResourceError(f"INVALID_TIME: {field} is too large") from exc
    if not math.isfinite(result) or result < 0:
        raise ResourceError(f"INVALID_TIME: {field} must be finite and nonnegative")
    return result


def _json_evidence(value: dict[str, Any] | None, field: str) -> str:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ResourceError(f"INVALID_EVIDENCE: {field} must be a JSON object")

    def validate(item: Any, active: set[int]) -> None:
        if type(item) in (str, int, bool) or item is None:
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) not in (dict, list) or id(item) in active:
            raise ResourceError(
                f"INVALID_EVIDENCE: {field} must contain finite JSON values"
            )
        active.add(id(item))
        if isinstance(item, dict):
            if any(type(key) is not str for key in item):
                raise ResourceError(f"INVALID_EVIDENCE: {field} keys must be strings")
            children = item.values()
        else:
            children = item
        for child in children:
            validate(child, active)
        active.remove(id(item))

    validate(value, set())
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class Carrier:
    """Immutable carrier snapshot, replaced on each legal transition.

    ``epoch`` advances only when a new preparation starts. An owner continues to
    protect the carrier after a token is consumed, until explicit completion.
    Physical carriers retain actual atom footprints and physical safe exits.
    Logical carriers have no atoms; their safe exits are explicitly estimated.
    """

    carrier_id: str
    code_id: str
    distance: int
    atom_ids: tuple[str | int, ...]
    epoch: int = 0
    owner: str | None = None
    phase: str = "free"
    safe_exit_at_us: float = 0.0
    last_at_us: float = 0.0
    representation: str = "physical"

    def __post_init__(self) -> None:
        if self.representation not in ("physical", "logical_estimate") or (
            (self.representation == "physical") != bool(self.atom_ids)
        ):
            raise ResourceError("CARRIER_REPRESENTATION_FOOTPRINT_MISMATCH")

    def to_dict(self) -> dict[str, Any]:
        """Return a fresh JSON-compatible carrier record."""
        return {
            "carrier_id": self.carrier_id,
            "code_id": self.code_id,
            "distance": self.distance,
            **(
                {"atom_ids": list(self.atom_ids)}
                if self.representation == "physical"
                else {
                    "representation": "logical_estimate",
                    "resource_time_basis": "logical_estimated_us",
                }
            ),
            "epoch": self.epoch,
            "owner": self.owner,
            "phase": self.phase,
            "safe_exit_at_us": self.safe_exit_at_us,
            "last_at_us": self.last_at_us,
        }


@dataclass(frozen=True)
class ResourceToken:
    """Immutable resource identity and evidence with explicit lifecycle state.

    Code protocols supply kind and canonicalization labels (for example ``A``,
    ``A_dagger``, ``canonical`` and ``unresolved``). Evidence is canonical JSON;
    this class and the ledger make no quantum-quality inference.
    """

    token_id: str
    carrier_id: str
    epoch: int
    resource_kind: str
    producer: str
    ready_at_us: float
    exit_at_us: float
    canonicalization: str
    quality_json: str
    provenance_json: str
    status: str = "offered"
    consumer: str | None = None
    consumed_at_us: float | None = None
    discarded_at_us: float | None = None
    usage_kind: str | None = None

    @property
    def quality(self) -> dict[str, Any]:
        """Return a copy of caller-provided quality evidence."""
        return dict(json.loads(self.quality_json))

    @property
    def provenance(self) -> dict[str, Any]:
        """Return a copy of caller-provided provenance."""
        return dict(json.loads(self.provenance_json))

    def to_dict(self) -> dict[str, Any]:
        """Return a fresh JSON-compatible token including its evidence."""
        return {
            "token_id": self.token_id,
            "carrier_id": self.carrier_id,
            "epoch": self.epoch,
            "resource_kind": self.resource_kind,
            "producer": self.producer,
            "ready_at_us": self.ready_at_us,
            "exit_at_us": self.exit_at_us,
            "canonicalization": self.canonicalization,
            "quality": self.quality,
            "provenance": self.provenance,
            "status": self.status,
            "consumer": self.consumer,
            "consumed_at_us": self.consumed_at_us,
            "discarded_at_us": self.discarded_at_us,
            "usage_kind": self.usage_kind,
        }


class ResourceLedger:
    """Own explicit resource transitions without production or storage policies.

    Mutation methods raise ResourceError on invalid transitions and leave the
    ledger unchanged. Unknown carrier/token lookups raise KeyError.
    """

    def __init__(self) -> None:
        self._carriers: dict[str, Carrier] = {}
        self._tokens: dict[str, ResourceToken] = {}
        self._atoms: set[str | int] = set()
        self._audit: list[str] = []

    def carrier(self, carrier_id: str) -> Carrier:
        """Return the immutable current carrier; raise KeyError if unknown."""
        return self._carriers[carrier_id]

    def token(self, token_id: str) -> ResourceToken:
        """Return the immutable historical/current token; raise KeyError if unknown."""
        return self._tokens[token_id]

    def _record(self, action: str, at_us: float, **fields: Any) -> None:
        self._audit.append(
            json.dumps(
                {
                    "sequence": len(self._audit),
                    "action": action,
                    "at_us": at_us,
                    **fields,
                },
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        )

    def _at(self, carrier: Carrier, at_us: float) -> float:
        at = _time(at_us, "at_us")
        if at < carrier.last_at_us:
            raise ResourceError(f"TIME_REVERSED: carrier {carrier.carrier_id!r}")
        return at

    def _owner(self, carrier: Carrier, owner: str) -> None:
        _name(owner, "owner")
        if carrier.owner != owner:
            raise ResourceError(f"OWNER_MISMATCH: carrier {carrier.carrier_id!r}")

    def _active(self, carrier: Carrier) -> bool:
        return any(
            token.carrier_id == carrier.carrier_id
            and token.epoch == carrier.epoch
            and token.status in ("offered", "reserved")
            for token in self._tokens.values()
        )

    def _current_token(self, token_id: str) -> tuple[ResourceToken, Carrier]:
        token = self.token(token_id)
        carrier = self.carrier(token.carrier_id)
        if token.epoch != carrier.epoch:
            raise ResourceError(
                f"STALE_TOKEN: {token_id!r} references an earlier epoch"
            )
        return token, carrier

    def register_carrier(
        self,
        carrier_id: str,
        *,
        code_id: str,
        distance: int,
        atom_ids: Iterable[str | int],
    ) -> Carrier:
        """Register a disjoint atom set and code identity, initially free at epoch 0."""
        if any(
            carrier.representation != "physical" for carrier in self._carriers.values()
        ):
            raise ResourceError("MIXED_RESOURCE_REPRESENTATIONS")
        _name(carrier_id, "carrier_id")
        _name(code_id, "code_id")
        if isinstance(distance, bool) or not isinstance(distance, int) or distance < 1:
            raise ResourceError(
                "INVALID_RESOURCE_INPUT: distance must be a positive integer"
            )
        atoms = tuple(atom_ids)
        if not atoms or any(type(atom) not in (int, str) for atom in atoms):
            raise ResourceError(
                "INVALID_RESOURCE_INPUT: atom_ids must be nonempty integer/string IDs"
            )
        if any(isinstance(atom, str) and not atom.strip() for atom in atoms):
            raise ResourceError("INVALID_RESOURCE_INPUT: empty atom ID")
        if len(set(atoms)) != len(atoms):
            raise ResourceError("ATOM_OVERLAP: duplicate atoms within carrier")
        if carrier_id in self._carriers:
            raise ResourceError(f"DUPLICATE_CARRIER: {carrier_id!r}")
        if self._atoms.intersection(atoms):
            raise ResourceError("ATOM_OVERLAP: atoms already belong to another carrier")
        result = Carrier(carrier_id, code_id, distance, atoms)
        self._carriers[carrier_id] = result
        self._atoms.update(atoms)
        self._record("register_carrier", 0.0, carrier=result.to_dict())
        return result

    def register_logical_carrier(
        self, carrier_id: str, *, code_id: str, distance: int
    ) -> Carrier:
        """Register a logical carrier with estimated times and no atom footprint.

        Subsequent epoch, ownership and token transitions are the same state
        machine as physical carriers. Estimated exits never certify atom safety.
        """
        _name(carrier_id, "carrier_id")
        _name(code_id, "code_id")
        if type(distance) is not int or distance < 1:
            raise ResourceError("INVALID_RESOURCE_INPUT: distance must be positive")
        if carrier_id in self._carriers:
            raise ResourceError(f"DUPLICATE_CARRIER: {carrier_id!r}")
        if any(
            carrier.representation != "logical_estimate"
            for carrier in self._carriers.values()
        ):
            raise ResourceError("MIXED_RESOURCE_REPRESENTATIONS")
        result = Carrier(
            carrier_id, code_id, distance, (), representation="logical_estimate"
        )
        self._carriers[carrier_id] = result
        self._record("register_carrier", 0.0, carrier=result.to_dict())
        return result

    def begin_preparation(
        self, carrier_id: str, *, owner: str, at_us: float
    ) -> Carrier:
        """Start a fresh epoch only after explicit release and the physical exit."""
        carrier = self.carrier(carrier_id)
        _name(owner, "owner")
        at = self._at(carrier, at_us)
        if carrier.owner is not None:
            raise ResourceError(
                f"CARRIER_OWNED: {carrier_id!r} requires explicit completion"
            )
        if self._active(carrier):
            raise ResourceError(
                f"ACTIVE_TOKEN: {carrier_id!r} still protects a resource"
            )
        if at < carrier.safe_exit_at_us:
            raise ResourceError(f"CARRIER_NOT_SAFE: {carrier_id!r}")
        result = replace(
            carrier,
            epoch=carrier.epoch + 1,
            owner=owner,
            phase="preparing",
            last_at_us=at,
            safe_exit_at_us=at,
        )
        self._carriers[carrier_id] = result
        self._record(
            "begin_preparation",
            at,
            carrier_id=carrier_id,
            epoch=result.epoch,
            owner=owner,
        )
        return result

    def finish_preparation(
        self, carrier_id: str, *, owner: str, at_us: float
    ) -> Carrier:
        """Mark a token-free preparation as work after its declared physical exit.

        The caller must finish any required canonicalization before this call.
        This lifecycle transition neither applies corrections nor verifies or
        infers quantum quality. It preserves the owner, epoch and safe exit.

        Returns the new immutable carrier record. Raises ResourceError, without
        mutation, for a wrong owner, active token, non-preparing phase or unsafe
        time. Unknown carriers raise KeyError.
        """
        carrier = self.carrier(carrier_id)
        self._owner(carrier, owner)
        at = self._at(carrier, at_us)
        if self._active(carrier):
            raise ResourceError(
                f"ACTIVE_TOKEN: {carrier_id!r} still protects a resource"
            )
        if carrier.phase != "preparing":
            raise ResourceError(
                f"INVALID_PREPARATION_STATE: {carrier_id!r} is {carrier.phase!r}"
            )
        if at < carrier.safe_exit_at_us:
            raise ResourceError(f"CARRIER_NOT_SAFE: {carrier_id!r}")
        result = replace(carrier, phase="work", last_at_us=at)
        self._carriers[carrier_id] = result
        self._record(
            "finish_preparation",
            at,
            carrier_id=carrier_id,
            epoch=carrier.epoch,
            owner=owner,
        )
        return result

    def offer(
        self,
        token_id: str,
        *,
        carrier_id: str,
        epoch: int,
        owner: str,
        resource_kind: str,
        producer: str,
        ready_at_us: float,
        exit_at_us: float,
        canonicalization: str,
        quality: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> ResourceToken:
        """Declare one resource on the owned epoch, preserving supplied evidence.

        Readiness may precede physical exit. The offer is a declaration at the
        carrier's latest ledger time; it does not assert that either time passed.
        """
        carrier = self.carrier(carrier_id)
        self._owner(carrier, owner)
        for value, field in (
            (token_id, "token_id"),
            (resource_kind, "resource_kind"),
            (producer, "producer"),
            (canonicalization, "canonicalization"),
        ):
            _name(value, field)
        if (
            isinstance(epoch, bool)
            or not isinstance(epoch, int)
            or epoch != carrier.epoch
        ):
            raise ResourceError(f"STALE_EPOCH: {carrier_id!r} epoch {epoch!r}")
        if token_id in self._tokens:
            raise ResourceError(f"DUPLICATE_TOKEN: {token_id!r}")
        if self._active(carrier):
            raise ResourceError(
                f"ACTIVE_TOKEN: {carrier_id!r} already contains a resource"
            )
        ready = _time(ready_at_us, "ready_at_us")
        exit_time = _time(exit_at_us, "exit_at_us")
        if ready < carrier.last_at_us or exit_time < max(
            carrier.last_at_us, carrier.safe_exit_at_us
        ):
            raise ResourceError(
                "INVALID_SAFE_EXIT: token times precede carrier operations"
            )
        result = ResourceToken(
            token_id,
            carrier_id,
            epoch,
            resource_kind,
            producer,
            ready,
            exit_time,
            canonicalization,
            _json_evidence(quality, "quality"),
            _json_evidence(provenance, "provenance"),
        )
        self._tokens[token_id] = result
        self._carriers[carrier_id] = replace(
            carrier, phase="resource", safe_exit_at_us=exit_time
        )
        self._record("offer", carrier.last_at_us, token=result.to_dict(), owner=owner)
        return result

    def reserve(
        self,
        token_id: str,
        *,
        consumer: str,
        at_us: float,
        expected_code: str,
        expected_kind: str,
        expected_canonicalization: str,
        expected_distance: int | None = None,
    ) -> ResourceToken:
        """Reserve a ready compatible token and transfer ownership to consumer."""
        token, carrier = self._current_token(token_id)
        _name(consumer, "consumer")
        at = self._at(carrier, at_us)
        if token.status != "offered":
            raise ResourceError(f"TOKEN_NOT_AVAILABLE: {token_id!r} is {token.status}")
        if at < token.ready_at_us:
            raise ResourceError(f"TOKEN_NOT_READY: {token_id!r}")
        if (
            carrier.code_id != expected_code
            or token.resource_kind != expected_kind
            or token.canonicalization != expected_canonicalization
            or (
                expected_distance is not None
                and (
                    isinstance(expected_distance, bool)
                    or not isinstance(expected_distance, int)
                    or carrier.distance != expected_distance
                )
            )
        ):
            raise ResourceError(f"INCOMPATIBLE_RESOURCE: {token_id!r}")
        result = replace(token, status="reserved", consumer=consumer)
        self._tokens[token_id] = result
        self._carriers[carrier.carrier_id] = replace(
            carrier, owner=consumer, last_at_us=at
        )
        self._record("reserve", at, token_id=token_id, consumer=consumer)
        return result

    def consume(
        self,
        token_id: str,
        *,
        consumer: str,
        at_us: float,
        safe_exit_at_us: float,
        usage_kind: str = "consume",
    ) -> ResourceToken:
        """Consume exactly once at irreversible-use start, retaining carrier ownership.

        ``adopt`` denotes transfer into a work state rather than physical
        destruction; both usages prohibit resource reassignment and require a
        later complete_use after the declared safe exit.
        """
        token, carrier = self._current_token(token_id)
        self._owner(carrier, consumer)
        at = self._at(carrier, at_us)
        safe_exit = _time(safe_exit_at_us, "safe_exit_at_us")
        if token.status == "consumed":
            raise ResourceError(f"TOKEN_ALREADY_CONSUMED: {token_id!r}")
        if token.status != "reserved" or token.consumer != consumer:
            raise ResourceError(f"TOKEN_NOT_RESERVED: {token_id!r}")
        if usage_kind not in ("consume", "adopt"):
            raise ResourceError("INVALID_USAGE_KIND: expected consume or adopt")
        if at < max(token.ready_at_us, token.exit_at_us, carrier.safe_exit_at_us):
            raise ResourceError(f"CARRIER_NOT_SAFE: {carrier.carrier_id!r}")
        if safe_exit < at:
            raise ResourceError("INVALID_SAFE_EXIT: use exit precedes its start")
        result = replace(
            token, status="consumed", consumed_at_us=at, usage_kind=usage_kind
        )
        self._tokens[token_id] = result
        self._carriers[carrier.carrier_id] = replace(
            carrier, phase="work", last_at_us=at, safe_exit_at_us=safe_exit
        )
        self._record(
            "consume",
            at,
            token_id=token_id,
            consumer=consumer,
            usage_kind=usage_kind,
            safe_exit_at_us=safe_exit,
        )
        return result

    def discard(
        self,
        token_id: str,
        *,
        owner: str,
        at_us: float,
        safe_exit_at_us: float | None = None,
    ) -> ResourceToken:
        """Discard an unconsumed token without releasing its physical carrier."""
        token, carrier = self._current_token(token_id)
        self._owner(carrier, owner)
        at = self._at(carrier, at_us)
        if token.status not in ("offered", "reserved"):
            raise ResourceError(f"TOKEN_NOT_AVAILABLE: {token_id!r} is {token.status}")
        safe_exit = (
            carrier.safe_exit_at_us
            if safe_exit_at_us is None
            else _time(safe_exit_at_us, "safe_exit_at_us")
        )
        if safe_exit_at_us is not None and safe_exit < max(at, carrier.safe_exit_at_us):
            raise ResourceError(
                "INVALID_SAFE_EXIT: discard cannot shorten a physical exit"
            )
        result = replace(token, status="discarded", discarded_at_us=at)
        self._tokens[token_id] = result
        self._carriers[carrier.carrier_id] = replace(
            carrier, phase="work", last_at_us=at, safe_exit_at_us=safe_exit
        )
        self._record(
            "discard", at, token_id=token_id, owner=owner, safe_exit_at_us=safe_exit
        )
        return result

    def extend_use(
        self,
        carrier_id: str,
        *,
        owner: str,
        at_us: float,
        safe_exit_at_us: float,
    ) -> Carrier:
        """Record a later scheduled exit without releasing the owned carrier."""
        carrier = self.carrier(carrier_id)
        self._owner(carrier, owner)
        at = self._at(carrier, at_us)
        safe_exit = _time(safe_exit_at_us, "safe_exit_at_us")
        if self._active(carrier):
            raise ResourceError(
                f"ACTIVE_TOKEN: {carrier_id!r} must be consumed before work"
            )
        if safe_exit < max(at, carrier.safe_exit_at_us):
            raise ResourceError("INVALID_SAFE_EXIT: physical exit cannot be shortened")
        result = replace(carrier, last_at_us=at, safe_exit_at_us=safe_exit)
        self._carriers[carrier_id] = result
        self._record(
            "extend_use",
            at,
            carrier_id=carrier_id,
            owner=owner,
            safe_exit_at_us=safe_exit,
        )
        return result

    def complete_use(self, carrier_id: str, *, owner: str, at_us: float) -> Carrier:
        """End or abandon work after its safe exit, with no active token."""
        carrier = self.carrier(carrier_id)
        self._owner(carrier, owner)
        at = self._at(carrier, at_us)
        if self._active(carrier):
            raise ResourceError(
                f"ACTIVE_TOKEN: {carrier_id!r} still protects a resource"
            )
        if at < carrier.safe_exit_at_us:
            raise ResourceError(f"CARRIER_NOT_SAFE: {carrier_id!r}")
        result = replace(carrier, owner=None, phase="free", last_at_us=at)
        self._carriers[carrier_id] = result
        self._record(
            "complete_use", at, carrier_id=carrier_id, owner=owner, epoch=carrier.epoch
        )
        return result

    def snapshot(self) -> dict[str, Any]:
        """Return current records and the complete successful-transition audit."""
        return {
            "schema": "nadit.resource_ledger/2"
            if any(
                carrier.representation == "logical_estimate"
                for carrier in self._carriers.values()
            )
            else "nadit.resource_ledger/1",
            **(
                {"resource_time_basis": "logical_estimated_us"}
                if any(
                    carrier.representation == "logical_estimate"
                    for carrier in self._carriers.values()
                )
                else {}
            ),
            "carriers": [
                self._carriers[key].to_dict() for key in sorted(self._carriers)
            ],
            "tokens": [self._tokens[key].to_dict() for key in sorted(self._tokens)],
            "audit": [json.loads(event) for event in self._audit],
        }
