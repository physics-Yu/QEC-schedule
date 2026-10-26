"""Replaceable pure geometry strategies and common initial/return validation."""

import json
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from hashlib import sha256
from heapq import heappop, heappush
from itertools import accumulate
from math import hypot, isfinite

from nadit_physical_compiler.device import Position, Region

from modules.codes.contracts.geometry import BlockGeometry

from .model import (
    BlockPlacement,
    BlockSpec,
    PlacementPlan,
    PlacementRequest,
    PlacementStrategy,
)


def block_bounds(geometry: BlockGeometry, placement: BlockPlacement) -> Region:
    """Return a translated, code-authorized footprint for cache and layout checks.

    Raises ValueError when the code has not declared the requested orientation.
    This is a static footprint, never the swept region of a component operation.
    """
    if placement.orientation not in geometry.allowed_orientations:
        raise ValueError(f"UNSUPPORTED_PLACEMENT_ORIENTATION: {placement.orientation}")
    bounds = geometry.relative_bounds
    turns = {"standard": 0, "rot90": 1, "rot180": 2, "rot270": 3}[placement.orientation]
    corners = []
    for x in (bounds.x_min, bounds.x_max):
        for y in (bounds.y_min, bounds.y_max):
            dx, dy = x, y
            for _ in range(turns):
                dx, dy = -dy, dx
            corners.append((placement.origin.x + dx, placement.origin.y + dy))
    return Region(
        min(x for x, _ in corners),
        min(y for _, y in corners),
        max(x for x, _ in corners),
        max(y for _, y in corners),
    )


def _projection_count(intervals: list[tuple[float, str, float, float, float]]) -> int:
    """Count conservative projected pairs without enumerating them."""
    ends: list[float] = []
    count = 0
    for start, _, end, _, _ in intervals:
        while ends and ends[0] < start:
            heappop(ends)
        count += len(ends)
        heappush(ends, end)
    return count


def _candidate_pairs(
    boxes: Mapping[str, Region], spacing: Mapping[str, float]
) -> Iterator[tuple[str, str]]:
    """Sweep the less-overlapping axis of spacing-expanded closed footprints.

    Expanding each block by its own spacing conservatively includes every pair
    violating max(spacing_a, spacing_b). A second-axis filter removes unrelated
    intervals before exact Euclidean checks. Axis selection costs O(n log n);
    sparse regular rows or columns avoid all-pairs work. Dense overlap can still
    require quadratic candidate work, without changing admission semantics.
    """
    projections = [
        sorted(
            (
                float(getattr(box, axis + "_min") - spacing[identity]),
                identity,
                float(getattr(box, axis + "_max") + spacing[identity]),
                float(getattr(box, other + "_min") - spacing[identity]),
                float(getattr(box, other + "_max") + spacing[identity]),
            )
            for identity, box in boxes.items()
        )
        for axis, other in (("x", "y"), ("y", "x"))
    ]
    intervals = min(projections, key=_projection_count)
    expiry: list[tuple[float, str]] = []
    active: dict[str, tuple[float, float]] = {}
    for start, identity, end, lower, upper in intervals:
        while expiry and expiry[0][0] < start:
            _, previous = heappop(expiry)
            del active[previous]
        for previous, (other_lower, other_upper) in active.items():
            if lower <= other_upper and other_lower <= upper:
                yield previous, identity
        active[identity] = (lower, upper)
        heappush(expiry, (end, identity))


def _validate(
    request: PlacementRequest, placements: Mapping[str, BlockPlacement]
) -> Region:
    expected = {block.block_id for block in request.blocks}
    if set(placements) != expected:
        raise ValueError(
            "INCOMPLETE_PLACEMENT: "
            f"missing={sorted(expected - placements.keys())}, "
            f"extra={sorted(placements.keys() - expected)}"
        )
    boxes = {}
    by_id = {block.block_id: block for block in request.blocks}
    for block_id, placement in placements.items():
        if not isinstance(placement, BlockPlacement):
            raise TypeError(f"INVALID_BLOCK_PLACEMENT: {block_id}")
        box = block_bounds(request.geometries[by_id[block_id].code], placement)
        if request.region is not None and not (
            request.region.contains(Position(box.x_min, box.y_min))
            and request.region.contains(Position(box.x_max, box.y_max))
        ):
            raise ValueError(f"PLACEMENT_OUTSIDE_REGION: {block_id}")
        boxes[block_id] = box
    spacing = {
        block.block_id: request.geometries[block.code].minimum_spacing_um
        for block in request.blocks
    }
    for first, second in _candidate_pairs(boxes, spacing):
        a, b = boxes[first], boxes[second]
        dx = max(a.x_min - b.x_max, b.x_min - a.x_max, 0)
        dy = max(a.y_min - b.y_max, b.y_min - a.y_max, 0)
        if not dx and not dy:
            raise ValueError(f"PLACEMENT_OVERLAP: {first}, {second}")
        if hypot(dx, dy) < max(spacing[first], spacing[second]):
            raise ValueError(f"PLACEMENT_SPACING: {first}, {second}")
    return Region(
        min(box.x_min for box in boxes.values()),
        min(box.y_min for box in boxes.values()),
        max(box.x_max for box in boxes.values()),
        max(box.y_max for box in boxes.values()),
    )


