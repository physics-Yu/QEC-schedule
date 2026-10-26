"""Pure code-aware block placement shared by logical and physical execution."""

from .model import (
    BlockPlacement,
    BlockSpec,
    PlacementPlan,
    PlacementRequest,
    PlacementStrategy,
)
from .strategies import (
    ExplicitPlacement,
    GridFactoryPlacement,
    VerticalFactoryPlacement,
    block_bounds,
    place,
    validate_plan,
)

__all__ = [
    "BlockPlacement",
    "BlockSpec",
    "ExplicitPlacement",
    "GridFactoryPlacement",
    "PlacementPlan",
    "PlacementRequest",
    "PlacementStrategy",
    "VerticalFactoryPlacement",
    "block_bounds",
    "place",
    "validate_plan",
]
