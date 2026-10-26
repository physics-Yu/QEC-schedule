"""Immutable code-owned factory declarations; no scheduler, sampler or state.

The consumer traverses declared stages. It owns budgets, tokens, epochs, clocks,
and physical continuations. Code libraries own concrete gate/support conventions.
"""

from dataclasses import dataclass

from .event_probability import JSONScalar


@dataclass(frozen=True, slots=True)
class ComponentCall:
    """One physical component invocation and its irreversible resource milestone."""

    key: str
    component_id: str
    participant_roles: tuple[str, ...]
    parameters: tuple[tuple[str, JSONScalar], ...] = ()
    consumes_resource_role: str | None = None


@dataclass(frozen=True, slots=True)
class EventRequest:
    """Resolve a code-owned joint port only after every dependency is ready."""

    key: str
    selector: str
    dependency_call_keys: tuple[str, ...]
    participant_roles: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EventBranch:
    """An outcome continuation; calls complete before the transition applies."""

    outcome_key: str
    calls: tuple[ComponentCall, ...]
    transition: str = "continue"


@dataclass(frozen=True, slots=True)
class ResourcePreparation:
    """Local retry unit, canonicalized before adoption or further interactions.

    ``resource_kind=None`` means a working state. A non-None input resource is
    uniquely issued and adopted when ownership='adopt', or reserved for later
    consumption when ownership='reserve'. Failure retries only this role.
    Parameters belong to the code-owned component and are forwarded unchanged
    on every attempt; they are distinct from probability-model parameters.
    """

    key: str
    role: str
    component_id: str
    event_selector: str
    canonicalization_id: str
    resource_kind: str | None
    ownership: str
    parameters: tuple[tuple[str, JSONScalar], ...] = ()


@dataclass(frozen=True, slots=True)
class TConsumptionRecipe:
    """CX, destructive MZ and outcome response, with no postselection branch."""

    key: str
    data_role: str
    magic_role: str
    cx_call: ComponentCall
    mz_call: ComponentCall
    event: EventRequest
    branches: tuple[EventBranch, ...]


@dataclass(frozen=True, slots=True)
class RotationRecipe:
    """Prepare, compute, consume/correct, uncompute, then declared EC rounds.

    A round exposes independent calls together and joins their result times.
    The code chooses the calls and cadence; the compiler does not infer either.
    These declarations do not by themselves decode or sample syndrome values.
    """

    key: str
    support: tuple[str, ...]
    pivot: str
    preparation: ResourcePreparation
    compute_calls: tuple[ComponentCall, ...]
    consumption: TConsumptionRecipe
    uncompute_calls: tuple[ComponentCall, ...]
    post_rotation_rounds: tuple[tuple[ComponentCall, ...], ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.post_rotation_rounds, tuple):
            raise TypeError("INVALID_RECIPE: EC rounds must be immutable tuples")
        keys = {
            call.key
            for call in (
                *self.compute_calls,
                self.consumption.cx_call,
                self.consumption.mz_call,
                *(
                    call
                    for branch in self.consumption.branches
                    for call in branch.calls
                ),
                *self.uncompute_calls,
            )
        }
        for calls in self.post_rotation_rounds:
            if not isinstance(calls, tuple) or not calls:
                raise ValueError("INVALID_RECIPE: an EC round needs immutable calls")
            roles: set[str] = set()
            for call in calls:
                if (
                    not isinstance(call, ComponentCall)
                    or not call.participant_roles
                    or call.consumes_resource_role is not None
                    or call.key in keys
                    or roles.intersection(call.participant_roles)
                ):
                    raise ValueError(
                        "INVALID_RECIPE: EC calls overlap or consume state"
                    )
                keys.add(call.key)
                roles.update(call.participant_roles)


@dataclass(frozen=True, slots=True)
class FactoryRecipe:
    """A complete frozen factory skeleton and explicit batch retry boundaries.

    Raw preparation exhaustion stops without a new batch or hidden reset. Final
    rejection invalidates all work states; a new batch replays every initial
    preparation. Measured roles retain atoms, not their old quantum states.
    """

    code_id: str
    protocol_id: str
    version: str
    work_roles: tuple[str, ...]
    resource_role: str
    initial_preparations: tuple[ResourcePreparation, ...]
    rotations: tuple[RotationRecipe, ...]
    final_measurement_calls: tuple[ComponentCall, ...]
    final_event: EventRequest
    accepted_output_calls: tuple[ComponentCall, ...]
    retry_work_roles: tuple[str, ...]
    released_roles: tuple[str, ...]
    output_role: str
    output_resource_kind: str
