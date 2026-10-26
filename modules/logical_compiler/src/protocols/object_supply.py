"""Progressive producer-held supply on the existing cooperative object runtime."""

from dataclasses import dataclass
from math import isfinite
from typing import Any

from modules.codes.contracts.factory_recipe import ComponentCall, ResourcePreparation

from ..estimation.kernel import ProfileExecutionKernel
from .factory import _Stop
from .factory_process import FactoryProcess
from .production import OutputHandoff
from .protocol_intents import ProtocolFlow, SupplyWaitIntent
from .resources import ResourceToken


@dataclass
class _Demand:
    process: FactoryProcess
    preparation: ResourcePreparation
    identity: str
    owner: str
    requested_at_us: float


class ObjectFactorySupply:
    """Finite published entries; committed delivery frees a slot, never the state.

    Args: capacity is positive B; parking is an explicit vacant block origin.
    Raises ValueError for invalid capacity/coordinates or incompatible resources.
    FIFO and oldest eligible demand use registration order, never future events.
    """

    def __init__(self, *, capacity: int, parking: tuple[float, float]) -> None:
        if type(capacity) is not int or capacity < 1:
            raise ValueError("INVALID_SUPPLY_CAPACITY")
        if len(parking) != 2 or any(
            type(v) not in (float, int) or not isfinite(v) for v in parking
        ):
            raise ValueError("INVALID_PARKING_POSITION")
        self.capacity, self.parking = capacity, parking
        self.producers: list[FactoryProcess] = []
        self.consumers: list[FactoryProcess] = []
        self.closed: set[str] = set()
        self.queue: list[tuple[FactoryProcess, ResourceToken]] = []
        self.pending: dict[str, str] = {}
        self.demands: list[_Demand] = []
        self.deliveries: list[dict[str, Any]] = []
        self.dispositions: dict[str, OutputHandoff] = {}
        self.published_tokens: set[str] = set()
        self.history: list[dict[str, Any]] = []
        self.waits: list[dict[str, Any]] = []
        self.parking_owner: str | None = None

    @property
    def is_closed(self) -> bool:
        """Demand closes only after all registered consumers finish their rounds."""
        return bool(self.consumers) and len(self.closed) == len(self.consumers)

    def _record(self, process: FactoryProcess, kind: str, **details: Any) -> None:
        self.history.append(
            {
                "at_us": process.execution.clock_us,
                "kind": kind,
                "queue_size": len(self.queue),
                "pending": dict(self.pending),
                "parking_owner": self.parking_owner,
                **details,
            }
        )

    def close(self, process: FactoryProcess) -> None:
        """Close one consumer's demand, retaining any surplus producer state."""
        if process not in self.consumers or any(
            d.process is process for d in self.demands
        ):
            raise ValueError("INVALID_SUPPLY_CLOSURE")
        self.closed.add(process.factory_id)
        self._record(process, "demand_closed", consumer=process.factory_id)

    def gate(self, process: FactoryProcess) -> ProtocolFlow:
        """Start a fresh producer round only with outstanding current demand."""
        start = process.execution.clock_us
        yield SupplyWaitIntent(
            lambda: self.is_closed or bool(self.demands), "producer_waiting_demand"
        )
        self.waits.append(
            {
                "factory_id": process.factory_id,
                "kind": "producer_waiting_demand",
                "start_us": start,
                "end_us": process.execution.clock_us,
            }
        )
        return not self.is_closed

    def __call__(self, process: FactoryProcess, token: ResourceToken) -> ProtocolFlow:
        """Retain an output through queue admission and costed delivery."""
        if (
            process not in self.producers
            or token.token_id in self.published_tokens
            or process.factory_id in self.pending.values()
            or any(p is process for p, _ in self.queue)
        ):
            raise ValueError("INVALID_OR_DUPLICATE_SUPPLY_PUBLICATION")
        current = process.ledger.token(token.token_id)
        if current != token or current.status != "offered":
            raise ValueError("INVALID_SUPPLY_TOKEN_STATE")
        self.published_tokens.add(token.token_id)
        self.pending[token.token_id] = process.factory_id
        start = process.execution.clock_us
        self._record(process, "pending_publication", token_id=token.token_id)
        yield SupplyWaitIntent(
            lambda: self.is_closed or len(self.queue) < self.capacity,
            "producer_buffer_full",
        )
        if not self.is_closed:
            del self.pending[token.token_id]
            self.queue.append((process, token))
            self._record(process, "published", token_id=token.token_id)
            yield SupplyWaitIntent(
                lambda: self.is_closed or token.token_id in self.dispositions,
                "producer_output_handoff",
            )
        if token.token_id not in self.dispositions:
            self.queue = [(p, t) for p, t in self.queue if t.token_id != token.token_id]
            self.pending.pop(token.token_id, None)
            carrier = process.ledger.carrier(token.carrier_id)
            assert carrier.owner is not None
            self.dispositions[token.token_id] = OutputHandoff(
                token.token_id,
                token.carrier_id,
                carrier.owner,
                token.ready_at_us,
                process.execution.clock_us,
                (),
                retained=True,
            )
            self._record(process, "surplus_retained", token_id=token.token_id)
        self.waits.append(
            {
                "factory_id": process.factory_id,
                "kind": "producer_output_backpressure",
                "start_us": start,
                "end_us": process.execution.clock_us,
            }
        )
        return self.dispositions[token.token_id]

    def _eligible(self, demand: _Demand) -> bool:
        if self.is_closed:
            raise _Stop("supply_closed", demand.identity)
        if not self.queue:
            if all(p.status not in ("pending", "running") for p in self.producers):
                raise _Stop(
                    "input_supply_exhausted",
                    f"demand={demand.identity}; producers="
                    f"{[(p.factory_id, p.status, p._stage) for p in self.producers]}",
                )
            return False
        if self.parking_owner is not None:
            return False
        for candidate in self.demands:
            carrier = candidate.process.ledger.carrier(
                candidate.process.roles[candidate.preparation.role]
            )
            if (
                carrier.owner is None
                and carrier.safe_exit_at_us <= candidate.process.execution.clock_us
            ):
                return candidate is demand
        return False

    def prepare(
        self,
        process: FactoryProcess,
        preparation: ResourcePreparation,
        scope: str,
        owner: str,
    ) -> ProtocolFlow:
        """Deliver one accepted state, adopting work or reserving a later injection."""
        if process not in self.consumers or preparation.ownership not in (
            "adopt",
            "reserve",
        ):
            raise ValueError("INVALID_EXTERNAL_RESOURCE_DEMAND")
        demand = _Demand(
            process,
            preparation,
            f"{scope}/{preparation.key}",
            owner,
            process.execution.clock_us,
        )
        if any(d.identity == demand.identity for d in self.demands):
            raise ValueError("DUPLICATE_SUPPLY_DEMAND")
        self.demands.append(demand)
        process._stage = demand.identity
        self._record(process, "demand_registered", demand=demand.identity)
        yield SupplyWaitIntent(
            lambda: self._eligible(demand), f"consumer_input:{demand.identity}"
        )
        producer, offered = self.queue[0]
        validate_quality = getattr(process.backend, "validate_supplied_quality", None)
        if not callable(validate_quality):
            raise TypeError("SUPPLY_QUALITY_VALIDATOR_REQUIRED")
        validate_quality(offered, producer.backend)
        execution = process.execution
        if not isinstance(execution, ProfileExecutionKernel):
            raise TypeError("OBJECT_SUPPLY_REQUIRES_PROFILE_EXECUTION")
        token = process.ledger.reserve(
            offered.token_id,
            consumer=owner,
            at_us=process.execution.clock_us,
            expected_code=process.code,
            expected_kind=str(preparation.resource_kind),
            expected_canonicalization="canonical",
            expected_distance=process.distance,
        )
        receiver = process.roles[preparation.role]
        output = token.carrier_id
        if producer.roles[producer.recipe.output_role] != output:
            raise ValueError("STALE_PRODUCER_OUTPUT_BINDING")
        process.ledger.claim_transport(
            receiver, owner=demand.identity, at_us=process.execution.clock_us
        )
        self.parking_owner = demand.identity
        profile = execution.profile
        source = profile._patches[output].origin
        destination = profile._patches[receiver].origin
        start = process.execution.clock_us
        self.waits.append(
            {
                "factory_id": process.factory_id,
                "kind": "consumer_starvation",
                "demand": demand.identity,
                "start_us": demand.requested_at_us,
                "end_us": start,
            }
        )
        self._record(
            process, "exchange_started", token_id=token.token_id, demand=demand.identity
        )
        receipts = []
        for leg, (block, target) in enumerate(
            (
                (receiver, self.parking),
                (output, (destination.x, destination.y)),
                (receiver, (source.x, source.y)),
            )
        ):
            call = ComponentCall(
                f"leg[{leg}]",
                "block_delivery",
                (),
                parameters=(
                    ("x", target[0]),
                    ("y", target[1]),
                    ("version", profile.versions[block]),
                ),
            )
            parts = yield from process._call(
                call, demand.identity + "/delivery", transport_blocks=(block,)
            )
            receipt = parts[0]
            execution.commit_transport(receipt.invocation_id)
            receipts.append(receipt.invocation_id)
            self._record(
                process,
                "leg_completed",
                token_id=token.token_id,
                receipt_id=receipt.invocation_id,
                carrier_id=block,
            )
        process.ledger.complete_use(
            receiver, owner=demand.identity, at_us=process.execution.clock_us
        )
        process.roles[preparation.role] = output
        producer.roles[producer.recipe.output_role] = receiver
        # Both roles depend on the completed exchange; carrier IDs never change.
        process._role_calls[preparation.role] = receipts[-1]
        producer._role_calls[producer.recipe.output_role] = receipts[-1]
        if preparation.ownership == "adopt":
            token = process.ledger.consume(
                token.token_id,
                consumer=owner,
                at_us=process.execution.clock_us,
                safe_exit_at_us=process.execution.clock_us,
                usage_kind="adopt",
            )
        self.queue.pop(0)
        self.demands.remove(demand)
        self.parking_owner = None
        self.dispositions[token.token_id] = OutputHandoff(
            token.token_id,
            output,
            owner,
            token.ready_at_us,
            process.execution.clock_us,
            tuple(receipts),
        )
        self.deliveries.append(
            {
                "token_id": token.token_id,
                "carrier_id": output,
                "epoch": token.epoch,
                "producer": producer.factory_id,
                "consumer": process.factory_id,
                "round": process.cycle_index,
                "role": preparation.role,
                "ownership": preparation.ownership,
                "demand": demand.identity,
                "start_us": start,
                "end_us": process.execution.clock_us,
                "receipt_ids": receipts,
                "quality": token.quality,
                "provenance": token.provenance,
            }
        )
        self._record(
            process,
            "delivery_committed",
            token_id=token.token_id,
            demand=demand.identity,
        )
        return token

    def lineage(self, process: FactoryProcess) -> dict[str, Any]:
        """Attach the current round's delivered input identities to its output."""
        return {
            "input_token_ids": [
                d["token_id"]
                for d in self.deliveries
                if d["consumer"] == process.factory_id
                and d["round"] == process.cycle_index
            ]
        }

    def snapshot(self) -> dict[str, Any]:
        """Export bounded inventory, deliveries, lineage and wait diagnostics."""
        return {
            "capacity": self.capacity,
            "parking": list(self.parking),
            "parking_owner": self.parking_owner,
            "queue": [t.token_id for _, t in self.queue],
            "pending": dict(self.pending),
            "unmet_demands": [d.identity for d in self.demands],
            "closed": sorted(self.closed),
            "deliveries": self.deliveries,
            "history": self.history,
            "waits": self.waits,
        }
