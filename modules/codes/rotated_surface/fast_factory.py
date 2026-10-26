"""Code-owned generic factory recipe; object cost coverage is supplied separately.

Selected from 85f5479. Position-calibrated and exact-frontier profiles are not
part of this object-scheduler baseline. Missing object costs must fail explicitly.
"""

from dataclasses import replace

from modules.codes.contracts.factory_recipe import FactoryRecipe, ResourcePreparation
from modules.codes.rotated_surface_d3.protocols.factory import (
    factory_recipe as d3_recipe,
)

from .definition import definition


def factory_recipe(distance: int) -> FactoryRecipe:
    """Reuse the code-independent 4+11 circuit with explicit small-code injection."""
    definition(distance)
    code = f"rotated_surface_d{distance}"
    original = d3_recipe()

    def preparation(p: ResourcePreparation) -> ResourcePreparation:
        return replace(
            p,
            resource_kind=None if p.resource_kind is None else f"{code}/A",
            parameters=() if p.resource_kind is None else (("injection_rounds", 3),),
        )

    return replace(
        original,
        code_id=code,
        protocol_id=f"{code}.small_injection_factory_15_to_1",
        version="1",
        initial_preparations=tuple(
            preparation(p) for p in original.initial_preparations
        ),
        rotations=tuple(
            replace(r, preparation=preparation(r.preparation))
            for r in original.rotations
        ),
        output_resource_kind=f"{code}/A",
    )


def required_variants(distance: int) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Enumerate finite component/role coverage before any stochastic experiment."""
    recipe = factory_recipe(distance)
    variants: set[tuple[str, tuple[str, ...]]] = set()
    for p in (*recipe.initial_preparations, *(r.preparation for r in recipe.rotations)):
        variants.add((p.component_id, (p.role,)))
        variants.add((p.canonicalization_id + "/canonicalize", (p.role,)))
    calls = [*recipe.final_measurement_calls, *recipe.accepted_output_calls]
    for r in recipe.rotations:
        calls.extend(
            (
                *r.compute_calls,
                *r.uncompute_calls,
                r.consumption.cx_call,
                r.consumption.mz_call,
            )
        )
        calls.extend(c for branch in r.consumption.branches for c in branch.calls)
    variants.update((c.component_id, c.participant_roles) for c in calls)
    return tuple(sorted(variants))
