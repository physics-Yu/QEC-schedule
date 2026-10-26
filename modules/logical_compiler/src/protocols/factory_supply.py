"""Bounded same-distance factory supply through existing mechanical intents.

Inventory stays on producer carriers. A single parking lease protects the
three-hop exchange; this module neither schedules atoms nor changes quality.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from modules.codes.contracts.component import ComponentBinding
from modules.codes.contracts.factory_recipe import ComponentCall, ResourcePreparation

from .factory import _Stop
from .production import OutputHandoff, OutputRetention
from .protocol_intents import (
    CallIntent,
    ProtocolFlow,
    ResourceWaitIntent,
    RoleHandoffIntent,
)
from .receipts import ComponentReceipt
from .resources import ResourceLedger, ResourceToken
from .supply import TokenBuffer

if TYPE_CHECKING:
    from .factory_process import FactoryProcess


def _active(process: FactoryProcess) -> bool:
    return process.status in ("pending", "running")


@dataclass(eq=False)
class _Output:
    process: FactoryProcess
    token: ResourceToken
    record: dict[str, Any]
    reservation: str
    transfer: _Transfer | None = None
    published: bool = False


@dataclass(eq=False)
class _Demand:
    process: FactoryProcess
    preparation: ResourcePreparation
    identity: str
    owner: str


@dataclass(eq=False)
class _Transfer:
    output: _Output
    demand: _Demand
    replacement: str
    parked: ComponentReceipt | None = None
    delivered: ComponentReceipt | None = None
    returned: ComponentReceipt | None = None
    handed_off: bool = False
    finished: bool = False


class FactorySupply:
    """FIFO accepted-token supply with finite inventory and one parking slot.

    Args:
        buffer_id: Inventory identity used in wait and audit records.
        capacity: Maximum published inventory, including claimed inputs until use.
        parking_slot: Explicit vacant transport destination for the receiver block.
        role_slots: Fixed physical destination name for each participating role.
        expected_consumption_parameters: Existing L2 model's exact input quality.
        current_bindings: Pure getter for committed physical bindings of named
            carriers, used only after all three native transport receipts exist.

    Bind processes once before running. All participants must share the runtime,
    code and distance; producer and consumer cohorts must be distinct. A capacity
    larger than the producer count does not allocate extra atoms or storage sites.
    """

    def __init__(
        self,
        buffer_id: str,
        capacity: int,
        parking_slot: str,
        role_slots: Mapping[tuple[str, str], str],
        expected_consumption_parameters: Mapping[str, Any],
        *,
        current_bindings: Callable[[tuple[str, ...]], tuple[ComponentBinding, ...]],
    ) -> None:
        self.buffer = TokenBuffer(buffer_id, capacity)
        if (
            not isinstance(parking_slot, str)
            or not parking_slot.strip()
            or not callable(current_bindings)
        ):
            raise ValueError("INVALID_FACTORY_SUPPLY_DESTINATION")
        if not isinstance(role_slots, Mapping) or any(
            not isinstance(key, tuple)
            or len(key) != 2
            or any(
                not isinstance(value, str) or not value.strip()
                for value in (*key, slot)
            )
            for key, slot in role_slots.items()
        ):
            raise ValueError("INVALID_FACTORY_SUPPLY_ROLE_SLOTS")
        if parking_slot in role_slots.values() or len(set(role_slots.values())) != len(
            role_slots
        ):
            raise ValueError("ALIASED_FACTORY_SUPPLY_SLOTS")
        if (
            not isinstance(expected_consumption_parameters, Mapping)
            or not expected_consumption_parameters
        ):
            raise ValueError("EXPLICIT_FACTORY_SUPPLY_QUALITY_REQUIRED")
        self._quality = json.dumps(
            dict(expected_consumption_parameters),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        self.parking_slot, self.role_slots = parking_slot, dict(role_slots)
        self.current_bindings = current_bindings
        self.producers: tuple[FactoryProcess, ...] = ()
        self.consumers: tuple[FactoryProcess, ...] = ()
        self._waiting: dict[str, _Output] = {}
        self._published: dict[str, _Output] = {}
        self._demands: dict[str, _Demand] = {}
        self._demand_ids: set[str] = set()
        self._parking: _Transfer | None = None
        self._failure: str | None = None
        self._history: list[dict[str, Any]] = []
        self._retained: list[str] = []
        self._counts = {
            "published": 0,
            "claimed": 0,
            "handed_off": 0,
            "supplied": 0,
            "reclaimed": 0,
        }

    def bind_processes(
        self, producers: Sequence[FactoryProcess], consumers: Sequence[FactoryProcess]
    ) -> None:
        """Bind actual factories once without registering or copying resources."""
        if self.producers or self.consumers or not producers or not consumers:
            raise ValueError("FACTORY_SUPPLY_REQUIRES_ONE_NONEMPTY_BINDING")
        all_processes = tuple(producers) + tuple(consumers)
        if len({p.factory_id for p in all_processes}) != len(all_processes):
            raise ValueError("ALIASED_FACTORY_SUPPLY_PROCESSES")
        if len({(p.code, p.distance) for p in all_processes}) != 1:
            raise ValueError("FACTORY_SUPPLY_REQUIRES_SAME_CODE_AND_DISTANCE")
        if {p.cohort_id for p in producers} & {p.cohort_id for p in consumers}:
            raise ValueError("FACTORY_SUPPLY_LEVELS_REQUIRE_DISTINCT_COHORTS")
        required = {(p.factory_id, p.recipe.output_role) for p in producers}
        required.update(
            (p.factory_id, preparation.role)
            for p in consumers
            for preparation in (
                *p.recipe.initial_preparations,
                *(r.preparation for r in p.recipe.rotations),
            )
            if preparation.resource_kind is not None
        )
        if not required <= self.role_slots.keys():
            raise ValueError("FACTORY_SUPPLY_ROLE_SLOT_MISSING")
        self.producers, self.consumers = tuple(producers), tuple(consumers)

    def _context(
        self, process: FactoryProcess, participants: tuple[FactoryProcess, ...]
    ) -> None:
        if process not in participants or not self.producers or not self.consumers:
            raise ValueError("UNKNOWN_FACTORY_SUPPLY_PROCESS")
        if any(
            p.execution is not process.execution or p.ledger is not process.ledger
            for p in (*self.producers, *self.consumers)
        ):
            raise ValueError("FACTORY_SUPPLY_REQUIRES_ONE_RUNTIME_WORLD")

    def production_continuation(self, process: FactoryProcess) -> bool:
        """Read-only stop policy: no further cycle after downstream termination."""
        self._context(process, self.producers)
        return self._failure is None and any(_active(p) for p in self.consumers)

    def _check_quality(
        self, process: FactoryProcess, token: ResourceToken, kind: str
    ) -> None:
        carrier = process.ledger.carrier(token.carrier_id)
        quality = token.quality
        parameters = quality.get("consumption_parameters")
        if (
            process.ledger.token(token.token_id) != token
            or token.epoch != carrier.epoch
            or carrier.code_id != process.code
            or carrier.distance != process.distance
            or token.canonicalization != "canonical"
            or token.resource_kind != kind
            or quality.get("status") in ("unsupported", "unknown")
            or not isinstance(parameters, dict)
            or json.dumps(
                parameters, sort_keys=True, separators=(",", ":"), allow_nan=False
            )
            != self._quality
        ):
            raise _Stop(
                "unsupported_resource_quality",
                "Factory input differs from the configured accepted L1 quality",
            )

    def _reclaimable(self, ledger: ResourceLedger, now: float) -> tuple[str, ...]:
        result = []
        for token_id in self._published:
            token = ledger.token(token_id)
            carrier = ledger.carrier(token.carrier_id)
            if (
                token.status in ("consumed", "discarded")
                and max(carrier.safe_exit_at_us, carrier.last_at_us) <= now
            ):
                result.append(token_id)
        return tuple(result)

    def _reap(self, ledger: ResourceLedger, now: float) -> None:
        for token_id in self._reclaimable(ledger, now):
            self.buffer.remove(token_id, ledger=ledger, at_us=now)
            del self._published[token_id]
            self._counts["reclaimed"] += 1

    def _downstream_done(self) -> bool:
        return not any(_active(p) for p in self.consumers)

    def _raise_failure(self) -> None:
        if self._failure is not None:
            raise _Stop("supply_delivery_failed", self._failure)

    def _retain(self, output: _Output) -> OutputRetention:
        process, token = output.process, output.token
        self.buffer.close(at_us=process.execution.clock_us)
        self._retained.append(token.token_id)
        owner = process.ledger.carrier(token.carrier_id).owner
        if owner is None:
            raise ValueError("UNOWNED_FACTORY_SUPPLY_RETAINED_OUTPUT")
        return OutputRetention(
            token.token_id,
            token.carrier_id,
            owner,
            process.execution.clock_us,
            "all_consumers_terminal",
            {
                "scope": "producer_carrier_held_surplus",
                "physical_delivery": False,
                "quality_unchanged": True,
            },
        )

    def producer_sink(
        self, process: FactoryProcess, token: ResourceToken
    ) -> ProtocolFlow:
        """Publish a real offered output, perform its delivery hop, then acknowledge."""
        self._context(process, self.producers)
        self._check_quality(process, token, process.recipe.output_resource_kind)
        if not process.outputs or process.outputs[-1]["token_id"] != token.token_id:
            raise ValueError("FACTORY_SUPPLY_PRODUCTION_RECORD_REQUIRED")
        output = _Output(
            process,
            token,
            process.outputs[-1],
            f"{self.buffer.buffer_id}/{token.token_id}",
        )
        if token.token_id in self._waiting or token.token_id in self._published:
            raise ValueError("DUPLICATE_FACTORY_SUPPLY_OUTPUT")
        self._waiting[token.token_id] = output
        completed = False
        try:
            while not output.published:
                self._reap(process.ledger, process.execution.clock_us)
                self._raise_failure()
                if self._downstream_done():
                    completed = True
                    return self._retain(output)
                if (
                    next(iter(self._waiting)) == token.token_id
                    and self.buffer.available_capacity
                ):
                    owner = process.ledger.carrier(token.carrier_id).owner
                    if owner is None:
                        raise ValueError("UNOWNED_FACTORY_SUPPLY_OUTPUT")
                    reserved = self.buffer.reserve_capacity(
                        output.reservation,
                        owner=owner,
                        at_us=process.execution.clock_us,
                    )
                    if not reserved:
                        raise ValueError("FACTORY_SUPPLY_CAPACITY_CHANGED")
                    try:
                        self.buffer.publish(
                            output.reservation,
                            token.token_id,
                            ledger=process.ledger,
                            at_us=process.execution.clock_us,
                        )
                    except (ValueError, TypeError, KeyError):
                        self.buffer.abort_reservation(
                            output.reservation,
                            owner=owner,
                            at_us=process.execution.clock_us,
                        )
                        raise
                    output.published = True
                    self._published[token.token_id] = output
                    del self._waiting[token.token_id]
                    self._counts["published"] += 1
                    break
                yield ResourceWaitIntent(
                    self.buffer.buffer_id,
                    "producer_buffer_backpressure",
                    lambda: (
                        self._failure is not None
                        or self._downstream_done()
                        or bool(
                            self._reclaimable(
                                process.ledger, process.execution.clock_us
                            )
                        )
                        or (
                            next(iter(self._waiting), None) == token.token_id
                            and bool(self.buffer.available_capacity)
                        )
                    ),
                    wait_kind="buffer",
                )
            while True:
                self._reap(process.ledger, process.execution.clock_us)
                self._raise_failure()
                transfer = output.transfer
                if transfer is None and self._downstream_done():
                    completed = True
                    return self._retain(output)
                if transfer is not None:
                    self._check_peers(transfer)
                    if transfer.parked is not None and transfer.delivered is None:
                        parts = yield CallIntent(
                            ComponentCall(
                                "deliver",
                                "block_translation",
                                (process.recipe.output_role,),
                                (
                                    (
                                        "destination",
                                        self.role_slots[
                                            (
                                                transfer.demand.process.factory_id,
                                                transfer.demand.preparation.role,
                                            )
                                        ],
                                    ),
                                ),
                            ),
                            f"{process.factory_id}/supply/{output.reservation}",
                            token=process.ledger.token(token.token_id),
                            transport_owner=transfer.demand.owner,
                        )
                        transfer.delivered = self._one(parts)
                    if transfer.handed_off:
                        assert transfer.delivered is not None
                        proof = getattr(process.execution, "transport_evidence", None)
                        if not callable(proof):
                            raise NotImplementedError(
                                "FACTORY_SUPPLY_TRANSPORT_PROOF_REQUIRED"
                            )
                        before = process.execution.snapshot_id
                        evidence = proof(transfer.delivered)
                        if process.execution.snapshot_id != before:
                            raise ValueError("FACTORY_SUPPLY_PROOF_MUTATED_EXECUTION")
                        completed = True
                        return OutputHandoff(
                            token.token_id,
                            token.carrier_id,
                            transfer.demand.owner,
                            process.execution.clock_us,
                            transfer.replacement,
                            process.execution.clock_us,
                            {
                                "scope": "same_distance_native_factory_supply",
                                "delivery_trace_ref": evidence["trace_sha256"],
                                "quality_model": "existing_per_token_reference_unchanged",
                            },
                        )
                yield ResourceWaitIntent(
                    self.buffer.buffer_id,
                    "producer_waiting_for_delivery_handshake",
                    lambda: (
                        self._failure is not None
                        or self._downstream_done()
                        or (
                            output.transfer is not None
                            and (
                                not _active(output.transfer.demand.process)
                                or output.transfer.handed_off
                                or (
                                    output.transfer.parked is not None
                                    and output.transfer.delivered is None
                                )
                            )
                        )
                    ),
                )
        finally:
            self._waiting.pop(token.token_id, None)
            if not completed and output.transfer is not None:
                self._fail_transfer(
                    output.transfer, "producer ended before handoff acknowledgement"
                )

    @staticmethod
    def _one(parts: Any) -> ComponentReceipt:
        if (
            not isinstance(parts, tuple)
            or len(parts) != 1
            or not isinstance(parts[0], ComponentReceipt)
        ):
            raise ValueError("FACTORY_SUPPLY_REQUIRES_ONE_TRANSPORT_RECEIPT")
        return parts[0]

    def _first_demand(self) -> _Demand | None:
        return next((d for d in self._demands.values() if _active(d.process)), None)

    def _can_start(self, demand: _Demand) -> bool:
        if self._parking is not None or self._first_demand() is not demand:
            return False
        process = demand.process
        carrier = process.ledger.carrier(process.roles[demand.preparation.role])
        return (
            carrier.phase == "free"
            and carrier.owner is None
            and max(carrier.safe_exit_at_us, carrier.last_at_us)
            <= process.execution.clock_us
            and bool(
                self.buffer.available(
                    ledger=process.ledger, at_us=process.execution.clock_us
                )
            )
        )

    def _exhausted(self, demand: _Demand) -> bool:
        return not any(
            _active(p) for p in self.producers
        ) and not self.buffer.available(
            ledger=demand.process.ledger, at_us=demand.process.execution.clock_us
        )

    def _check_peers(self, transfer: _Transfer) -> None:
        if not _active(transfer.demand.process) or (
            not _active(transfer.output.process) and not self._acknowledged(transfer)
        ):
            self._fail_transfer(transfer, "peer terminated during physical delivery")
        self._raise_failure()

    def _fail_transfer(self, transfer: _Transfer, reason: str) -> None:
        if not transfer.finished and self._failure is None:
            self._failure = f"{transfer.demand.identity}: {reason}"

    @staticmethod
    def _acknowledged(transfer: _Transfer) -> bool:
        return transfer.output.record.get("handoff_at_us") is not None

    def consumer_supplier(
        self,
        process: FactoryProcess,
        preparation: ResourcePreparation,
        identity: str,
        owner: str,
        /,
    ) -> ProtocolFlow:
        """Deliver a claimed token; return only after producer acknowledgement."""
        self._context(process, self.consumers)
        if (
            preparation.resource_kind is None
            or (process.factory_id, preparation.role) not in self.role_slots
        ):
            raise ValueError("INVALID_FACTORY_SUPPLY_PREPARATION")
        if identity in self._demand_ids:
            raise ValueError("DUPLICATE_FACTORY_SUPPLY_REQUEST")
        demand = _Demand(process, preparation, identity, owner)
        self._demands[identity] = demand
        self._demand_ids.add(identity)
        transfer = None
        try:
            while not self._can_start(demand):
                self._reap(process.ledger, process.execution.clock_us)
                self._raise_failure()
                if self._can_start(demand):
                    break
                yield ResourceWaitIntent(
                    self.buffer.buffer_id,
                    "consumer_waiting_for_accepted_input",
                    lambda: (
                        self._failure is not None
                        or self._can_start(demand)
                        or bool(
                            self._reclaimable(
                                process.ledger, process.execution.clock_us
                            )
                        )
                    ),
                    exhausted=lambda: self._exhausted(demand),
                )
            self._raise_failure()
            token_id = self.buffer.available(
                ledger=process.ledger, at_us=process.execution.clock_us
            )[0]
            output = self._published[token_id]
            token = process.ledger.token(token_id)
            self._check_quality(process, token, preparation.resource_kind)
            self.buffer.claim(
                token_id,
                ledger=process.ledger,
                consumer=owner,
                at_us=process.execution.clock_us,
                expected_code=process.code,
                expected_kind=preparation.resource_kind,
                expected_distance=process.distance,
            )
            transfer = _Transfer(output, demand, process.roles[preparation.role])
            self._parking = transfer
            output.transfer = transfer
            self._counts["claimed"] += 1
            del self._demands[identity]
            scope = f"{identity}/delivery"
            parked = yield CallIntent(
                ComponentCall(
                    "park",
                    "block_translation",
                    (preparation.role,),
                    (("destination", self.parking_slot),),
                ),
                scope,
                transport_owner=owner,
            )
            transfer.parked = self._one(parked)
            yield ResourceWaitIntent(
                self.buffer.buffer_id,
                "consumer_waiting_for_source_delivery",
                lambda: (
                    self._failure is not None
                    or transfer.delivered is not None
                    or not _active(output.process)
                ),
            )
            self._check_peers(transfer)
            returned = yield CallIntent(
                ComponentCall(
                    "replace",
                    "block_translation",
                    (preparation.role,),
                    (
                        (
                            "destination",
                            self.role_slots[
                                (
                                    output.process.factory_id,
                                    output.process.recipe.output_role,
                                )
                            ],
                        ),
                    ),
                ),
                scope,
                transport_owner=owner,
            )
            transfer.returned = self._one(returned)
            process.ledger.complete_use(
                transfer.replacement, owner=owner, at_us=process.execution.clock_us
            )
            assert transfer.delivered is not None
            receipts = (transfer.parked, transfer.delivered, transfer.returned)
            yield RoleHandoffIntent(
                output.process.factory_id,
                process.factory_id,
                output.process.recipe.output_role,
                preparation.role,
                token_id,
                owner,
                output.token.carrier_id,
                transfer.replacement,
                receipts,
                process.execution.snapshot_id,
                self.current_bindings((output.token.carrier_id, transfer.replacement)),
            )
            transfer.handed_off = True
            self._parking = None
            self._counts["handed_off"] += 1
            yield ResourceWaitIntent(
                self.buffer.buffer_id,
                "consumer_waiting_for_producer_ack",
                lambda: (
                    self._failure is not None
                    or self._acknowledged(transfer)
                    or not _active(output.process)
                ),
            )
            self._check_peers(transfer)
            if not self._acknowledged(transfer):
                raise _Stop(
                    "supply_delivery_failed",
                    "Producer did not acknowledge reserved output",
                )
            transfer.finished = True
            self._counts["supplied"] += 1
            self._history.append(
                {
                    "token_id": token_id,
                    "producer_id": output.process.factory_id,
                    "consumer_id": process.factory_id,
                    "role": preparation.role,
                    "ownership": preparation.ownership,
                    "handoff_at_us": output.record["handoff_at_us"],
                    "transport_invocations": [r.invocation_id for r in receipts],
                }
            )
            return process.ledger.token(token_id)
        finally:
            self._demands.pop(identity, None)
            if transfer is not None and not transfer.finished:
                self._fail_transfer(
                    transfer, "consumer ended before delivery acknowledgement"
                )

    def snapshot(self, *, ledger: ResourceLedger, at_us: float) -> dict[str, Any]:
        """Return inventory and handshake evidence without scanning the ledger audit."""
        return {
            "schema": "nadit.factory_supply/1",
            "buffer": self.buffer.snapshot(ledger=ledger),
            "storage": "producer-carrier-held FIFO; capacity does not allocate physical buffer carriers",
            "parking_slot": self.parking_slot,
            "parking_lease": None
            if self._parking is None
            else self._parking.demand.identity,
            "waiting_producer_outputs": list(self._waiting),
            "pending_consumer_requests": list(self._demands),
            "reclaimable_token_ids": list(self._reclaimable(ledger, at_us)),
            "retained_outputs": list(self._retained),
            "failure": self._failure,
            "counts": dict(self._counts),
            "deliveries": deepcopy(self._history),
            "expected_consumption_parameters": json.loads(self._quality),
            "quality_scope": "existing theory parameters; no quality inference from transport",
        }
