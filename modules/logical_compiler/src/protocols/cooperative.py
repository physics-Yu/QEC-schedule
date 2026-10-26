"""One deterministic coordinator serving factories through an execution kernel."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from math import isfinite
from typing import Any

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
    BarrierIntent,
    CallIntent,
    FeedbackIntent,
    ParallelPreparations,
    ProtocolFlow,
    ProtocolIntent,
    WaitIntent,
)
from .resources import ResourceLedger


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
        if any(p.recipe != processes[0].recipe for p in processes):
            raise ValueError(
                "INCOMPATIBLE_COHORT_RECIPES: stage barriers require the same recipe"
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

    def _state(
        self,
        process: FactoryProcess,
        state: str,
        reason: str,
        *,
        stage_key: str | None = None,
        peers: tuple[str, ...] = (),
        at_us: float | None = None,
    ) -> None:
        key = json.dumps((state, stage_key, peers))
        if self._states.get(process.factory_id) != key:
            self._states[process.factory_id] = key
            process.mark(
                "line_state_changed",
                state=state,
                reason=reason,
                stage_key=stage_key,
                peers=list(peers),
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
        for record in self.ledger.snapshot()["tokens"]:
            if record["carrier_id"] in process.roles.values() and record["status"] in (
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
        for carrier_id in process.roles.values():
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
                | BarrierIntent
                | ParallelPreparations,
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
                    elif isinstance(intent, ParallelPreparations):
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
                    if p.status == "running" and p.batch_index == barrier.batch_index
                )
                self._state(
                    process,
                    "waiting_peers",
                    "cohort stage barrier",
                    stage_key=f"batch[{barrier.batch_index}]/{barrier.stage_key}",
                    peers=peers,
                )
                continue
            waiting = any(isinstance(f.intent, CallIntent) for f in fibers)
            self._state(
                process,
                "waiting_resources" if waiting else "waiting_feedback",
                "component frontier" if waiting else "source results or safe exit",
            )

    def _release_barriers(self) -> bool:
        groups: dict[tuple[int, str], list[_Fiber]] = {}
        for fiber in self._fibers:
            if not fiber.done and isinstance(fiber.intent, BarrierIntent):
                intent = fiber.intent
                groups.setdefault((intent.batch_index, intent.stage_key), []).append(
                    fiber
                )
        changed = False
        for (batch, stage), fibers in groups.items():
            expected = {
                p.factory_id
                for p in self.processes
                if p.status == "running" and p.batch_index == batch
            }
            if {fiber.process.factory_id for fiber in fibers} != expected:
                continue
            for fiber in fibers:
                fiber.process.mark(
                    "cohort_barrier_released",
                    stage_key=f"batch[{batch}]/{stage}",
                    peers=sorted(expected),
                )
                self._state(
                    fiber.process,
                    "ready",
                    "cohort stage released",
                    stage_key=f"batch[{batch}]/{stage}",
                    peers=tuple(sorted(expected)),
                )
            for fiber in fibers:
                self._advance(fiber)
            changed = True
        return changed

    def _execute(self, admission: Any) -> None:
        fibers = [self._pending[node.id] for node in admission.nodes]
        participants = {fiber.process.factory_id: fiber.process for fiber in fibers}
        ledger = deepcopy(self.ledger)
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
                if intent.begin_preparation_owner is not None:
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
        for fiber in fibers:
            intent, process = fiber.intent, fiber.process
            assert isinstance(intent, CallIntent)
            end = max(part.action_end_us for part in outputs[intent.invocation_id])
            for role in intent.call.participant_roles:
                carrier = ledger.carrier(process.roles[role])
                assert carrier.owner is not None
                ledger.extend_use(
                    carrier.carrier_id,
                    owner=carrier.owner,
                    at_us=start,
                    safe_exit_at_us=end,
                )
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
            }
            process.calls.append(record)
            self.calls.append(record)
            process._role_calls.update(
                (role, node.id) for role in intent.call.participant_roles
            )
            if (
                record["consumed_token_id"] is not None
                and record["consumed_token_id"] == process._output
            ):
                process._algorithm_consumed = str(record["consumed_token_id"])
            process.last_serviced = self._ordinal
        # Resume only after all members of this atomic wave are committed.
        for fiber in fibers:
            self._state(fiber.process, "ready", "component wave completed")
            assert isinstance(fiber.intent, CallIntent)
            self._advance(fiber, outputs[fiber.intent.invocation_id])

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
