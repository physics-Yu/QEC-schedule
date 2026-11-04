"""Adapt explicit logical placement to the existing d3 factory cost interface.

Geometry generation and validation belong to logical placement. This adapter
creates no atoms, compiles no components and samples no protocol outcomes.
"""

from __future__ import annotations

from collections.abc import Sequence
from math import isfinite
from typing import TYPE_CHECKING, Any

from nadit_physical_compiler.device import Position, Region

from modules.codes.rotated_surface import definition
from modules.codes.rotated_surface.geometry import geometry
from modules.logical_compiler.src.placement import (
    BlockPlacement,
    BlockSpec,
    ExplicitPlacement,
    PlacementPlan,
    PlacementRequest,
    place,
    validate_plan,
)

from .factory import factory_recipe

if TYPE_CHECKING:
    from .fast_profile import FastLayout

DEFAULT_ORIGIN = Position(0, 0)


def _positive(value: int, label: str, minimum: int = 1) -> None:
    if type(value) is not int or value < minimum:
        raise ValueError(f"INVALID_FAST_LAYOUT_BUDGET: {label}")


def _roles() -> tuple[str, ...]:
    recipe = factory_recipe()
    return (*recipe.work_roles, recipe.resource_role)


def legacy_factory_plan(
    factory_count: int,
    *,
    origin: Position = DEFAULT_ORIGIN,
    factory_gap_columns: int = 2,
    block_spacing_columns: int = 10,
    factory_id_prefix: str = "factory",
) -> PlacementPlan:
    """Express the historical horizontal layout as an explicit placement plan.

    This compatibility strategy preserves the old coordinates exactly. New
    placements can use any supported strategy before calling ``layout_from_plan``.
    Invalid counts, identities or geometries raise ValueError.
    """
    _positive(factory_count, "factories")
    _positive(factory_gap_columns, "gap", 0)
    _positive(block_spacing_columns, "patch spacing")
    if not isinstance(origin, Position):
        raise TypeError("INVALID_FAST_LAYOUT_ORIGIN")
    if not isinstance(factory_id_prefix, str) or not factory_id_prefix.strip():
        raise ValueError("INVALID_FAST_LAYOUT_IDENTITY")
    roles = _roles()
    stride = len(roles) * block_spacing_columns + factory_gap_columns
    code = factory_recipe().code_id
    blocks = tuple(
        BlockSpec(
            f"{factory_id_prefix}{index}/{role}",
            code,
            3,
            f"{factory_id_prefix}{index}",
            role,
        )
        for index in range(factory_count)
        for role in roles
    )
    positions = {
        block.block_id: BlockPlacement(
            Position(
                origin.x + 10 * (index * stride + slot * block_spacing_columns),
                origin.y,
            )
        )
        for index in range(factory_count)
        for slot, block in enumerate(
            blocks[index * len(roles) : (index + 1) * len(roles)]
        )
    }
    return place(
        PlacementRequest(
            blocks=blocks,
            geometries={code: geometry(code, 3)},
            positions=positions,
        ),
        ExplicitPlacement(),
    )


def _bounds(value: Sequence[float] | None, name: str) -> list[float] | None:
    if value is None:
        return None
    if len(value) != 4 or any(
        type(v) not in (int, float) or not isfinite(v) for v in value
    ):
        raise ValueError(f"INVALID_FAST_DEVICE_REGION: {name}")
    region = Region(*value)
    return [region.x_min, region.y_min, region.x_max, region.y_max]


def legacy_regions(plan: PlacementPlan) -> tuple[list[float], list[float]]:
    """Return historical regions only for the compatibility layout entry.

    This explicit convention is not a readout-placement decision for arbitrary
    user plans, including the single-row vertical standard.
    """
    validate_plan(plan)
    origins = [placement.origin for placement in plan.placements.values()]
    if len({origin.y for origin in origins}) != 1:
        raise ValueError("LEGACY_FAST_REGIONS_REQUIRE_ONE_HORIZONTAL_ROW")
    left, right = (
        min(origin.x for origin in origins),
        max(origin.x for origin in origins) + 85,
    )
    y = origins[0].y
    return [left - 22, y - 2, right, y + 80], [left - 20, y + 90, right, y + 130]


