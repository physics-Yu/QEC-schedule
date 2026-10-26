"""One deterministic coordinator serving factories through an execution kernel."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from math import isfinite
from typing import Any

from modules.codes.contracts.factory_recipe import FactoryRecipe

from ..scheduling import ComponentNode, ComponentScheduler
from .assembly import PhysicalBundle
from .events import EventDependency, EventJournal
from .execution_kernel import (
    ExecutionBindingError,
    ExecutionKernel,
    ExecutionRequest,
    PhysicalExecutionKernel,
)
from .factory import _Stop
from .factory_process import FactoryProcess
from .physical import PhysicalContext
from .protocol_intents import (
    RESOURCE_WAIT_INSTRUMENTATION_SCHEMA,
    RESOURCE_WAIT_KINDS,
    BarrierIntent,
    CallIntent,
    FeedbackIntent,
    ParallelFlows,
    ProtocolFlow,
    ProtocolIntent,
    ResourceWaitIntent,
    RoleHandoffIntent,
    WaitIntent,
)
from .receipts import ComponentReceipt
from .resources import ResourceLedger, ResourceToken


@dataclass(frozen=True)
class CooperativeFactoryCase:
    """Line outcomes with either logical estimates or a validated physical prefix."""

    _document_json: str
    physical: PhysicalBundle | None

    @property
    def status(self) -> str:
        return str(json.loads(self._document_json)["status"])

    def to_dict(self) -> dict[str, Any]:
        document: dict[str, Any] = json.loads(self._document_json)
        document["physical"] = (
            None if self.physical is None else self.physical.to_dict()
        )
        return document

    def to_json(self) -> str:
        return json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
        )


@dataclass(eq=False)
class _Fiber:
    process: FactoryProcess
    flow: ProtocolFlow
    main: bool = False
    intent: ProtocolIntent | None = None
    children: list[_Fiber] = field(default_factory=list)
    started: bool = False
    done: bool = False
    result: Any = None
    node: ComponentNode | None = None


class CooperativeFactoryRuntime:
    """Cooperatively admit calls from every live line before expanding a wave.

    Distinct lines require disjoint carriers. All calls still run at completed
    wave boundaries; arbitrary overlap inside an in-flight component is absent.
    Feedback and safe-exit waits block their own flow. The global clock waits
    only when there is no ready call, and then only to the earliest deadline.
    Explicit recipe-stage barriers hold ready lines until their active batch
    cohort arrives. Raw retries stay local within that shared stage.
    """

    def __init__(
        self,
        physical: PhysicalContext | None = None,
        *,
        execution: ExecutionKernel | None = None,
        case_id: str,
        seed: int,
        scheduler: ComponentScheduler,
        processes: tuple[FactoryProcess, ...],
    ) -> None:
        if (physical is None) == (execution is None):
            raise ValueError("EXECUTION_ENTRY_REQUIRED: choose physical or execution")
        kernel = (
            PhysicalExecutionKernel(physical) if physical is not None else execution
        )
        assert kernel is not None
        if (
            not isinstance(processes, tuple)
            or not processes
            or any(not isinstance(p, FactoryProcess) for p in processes)
        ):
            raise ValueError(
                "INVALID_FACTORY_PROCESSES: nonempty immutable processes required"
            )
        if len({p.factory_id for p in processes}) != len(processes):
            raise ValueError("DUPLICATE_FACTORY_ID")
        if (
            kernel.used
            or scheduler.snapshot()["nodes"]
            or any(p._runtime is not None for p in processes)
        ):
            raise ValueError(
                "COOPERATIVE_RUNTIME_REUSED: fresh world and processes required"
            )
        recipes: dict[str, FactoryRecipe] = {}
        for process in processes:
            previous = recipes.setdefault(process.cohort_id, process.recipe)
            if previous != process.recipe:
                raise ValueError(
                    "INCOMPATIBLE_COHORT_RECIPES: stage barriers require the same recipe within a cohort"
                )
        ledger = ResourceLedger()
        claimed: set[str] = set()
        declarations = kernel.carriers
        for process in processes:
            carriers = set(process.roles.values())
            if claimed & carriers or not carriers <= set(declarations):
                raise ValueError("ALIASED_OR_UNKNOWN_FACTORY_CARRIERS")
            for carrier in sorted(carriers):
                declaration = declarations[carrier]
                if declaration.representation != kernel.representation:
                    raise ValueError("EXECUTION_CARRIER_REPRESENTATION_MISMATCH")
                if kernel.representation == "physical":
                    ledger.register_carrier(
                        carrier,
                        code_id=process.code,
                        distance=process.distance,
                        atom_ids=declaration.atom_ids,
                    )
                else:
                    ledger.register_logical_carrier(
                        carrier, code_id=process.code, distance=process.distance
                    )
            claimed.update(carriers)
        self.execution = kernel
        self.physical, self.case_id, self.seed, self.scheduler = (
            kernel.physical if isinstance(kernel, PhysicalExecutionKernel) else None,
            case_id,
            seed,
            scheduler,
        )
        self.processes = tuple(sorted(processes, key=lambda p: p.factory_id))
        self.ledger, self.journal = ledger, EventJournal(case_id, seed)
        self.calls: list[dict[str, Any]] = []
        self.milestones: list[dict[str, Any]] = []
        self._fibers: list[_Fiber] = []
        self._pending: dict[str, _Fiber] = {}
        self._states: dict[str, str] = {}
        self._ordinal = 0
        self._started = False
        for process in self.processes:
            process._runtime = self
            self._fibers.append(_Fiber(process, process.flow(), main=True))

    def commit_role_handoff(self, intent: RoleHandoffIntent) -> ResourceToken:
        """Atomically exchange two roles after committed mechanical delivery.

        Args:
            intent: Named producer output, consumer receiving role, current
                reserved token, free replacement and exact transport evidence.

        Returns:
            The unchanged current reserved token now addressed by the consumer role.

        Raises ValueError for stale bindings, unsafe ownership, pending old-binding
        dependencies or rejected kernel evidence. A kernel without transport-proof
        validation raises NotImplementedError. No role/ledger mutation occurs until
        all checks succeed; physical execution and role exchange are separate steps.
        """
        if not isinstance(intent, RoleHandoffIntent):
            raise TypeError("INVALID_ROLE_HANDOFF_INTENT")
        processes = {process.factory_id: process for process in self.processes}
        if intent.producer_id not in processes or intent.consumer_id not in processes:
            raise ValueError("UNKNOWN_ROLE_HANDOFF_PROCESS")
        producer, consumer = (
            processes[intent.producer_id],
            processes[intent.consumer_id],
        )
        token = self._check_handoff_resources(intent, producer, consumer)
        schedule = self.scheduler.snapshot()
        self._check_handoff_dependencies(intent, producer, consumer, schedule)
        producer_roles, consumer_roles = dict(producer.roles), dict(consumer.roles)
        producer_roles[intent.producer_role] = intent.replacement_carrier_id
        consumer_roles[intent.consumer_role] = intent.source_carrier_id
        proposed = {
            producer.factory_id: producer_roles,
            consumer.factory_id: consumer_roles,
        }
        carriers = [
            carrier
            for process in self.processes
            for carrier in proposed.get(process.factory_id, process.roles).values()
        ]
        if len(carriers) != len(set(carriers)):
            raise ValueError("ALIASED_ROLE_HANDOFF_BINDINGS")
        validate = getattr(self.execution, "validate_handoff_transport", None)
        if not callable(validate):
            raise NotImplementedError("ROLE_HANDOFF_TRANSPORT_PROOF_UNSUPPORTED")
        before = self.execution.snapshot_id
        if before != intent.expected_snapshot_id:
            raise ValueError("STALE_ROLE_HANDOFF_SNAPSHOT")
        result = validate(
            intent.transport_receipts,
            expected_snapshot_id=intent.expected_snapshot_id,
            expected_bindings=intent.expected_bindings,
        )
        if result is not None or self.execution.snapshot_id != before:
            raise ValueError("INVALID_ROLE_HANDOFF_VALIDATOR")
        # No callbacks, waits, physical execution or ledger updates during commit.
        producer.roles, consumer.roles = producer_roles, consumer_roles
        for process, role in (
            (producer, intent.producer_role),
            (consumer, intent.consumer_role),
        ):
            process._role_calls.pop(role, None)
            process._role_events.pop(role, None)
            process.mark(
                "role_handoff_committed",
                producer_id=intent.producer_id,
                consumer_id=intent.consumer_id,
                producer_role=intent.producer_role,
                consumer_role=intent.consumer_role,
                token_id=intent.token_id,
                source_carrier_id=intent.source_carrier_id,
                replacement_carrier_id=intent.replacement_carrier_id,
                transport_invocations=[
                    r.invocation_id for r in intent.transport_receipts
                ],
                execution_snapshot_id=before,
            )
        return token

    def _check_handoff_resources(
        self,
        intent: RoleHandoffIntent,
        producer: FactoryProcess,
        consumer: FactoryProcess,
    ) -> ResourceToken:
        token = self.ledger.token(intent.token_id)
        source = self.ledger.carrier(intent.source_carrier_id)
        replacement = self.ledger.carrier(intent.replacement_carrier_id)
        now = self.execution.clock_us
        if (
            producer.status not in ("pending", "running")
            or consumer.status not in ("pending", "running")
            or intent.producer_role != producer.recipe.output_role
            or producer.roles.get(intent.producer_role) != source.carrier_id
            or consumer.roles.get(intent.consumer_role) != replacement.carrier_id
            or producer.code != consumer.code
            or producer.distance != consumer.distance
            or any(
                c.code_id != producer.code
                or c.distance != producer.distance
                or c.representation != self.execution.representation
                for c in (source, replacement)
            )
            or token.carrier_id != source.carrier_id
            or token.epoch != source.epoch
            or not (
                token.producer == producer.factory_id
                or token.producer.startswith(producer.factory_id + "/")
            )
            or token.resource_kind != producer.recipe.output_resource_kind
            or token.canonicalization != "canonical"
            or token.status != "reserved"
            or token.consumer != intent.consumer_owner
            or source.owner != intent.consumer_owner
            or not (
                intent.consumer_owner == consumer.factory_id
                or intent.consumer_owner.startswith(consumer.factory_id + "/")
            )
            or source.phase != "resource"
            or replacement.phase != "free"
            or replacement.owner is not None
            or max(
                token.ready_at_us,
                token.exit_at_us,
                source.safe_exit_at_us,
                source.last_at_us,
                replacement.safe_exit_at_us,
                replacement.last_at_us,
            )
            > now
            or any(
                r.representation != self.execution.representation
                or r.results_ready_us > now
                for r in intent.transport_receipts
            )
        ):
            raise ValueError("INVALID_ROLE_HANDOFF_RESOURCES")
        source_transports = tuple(
            receipt
            for receipt in intent.transport_receipts
            if source.carrier_id in receipt.participant_blocks
        )
        # Static bindings can survive a later preparation. The supplied source
        # transport chain must therefore belong after this token's preparation.
        if not source_transports or any(
            receipt.start_us < max(token.ready_at_us, token.exit_at_us)
            for receipt in source_transports
        ):
            raise ValueError("ROLE_HANDOFF_SOURCE_TRANSPORT_NOT_CURRENT")
        declarations = self.execution.carriers
        expected = {b.block_id: b for b in intent.expected_bindings}
        for carrier in (source, replacement):
            declaration = declarations.get(carrier.carrier_id)
            if (
                declaration is None
                or declaration.representation != carrier.representation
                or (
                    carrier.representation == "physical"
                    and (
                        tuple(declaration.atom_ids) != carrier.atom_ids
                        or expected[carrier.carrier_id].atom_ids != carrier.atom_ids
                    )
                )
            ):
                raise ValueError("ROLE_HANDOFF_CARRIER_IDENTITY_MISMATCH")
        return token

    def _check_handoff_dependencies(
        self,
        intent: RoleHandoffIntent,
        producer: FactoryProcess,
        consumer: FactoryProcess,
        schedule: dict[str, Any],
    ) -> None:
        carriers = {intent.source_carrier_id, intent.replacement_carrier_id}
        finished = set(schedule["completed"]) | set(schedule["cancelled"])
        if any(
            node["id"] not in finished
            and carriers.intersection(node["spec"]["participant_blocks"])
            for node in schedule["nodes"]
        ):
            raise ValueError("ROLE_HANDOFF_PENDING_SCHEDULE")
        for fiber in self._fibers:
            if fiber.done:
                continue
            request = fiber.intent
            if isinstance(request, CallIntent) and carriers.intersection(
                fiber.process.roles.get(role) for role in request.call.participant_roles
            ):
                raise ValueError("ROLE_HANDOFF_PENDING_CALL")
            if isinstance(request, FeedbackIntent) and (
                carriers.intersection(
                    block for part in request.parts for block in part.participant_blocks
                )
                or carriers.intersection(
                    fiber.process.roles.get(role) for role in request.participant_roles
                )
            ):
                raise ValueError("ROLE_HANDOFF_PENDING_FEEDBACK")
        for process, role in (
            (producer, intent.producer_role),
            (consumer, intent.consumer_role),
        ):
            call = process._role_calls.get(role)
            if call is not None and (
                schedule["completed"].get(call, float("inf")) > self.execution.clock_us
                or call not in process._sources
                or any(
                    part.results_ready_us > self.execution.clock_us
                    for part in process._sources[call]
                )
            ):
                raise ValueError("ROLE_HANDOFF_PENDING_CALL_METADATA")
            event = process._role_events.get(role)
            if event is not None and (
                event.released_at_us > self.execution.clock_us
                or schedule["event_releases"].get(
                    process.event_key(event), float("inf")
                )
                > self.execution.clock_us
            ):
                raise ValueError("ROLE_HANDOFF_PENDING_EVENT_METADATA")

    def _state(
        self,
        process: FactoryProcess,
        state: str,
        reason: str,
        *,
        stage_key: str | None = None,
        peers: tuple[str, ...] = (),
        at_us: float | None = None,
        resource_id: str | None = None,
    ) -> None:
        reason_key = (
            reason
            if resource_id is not None and state in ("waiting_supply", "waiting_buffer")
            else None
        )
        key = json.dumps((state, stage_key, peers, resource_id, reason_key))
        if self._states.get(process.factory_id) != key:
            self._states[process.factory_id] = key
            process.mark(
                "line_state_changed",
                state=state,
                reason=reason,
                stage_key=stage_key,
                peers=list(peers),
                **({"resource_id": resource_id} if resource_id is not None else {}),
                **({"at_us": at_us} if at_us is not None else {}),
            )

    def _fail(self, process: FactoryProcess, error: Exception) -> None:
        if process.status not in ("pending", "running"):
            return
        process.status = error.code if isinstance(error, _Stop) else "protocol_failure"
        process.failure = {
            "code": process.status,
            "stage": process._stage,
            "at_us": self.execution.clock_us,
            "detail": str(error),
        }
        process.finished_at_us = self.execution.clock_us
        cancelled = tuple(
            key for key, fiber in self._pending.items() if fiber.process is process
        )
        if cancelled:
            self.scheduler.cancel_pending(cancelled, reason=process.status)
        for key in cancelled:
            del self._pending[key]
        for fiber in self._fibers:
            if fiber.process is process:
                fiber.done = True
                fiber.flow.close()
        # A failed line explicitly abandons owned work. Consumed resources keep
        # their irreversible record; only unconsumed tokens can be discarded.
        # Role bindings can lag a failed handoff. They are not authority to
        # discard a resource already reserved by another process or consumer.
        snapshot = self.ledger.snapshot()
        owned = {
            record["carrier_id"]
            for record in snapshot["carriers"]
            if record["owner"] is not None
            and (
                record["owner"] == process.factory_id
                or record["owner"] == process.algorithm_scope
                or record["owner"].startswith(process.factory_id + "/")
            )
        }
        for record in snapshot["tokens"]:
            if record["carrier_id"] in owned and record["status"] in (
                "offered",
                "reserved",
            ):
                carrier = self.ledger.carrier(record["carrier_id"])
                assert carrier.owner is not None
                self.ledger.discard(
                    record["token_id"],
                    owner=carrier.owner,
                    at_us=self.execution.clock_us,
                )
        for carrier_id in sorted(owned):
            carrier = self.ledger.carrier(carrier_id)
            if carrier.owner is not None:
                self.ledger.complete_use(
                    carrier_id, owner=carrier.owner, at_us=self.execution.clock_us
                )
        self._state(process, "failed", str(error))

    def _advance(self, fiber: _Fiber, value: Any = None) -> None:
        try:
            intent = fiber.flow.send(value) if fiber.started else next(fiber.flow)
            fiber.started = True
            if not isinstance(
                intent,
                CallIntent
                | FeedbackIntent
                | WaitIntent
                | ResourceWaitIntent
                | RoleHandoffIntent
                | BarrierIntent
                | ParallelFlows,
            ):
                raise TypeError("INVALID_PROTOCOL_INTENT")
            fiber.intent, fiber.node = intent, None
        except StopIteration as result:
            fiber.done, fiber.result = True, result.value
            if fiber.main:
                fiber.process.status = "complete"
                fiber.process.finished_at_us = self.execution.clock_us
                self._state(fiber.process, "complete", "requested goal completed")
        except (ValueError, TypeError, KeyError, NotImplementedError, _Stop) as error:
            self._fail(fiber.process, error)

    def _queue(self, fiber: _Fiber, intent: CallIntent) -> None:
        process, call = fiber.process, intent.call
        if len(process.calls) >= process.limits.max_component_calls:
            raise _Stop("expansion_budget_exhausted", "Maximum component calls reached")
        if intent.invocation_id in process._sources:
            raise ValueError("DUPLICATE_PROCESS_INVOCATION")
        spec = self.execution.describe(
            process.backend,
            call,
            tuple(process.roles[r] for r in call.participant_roles),
        )
        events = process.call_events(call, intent.events)
        if intent.token is not None:
            self.scheduler.release_token(
                intent.token.token_id, intent.token.ready_at_us
            )
        node = ComponentNode(
            intent.invocation_id,
            spec,
            after_calls=tuple(
                dict.fromkeys(
                    process._role_calls[r]
                    for r in call.participant_roles
                    if r in process._role_calls
                )
            ),
            event_dependencies=tuple(process.event_key(event) for event in events),
            token_dependencies=() if intent.token is None else (intent.token.token_id,),
            # Finish accepted states before another raw attempt. Fair service
            # ordinals order ordinary calls, never outrank a ready correction.
            priority=-1
            if intent.bound_factory is not None or intent.selection is not None
            else 2 * process.last_serviced + 1,
        )
        fiber.node = self.scheduler.add(node)[0]
        self._pending[node.id] = fiber

    def _feedback(self, fiber: _Fiber, intent: FeedbackIntent) -> None:
        fiber.process._stage = intent.identity
        before = self.execution.snapshot_id
        port = intent.resolve_port()
        if before != self.execution.snapshot_id:
            raise ValueError("FEEDBACK_RESOLVER_MUTATED_PHYSICAL_CONTEXT")
        observation = self.journal.sample(
            port,
            invocation_id=intent.identity,
            attempt=intent.attempt,
            dependencies=tuple(EventDependency.from_receipt(p) for p in intent.parts),
            context=self.execution,
        )
        if before != self.execution.snapshot_id:
            raise ValueError("READY_FEEDBACK_ADVANCED_PHYSICAL_CONTEXT")
        fiber.process.observe(intent, observation)
        self.scheduler.release_event(
            fiber.process.event_key(observation), observation.released_at_us
        )
        self._advance(fiber, (port, observation))

    def _pump(self) -> None:
        changed = True
        while changed:
            changed = False
            for fiber in tuple(self._fibers):
                if fiber.done:
                    continue
                try:
                    intent = fiber.intent
                    if intent is None:
                        self._advance(fiber)
                        changed = True
                    elif isinstance(intent, ParallelFlows):
                        if not fiber.children:
                            fiber.children = [
                                _Fiber(fiber.process, flow) for flow in intent.children
                            ]
                            self._fibers.extend(fiber.children)
                            if not fiber.children:
                                self._advance(fiber, ())
                            changed = True
                        elif all(child.done for child in fiber.children):
                            results = tuple(child.result for child in fiber.children)
                            fiber.children = []
                            self._advance(fiber, results)
                            changed = True
                    elif isinstance(intent, CallIntent) and fiber.node is None:
                        self._queue(fiber, intent)
                        changed = True
                    elif isinstance(intent, RoleHandoffIntent):
                        if fiber.process.factory_id not in (
                            intent.producer_id,
                            intent.consumer_id,
                        ):
                            raise ValueError("ROLE_HANDOFF_CALLER_IS_NOT_PARTICIPANT")
                        self._advance(fiber, self.commit_role_handoff(intent))
                        changed = True
                    elif (
                        isinstance(intent, FeedbackIntent)
                        and intent.ready_at_us <= self.execution.clock_us
                    ):
                        self._feedback(fiber, intent)
                        changed = True
                    elif isinstance(intent, WaitIntent):
                        if not isfinite(intent.until_us) or intent.until_us < 0:
                            raise ValueError("INVALID_FLOW_WAIT")
                        if intent.until_us <= self.execution.clock_us:
                            self._advance(fiber)
                            changed = True
                    elif isinstance(intent, ResourceWaitIntent):
                        ready = intent.ready()
                        if type(ready) is not bool:
                            raise TypeError("INVALID_RESOURCE_WAIT_RESULT")
                        if ready:
                            self._advance(fiber)
                            changed = True
                        elif intent.exhausted is not None:
                            exhausted = intent.exhausted()
                            if type(exhausted) is not bool:
                                raise TypeError("INVALID_RESOURCE_WAIT_RESULT")
                            if exhausted:
                                raise _Stop(
                                    "external_supply_exhausted",
                                    f"{intent.resource_id}: {intent.reason}",
                                )
                except (
                    ValueError,
                    TypeError,
                    KeyError,
                    NotImplementedError,
                    _Stop,
                ) as error:
                    self._fail(fiber.process, error)
                    changed = True
            # Settle every ready event/child continuation before observing cohort
            # membership. Iteration order cannot release a next-batch singleton.
            if not changed and self._release_barriers():
                changed = True
        for process in self.processes:
            if process.status != "running":
                continue
            fibers = [f for f in self._fibers if f.process is process and not f.done]
            barrier = next(
                (f.intent for f in fibers if isinstance(f.intent, BarrierIntent)), None
            )
            if barrier is not None:
                peers = tuple(
                    p.factory_id
                    for p in self.processes
                    if self._in_cohort(p, barrier, process.cohort_id)
                )
                self._state(
                    process,
                    "waiting_peers",
                    "cohort stage barrier",
                    stage_key=self._barrier_key(barrier),
                    peers=peers,
                )
                continue
            waiting = any(isinstance(f.intent, CallIntent) for f in fibers)
            supply_wait = next(
                (f.intent for f in fibers if isinstance(f.intent, ResourceWaitIntent)),
                None,
            )
            if not waiting and supply_wait is not None:
                self._state(
                    process,
                    "waiting_" + supply_wait.wait_kind,
                    supply_wait.reason,
                    resource_id=supply_wait.resource_id,
                )
                continue
            self._state(
                process,
                "waiting_resources" if waiting else "waiting_feedback",
                "component frontier" if waiting else "source results or safe exit",
            )

    @staticmethod
    def _in_cohort(
        process: FactoryProcess, intent: BarrierIntent, cohort_id: str
    ) -> bool:
        return (
            process.status == "running"
            and process.cohort_id == cohort_id
            and process.cycle_index == intent.cycle_index
            and (
                intent.batch_index is None or process.batch_index == intent.batch_index
            )
        )

    @staticmethod
    def _barrier_key(intent: BarrierIntent) -> str:
        prefix = "" if intent.cycle_index is None else f"cycle[{intent.cycle_index}]/"
        if intent.batch_index is not None:
            prefix += f"batch[{intent.batch_index}]/"
        return prefix + intent.stage_key

    def _release_barriers(self) -> bool:
        groups: dict[tuple[str, BarrierIntent], list[_Fiber]] = {}
        for fiber in self._fibers:
            if not fiber.done and isinstance(fiber.intent, BarrierIntent):
                intent = fiber.intent
                groups.setdefault((fiber.process.cohort_id, intent), []).append(fiber)
        changed = False
        for (cohort_id, intent), fibers in groups.items():
            expected = {
                p.factory_id
                for p in self.processes
                if self._in_cohort(p, intent, cohort_id)
            }
            if {fiber.process.factory_id for fiber in fibers} != expected:
                continue
            for fiber in fibers:
                fiber.process.mark(
                    "cohort_barrier_released",
                    stage_key=self._barrier_key(intent),
                    peers=sorted(expected),
                )
                self._state(
                    fiber.process,
                    "ready",
                    "cohort stage released",
                    stage_key=self._barrier_key(intent),
                    peers=tuple(sorted(expected)),
                )
            for fiber in fibers:
                self._advance(fiber)
            changed = True
        return changed

    def _execute(self, admission: Any) -> None:
        fibers = [self._pending[node.id] for node in admission.nodes]
        participants = {fiber.process.factory_id: fiber.process for fiber in fibers}
        ledger = self.ledger.fork()
        requests = []
        start = admission.start_us
        physical_started = False
        try:
            for node, fiber in zip(admission.nodes, fibers, strict=True):
                intent, process = fiber.intent, fiber.process
                assert isinstance(intent, CallIntent)
                process._stage = intent.invocation_id
                if (
                    sum(f.process is process for f in fibers) + len(process.calls)
                    > process.limits.max_component_calls
                ):
                    raise _Stop(
                        "expansion_budget_exhausted", "Maximum component calls reached"
                    )
                if intent.transport_owner is not None:
                    self._prepare_transport_call(ledger, process, intent, start)
                elif intent.begin_preparation_owner is not None:
                    if len(intent.call.participant_roles) != 1:
                        raise ValueError("PREPARATION_REQUIRES_ONE_CARRIER")
                    ledger.begin_preparation(
                        process.roles[intent.call.participant_roles[0]],
                        owner=intent.begin_preparation_owner,
                        at_us=start,
                    )
                if intent.call.consumes_resource_role is not None:
                    token = intent.token
                    if (
                        token is None
                        or token.carrier_id
                        != process.roles[intent.call.consumes_resource_role]
                    ):
                        raise ValueError("INVALID_CONSUMPTION_TOKEN")
                    ledger.consume(
                        token.token_id,
                        consumer=str(token.consumer),
                        at_us=start,
                        safe_exit_at_us=start,
                    )
                if intent.transport_owner is None:
                    for role in intent.call.participant_roles:
                        carrier = ledger.carrier(process.roles[role])
                        if carrier.owner is None:
                            raise ValueError("UNOWNED_CARRIER")
                        ledger.extend_use(
                            carrier.carrier_id,
                            owner=carrier.owner,
                            at_us=start,
                            safe_exit_at_us=start,
                        )
                requests.append(
                    ExecutionRequest(
                        node.id,
                        process.backend,
                        intent.call,
                        tuple(process.roles[r] for r in intent.call.participant_roles),
                        intent.bound_factory,
                        intent.selection,
                    )
                )
            physical_started = True
            outputs = self.execution.execute(admission, tuple(requests))
            for fiber in fibers:
                intent, process = fiber.intent, fiber.process
                assert isinstance(intent, CallIntent)
                parts = outputs[intent.invocation_id]
                if intent.transport_owner is not None:
                    self._record_transport_call(ledger, process, intent, parts, start)
                else:
                    end = max(part.action_end_us for part in parts)
                    for role in intent.call.participant_roles:
                        carrier = ledger.carrier(process.roles[role])
                        assert carrier.owner is not None
                        ledger.extend_use(
                            carrier.carrier_id,
                            owner=carrier.owner,
                            at_us=start,
                            safe_exit_at_us=end,
                        )
        except (ValueError, TypeError, KeyError, NotImplementedError, _Stop) as error:
            failure = (
                error
                if isinstance(error, _Stop)
                else _Stop(
                    "physical_failure"
                    if self.execution.representation == "physical"
                    else "execution_failure",
                    str(error),
                )
            )
            # A binding/ledger failure identifies one line and has emitted no
            # actions. A failed merged physical validation affects the wave.
            affected: tuple[FactoryProcess, ...]
            if isinstance(error, ExecutionBindingError):
                affected = (self._pending[error.invocation_id].process,)
            else:
                affected = (
                    tuple(participants.values())
                    if physical_started
                    else (fiber.process,)
                )
                if physical_started:
                    for process in affected:
                        self._state(
                            process, "running", "admitted component wave", at_us=start
                        )
            for process in affected:
                self._fail(process, failure)
            return
        for process in participants.values():
            self._state(process, "running", "admitted component wave", at_us=start)
        self.ledger = ledger
        self.scheduler.commit_admission(admission)
        self._ordinal += 1
        for node, fiber in zip(admission.nodes, fibers, strict=True):
            intent, process = fiber.intent, fiber.process
            assert isinstance(intent, CallIntent)
            parts = outputs[node.id]
            end = max(part.action_end_us for part in parts)
            self.scheduler.mark_completed(node.id, end)
            del self._pending[node.id]
            process._sources[node.id] = parts
            record = {
                "factory_id": process.factory_id,
                "invocation_id": node.id,
                "component_id": intent.call.component_id,
                "parameters": dict(intent.call.parameters),
                "participant_roles": list(intent.call.participant_roles),
                "start_us": start,
                "end_us": end,
                "after_calls": list(node.after_calls),
                "event_dependencies": [
                    e.result.occurrence.to_dict()
                    for e in process.call_events(intent.call, intent.events)
                ],
                "part_invocations": [part.invocation_id for part in parts],
                "batch_id": admission.batch_id,
                "consumed_token_id": intent.token.token_id
                if intent.token is not None
                and intent.call.consumes_resource_role is not None
                else None,
                **(
                    {
                        "transport_owner": intent.transport_owner,
                        "mechanical_transport": True,
                    }
                    if intent.transport_owner is not None
                    else {}
                ),
            }
            process.calls.append(record)
            self.calls.append(record)
            process._role_calls.update(
                (role, node.id) for role in intent.call.participant_roles
            )
            if (
                process.algorithm_consumption is not None
                and record["consumed_token_id"] is not None
                and record["consumed_token_id"] == process._output
            ):
                process._algorithm_consumed = str(record["consumed_token_id"])
            process.last_serviced = self._ordinal
        # Resume only after all members of this atomic wave are committed.
        for fiber in fibers:
            self._state(fiber.process, "ready", "component wave completed")
            assert isinstance(fiber.intent, CallIntent)
            self._advance(fiber, outputs[fiber.intent.invocation_id])

    def _prepare_transport_call(
        self,
        ledger: ResourceLedger,
        process: FactoryProcess,
        intent: CallIntent,
        start: float,
    ) -> None:
        if not callable(getattr(self.execution, "transport_evidence", None)):
            raise NotImplementedError("TRANSPORT_EVIDENCE_HOOK_REQUIRED")
        assert intent.transport_owner is not None
        carrier = ledger.carrier(process.roles[intent.call.participant_roles[0]])
        if (
            carrier.code_id != process.code
            or carrier.distance != process.distance
            or carrier.representation != self.execution.representation
        ):
            raise ValueError("TRANSPORT_CALL_CARRIER_MISMATCH")
        if start < max(carrier.last_at_us, carrier.safe_exit_at_us):
            raise ValueError("TRANSPORT_CALL_CARRIER_NOT_SAFE")
        if carrier.phase == "resource" and intent.token is None:
            raise ValueError("TRANSPORT_CALL_ACTIVE_TOKEN_REQUIRED")
        if intent.token is not None:
            token = intent.token
            if (
                ledger.token(token.token_id) != token
                or token.carrier_id != carrier.carrier_id
                or token.epoch != carrier.epoch
                or token.status not in ("offered", "reserved")
                or carrier.phase != "resource"
                or (
                    token.status == "reserved"
                    and token.consumer != intent.transport_owner
                )
                or max(token.ready_at_us, token.exit_at_us) > start
            ):
                raise ValueError("TRANSPORT_CALL_INVALID_TOKEN")
        if carrier.owner is None:
            ledger.acquire_transport(
                carrier.carrier_id, owner=intent.transport_owner, at_us=start
            )
        elif carrier.owner != intent.transport_owner:
            raise ValueError("TRANSPORT_CALL_OWNER_MISMATCH")

    def _record_transport_call(
        self,
        ledger: ResourceLedger,
        process: FactoryProcess,
        intent: CallIntent,
        parts: tuple[ComponentReceipt, ...],
        start: float,
    ) -> None:
        assert intent.transport_owner is not None
        carrier_id = process.roles[intent.call.participant_roles[0]]
        if len(parts) != 1:
            raise ValueError("TRANSPORT_CALL_REQUIRES_SINGLE_RECEIPT")
        receipt = parts[0]
        if (
            not isinstance(receipt, ComponentReceipt)
            or receipt.component_id != "block_translation"
            or receipt.participant_blocks != (carrier_id,)
            or receipt.representation != self.execution.representation
            or receipt.start_us != start
            or receipt.action_end_us <= start
            or receipt.action_end_us > self.execution.clock_us
            or receipt.result_availability
        ):
            raise ValueError("TRANSPORT_CALL_INVALID_RECEIPT")
        before = self.execution.snapshot_id
        extract = getattr(self.execution, "transport_evidence", None)
        if not callable(extract):
            raise NotImplementedError("TRANSPORT_EVIDENCE_HOOK_REQUIRED")
        evidence = extract(receipt)
        if self.execution.snapshot_id != before:
            raise ValueError("TRANSPORT_EVIDENCE_MUTATED_EXECUTION")
        ledger.record_transport(
            carrier_id,
            owner=intent.transport_owner,
            at_us=start,
            safe_exit_at_us=receipt.action_end_us,
            evidence=evidence,
        )

    def run(self) -> CooperativeFactoryCase:
        """Run to terminal states, then finalize the selected execution evidence."""
        if self._started:
            raise ValueError("COOPERATIVE_RUNTIME_REUSED")
        self._started = True
        for process in self.processes:
            process.status = "running"
            self._state(process, "ready", "factory process started")
        while any(p.status == "running" for p in self.processes):
            self._pump()
            if not any(p.status == "running" for p in self.processes):
                break
            admission = self.scheduler.admit(
                self.execution.clock_us, snapshot_id=self.execution.snapshot_id
            )
            if admission is not None:
                self._execute(admission)
                continue
            deadlines = [
                intent.ready_at_us
                if isinstance(intent, FeedbackIntent)
                else intent.until_us
                for fiber in self._fibers
                if not fiber.done
                for intent in (fiber.intent,)
                if isinstance(intent, FeedbackIntent | WaitIntent)
                if (
                    intent.ready_at_us
                    if isinstance(intent, FeedbackIntent)
                    else intent.until_us
                )
                > self.execution.clock_us
            ]
            if not deadlines:
                for process in self.processes:
                    if process.status == "running":
                        self._fail(
                            process,
                            _Stop(
                                "protocol_deadlock",
                                "No ready component or future feedback",
                            ),
                        )
                break
            self.execution.wait_until(
                min(deadlines), reason="cooperative_earliest_feedback"
            )
        status = (
            "complete"
            if all(p.status == "complete" for p in self.processes)
            else "partial_failure"
        )
        failure = None
        try:
            bundle = self.execution.finalize()
            if (
                self.execution.representation == "logical_estimate"
                and bundle is not None
            ):
                raise ValueError("LOGICAL_EXECUTION_RETURNED_PHYSICAL_BUNDLE")
        except ValueError as error:
            bundle, status = (
                None,
                "physical_failure"
                if self.execution.representation == "physical"
                else "execution_failure",
            )
            failure = {
                "code": status,
                "stage": "whole_program_validation"
                if self.execution.representation == "physical"
                else "logical_execution_finalization",
                "at_us": self.execution.clock_us,
                "detail": str(error),
            }
        document = {
            "schema": "nadit.cooperative_factory_case/1",
            "artifact_kind": "static_protocol_case",
            "case_id": self.case_id,
            "seed": self.seed,
            "status": status,
            "failure": failure,
            "factories": {p.factory_id: p.snapshot() for p in self.processes},
            "calls": self.calls,
            "milestones": self.milestones,
            "resources": self.ledger.snapshot(),
            "component_schedule": self.scheduler.snapshot(),
            **self.journal.snapshot(),
            "duration_us": self.execution.clock_us,
            "physical_execution": False,
            "full_quantum_simulation": False,
            "physical_measurement_values": "unobserved",
            "logical_success": None,
            "inventory_maintenance": "not_implemented",
            "supply_mode": "on_demand",
            "coordination_policy": "cohort_stage_barriers",
            "wait_instrumentation": {
                "schema": RESOURCE_WAIT_INSTRUMENTATION_SCHEMA,
                "resource_wait_kinds": list(RESOURCE_WAIT_KINDS),
            },
        }
        if self.execution.representation == "logical_estimate":
            document.update(
                {
                    "schema": "nadit.logical_factory_case/1",
                    "artifact_kind": "logical_estimate_case",
                    "execution_representation": "logical_estimate",
                    "physical_validation": "not_run",
                    "physical_measurement_values": "not_present",
                    "resource_time_basis": "logical_estimated_us",
                    "execution": self.execution.snapshot(),
                }
            )
        return CooperativeFactoryCase(
            json.dumps(
                document, sort_keys=True, separators=(",", ":"), allow_nan=False
            ),
            bundle,
        )
