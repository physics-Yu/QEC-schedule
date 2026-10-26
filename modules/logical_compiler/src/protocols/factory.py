"""Execute code-owned factory recipes using on-demand resources and real bodies.

The recipe supplies every gate, role, correction and measurement model. This
module defines recipe validation and a single-factory facade over the shared runtime.
It has no code-specific matrices, Pauli corrections, noise equations or inventory
maintenance policy. Probability-port steps are evidence, never a second program.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

from modules.codes.contracts.component import ComponentBinding
from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.contracts.factory_recipe import (
    FactoryRecipe,
    ResourcePreparation,
    TConsumptionRecipe,
)
from modules.codes.contracts.parallel import ComponentExecutionSpec

from ..scheduling import ComponentScheduler
from .assembly import PhysicalBundle
from .physical import PhysicalContext
from .resources import ResourceLedger


class FactoryBackend(Protocol):
    """Code-owned binding, decision construction and quality-model boundary."""

    def describe_execution(
        self,
        component_id: str,
        participant_bindings: tuple[ComponentBinding, ...],
        parameters: tuple[tuple[str, Any], ...] = (),
    ) -> ComponentExecutionSpec: ...

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
    """Single-factory facade over the shared component-batching runtime.

    Code, recipe and carrier bindings are explicit. A missing scheduler creates
    the same mandatory batching scheduler used by full and fast factory arrays.
    The legacy single-case envelope and event namespace remain stable; there is
    no independent sequential execution path.
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
        if physical.invocations:
            raise ValueError("PHYSICAL_CONTEXT_ALREADY_USED")
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
        self.scheduler = scheduler if scheduler is not None else ComponentScheduler()
        self.ledger = ResourceLedger()
        self._started = False

    def run(
        self,
        *,
        algorithm_preparation: ResourcePreparation | None = None,
        algorithm_consumption: TConsumptionRecipe | None = None,
    ) -> FactoryCase:
        """Compile once through the common process, scheduler and physical kernel.

        Invalid entry recipes raise before work starts. Component failures retain
        the committed physical prefix and resource ledger in the returned case.
        """
        from .cooperative import CooperativeFactoryRuntime
        from .factory_process import FactoryProcess

        if self._started:
            raise ValueError("FACTORY_EXECUTOR_REUSED")

        class SingleFactoryProcess(FactoryProcess):
            @property
            def algorithm_scope(self) -> str:
                # Preserve existing single-case result identities and RNG keys.
                return "algorithm"

        process = SingleFactoryProcess(
            "factory",
            code=self.code,
            recipe=self.recipe,
            backend=self.backend,
            role_bindings=self.roles,
            distance=self.distance,
            limits=self.limits,
            reference_parameters=self.parameters,
            algorithm_preparation=algorithm_preparation,
            algorithm_consumption=algorithm_consumption,
        )
        runtime = CooperativeFactoryRuntime(
            self.physical,
            case_id=self.case_id,
            seed=self.seed,
            scheduler=self.scheduler,
            processes=(process,),
        )
        self._started = True
        result = runtime.run()
        self.ledger = runtime.ledger
        document = result.to_dict()
        failure = document["failure"] or process.failure
        document.pop("physical")
        document.pop("factories")
        document.update(process.snapshot())
        document.update(
            schema="nadit.factory_case/1",
            status=result.status
            if result.status == "physical_failure"
            else process.status,
            failure=failure,
            global_frame="not_implemented",
        )
        return FactoryCase(
            json.dumps(
                document, sort_keys=True, separators=(",", ":"), allow_nan=False
            ),
            result.physical,
        )
