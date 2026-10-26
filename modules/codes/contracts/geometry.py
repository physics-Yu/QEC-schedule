"""Code-owned initial/return footprints, independent of component execution."""

from dataclasses import dataclass
from math import isfinite
from typing import Any

from nadit_physical_compiler.device import Region

ORIENTATIONS = ("standard", "rot90", "rot180", "rot270")


@dataclass(frozen=True, slots=True)
class BlockGeometry:
    """Describe a block's local footprint and permitted planar orientations.

    Bounds use micrometers in the standard orientation. Rotations, when explicitly
    allowed by the code, are counterclockwise about the block origin. Spacing is
    the minimum Euclidean distance between two closed footprints. Neither this
    record nor its version certifies a component's movement envelope or gate.
    """

    code_id: str
    distance: int
    relative_bounds: Region
    allowed_orientations: tuple[str, ...] = ("standard",)
    minimum_spacing_um: float = 0
    version: str = "code_geometry/1"

    def __post_init__(self) -> None:
        for name in ("code_id", "version"):
            if (
                not isinstance(getattr(self, name), str)
                or not getattr(self, name).strip()
            ):
                raise ValueError(f"INVALID_BLOCK_GEOMETRY: {name} must be nonempty")
        if type(self.distance) is not int or self.distance < 1:
            raise ValueError("INVALID_BLOCK_GEOMETRY: distance must be positive")
        if not isinstance(self.relative_bounds, Region):
            raise TypeError("INVALID_BLOCK_GEOMETRY: relative_bounds must be a Region")
        if (
            not isinstance(self.allowed_orientations, tuple)
            or not self.allowed_orientations
            or len(set(self.allowed_orientations)) != len(self.allowed_orientations)
            or any(value not in ORIENTATIONS for value in self.allowed_orientations)
        ):
            raise ValueError(
                "INVALID_BLOCK_GEOMETRY: unsupported orientation declarations"
            )
        if (
            type(self.minimum_spacing_um) not in (int, float)
            or not isfinite(self.minimum_spacing_um)
            or self.minimum_spacing_um < 0
        ):
            raise ValueError(
                "INVALID_BLOCK_GEOMETRY: spacing must be finite and nonnegative"
            )

    def to_dict(self) -> dict[str, Any]:
        """Return independent JSON-ready geometry and version declarations."""
        bounds = self.relative_bounds
        return {
            "code_id": self.code_id,
            "distance": self.distance,
            "relative_bounds": {
                name: float(getattr(bounds, name))
                for name in ("x_min", "y_min", "x_max", "y_max")
            },
            "allowed_orientations": list(self.allowed_orientations),
            "minimum_spacing_um": float(self.minimum_spacing_um),
            "version": self.version,
        }
