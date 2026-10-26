"""Execute code-owned factory recipes using on-demand resources and real bodies.

The recipe supplies every gate, role, correction and measurement model. This
module owns serial control, resource lifetimes, bounded retries and case records.
It has no code-specific matrices, Pauli corrections, noise equations or inventory
maintenance policy. Probability-port steps are evidence, never a second program.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from modules.codes.contracts.component import ComponentBinding, ComponentExpansion
from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.contracts.factory_recipe import (
    ComponentCall,
    EventRequest,
    FactoryRecipe,
    ResourcePreparation,
    TConsumptionRecipe,
)

from ..scheduling import ComponentNode, ComponentScheduler
from .assembly import PhysicalBundle
from .events import EventDependency, EventJournal, EventObservation
from .physical import PhysicalContext
from .resources import ResourceLedger, ResourceToken


class FactoryBackend(Protocol):
    """Code-owned binding, decision construction and quality-model boundary."""

    def bind_call(
        self,
        component_id: str,
        participant_bindings: tuple[ComponentBinding, ...],
        parameters: tuple[tuple[str, Any], ...] = (),
    ) -> Any: ...

    def bind_canonicalization(
        self,
        preparation: str,
        source: Any,
        decision: Any,
        probability_port: ProbabilityPort,
    ) -> Any: ...

    def correction_decision(
        self,
        source: Any,
        *,
        event_id: str,
        probability_port: ProbabilityPort,
        values: Mapping[str, object],
        available_at_us: float,
    ) -> Any: ...

    def resolve_event(
        self,
        selector: str,
        parameters: Mapping[str, Any] | None = None,
    ) -> ProbabilityPort: ...

    def preparation_quality(
        self,
        preparation: str,
        parameters: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def output_quality(self, factory_port: ProbabilityPort) -> dict[str, Any]: ...


@dataclass(frozen=True)
class FactoryLimits:
    """Correctness bounds only; no prefetch or storage maintenance policies."""

    raw_attempts: int = 3
    batches: int = 1
    max_component_calls: int = 10000

    def __post_init__(self) -> None:
        for name in ("raw_attempts", "batches", "max_component_calls"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(
                    f"INVALID_FACTORY_LIMIT: {name} must be a positive integer"
                )


@dataclass(frozen=True)
class FactoryCase:
    """Selected protocol case and independently validated, unobserved Atom IR.

    Physical validity is distinct from a coarse event's quantum assumptions.
    A partial failure retains resource ownership, events and actual prefix costs.
    """

    _document_json: str
    physical: PhysicalBundle | None

    @property
    def status(self) -> str:
        """Return the explicit terminal status of the requested goal."""
        return str(json.loads(self._document_json)["status"])

    def to_dict(self) -> dict[str, Any]:
        """Return a fresh complete envelope, including pending physical results."""
        document: dict[str, Any] = json.loads(self._document_json)
        document["physical"] = (
            None if self.physical is None else self.physical.to_dict()
        )
        return document

    def to_json(self) -> str:
        """Return deterministic JSON for the one selected finite execution path."""
        return json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False
        )


class _Stop(Exception):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code


def _validate_consumption(recipe: TConsumptionRecipe, roles: set[str]) -> None:
    if (
        recipe.data_role == recipe.magic_role
        or not {recipe.data_role, recipe.magic_role} <= roles
    ):
        raise ValueError("INVALID_RECIPE: consumption roles alias or are absent")
    if recipe.cx_call.consumes_resource_role != recipe.magic_role:
        raise ValueError(
            "INVALID_RECIPE: injection call must mark irreversible consumption"
        )
    if tuple(recipe.cx_call.participant_roles) != (recipe.data_role, recipe.magic_role):
        raise ValueError(
            "INVALID_RECIPE: injection participants disagree with consumption roles"
        )
    if len({branch.outcome_key for branch in recipe.branches}) != len(recipe.branches):
        raise ValueError("INVALID_RECIPE: duplicate consumption outcomes")
    if any(branch.transition != "continue" for branch in recipe.branches):
        raise ValueError(
            "INVALID_RECIPE: T-consumption branches cannot retry prepared inputs"
        )
    keys = {recipe.cx_call.key, recipe.mz_call.key}
    if (
        not recipe.event.dependency_call_keys
        or not set(recipe.event.dependency_call_keys) <= keys
    ):
        raise ValueError("INVALID_RECIPE: consumption event has unknown dependencies")


def _validate_recipe(recipe: FactoryRecipe, roles: set[str]) -> None:
    work = set(recipe.work_roles)
    if len(work) != len(recipe.work_roles) or recipe.resource_role in work:
        raise ValueError("INVALID_RECIPE: duplicate or aliased work/resource roles")
    if not work | {recipe.resource_role} <= roles or recipe.output_role not in work:
        raise ValueError("INVALID_RECIPE: missing factory roles or output")
    if (
        set(recipe.retry_work_roles) != work
        or recipe.output_role in recipe.released_roles
    ):
        raise ValueError("INVALID_RECIPE: unsafe batch reset or output release")
    if {item.role for item in recipe.initial_preparations} != work or len(
        recipe.initial_preparations
    ) != len(work):
        raise ValueError("INVALID_RECIPE: initialize each work role exactly once")
    for item in recipe.initial_preparations:
        expected = "working" if item.resource_kind is None else "adopt"
        if item.ownership != expected:
            raise ValueError("INVALID_RECIPE: initial preparation ownership")
    for rotation in recipe.rotations:
        if not set(rotation.support) <= work or rotation.pivot not in rotation.support:
            raise ValueError("INVALID_RECIPE: invalid rotation support or pivot")
        if (
            rotation.preparation.role != recipe.resource_role
            or rotation.preparation.ownership != "reserve"
        ):
            raise ValueError(
                "INVALID_RECIPE: rotation requires its own reserved resource"
            )
        if (
            rotation.consumption.data_role != rotation.pivot
            or rotation.consumption.magic_role != recipe.resource_role
        ):
            raise ValueError(
                "INVALID_RECIPE: rotation consumption disagrees with roles"
            )
        _validate_consumption(rotation.consumption, roles)
    final_keys = {call.key for call in recipe.final_measurement_calls}
    if (
        not recipe.final_event.dependency_call_keys
        or not set(recipe.final_event.dependency_call_keys) <= final_keys
    ):
        raise ValueError(
            "INVALID_RECIPE: final event must depend on declared measurements"
        )


class FactoryExecutor:
    """Run a finite code-selected factory and optionally consume its output once.

    Args:
        code: Explicit code identity, required to equal recipe.code_id.
        recipe: Code-owned stages; no protocol gates are inferred here.
        backend: Code-owned real component and event-model provider.
        physical: Shared real world, clock, binding and result-identity context.
        role_bindings: Recipe roles mapped to registered physical block IDs.
        distance: Declared distance of these carriers, not an FT certification.
        case_id: Stable case identity for reproducible event sampling.
        seed: Integer seed; ordering does not reassign event identities.
        limits: Finite local preparation, outer batch and expansion bounds.
        reference_parameters: Explicit parameters passed to code-owned quality
            and final-check models. They are never inferred from raw rejection.

    Invalid recipe/role interfaces raise ValueError before any physical work.
    Execution failures are returned as partial FactoryCase records.
    """

    def __init__(
        self,
        *,
        code: str,
        recipe: FactoryRecipe,
        backend: FactoryBackend,
        physical: PhysicalContext,
        role_bindings: Mapping[str, str],
        distance: int,
        case_id: str,
        seed: int,
        limits: FactoryLimits | None = None,
        reference_parameters: Mapping[str, Any] | None = None,
        scheduler: ComponentScheduler | None = None,
    ) -> None:
        if not code or code != recipe.code_id:
            raise ValueError("CODE_ENTRY_MISMATCH: explicit code must match the recipe")
        if getattr(physical, "invocations", ()):
            raise ValueError(
                "PHYSICAL_CONTEXT_ALREADY_USED: do not replace a live case's ledger"
            )
        bindings = dict(role_bindings)
        if len(set(bindings.values())) != len(bindings) or not set(
            bindings.values()
        ) <= set(physical.bindings):
            raise ValueError("INVALID_RECIPE: aliased or unknown physical bindings")
        _validate_recipe(recipe, set(bindings))
        self.code, self.recipe, self.backend, self.physical = (
            code,
            recipe,
            backend,
            physical,
        )
        self.roles, self.distance, self.case_id, self.seed = (
            bindings,
            distance,
            case_id,
            seed,
        )
        self.limits = limits or FactoryLimits()
        self.parameters = deepcopy(dict(reference_parameters or {}))
        self.scheduler = scheduler
        self.ledger, self.journal = ResourceLedger(), EventJournal(case_id, seed)
        for carrier_id in sorted(bindings.values()):
            self.ledger.register_carrier(
                carrier_id,
                code_id=code,
                distance=distance,
                atom_ids=physical.bindings[carrier_id].atom_ids,
            )
        self.calls: list[dict[str, Any]] = []
        self.milestones: list[dict[str, Any]] = []
        self._sources: dict[str, tuple[ComponentExpansion, ...]] = {}
        self._started = False
        self._stage = "entry"
        self._output: str | None = None
        self._algorithm_consumed: str | None = None
        self._last_event: EventObservation | None = None
        self._role_calls: dict[str, str] = {}
        self._role_events: dict[str, EventObservation] = {}

    def _queue_call(
        self,
        call: ComponentCall,
        scope: str,
        *,
        priority: int = 0,
        events: tuple[EventObservation, ...] = (),
        token: ResourceToken | None = None,
    ) -> ComponentNode:
        """Publish a code-declared call before binding or expanding atom actions."""
        assert self.scheduler is not None
        describe = getattr(self.backend, "describe_execution", None)
        if not callable(describe):
            raise TypeError(
                "COMPONENT_DECLARATION_REQUIRED: no execution specification"
            )
        spec = describe(
            call.component_id,
            tuple(
                self.physical.bindings[self.roles[role]]
                for role in call.participant_roles
            ),
            call.parameters,
        )
        dependencies = self._call_events(call, events)
        keys = tuple(self._event_key(event) for event in dependencies)
        if token is not None:
            self.scheduler.release_token(token.token_id, token.ready_at_us)
        node = ComponentNode(
            f"{scope}/{call.key}",
            spec,
            after_calls=tuple(
                dict.fromkeys(
                    self._role_calls[role]
                    for role in call.participant_roles
                    if role in self._role_calls
                )
            ),
            event_dependencies=keys,
            token_dependencies=() if token is None else (token.token_id,),
            priority=priority,
        )
        return self.scheduler.add(node)[0]

    @staticmethod
    def _event_key(event: EventObservation) -> str:
        return json.dumps(
            event.result.occurrence.to_dict(), sort_keys=True, separators=(",", ":")
        )

    def _call_events(
        self,
        call: ComponentCall,
        extra: tuple[EventObservation, ...] = (),
    ) -> tuple[EventObservation, ...]:
        events = (
            tuple(
                self._role_events[role]
                for role in call.participant_roles
                if role in self._role_events
            )
            + extra
        )
        return tuple({self._event_key(event): event for event in events}.values())

    def _mark(self, kind: str, **details: Any) -> None:
        self.milestones.append(
            {"kind": kind, "at_us": self.physical.clock_us, **details}
        )

    def _invoke(
        self,
        call: ComponentCall,
        scope: str,
        *,
        bound: Any = None,
        token: ResourceToken | None = None,
        event_dependencies: tuple[EventObservation, ...] = (),
    ) -> tuple[ComponentExpansion, ...]:
        invocation_id = f"{scope}/{call.key}"
        self._stage = invocation_id
        if len(self.calls) >= self.limits.max_component_calls:
            raise _Stop("expansion_budget_exhausted", "Maximum component calls reached")
        if invocation_id in self._sources or len(set(call.participant_roles)) != len(
            call.participant_roles
        ):
            raise ValueError("INVALID_RECIPE: duplicate call or participant")
        start = self.physical.clock_us
        node = None
        admission = None
        if self.scheduler is not None:
            node = self._queue_call(
                call,
                scope,
                priority=-1 if bound is not None else 0,
                events=event_dependencies,
                token=token,
            )
            admission = self.scheduler.admit(
                start, snapshot_id=self.physical.snapshot_id
            )
            if admission is None or admission.node_ids != (invocation_id,):
                raise ValueError("CALL_NOT_READY: expected one admitted component")
        next_ledger = deepcopy(self.ledger)
        if call.consumes_resource_role is not None:
            if (
                token is None
                or token.carrier_id != self.roles[call.consumes_resource_role]
            ):
                raise ValueError(
                    "INVALID_RECIPE: consuming call lacks the exact reserved token"
                )
            next_ledger.consume(
                token.token_id,
                consumer=str(token.consumer),
                at_us=start,
                safe_exit_at_us=start,
            )
        for role in call.participant_roles:
            carrier = next_ledger.carrier(self.roles[role])
            if carrier.owner is None:
                raise ValueError(f"UNOWNED_CARRIER: {role}")
            next_ledger.extend_use(
                carrier.carrier_id,
                owner=carrier.owner,
                at_us=start,
                safe_exit_at_us=start,
            )
        try:
            if bound is None:
                bound = self.backend.bind_call(
                    call.component_id,
                    tuple(
                        self.physical.bindings[self.roles[role]]
                        for role in call.participant_roles
                    ),
                    call.parameters,
                )
            parts = self.physical.invoke(bound, invocation_id, bound.result_count)
        except (ValueError, NotImplementedError) as error:
            raise _Stop("physical_failure", str(error)) from error
        for role in call.participant_roles:
            carrier = next_ledger.carrier(self.roles[role])
            assert carrier.owner is not None
            next_ledger.extend_use(
                carrier.carrier_id,
                owner=carrier.owner,
                at_us=start,
                safe_exit_at_us=self.physical.clock_us,
            )
        self.ledger = next_ledger
        if self.scheduler is not None:
            assert admission is not None
            self.scheduler.commit_admission(admission)
            self.scheduler.mark_completed(invocation_id, self.physical.clock_us)
        if (
            token is not None
            and call.consumes_resource_role is not None
            and token.token_id == self._output
        ):
            self._algorithm_consumed = token.token_id
        self._sources[invocation_id] = parts
        self.calls.append(
            {
                "invocation_id": invocation_id,
                "component_id": call.component_id,
                "participant_roles": list(call.participant_roles),
                "start_us": start,
                "end_us": self.physical.clock_us,
                "after_calls": list(node.after_calls)
                if node is not None
                else list(
                    dict.fromkeys(
                        self._role_calls[role]
                        for role in call.participant_roles
                        if role in self._role_calls
                    )
                ),
                "event_dependencies": [
                    event.result.occurrence.to_dict()
                    for event in self._call_events(call, event_dependencies)
                ],
                "part_invocations": [part.invocation_id for part in parts],
                "consumed_token_id": None
                if call.consumes_resource_role is None
                else token.token_id
                if token
                else None,
            }
        )
        self._role_calls.update(
            (role, invocation_id) for role in call.participant_roles
        )
        return parts

    def _sample(
        self,
        port: ProbabilityPort,
        identity: str,
        attempt: int,
        parts: tuple[ComponentExpansion, ...],
    ) -> EventObservation:
        self._stage = identity
        observation = self.journal.sample(
            port,
            invocation_id=identity,
            attempt=attempt,
            dependencies=tuple(EventDependency.from_expansion(part) for part in parts),
            context=self.physical,
        )
        self._last_event = observation
        blocks = {
            binding.block_id
            for part in parts
            for binding in (
                getattr(part, "participant_bindings", ()) or (part.exit_binding,)
            )
            if binding is not None
        }
        self._role_events.update(
            (role, observation)
            for role, carrier in self.roles.items()
            if carrier in blocks
        )
        if self.scheduler is not None:
            self.scheduler.release_event(
                self._event_key(observation), observation.released_at_us
            )
        return observation

    def _event(
        self,
        request: EventRequest,
        scope: str,
        parameters: Mapping[str, Any],
    ) -> tuple[ProbabilityPort, EventObservation]:
        parts = tuple(
            part
            for key in request.dependency_call_keys
            for part in self._sources[f"{scope}/{key}"]
        )
        identity = f"{scope}/{request.key}"
        source_hook = getattr(self.backend, "resolve_event_from_sources", None)
        if callable(source_hook):
            self.physical.wait_until(
                max(part.results_ready_us for part in parts),
                reason=f"event_model_sources:{identity}",
            )
            port = source_hook(request.selector, parts, parameters, event_id=identity)
        else:
            port = self.backend.resolve_event(request.selector, parameters)
        observation = self._sample(port, identity, 0, parts)
        self._role_events.update(
            (role, observation) for role in request.participant_roles
        )
        return port, observation

    def _prepare(
        self, preparation: ResourcePreparation, scope: str, owner: str
    ) -> ResourceToken | None:
        identity = f"{scope}/{preparation.key}"
        carrier_id = self.roles[preparation.role]
        for attempt in range(self.limits.raw_attempts):
            attempt_scope = f"{identity}/attempt[{attempt}]"
            self.ledger.begin_preparation(
                carrier_id, owner=owner, at_us=self.physical.clock_us
            )
            call = ComponentCall("body", preparation.component_id, (preparation.role,))
            parts = self._invoke(call, attempt_scope)
            source = self.physical.source(f"{attempt_scope}/body")
            event_hook = getattr(self.backend, "preparation_event", None)
            port = (
                event_hook(preparation.canonicalization_id, source, self.parameters)
                if callable(event_hook)
                else self.backend.resolve_event(preparation.event_selector)
            )
            observation = self._sample(port, identity, attempt, parts)
            accepted = observation.values.get("accepted")
            if type(accepted) is not bool:
                raise ValueError(
                    "INVALID_PREPARATION_EVENT: Boolean acceptance is required"
                )
            self._mark(
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
                    carrier_id, owner=owner, at_us=self.physical.clock_us
                )
                continue
            return self._accept_preparation(
                preparation, identity, attempt, owner, source, port, observation
            )
        raise AssertionError("Finite preparation budget must return or stop")

    def _accept_preparation(
        self,
        preparation: ResourcePreparation,
        identity: str,
        attempt: int,
        owner: str,
        source: Any,
        port: ProbabilityPort,
        observation: EventObservation,
    ) -> ResourceToken | None:
        """Canonicalize one accepted local event, then publish its actual resource."""
        carrier_id = self.roles[preparation.role]
        carrier = self.ledger.carrier(carrier_id)
        attempt_scope = f"{identity}/attempt[{attempt}]"
        decision = self.backend.correction_decision(
            source,
            event_id=f"{identity}/event[{attempt}]",
            probability_port=port,
            values=observation.values,
            available_at_us=observation.released_at_us,
        )
        bound = self.backend.bind_canonicalization(
            preparation.canonicalization_id, source, decision, port
        )
        self._invoke(
            ComponentCall(
                "canonicalize",
                preparation.canonicalization_id + "/canonicalize",
                (preparation.role,),
            ),
            attempt_scope,
            bound=bound,
        )
        self._mark(
            "preparation_canonicalized",
            preparation=identity,
            attempt=attempt,
            carrier_id=carrier_id,
            port_sha256=port.content_sha256,
        )
        if preparation.resource_kind is None:
            self.ledger.finish_preparation(
                carrier_id, owner=owner, at_us=self.physical.clock_us
            )
            return None
        quality_hook = getattr(self.backend, "preparation_quality_from_event", None)
        quality = (
            quality_hook(
                preparation.canonicalization_id,
                source,
                port,
                observation.values,
                self.parameters,
            )
            if callable(quality_hook)
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
            ready_at_us=self.physical.clock_us,
            exit_at_us=self.physical.clock_us,
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
                f"Resource {token.token_id!r} has no supported consumption model: "
                f"{quality.get('reason', quality.get('reasons', 'unspecified'))}",
            )
        token = self.ledger.reserve(
            token.token_id,
            consumer=owner,
            at_us=self.physical.clock_us,
            expected_code=self.code,
            expected_kind=preparation.resource_kind,
            expected_canonicalization="canonical",
            expected_distance=self.distance,
        )
        if preparation.ownership == "adopt":
            token = self.ledger.consume(
                token.token_id,
                consumer=owner,
                at_us=self.physical.clock_us,
                safe_exit_at_us=self.physical.clock_us,
                usage_kind="adopt",
            )
        elif preparation.ownership != "reserve":
            raise ValueError("INVALID_RECIPE: unknown prepared-resource ownership")
        return token

    def _consume(
        self, recipe: TConsumptionRecipe, scope: str, token: ResourceToken
    ) -> None:
        parameters = token.quality.get("consumption_parameters")
        if (
            token.quality.get("status") in ("unsupported", "unknown")
            or parameters is None
        ):
            raise _Stop(
                "unsupported_resource_quality",
                f"Resource {token.token_id!r} has no supported consumption model",
            )
        if not isinstance(parameters, dict):
            raise TypeError(
                "INVALID_RESOURCE_QUALITY: consumption parameters must be an object"
            )
        self._invoke(recipe.cx_call, scope, token=token)
        self._invoke(recipe.mz_call, scope)
        _, observation = self._event(recipe.event, scope, parameters)
        branch = next(
            (
                branch
                for branch in recipe.branches
                if branch.outcome_key == observation.result.outcome_key
            ),
            None,
        )
        if branch is None:
            raise ValueError("UNSUPPORTED_CONSUMPTION_BRANCH: no declared continuation")
        for call in branch.calls:
            self._invoke(call, scope, event_dependencies=(observation,))
        # This first implementation completes the full consumption before slot reuse.
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
        self.physical.wait_until(
            ready, reason=f"consumption_complete:{scope}/{recipe.key}"
        )
        self._mark(
            "resource_consumption_complete", token_id=token.token_id, recipe=recipe.key
        )

    def _release(self, roles: tuple[str, ...]) -> None:
        for role in roles:
            carrier = self.ledger.carrier(self.roles[role])
            if carrier.owner is not None:
                self.ledger.complete_use(
                    carrier.carrier_id,
                    owner=carrier.owner,
                    at_us=self.physical.clock_us,
                )

    def _factory(self) -> ResourceToken:
        for batch in range(self.limits.batches):
            scope = f"factory/batch[{batch}]"
            self._mark("batch_started", batch=batch)
            if self.scheduler is None:
                for preparation in self.recipe.initial_preparations:
                    self._prepare(preparation, scope, scope)
            else:
                from .initial_supply import prepare_initial

                prepare_initial(self, scope)
            for rotation in self.recipe.rotations:
                owner = f"{scope}/{rotation.key}"
                token = self._prepare(rotation.preparation, scope, owner)
                if token is None:
                    raise ValueError(
                        "INVALID_RECIPE: rotation preparation did not issue a token"
                    )
                for call in rotation.compute_calls:
                    self._invoke(call, scope)
                self._consume(rotation.consumption, scope, token)
                for call in rotation.uncompute_calls:
                    self._invoke(call, scope)
                self._release((rotation.preparation.role,))
                self._mark("rotation_complete", batch=batch, rotation=rotation.key)
            for call in self.recipe.final_measurement_calls:
                self._invoke(call, scope)
            port, observation = self._event(
                self.recipe.final_event, scope, self.parameters
            )
            accepted = observation.values.get("accepted")
            if type(accepted) is not bool:
                raise ValueError(
                    "INVALID_FACTORY_EVENT: Boolean acceptance is required"
                )
            self._mark("batch_decision", batch=batch, accepted=accepted)
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
                self._invoke(call, scope, event_dependencies=(observation,))
            carrier = self.ledger.carrier(self.roles[self.recipe.output_role])
            token = self.ledger.offer(
                f"{scope}/output",
                carrier_id=carrier.carrier_id,
                epoch=carrier.epoch,
                owner=scope,
                resource_kind=self.recipe.output_resource_kind,
                producer=f"{scope}/{self.recipe.final_event.key}",
                ready_at_us=self.physical.clock_us,
                exit_at_us=self.physical.clock_us,
                canonicalization="canonical",
                quality=self.backend.output_quality(port),
                provenance={
                    "port_sha256": port.content_sha256,
                    "protocol_id": self.recipe.protocol_id,
                },
            )
            self._output = token.token_id
            self._release(self.recipe.released_roles)
            self._mark("factory_output_ready", token_id=token.token_id)
            return token
        raise AssertionError("Finite factory budget must return or stop")

    def run(
        self,
        *,
        algorithm_preparation: ResourcePreparation | None = None,
        algorithm_consumption: TConsumptionRecipe | None = None,
    ) -> FactoryCase:
        """Run once; retain a factory output or consume it in the declared algorithm T.

        Passing one algorithm recipe requires both. The data role must be free
        after successful factory output; it cannot alias the output carrier.
        Invalid input or reuse raises ValueError before executing this run.
        """
        if self._started:
            raise ValueError("FACTORY_EXECUTOR_REUSED: construct a fresh case executor")
        if (algorithm_preparation is None) != (algorithm_consumption is None):
            raise ValueError(
                "INVALID_ALGORITHM_ENTRY: supply both preparation and consumption"
            )
        if algorithm_consumption is not None:
            assert algorithm_preparation is not None
            _validate_consumption(algorithm_consumption, set(self.roles))
            if (
                algorithm_preparation.role != algorithm_consumption.data_role
                or algorithm_consumption.magic_role != self.recipe.output_role
                or algorithm_preparation.resource_kind is not None
            ):
                raise ValueError(
                    "INVALID_ALGORITHM_ENTRY: incompatible resource/data roles"
                )
        self._started = True
        status, failure = "complete", None
        try:
            token = self._factory()
            if algorithm_consumption is not None:
                assert algorithm_preparation is not None
                self._prepare(algorithm_preparation, "algorithm", "algorithm")
                token = self.ledger.reserve(
                    token.token_id,
                    consumer="algorithm",
                    at_us=self.physical.clock_us,
                    expected_code=self.code,
                    expected_kind=self.recipe.output_resource_kind,
                    expected_canonicalization="canonical",
                    expected_distance=self.distance,
                )
                self._consume(algorithm_consumption, "algorithm", token)
                self._algorithm_consumed = token.token_id
                self._release((algorithm_consumption.magic_role,))
                self._mark("algorithm_t_complete", token_id=token.token_id)
        except (_Stop, ValueError, TypeError, KeyError, NotImplementedError) as error:
            status = error.code if isinstance(error, _Stop) else "protocol_failure"
            failure = {
                "code": status,
                "stage": self._stage,
                "at_us": self.physical.clock_us,
                "detail": str(error),
            }
        bundle = None
        try:
            bundle = self.physical.finalize()
        except ValueError as error:
            status = "physical_failure"
            failure = {
                "code": status,
                "stage": "whole_program_validation",
                "at_us": self.physical.clock_us,
                "detail": str(error),
                "prior_failure": failure,
            }
        document = {
            "schema": "nadit.factory_case/1",
            "artifact_kind": "static_protocol_case",
            "code": self.code,
            "case_id": self.case_id,
            "seed": self.seed,
            "goal": "factory_output"
            if algorithm_consumption is None
            else "factory_output_to_t",
            "status": status,
            "failure": failure,
            "recipe": asdict(self.recipe),
            "limits": asdict(self.limits),
            "reference_parameters": self.parameters,
            "supply_mode": "on_demand",
            "inventory_maintenance": "not_implemented",
            "physical_execution": False,
            "full_quantum_simulation": False,
            "physical_measurement_values": "unobserved",
            "global_frame": "not_implemented",
            "calls": self.calls,
            "component_schedule": None
            if self.scheduler is None
            else self.scheduler.snapshot(),
            "milestones": self.milestones,
            "resources": self.ledger.snapshot(),
            **self.journal.snapshot(),
            "output_token_id": self._output,
            "algorithm_consumed_token_id": self._algorithm_consumed,
            "duration_us": self.physical.clock_us,
        }
        return FactoryCase(
            json.dumps(
                document, sort_keys=True, separators=(",", ":"), allow_nan=False
            ),
            bundle,
        )