def _fingerprint(
    blocks: tuple[BlockSpec, ...],
    geometries: Mapping[str, BlockGeometry],
    placements: Mapping[str, BlockPlacement],
) -> str:
    document = {
        "blocks": [
            block.to_dict() for block in sorted(blocks, key=lambda b: b.block_id)
        ],
        "geometries": {
            key: value.to_dict() for key, value in sorted(geometries.items())
        },
        "placements": {
            key: value.to_dict() for key, value in sorted(placements.items())
        },
    }
    return sha256(
        json.dumps(
            document, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def validate_plan(plan: PlacementPlan) -> PlacementPlan:
    """Recheck an externally supplied plan, including bounds and fingerprint.

    Records constructed directly or with dataclasses.replace must satisfy the
    same geometry contract as strategy output. Returns the unchanged valid plan;
    raises TypeError for wrong records or ValueError for inconsistent geometry,
    occupancy or fingerprints. Device constraints beyond this recorded geometry
    remain the downstream consumer's responsibility.
    """
    if not isinstance(plan, PlacementPlan):
        raise TypeError("INVALID_PLACEMENT_PLAN")
    request = PlacementRequest(plan.blocks, plan.geometries, positions=plan.placements)
    if set(plan.geometries) != {block.code for block in plan.blocks}:
        raise ValueError("PLACEMENT_PLAN_GEOMETRY_MISMATCH")
    bounds = _validate(request, plan.placements)
    if plan.occupied_bounds != bounds:
        raise ValueError("PLACEMENT_PLAN_BOUNDS_MISMATCH")
    if plan.geometry_fingerprint != _fingerprint(
        plan.blocks, plan.geometries, plan.placements
    ):
        raise ValueError("PLACEMENT_PLAN_FINGERPRINT_MISMATCH")
    return plan


def place(request: PlacementRequest, strategy: PlacementStrategy) -> PlacementPlan:
    """Validate a strategy's proposal and return immutable geometry evidence.

    No physical compiler, probability backend or quantum-state model is invoked.
    Raises TypeError for invalid records/strategies and ValueError for incomplete
    positions, forbidden orientations, region violations, overlap or spacing.
    """
    if not isinstance(request, PlacementRequest):
        raise TypeError("INVALID_PLACEMENT_REQUEST")
    if not callable(getattr(strategy, "place", None)):
        raise TypeError("INVALID_PLACEMENT_STRATEGY")
    proposed = strategy.place(request)
    if not isinstance(proposed, Mapping):
        raise TypeError("INVALID_PLACEMENT_PROPOSAL: expected a mapping")
    placements = dict(proposed)
    bounds = _validate(request, placements)
    geometries = {
        block.code: request.geometries[block.code] for block in request.blocks
    }
    fingerprint = _fingerprint(request.blocks, geometries, placements)
    return PlacementPlan(request.blocks, geometries, placements, bounds, fingerprint)


@dataclass(frozen=True, slots=True)
class ExplicitPlacement:
    """Use the user's requested positions; common validation rejects omissions."""

    def place(self, request: PlacementRequest) -> Mapping[str, BlockPlacement]:
        """Return the explicit proposal without changing origins or orientations."""
        return request.positions


@dataclass(frozen=True, slots=True)
class VerticalFactoryPlacement:
    """Place factory rows below y=0 using code footprints and caller role order.

    Factories retain their first appearance order in request.blocks. A factory
    must use one code/distance and exactly the caller's role set. Different rows
    may use different sizes. Neither role names nor factory protocols are built
    into this strategy. Both gaps are positive physical micrometers.
    """

    role_order: tuple[str, ...]
    patch_gap_um: float = 40
    factory_gap_um: float = 40

    def __post_init__(self) -> None:
        if (
            not isinstance(self.role_order, tuple)
            or not self.role_order
            or any(
                not isinstance(role, str) or not role.strip()
                for role in self.role_order
            )
            or len(set(self.role_order)) != len(self.role_order)
        ):
            raise ValueError("INVALID_FACTORY_ROLES")
        for name in ("patch_gap_um", "factory_gap_um"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not isfinite(value) or value <= 0:
                raise ValueError(f"INVALID_PLACEMENT_GAP: {name}")

    def place(self, request: PlacementRequest) -> Mapping[str, BlockPlacement]:
        """Pack code-declared footprints and leave routing to downstream compilers."""
        if request.positions:
            raise ValueError("VERTICAL_PLACEMENT_POSITIONS: use ExplicitPlacement")
        factories: dict[str, list[BlockSpec]] = {}
        for block in request.blocks:
            if block.factory_id is None or block.role is None:
                raise ValueError("MISSING_FACTORY_PLACEMENT_IDENTITY")
            factories.setdefault(block.factory_id, []).append(block)
        placements = {}
        top = 0.0
        for factory_id, blocks in factories.items():
            roles = {block.role: block for block in blocks}
            if len(roles) != len(blocks) or set(roles) != set(self.role_order):
                raise ValueError(f"INVALID_FACTORY_ROLES: {factory_id}")
            if len({(block.code, block.distance) for block in blocks}) != 1:
                raise ValueError(f"MIXED_FACTORY_GEOMETRY: {factory_id}")
            bounds = request.geometries[blocks[0].code].relative_bounds
            bottom = top - (bounds.y_max - bounds.y_min)
            left = 0.0
            for role in self.role_order:
                block = roles[role]
                placements[block.block_id] = BlockPlacement(
                    Position(left - bounds.x_min, top - bounds.y_max)
                )
                left += bounds.x_max - bounds.x_min + self.patch_gap_um
            top = bottom - self.factory_gap_um
        return placements


@dataclass(frozen=True, slots=True)
class GridFactoryPlacement:
    """Arrange whole factories in rows below y=0 with fixed internal role order.

    ``columns`` counts factories, not code blocks. Factories retain request order
    and fill rows left to right. Each column fits its widest factory and each row
    fits its tallest factory, using only code-owned footprints. Gaps are positive
    micrometers. One column preserves the vertical strategy's exact coordinates.
    """

    role_order: tuple[str, ...]
    columns: int = 1
    patch_gap_um: float = 40
    factory_gap_x_um: float = 40
    factory_gap_y_um: float = 40

    def __post_init__(self) -> None:
        if type(self.columns) is not int or self.columns < 1:
            raise ValueError("INVALID_GRID_COLUMNS: positive integer required")
        VerticalFactoryPlacement(
            self.role_order, self.patch_gap_um, self.factory_gap_y_um
        )
        if (
            type(self.factory_gap_x_um) not in (int, float)
            or not isfinite(self.factory_gap_x_um)
            or self.factory_gap_x_um <= 0
        ):
            raise ValueError("INVALID_PLACEMENT_GAP: factory_gap_x_um")

    def place(self, request: PlacementRequest) -> Mapping[str, BlockPlacement]:
        """Translate complete validated factory arrangements into grid cells.

        Explicit positions and malformed factory roles/code identities raise
        ValueError through the existing vertical strategy. Common ``place``
        subsequently checks footprint spacing, bounds and orientation constraints.
        """
        vertical = VerticalFactoryPlacement(
            self.role_order, self.patch_gap_um, self.factory_gap_y_um
        ).place(request)
        if self.columns == 1:
            return vertical
        factories: dict[str, list[BlockSpec]] = {}
        for block in request.blocks:
            assert block.factory_id is not None
            factories.setdefault(block.factory_id, []).append(block)
        groups = tuple(factories.values())
        boxes = []
        for group in groups:
            members = [
                block_bounds(request.geometries[b.code], vertical[b.block_id])
                for b in group
            ]
            boxes.append(
                Region(
                    min(b.x_min for b in members),
                    min(b.y_min for b in members),
                    max(b.x_max for b in members),
                    max(b.y_max for b in members),
                )
            )
        columns = min(self.columns, len(groups))
        widths = [
            max(b.x_max - b.x_min for b in boxes[c::columns]) for c in range(columns)
        ]
        heights = [
            max(b.y_max - b.y_min for b in boxes[r : r + columns])
            for r in range(0, len(boxes), columns)
        ]
        lefts = tuple(
            accumulate((w + self.factory_gap_x_um for w in widths), initial=0)
        )
        tops = tuple(
            accumulate((-h - self.factory_gap_y_um for h in heights), initial=0)
        )
        placements = {}
        for index, group in enumerate(groups):
            row, column = divmod(index, columns)
            box = boxes[index]
            for block in group:
                original = vertical[block.block_id]
                placements[block.block_id] = BlockPlacement(
                    Position(
                        original.origin.x + lefts[column] - box.x_min,
                        original.origin.y + tops[row] - box.y_max,
                    ),
                    original.orientation,
                )
        return placements