def layout_from_plan(
    plan: PlacementPlan,
    *,
    aod_max_rows: int = 4,
    aod_max_columns: int = 48,
    max_readout_atoms: int = 96,
    aod_id: str = "transport",
    shared_bounds_um: Sequence[float] | None = None,
    readout_bounds_um: Sequence[float] | None = None,
    aod_workspace_bounds_um: Sequence[float] | None = None,
) -> FastLayout:
    """Bind existing patch metadata to an already validated placement plan.

    Device regions describe budgets, not readout sites or atom trajectories.
    Only the historical horizontal shape has default region metadata; other
    placements retain missing regions as None until the caller supplies them.
    Profile coverage is checked separately before estimates are used.
    """
    from .fast_profile import FastLayout, FastPatch, FastPlacement

    if not isinstance(plan, PlacementPlan):
        raise TypeError("INVALID_PLACEMENT_PLAN: expected a validated logical plan")
    validate_plan(plan)
    for label, value in (
        ("rows", aod_max_rows),
        ("columns", aod_max_columns),
        ("readout", max_readout_atoms),
    ):
        _positive(value, label)
    if not isinstance(aod_id, str) or not aod_id.strip():
        raise ValueError("INVALID_FAST_LAYOUT_IDENTITY")
    roles = _roles()
    code = factory_recipe().code_id
    groups: dict[str, dict[str, Any]] = {}
    for block in plan.blocks:
        if block.factory_id is None or block.role not in roles:
            raise ValueError("FAST_FACTORY_PLACEMENT_REQUIRES_NAMED_ROLES")
        selected = groups.setdefault(block.factory_id, {})
        if block.role in selected:
            raise ValueError("DUPLICATE_FAST_FACTORY_ROLE")
        selected[block.role] = block
    if not groups or any(set(group) != set(roles) for group in groups.values()):
        raise ValueError("FAST_FACTORY_PLACEMENT_REQUIRES_COMPLETE_ROLES")
    factories = tuple(
        FastPlacement(
            factory_id,
            tuple(
                FastPatch(
                    group[role].block_id,
                    factory_id,
                    role,
                    slot,
                    plan.placements[group[role].block_id].origin,
                    group[role].code,
                    group[role].distance,
                )
                for slot, role in enumerate(roles)
            ),
        )
        for factory_id, group in groups.items()
    )
    patches = tuple(patch for factory in factories for patch in factory.patches)
    ys = {patch.origin.y for patch in patches}
    historical_shape = (
        ys == {0}
        and all(patch.code_id == code and patch.distance == 3 for patch in patches)
        and all(
            plan.placements[patch.block_id].orientation == "standard"
            for patch in patches
        )
        and all(
            all(
                patch.origin.x == factory.patches[0].origin.x + 100 * patch.slot
                for patch in factory.patches
            )
            for factory in factories
        )
    )
    shared = _bounds(shared_bounds_um, "shared")
    readout = _bounds(readout_bounds_um, "readout")
    workspace = _bounds(aod_workspace_bounds_um, "AOD workspace")
    if historical_shape:
        legacy_shared, legacy_readout = legacy_regions(plan)
        shared = shared if shared is not None else legacy_shared
        readout = readout if readout is not None else legacy_readout
        if workspace is None and shared_bounds_um is None and readout_bounds_um is None:
            workspace = [legacy_shared[0] - 3, -5, legacy_shared[2] + 5, 135]
    budget = {
        "aod_count": 1,
        "aod_id": aod_id,
        "aod_max_rows": aod_max_rows,
        "aod_max_columns": aod_max_columns,
        "max_readout_atoms": max_readout_atoms,
        "factory_count": len(factories),
        "patch_count": len(patches),
        "atom_count_estimate": sum(definition(p.distance).atom_count for p in patches),
        "shared_bounds_um": shared,
        "readout_bounds_um": readout,
        "aod_workspace_bounds_um": workspace,
        "capacity_scales_with_factory_count": False,
        "geometry_fingerprint": plan.geometry_fingerprint,
        "representation": "logical_estimate",
    }
    return FastLayout(factories, budget, placement_plan=plan)
