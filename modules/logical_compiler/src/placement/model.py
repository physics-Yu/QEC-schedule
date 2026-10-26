"""Immutable logical placement inputs and results; no atom or sampler state."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import isfinite
from types import MappingProxyType
from typing import Any, Protocol

from nadit_physical_compiler.device import Position, Region

from modules.codes.contracts.geometry import BlockGeometry


def _identity(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"INVALID_PLACEMENT_IDENTITY: {field_name}")


@dataclass(frozen=True, slots=True)
class BlockSpec:
    """One logical block's explicit code identity and optional factory role."""

    block_id: str
    code: str
    distance: int
    factory_id: str | None = None
    role: str | None = None

    def __post_init__(self) -> None:
        _identity(self.block_id, "block_id")
        _identity(self.code, "code")
        if type(self.distance) is not int or self.distance < 1:
            raise ValueError("INVALID_PLACEMENT_DISTANCE")
        for name in ("factory_id", "role"):
            value = getattr(self, name)
            if value is not None:
                _identity(value, name)

    def to_dict(self) -> dict[str, Any]:
        """Return JSON metadata without a physical carrier assignment."""
        return {
            "block_id": self.block_id,
            "code": self.code,
            "distance": self.distance,
            "factory_id": self.factory_id,
            "role": self.role,
        }


@dataclass(frozen=True, slots=True)
class BlockPlacement:
    """An initial/return origin and code-permitted orientation; never a move."""

    origin: Position
    orientation: str = "standard"

    def __post_init__(self) -> None:
        if not isinstance(self.origin, Position) or any(
            type(value) not in (int, float) or not isfinite(value)
            for value in (self.origin.x, self.origin.y)
        ):
            raise ValueError("INVALID_PLACEMENT_ORIGIN: finite coordinates required")
        _identity(self.orientation, "orientation")

    def to_dict(self) -> dict[str, Any]:
        """Return a fresh JSON-ready origin and orientation."""
        return {
            "origin": {"x": float(self.origin.x), "y": float(self.origin.y)},
            "orientation": self.orientation,
        }


@dataclass(frozen=True, slots=True)
class PlacementRequest:
    """Blocks, code geometry, optional home region and explicit user positions.

    Geometries are keyed by concrete code ID. Region constrains initial/return
    footprints, not temporary readout sites or component motion. Missing geometry,
    duplicate block identities and mismatched distances are rejected immediately.
    """

    blocks: tuple[BlockSpec, ...]
    geometries: Mapping[str, BlockGeometry]
    region: Region | None = None
    positions: Mapping[str, BlockPlacement] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.blocks, tuple) or not self.blocks:
            raise ValueError(
                "INVALID_PLACEMENT_BLOCKS: a nonempty immutable list is required"
            )
        if any(not isinstance(block, BlockSpec) for block in self.blocks):
            raise TypeError("INVALID_PLACEMENT_BLOCK: expected BlockSpec")
        if len({block.block_id for block in self.blocks}) != len(self.blocks):
            raise ValueError("DUPLICATE_PLACEMENT_BLOCK")
        if not isinstance(self.geometries, Mapping) or not isinstance(
            self.positions, Mapping
        ):
            raise TypeError("INVALID_PLACEMENT_MAPPING")
        geometries = dict(self.geometries)
        for code, item in geometries.items():
            if not isinstance(item, BlockGeometry) or code != item.code_id:
                raise ValueError("INVALID_CODE_GEOMETRY_MAPPING")
        for block in self.blocks:
            if block.code not in geometries:
                raise ValueError(f"MISSING_PLACEMENT_GEOMETRY: {block.code}")
            if geometries[block.code].distance != block.distance:
                raise ValueError(f"PLACEMENT_DISTANCE_MISMATCH: {block.block_id}")
        if self.region is not None and not isinstance(self.region, Region):
            raise TypeError("INVALID_PLACEMENT_REGION")
        positions = dict(self.positions)
        for block_id, position in positions.items():
            _identity(block_id, "position block_id")
            if not isinstance(position, BlockPlacement):
                raise TypeError("INVALID_BLOCK_PLACEMENT")
        object.__setattr__(self, "geometries", MappingProxyType(geometries))
        object.__setattr__(self, "positions", MappingProxyType(positions))


class PlacementStrategy(Protocol):
    """Return proposed origins; the common placement entry validates every result."""

    def place(self, request: PlacementRequest) -> Mapping[str, BlockPlacement]:
        """Propose one placement per requested block without executing components."""
        ...


@dataclass(frozen=True, slots=True)
class PlacementPlan:
    """Validated initial/return placements with deterministic geometry identity.

    Construct through ``place`` to establish completeness, bounds and spacing.
    The geometry fingerprint covers block identities, footprints and placements;
    downstream calibration must separately check Device, component and spectator
    assumptions before reusing any execution or cost record.
    """

    blocks: tuple[BlockSpec, ...]
    geometries: Mapping[str, BlockGeometry]
    placements: Mapping[str, BlockPlacement]
    occupied_bounds: Region
    geometry_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "geometries", MappingProxyType(dict(self.geometries)))
        object.__setattr__(self, "placements", MappingProxyType(dict(self.placements)))

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> PlacementPlan:
        """Restore and revalidate saved geometry evidence without regenerating it.

        The document must use ``nadit.logical_placement/1``. Invalid records,
        occupancy, bounds or fingerprints raise ValueError. Consumers still
        check code-owned geometry versions and physical-device applicability.
        """
        from .strategies import validate_plan

        if (
            not isinstance(document, Mapping)
            or document.get("schema") != "nadit.logical_placement/1"
        ):
            raise ValueError("INVALID_PLACEMENT_DOCUMENT_SCHEMA")
        try:
            plan = cls(
                blocks=tuple(BlockSpec(**block) for block in document["blocks"]),
                geometries={
                    identity: BlockGeometry(
                        code_id=row["code_id"],
                        distance=row["distance"],
                        relative_bounds=Region(**row["relative_bounds"]),
                        allowed_orientations=tuple(row["allowed_orientations"]),
                        minimum_spacing_um=row["minimum_spacing_um"],
                        version=row["version"],
                    )
                    for identity, row in document["geometries"].items()
                },
                placements={
                    identity: BlockPlacement(
                        Position(**row["origin"]), row["orientation"]
                    )
                    for identity, row in document["placements"].items()
                },
                occupied_bounds=Region(**document["occupied_bounds"]),
                geometry_fingerprint=document["geometry_fingerprint"],
            )
        except (KeyError, TypeError, ValueError, AttributeError) as error:
            raise ValueError(f"INVALID_PLACEMENT_DOCUMENT: {error}") from error
        return validate_plan(plan)

    def to_dict(self) -> dict[str, Any]:
        """Export fresh geometry evidence without atom IDs, routing or probabilities."""
        return {
            "schema": "nadit.logical_placement/1",
            "blocks": [block.to_dict() for block in self.blocks],
            "geometries": {
                key: item.to_dict() for key, item in sorted(self.geometries.items())
            },
            "placements": {
                key: item.to_dict() for key, item in sorted(self.placements.items())
            },
            "occupied_bounds": {
                name: float(getattr(self.occupied_bounds, name))
                for name in ("x_min", "y_min", "x_max", "y_max")
            },
            "geometry_fingerprint": self.geometry_fingerprint,
        }
