"""Execution boundary for the shared factory state machine and coordinator.

Only PhysicalExecutionKernel binds atom components. A logical implementation
provides receipts from a declared model, without impersonating physical state.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.contracts.factory_recipe import ComponentCall
from modules.codes.contracts.parallel import ComponentExecutionSpec

from ..scheduling import Admission
from .assembly import PhysicalBundle
from .events import EventDependency, EventObservation
from .parallel_physical import PhysicalBatchRequest
from .physical import PhysicalContext
from .receipts import ComponentReceipt, ExecutionCarrier, Representation


class ProtocolBackend(Protocol):
    """Protocol probability/quality surface; no atom binding requirement."""

    def resolve_event(
        self, selector: str, parameters: Mapping[str, Any] | None = None
    ) -> ProbabilityPort: ...
    def preparation_quality(
        self, preparation: str, parameters: Mapping[str, Any] | None = None
    ) -> dict[str, Any]: ...
    def output_quality(self, factory_port: ProbabilityPort) -> dict[str, Any]: ...


@dataclass(frozen=True)
class CorrectionPlan:
    bound_factory: Callable[[], Any] | None = None
    selection: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ExecutionRequest:
    invocation_id: str
    backend: Any
    call: ComponentCall
    participant_blocks: tuple[str, ...]
    bound_factory: Callable[[], Any] | None = None
    selection: Mapping[str, Any] | None = None


class ExecutionBindingError(ValueError):
    """Identify a failed pre-execution request without stopping unrelated lines."""

    def __init__(self, invocation_id: str, detail: str) -> None:
        super().__init__(detail)
        self.invocation_id = invocation_id


class ExecutionKernel(Protocol):
    representation: Representation

    @property
    def carriers(self) -> Mapping[str, ExecutionCarrier]: ...
    @property
    def clock_us(self) -> float: ...
    @property
    def snapshot_id(self) -> str: ...
    @property
    def used(self) -> bool: ...
    def describe(
        self, backend: Any, call: ComponentCall, participant_blocks: tuple[str, ...]
    ) -> ComponentExecutionSpec: ...
    def execute(
        self, admission: Admission, requests: tuple[ExecutionRequest, ...]
    ) -> dict[str, tuple[ComponentReceipt, ...]]: ...
    def source(self, invocation_id: str) -> Any: ...
    def event_parts(
        self, receipts: tuple[ComponentReceipt, ...]
    ) -> tuple[Any, ...]: ...
    def correction_plan(
        self,
        backend: Any,
        preparation: str,
        source: Any,
        port: ProbabilityPort,
        observation: EventObservation,
        *,
        event_id: str,
    ) -> CorrectionPlan: ...
    def wait_until(self, time_us: float, *, reason: str) -> None: ...
    def finalize(self) -> PhysicalBundle | None: ...
    def snapshot(self) -> dict[str, Any]: ...


class PhysicalExecutionKernel:
    """Thin adapter preserving native sources, clocks and serialized artifacts."""

    representation: Representation = "physical"

    def __init__(self, physical: PhysicalContext) -> None:
        self.physical = physical
        self._parts: dict[str, Any] = {}

    @property
    def carriers(self) -> Mapping[str, ExecutionCarrier]:
        return {
            key: ExecutionCarrier(key, "physical", binding.atom_ids)
            for key, binding in self.physical.bindings.items()
        }

    @property
    def clock_us(self) -> float:
        return self.physical.clock_us

    @property
    def snapshot_id(self) -> str:
        return self.physical.snapshot_id

    @property
    def used(self) -> bool:
        return bool(self.physical.invocations)

    def describe(
        self, backend: Any, call: ComponentCall, participant_blocks: tuple[str, ...]
    ) -> ComponentExecutionSpec:
        describe = getattr(backend, "describe_execution", None)
        if not callable(describe):
            raise TypeError("COMPONENT_DECLARATION_REQUIRED")
        result: ComponentExecutionSpec = describe(
            call.component_id,
            tuple(self.physical.bindings[block] for block in participant_blocks),
            call.parameters,
        )
        return result

    def execute(
        self, admission: Admission, requests: tuple[ExecutionRequest, ...]
    ) -> dict[str, tuple[ComponentReceipt, ...]]:
        if tuple(request.invocation_id for request in requests) != admission.node_ids:
            raise ValueError("EXECUTION_ADMISSION_MEMBERS_DIFFER")
        bound_requests = []
        for node, request in zip(admission.nodes, requests, strict=True):
            try:
                if request.selection is not None:
                    raise ValueError(
                        "PHYSICAL_EXECUTION_REQUIRES_NATIVE_CORRECTION_PLAN"
                    )
                bound = (
                    request.bound_factory()
                    if request.bound_factory is not None
                    else request.backend.bind_call(
                        request.call.component_id,
                        tuple(
                            self.physical.bindings[block]
                            for block in request.participant_blocks
                        ),
                        request.call.parameters,
                    )
                )
                if bound.result_count != node.spec.result_count:
                    raise ValueError("RESULT_DECLARATION_MISMATCH")
                bound_requests.append(
                    PhysicalBatchRequest(node.id, bound, bound.result_count)
                )
            except (ValueError, TypeError, KeyError, NotImplementedError) as error:
                raise ExecutionBindingError(
                    request.invocation_id, str(error)
                ) from error
        if len(bound_requests) == 1:
            bound_request = bound_requests[0]
            outputs = {
                bound_request.invocation_id: self.physical.invoke(
                    bound_request.bound,
                    bound_request.invocation_id,
                    bound_request.result_count,
                    not_before_us=admission.start_us,
                )
            }
        else:
            outputs = dict(
                self.physical.invoke_batch(
                    admission, tuple(bound_requests)
                ).member_parts
            )
        receipts: dict[str, tuple[ComponentReceipt, ...]] = {}
        new_parts = {}
        declared = {
            request.invocation_id: request.participant_blocks for request in requests
        }
        component_ids = {
            request.invocation_id: request.call.component_id for request in requests
        }
        for identity, parts in outputs.items():
            items = []
            for part in parts:
                dependency = EventDependency.from_expansion(part)
                blocks = (
                    tuple(
                        binding.block_id
                        for binding in (
                            getattr(part, "participant_bindings", ())
                            or (part.exit_binding,)
                        )
                        if binding is not None
                    )
                    or declared[identity]
                )
                component_id = part.description.component_id or component_ids[identity]
                items.append(
                    ComponentReceipt(
                        part.invocation_id,
                        component_id,
                        blocks,
                        part.start_us,
                        part.action_end_us,
                        part.results_ready_us,
                        dependency.results,
                        "physical",
                    )
                )
                new_parts[part.invocation_id] = part
            receipts[identity] = tuple(items)
        self._parts.update(new_parts)
        return receipts

    def source(self, invocation_id: str) -> Any:
        return self.physical.source(invocation_id)

    def event_parts(self, receipts: tuple[ComponentReceipt, ...]) -> tuple[Any, ...]:
        return tuple(self._parts[receipt.invocation_id] for receipt in receipts)

    def correction_plan(
        self,
        backend: Any,
        preparation: str,
        source: Any,
        port: ProbabilityPort,
        observation: EventObservation,
        *,
        event_id: str,
    ) -> CorrectionPlan:
        decision = backend.correction_decision(
            source,
            event_id=event_id,
            probability_port=port,
            values=observation.values,
            available_at_us=observation.released_at_us,
        )
        return CorrectionPlan(
            bound_factory=lambda: backend.bind_canonicalization(
                preparation, source, decision, port
            )
        )

    def wait_until(self, time_us: float, *, reason: str) -> None:
        self.physical.wait_until(time_us, reason=reason)

    def finalize(self) -> PhysicalBundle:
        return self.physical.finalize()

    def snapshot(self) -> dict[str, Any]:
        return {}
