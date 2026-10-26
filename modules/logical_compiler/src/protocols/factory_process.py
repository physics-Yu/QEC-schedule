"""Resumable factory recipes with independent epochs, retries and terminal states.

Generators request work; they never invoke an atom expander or advance time.
Code-owned recipes, decisions and quality records retain their original meaning.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import asdict
from typing import TYPE_CHECKING, Any

from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.contracts.factory_recipe import (
    ComponentCall,
    EventRequest,
    FactoryRecipe,
    ResourcePreparation,
    TConsumptionRecipe,
)

from .events import EventObservation
from .execution_kernel import ExecutionKernel, ProtocolBackend
from .factory import (
    FactoryLimits,
    _Stop,
    _validate_consumption,
    _validate_recipe,
)
from .production import (
    OutputDelivery,
    OutputHandoff,
    OutputRetention,
    OutputSink,
    ProductionPolicy,
)
from .protocol_intents import (
    BarrierIntent,
    CallIntent,
    FeedbackIntent,
    ParallelFlows,
    ProtocolFlow,
    WaitIntent,
)
from .receipts import ComponentReceipt
from .resources import ResourceLedger, ResourceToken
from .supply import PreparationSupplier

if TYPE_CHECKING:
    from .cooperative import CooperativeFactoryRuntime
    from .physical import PhysicalContext


class FactoryProcess:
    """One code-selected factory, attached once to a shared cooperative runtime.

    Optional production_continuation is a caller-owned read-only demand check.
    It returns a strict bool before each new continuous cycle; False completes
    normally without altering previously delivered or retained resources.
    """

    def __init__(
        self,
        factory_id: str,
        *,
        code: str,
        recipe: FactoryRecipe,
        backend: ProtocolBackend,
        role_bindings: Mapping[str, str],
        distance: int,
        limits: FactoryLimits | None = None,
        reference_parameters: Mapping[str, Any] | None = None,
        algorithm_preparation: ResourcePreparation | None = None,
        algorithm_consumption: TConsumptionRecipe | None = None,
        production_policy: ProductionPolicy | None = None,
        output_sink: OutputSink | None = None,
        production_continuation: Callable[[FactoryProcess], bool] | None = None,
        cohort_id: str = "default",
        external_inputs: bool = False,
        preparation_supplier: PreparationSupplier | None = None,
    ) -> None:
        if (
            not isinstance(factory_id, str)
            or not factory_id.strip()
            or "/" in factory_id
        ):
            raise ValueError("INVALID_FACTORY_ID: one nonempty scope segment required")
        if not code or recipe.code_id != code:
            raise ValueError("CODE_ENTRY_MISMATCH")
        if not isinstance(cohort_id, str) or not cohort_id.strip():
            raise ValueError("INVALID_FACTORY_COHORT")
        if type(external_inputs) is not bool:
            raise TypeError("INVALID_EXTERNAL_INPUT_MODE")
        if external_inputs and not callable(preparation_supplier):
            raise ValueError("EXTERNAL_PREPARATION_SUPPLIER_REQUIRED")
        if not external_inputs and preparation_supplier is not None:
            raise ValueError("EXTERNAL_SUPPLIER_REQUIRES_EXPLICIT_INPUT_MODE")
        if (production_policy is None) != (output_sink is None):
            raise ValueError("CONTINUOUS_PRODUCTION_REQUIRES_EXPLICIT_SINK_AND_POLICY")
        if production_policy is not None and (
            not isinstance(production_policy, ProductionPolicy)
            or not callable(output_sink)
        ):
            raise TypeError("INVALID_CONTINUOUS_PRODUCTION_ENTRY")
        if production_policy is not None and algorithm_consumption is not None:
            raise ValueError("CONTINUOUS_ALGORITHM_CONSUMPTION_UNSUPPORTED")
        if production_continuation is not None:
            if production_policy is None:
                raise ValueError("PRODUCTION_CONTINUATION_REQUIRES_CONTINUOUS_POLICY")
            if not callable(production_continuation):
                raise TypeError("INVALID_PRODUCTION_CONTINUATION")
        roles = dict(role_bindings)
        if len(set(roles.values())) != len(roles):
            raise ValueError("ALIASED_FACTORY_ROLES")
        _validate_recipe(recipe, set(roles))
        if (algorithm_preparation is None) != (algorithm_consumption is None):
            raise ValueError("INVALID_ALGORITHM_ENTRY: supply both recipes")
        if algorithm_consumption is not None:
            assert algorithm_preparation is not None
            _validate_consumption(algorithm_consumption, set(roles))
            if (
                algorithm_preparation.role != algorithm_consumption.data_role
                or algorithm_consumption.magic_role != recipe.output_role
                or algorithm_preparation.resource_kind is not None
            ):
                raise ValueError("INVALID_ALGORITHM_ENTRY: incompatible roles")
        self.factory_id, self.code, self.recipe, self.backend = (
            factory_id,
            code,
            recipe,
            backend,
        )
        self.roles, self.distance = roles, distance
        self.limits = limits or FactoryLimits()
        self.parameters = deepcopy(dict(reference_parameters or {}))
        self.algorithm_preparation, self.algorithm_consumption = (
            algorithm_preparation,
            algorithm_consumption,
        )
        self.calls: list[dict[str, Any]] = []
        self.milestones: list[dict[str, Any]] = []
        self._sources: dict[str, tuple[ComponentReceipt, ...]] = {}
        self._role_calls: dict[str, str] = {}
        self._role_events: dict[str, EventObservation] = {}
        self._runtime: CooperativeFactoryRuntime | None = None
        self._stage = "entry"
        self._output: str | None = None
        self._algorithm_consumed: str | None = None
        self.status = "pending"
        self.failure: dict[str, Any] | None = None
        self.last_serviced = 0
        self.finished_at_us: float | None = None
        self.batch_index = 0
        self.production_policy, self.output_sink = production_policy, output_sink
        self.production_continuation = production_continuation
        self._production_stop_reason: str | None = None
        self.cycle_index: int | None = None
        self.outputs: list[dict[str, Any]] = []
        self.cohort_id = cohort_id
        self.external_inputs, self.preparation_supplier = (
            external_inputs,
            preparation_supplier,
        )

    @property
    def physical(self) -> PhysicalContext:
        assert self._runtime is not None
        if self._runtime.physical is None:
            raise ValueError("LOGICAL_EXECUTION_HAS_NO_PHYSICAL_CONTEXT")
        return self._runtime.physical

    @property
    def execution(self) -> ExecutionKernel:
        assert self._runtime is not None
        return self._runtime.execution

    @property
    def ledger(self) -> ResourceLedger:
        assert self._runtime is not None
        return self._runtime.ledger

    @property
    def algorithm_scope(self) -> str:
        """Return this line's stable downstream algorithm invocation namespace."""
        return self.factory_id + "/algorithm"

    @staticmethod
    def event_key(event: EventObservation) -> str:
        return json.dumps(
            event.result.occurrence.to_dict(), sort_keys=True, separators=(",", ":")
        )

    def call_events(
        self, call: ComponentCall, extra: tuple[EventObservation, ...] = ()
    ) -> tuple[EventObservation, ...]:
        events = (
            tuple(
                self._role_events[r]
                for r in call.participant_roles
                if r in self._role_events
            )
            + extra
        )
        return tuple({self.event_key(event): event for event in events}.values())

    def mark(self, kind: str, **details: Any) -> None:
        record = {
            "kind": kind,
            "factory_id": self.factory_id,
            "at_us": self.execution.clock_us,
            **({"cycle": self.cycle_index} if self.cycle_index is not None else {}),
            **details,
        }
        self.milestones.append(record)
        assert self._runtime is not None
        self._runtime.milestones.append(record)

    def observe(self, intent: FeedbackIntent, event: EventObservation) -> None:
        blocks = {block for part in intent.parts for block in part.participant_blocks}
        self._role_events.update(
            (role, event) for role, block in self.roles.items() if block in blocks
        )
        self._role_events.update((role, event) for role in intent.participant_roles)

    def _call(self, call: ComponentCall, scope: str, **kwargs: Any) -> ProtocolFlow:
        self._stage = f"{scope}/{call.key}"
        parts = yield CallIntent(call, scope, **kwargs)
        return parts

    def _event(
        self, request: EventRequest, scope: str, parameters: Mapping[str, Any]
    ) -> ProtocolFlow:
        parts = tuple(
            part
            for key in request.dependency_call_keys
            for part in self._sources[f"{scope}/{key}"]
        )
        identity = f"{scope}/{request.key}"
        self._stage = identity

        def resolve() -> ProbabilityPort:
            hook = getattr(self.backend, "resolve_event_from_sources", None)
            return (
                hook(
                    request.selector,
                    self.execution.event_parts(parts),
                    parameters,
                    event_id=identity,
                )
                if callable(hook)
                else self.backend.resolve_event(request.selector, parameters)
            )

        result = yield FeedbackIntent(
            identity, 0, parts, resolve, request.participant_roles
        )
        return result

    def _prepare(
        self, preparation: ResourcePreparation, scope: str, owner: str
    ) -> ProtocolFlow:
        identity = f"{scope}/{preparation.key}"
        if self.external_inputs and preparation.resource_kind is not None:
            return (yield from self._external_prepare(preparation, identity, owner))
        carrier_id = self.roles[preparation.role]
        for attempt in range(self.limits.raw_attempts):
            attempt_scope = f"{identity}/attempt[{attempt}]"
            parts = yield from self._call(
                ComponentCall(
                    "body",
                    preparation.component_id,
                    (preparation.role,),
                    preparation.parameters,
                ),
                attempt_scope,
                begin_preparation_owner=owner,
            )
            source = self.execution.source(attempt_scope + "/body")

            def resolve(source: Any = source) -> ProbabilityPort:
                hook = getattr(self.backend, "preparation_event", None)
                return (
                    hook(preparation.canonicalization_id, source, self.parameters)
                    if callable(hook)
                    else self.backend.resolve_event(preparation.event_selector)
                )

            port, observation = yield FeedbackIntent(identity, attempt, parts, resolve)
            accepted = observation.values.get("accepted")
            if type(accepted) is not bool:
                raise ValueError(
                    "INVALID_PREPARATION_EVENT: Boolean acceptance required"
                )
            self.mark(
                "preparation_decision",
                preparation=identity,
                attempt=attempt,
                accepted=accepted,
                carrier_id=carrier_id,
            )
            if not accepted:
                if attempt + 1 == self.limits.raw_attempts:
                    raise _Stop(
                        "input_supply_exhausted",
                        f"Preparation {identity!r} exhausted its local budget",
                    )
                self.ledger.complete_use(
                    carrier_id, owner=owner, at_us=self.execution.clock_us
                )
                continue
            return (
                yield from self._accept(
                    preparation, identity, attempt, owner, source, port, observation
                )
            )
        raise AssertionError("Finite preparation budget must return or stop")

    def _external_prepare(
        self, preparation: ResourcePreparation, identity: str, owner: str
    ) -> ProtocolFlow:
        """Admit a delivered existing token; never move, retag or prepare a replacement."""
        supplier = self.preparation_supplier
        if supplier is None:
            raise ValueError("EXTERNAL_PREPARATION_SUPPLIER_REQUIRED")
        self._stage = identity
        token = yield from supplier(self, preparation, identity, owner)
        if not isinstance(token, ResourceToken):
            raise TypeError("INVALID_EXTERNAL_RESOURCE_TOKEN")
        carrier = self.ledger.carrier(token.carrier_id)
        if (
            self.ledger.token(token.token_id) != token
            or token.carrier_id != self.roles[preparation.role]
            or carrier.code_id != self.code
            or carrier.distance != self.distance
            or token.epoch != carrier.epoch
            or token.resource_kind != preparation.resource_kind
            or token.canonicalization != "canonical"
            or token.status != "reserved"
            or token.consumer != owner
            or carrier.owner != owner
            or max(
                token.ready_at_us,
                token.exit_at_us,
                carrier.safe_exit_at_us,
                carrier.last_at_us,
            )
            > self.execution.clock_us
        ):
            raise ValueError("INCOMPATIBLE_EXTERNAL_RESOURCE")
        quality = token.quality
        if quality.get("status") in ("unsupported", "unknown") or not isinstance(
            quality.get("consumption_parameters"), dict
        ):
            raise _Stop(
                "unsupported_resource_quality",
                f"External input {token.token_id!r} has no consumption model",
            )
        if preparation.ownership == "adopt":
            token = self.ledger.consume(
                token.token_id,
                consumer=owner,
                at_us=self.execution.clock_us,
                safe_exit_at_us=self.execution.clock_us,
                usage_kind="adopt",
            )
        elif preparation.ownership != "reserve":
            raise ValueError("INVALID_EXTERNAL_PREPARATION_OWNERSHIP")
        self.mark(
            "external_input_received",
            preparation=identity,
            token_id=token.token_id,
            carrier_id=token.carrier_id,
            ownership=preparation.ownership,
        )
        return token

    def _accept(
        self,
        preparation: ResourcePreparation,
        identity: str,
        attempt: int,
        owner: str,
        source: Any,
        port: ProbabilityPort,
        observation: EventObservation,
    ) -> ProtocolFlow:
        carrier_id = self.roles[preparation.role]
        carrier = self.ledger.carrier(carrier_id)
        attempt_scope = f"{identity}/attempt[{attempt}]"
        plan = self.execution.correction_plan(
            self.backend,
            preparation.canonicalization_id,
            source,
            port,
            observation,
            event_id=f"{identity}/event[{attempt}]",
        )
        yield from self._call(
            ComponentCall(
                "canonicalize",
                preparation.canonicalization_id + "/canonicalize",
                (preparation.role,),
            ),
            attempt_scope,
            bound_factory=plan.bound_factory,
            selection=plan.selection,
        )
        self.mark(
            "preparation_canonicalized",
            preparation=identity,
            attempt=attempt,
            carrier_id=carrier_id,
            port_sha256=port.content_sha256,
        )
        if preparation.resource_kind is None:
            self.ledger.finish_preparation(
                carrier_id, owner=owner, at_us=self.execution.clock_us
            )
            return None
        hook = getattr(self.backend, "preparation_quality_from_event", None)
        quality = (
            hook(
                preparation.canonicalization_id,
                source,
                port,
                observation.values,
                self.parameters,
            )
            if callable(hook)
            else self.backend.preparation_quality(
                preparation.canonicalization_id, self.parameters
            )
        )
        token = self.ledger.offer(
            f"{attempt_scope}/resource",
            carrier_id=carrier_id,
            epoch=carrier.epoch,
            owner=owner,
            resource_kind=preparation.resource_kind,
            producer=f"{attempt_scope}/canonicalize",
            ready_at_us=self.execution.clock_us,
            exit_at_us=self.execution.clock_us,
            canonicalization="canonical",
            quality=quality,
            provenance={
                "port_sha256": port.content_sha256,
                "occurrence": observation.result.occurrence.to_dict(),
            },
        )
        if quality.get("status") in ("unsupported", "unknown") or not isinstance(
            quality.get("consumption_parameters"), dict
        ):
            raise _Stop(
                "unsupported_resource_quality",
                f"Resource {token.token_id!r} has no supported consumption model",
            )
        token = self.ledger.reserve(
            token.token_id,
            consumer=owner,
            at_us=self.execution.clock_us,
            expected_code=self.code,
            expected_kind=preparation.resource_kind,
            expected_canonicalization="canonical",
            expected_distance=self.distance,
        )
        if preparation.ownership == "adopt":
            token = self.ledger.consume(
                token.token_id,
                consumer=owner,
                at_us=self.execution.clock_us,
                safe_exit_at_us=self.execution.clock_us,
                usage_kind="adopt",
            )
        elif preparation.ownership != "reserve":
            raise ValueError("INVALID_RECIPE: unknown ownership")
        return token

    def _consume(
        self, recipe: TConsumptionRecipe, scope: str, token: ResourceToken
    ) -> ProtocolFlow:
        parameters = token.quality.get("consumption_parameters")
        if (
            token.quality.get("status") in ("unsupported", "unknown")
            or parameters is None
        ):
            raise _Stop(
                "unsupported_resource_quality",
                f"Resource {token.token_id!r} has no consumption model",
            )
        if not isinstance(parameters, dict):
            raise TypeError("INVALID_RESOURCE_QUALITY: parameters must be an object")
        yield from self._call(recipe.cx_call, scope, token=token)
        yield from self._call(recipe.mz_call, scope)
        _, observation = yield from self._event(recipe.event, scope, parameters)
        branch = next(
            (
                branch
                for branch in recipe.branches
                if branch.outcome_key == observation.result.outcome_key
            ),
            None,
        )
        if branch is None:
            raise ValueError("UNSUPPORTED_CONSUMPTION_BRANCH")
        for call in branch.calls:
            yield from self._call(call, scope, events=(observation,))
        keys = (
            recipe.cx_call.key,
            recipe.mz_call.key,
            *(call.key for call in branch.calls),
        )
        ready = max(
            part.results_ready_us
            for key in keys
            for part in self._sources[f"{scope}/{key}"]
        )
        yield WaitIntent(ready, f"consumption_complete:{scope}/{recipe.key}")
        self.mark(
            "resource_consumption_complete", token_id=token.token_id, recipe=recipe.key
        )

    def _release(self, roles: tuple[str, ...]) -> None:
        for role in roles:
            carrier = self.ledger.carrier(self.roles[role])
            if carrier.owner is not None:
                self.ledger.complete_use(
                    carrier.carrier_id,
                    owner=carrier.owner,
                    at_us=self.execution.clock_us,
                )

    def _factory(self) -> ProtocolFlow:
        for batch in range(self.limits.batches):
            self.batch_index = batch
            prefix = self.factory_id
            if self.cycle_index is not None:
                prefix += f"/cycle[{self.cycle_index}]"
            scope = f"{prefix}/batch[{batch}]"
            self.mark("batch_started", batch=batch)
            yield ParallelFlows(
                tuple(
                    self._prepare(item, scope, scope)
                    for item in self.recipe.initial_preparations
                )
            )
            self.mark(
                "initial_preparations_ready",
                roles=[item.role for item in self.recipe.initial_preparations],
            )
            yield BarrierIntent(batch, "initial_preparations_ready", self.cycle_index)
            for rotation_index, rotation in enumerate(self.recipe.rotations):
                stage = f"rotation[{rotation_index}]"
                token = yield from self._prepare(
                    rotation.preparation, scope, f"{scope}/{rotation.key}"
                )
                if token is None:
                    raise ValueError("INVALID_RECIPE: rotation requires token")
                yield BarrierIntent(batch, stage + "/raw_prepared", self.cycle_index)
                for call_index, call in enumerate(rotation.compute_calls):
                    yield from self._call(call, scope)
                    yield BarrierIntent(
                        batch, f"{stage}/compute[{call_index}]", self.cycle_index
                    )
                yield from self._consume(rotation.consumption, scope, token)
                yield BarrierIntent(
                    batch, stage + "/consumption_complete", self.cycle_index
                )
                for call_index, call in enumerate(rotation.uncompute_calls):
                    yield from self._call(call, scope)
                    yield BarrierIntent(
                        batch, f"{stage}/uncompute[{call_index}]", self.cycle_index
                    )
                self._release((rotation.preparation.role,))
                for round_index, calls in enumerate(rotation.post_rotation_rounds):
                    yield ParallelFlows(
                        tuple(self._call(call, scope) for call in calls)
                    )
                    ready = max(
                        part.results_ready_us
                        for call in calls
                        for part in self._sources[f"{scope}/{call.key}"]
                    )
                    yield WaitIntent(
                        ready,
                        f"ec_results_ready:{scope}/{rotation.key}/round[{round_index}]",
                    )
                    self.mark(
                        "ec_round_complete",
                        batch=batch,
                        rotation=rotation.key,
                        round_index=round_index,
                        call_keys=[call.key for call in calls],
                        syndrome_interpretation="unobserved_cost_only",
                    )
                    yield BarrierIntent(
                        batch,
                        f"{stage}/ec[{round_index}]",
                        self.cycle_index,
                    )
                self.mark("rotation_complete", batch=batch, rotation=rotation.key)
                yield BarrierIntent(batch, stage + "/complete", self.cycle_index)
            yield ParallelFlows(
                tuple(
                    self._call(call, scope)
                    for call in self.recipe.final_measurement_calls
                )
            )
            yield BarrierIntent(batch, "final/measurements_complete", self.cycle_index)
            port, observation = yield from self._event(
                self.recipe.final_event, scope, self.parameters
            )
            accepted = observation.values.get("accepted")
            if type(accepted) is not bool:
                raise ValueError("INVALID_FACTORY_EVENT: Boolean acceptance required")
            self.mark("batch_decision", batch=batch, accepted=accepted)
            yield BarrierIntent(batch, "final/decision", self.cycle_index)
            if not accepted:
                if batch + 1 == self.limits.batches:
                    raise _Stop(
                        "distillation_rejected",
                        "Final checks rejected the last permitted batch",
                    )
                self._role_events.update(
                    (role, observation) for role in self.recipe.retry_work_roles
                )
                self._release(self.recipe.retry_work_roles)
                continue
            for call in self.recipe.accepted_output_calls:
                yield from self._call(call, scope, events=(observation,))
            carrier = self.ledger.carrier(self.roles[self.recipe.output_role])
            token = self.ledger.offer(
                f"{scope}/output",
                carrier_id=carrier.carrier_id,
                epoch=carrier.epoch,
                owner=scope,
                resource_kind=self.recipe.output_resource_kind,
                producer=f"{scope}/{self.recipe.final_event.key}",
                ready_at_us=self.execution.clock_us,
                exit_at_us=self.execution.clock_us,
                canonicalization="canonical",
                quality=self.backend.output_quality(port),
                provenance={
                    "port_sha256": port.content_sha256,
                    "protocol_id": self.recipe.protocol_id,
                },
            )
            self._output = token.token_id
            self._release(self.recipe.released_roles)
            self.mark("factory_output_ready", token_id=token.token_id)
            return token
        raise AssertionError("Finite factory budget must return or stop")

    def flow(self) -> ProtocolFlow:
        if self.production_policy is not None:
            yield from self._production()
            return
        token = yield from self._factory()
        if self.algorithm_consumption is not None:
            assert self.algorithm_preparation is not None
            scope = self.algorithm_scope
            yield from self._prepare(self.algorithm_preparation, scope, scope)
            token = self.ledger.reserve(
                token.token_id,
                consumer=scope,
                at_us=self.execution.clock_us,
                expected_code=self.code,
                expected_kind=self.recipe.output_resource_kind,
                expected_canonicalization="canonical",
                expected_distance=self.distance,
            )
            yield from self._consume(self.algorithm_consumption, scope, token)
            self._release((self.algorithm_consumption.magic_role,))
            self.mark("algorithm_t_complete", token_id=token.token_id)

    def _production(self) -> ProtocolFlow:
        policy, sink = self.production_policy, self.output_sink
        assert policy is not None and sink is not None
        for cycle in range(policy.max_cycles):
            if (
                policy.stop_at_us is not None
                and self.execution.clock_us >= policy.stop_at_us
            ):
                return
            if self.production_continuation is not None:
                continued = self.production_continuation(self)
                if type(continued) is not bool:
                    raise TypeError("INVALID_PRODUCTION_CONTINUATION_DECISION")
                if not continued:
                    self._production_stop_reason = "caller_no_demand"
                    self.mark(
                        "production_stopped",
                        reason="caller_no_demand",
                        next_cycle=cycle,
                    )
                    return
            self.cycle_index = cycle
            self.mark("production_cycle_started")
            token = yield from self._factory()
            record = {
                "cycle": cycle,
                "batch": self.batch_index,
                "token_id": token.token_id,
                "carrier_id": token.carrier_id,
                "epoch": token.epoch,
                "code": self.code,
                "distance": self.distance,
                "quality": token.quality,
                "ready_at_us": token.ready_at_us,
                "deliverable_at_us": None,
                "consumed_at_us": None,
                "released_at_us": None,
                "delivery": None,
            }
            self.outputs.append(record)
            producer_owner = self.ledger.carrier(token.carrier_id).owner
            delivery = yield from sink(self, token)
            if isinstance(delivery, OutputHandoff):
                delivery.validate(
                    token,
                    self.ledger,
                    self.execution.clock_us,
                    output_carrier_id=self.roles[self.recipe.output_role],
                    code_id=self.code,
                    distance=self.distance,
                )
                record.update(
                    handoff_at_us=delivery.handoff_at_us,
                    replacement_carrier_id=delivery.replacement_carrier_id,
                    replacement_ready_at_us=delivery.replacement_ready_at_us,
                    handoff=delivery.to_dict(),
                )
                self.mark(
                    "factory_output_handed_off",
                    token_id=token.token_id,
                    replacement_carrier_id=delivery.replacement_carrier_id,
                    at_us=delivery.handoff_at_us,
                )
            elif isinstance(delivery, OutputDelivery):
                delivery.validate(token, self.ledger, self.execution.clock_us)
                record.update(
                    deliverable_at_us=delivery.deliverable_at_us,
                    consumed_at_us=delivery.consumed_at_us,
                    released_at_us=delivery.released_at_us,
                    delivery=delivery.to_dict(),
                )
                for kind, at_us in (
                    ("factory_output_deliverable", delivery.deliverable_at_us),
                    ("factory_output_consumed", delivery.consumed_at_us),
                    ("factory_output_released", delivery.released_at_us),
                ):
                    self.mark(kind, token_id=token.token_id, at_us=at_us)
            elif isinstance(delivery, OutputRetention):
                if producer_owner is None:
                    raise ValueError("INVALID_OUTPUT_RETENTION_PRODUCER")
                delivery.validate(
                    token,
                    self.ledger,
                    self.execution.clock_us,
                    output_carrier_id=self.roles[self.recipe.output_role],
                    producer_owner=producer_owner,
                    code_id=self.code,
                    distance=self.distance,
                )
                record.update(
                    retained_at_us=delivery.retained_at_us,
                    retention_reason=delivery.reason,
                    retention=delivery.to_dict(),
                )
                self._production_stop_reason = "retained_output"
                self.mark(
                    "factory_output_retained",
                    token_id=token.token_id,
                    at_us=delivery.retained_at_us,
                    reason=delivery.reason,
                )
                return
            else:
                raise TypeError("INVALID_OUTPUT_DELIVERY_RECEIPT")
            yield BarrierIntent(None, "complete", cycle)
            self.mark("production_cycle_completed")
        if (
            policy.stop_at_us is not None
            and self.execution.clock_us < policy.stop_at_us
        ):
            raise _Stop(
                "production_cycle_budget_exhausted",
                "Maximum production cycles reached before requested horizon",
            )

    def snapshot(self) -> dict[str, Any]:
        return {
            "factory_id": self.factory_id,
            "code": self.code,
            "cohort_id": self.cohort_id,
            "input_supply": "external" if self.external_inputs else "local_preparation",
            "status": self.status,
            "failure": self.failure,
            "recipe": asdict(self.recipe),
            "limits": asdict(self.limits),
            **(
                {"production_continuation": "caller_controlled"}
                if self.production_continuation is not None
                else {}
            ),
            **(
                {"production_stop_reason": self._production_stop_reason}
                if self._production_stop_reason is not None
                else {}
            ),
            **(
                {
                    "production_policy": asdict(self.production_policy),
                    "cycle_index": self.cycle_index,
                    "outputs": deepcopy(self.outputs),
                }
                if self.production_policy is not None
                else {}
            ),
            "reference_parameters": deepcopy(self.parameters),
            "role_bindings": dict(self.roles),
            "goal": "continuous_factory_production"
            if self.production_policy is not None
            else "factory_output"
            if self.algorithm_consumption is None
            else "factory_output_to_t",
            "calls": deepcopy(self.calls),
            "milestones": deepcopy(self.milestones),
            "output_token_id": self._output,
            "algorithm_consumed_token_id": self._algorithm_consumed,
            "finished_at_us": self.finished_at_us,
            "completed_at_us": self.finished_at_us,
            "logical_success": None,
            "physical_execution": False,
        }
