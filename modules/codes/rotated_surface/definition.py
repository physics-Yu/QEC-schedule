"""Odd-distance rotated CSS patches in the existing distance-three convention."""

from dataclasses import dataclass
from functools import cache


@dataclass(frozen=True)
class SurfaceCodeDefinition:
    """Immutable geometry, check order, logical strings, and physical roles."""

    distance: int
    checks: tuple[tuple[str, tuple[int, ...]], ...]
    data_coordinates: tuple[tuple[int, int], ...]
    check_coordinates: tuple[tuple[int, int], ...]

    @property
    def data_count(self) -> int:
        """Number of data atoms."""
        return self.distance**2

    @property
    def check_count(self) -> int:
        """Number of independent stabilizer checks."""
        return self.data_count - 1

    @property
    def atom_count(self) -> int:
        """Number of data and dedicated syndrome atoms."""
        return self.data_count + self.check_count

    @property
    def check_roles(self) -> tuple[str, ...]:
        """X checks in row order, followed by Z checks in column order."""
        return tuple(
            f"{b}{i}" for b in ("X", "Z") for i in range(self.check_count // 2)
        )

    @property
    def roles(self) -> tuple[str, ...]:
        """Ordered data and syndrome roles, compatible with the d3 contract."""
        return tuple(f"data[{q}]" for q in range(self.data_count)) + self.check_roles

    @property
    def reference_coordinates(self) -> tuple[tuple[int, int], ...]:
        """Integer local coordinates in units of the caller's chosen pitch."""
        return self.data_coordinates + self.check_coordinates

    @property
    def reference_homes(self) -> tuple[str, ...]:
        """Reference grid site names; callers may supply their own homes."""
        return tuple(f"home_r{y}_c{x}" for x, y in self.reference_coordinates)

    @property
    def logical_x(self) -> tuple[int, ...]:
        """Left-column representative of logical X."""
        return tuple(range(0, self.data_count, self.distance))

    @property
    def logical_z(self) -> tuple[int, ...]:
        """Top-row representative of logical Z."""
        return tuple(range(self.distance))


def definition(distance: int) -> SurfaceCodeDefinition:
    """Construct an odd-distance patch; reject noninteger/even/small distances.

    Args:
        distance: Odd integer at least three; physical capacity is caller-owned.
    Returns:
        A cached immutable code definition with no device or runtime state.
    Raises:
        ValueError: If the distance is not an odd integer at least three.
    """
    if type(distance) is not int or distance < 3 or distance % 2 == 0:
        raise ValueError("Surface-code distance must be an odd integer at least 3.")
    return _definition(distance)


@cache
def _definition(distance: int) -> SurfaceCodeDefinition:
    data = tuple(
        (2 * (q % distance) + 1, 2 * (q // distance) + 1) for q in range(distance**2)
    )
    xs, zs = [], []
    for y in range(0, 2 * distance + 1, 2):
        for x in range(0, 2 * distance + 1, 2):
            basis = "X" if (x // 2 + y // 2) % 2 else "Z"
            if basis == "X" and 0 < x < 2 * distance:
                xs.append((x, y))
            elif basis == "Z" and 0 < y < 2 * distance:
                zs.append((x, y))
    coordinates = tuple(sorted(xs, key=lambda p: (p[1], p[0])) + sorted(zs))
    checks = tuple(
        (
            "X" if i < len(xs) else "Z",
            tuple(
                q for q, (dx, dy) in enumerate(data) if abs(dx - x) == abs(dy - y) == 1
            ),
        )
        for i, (x, y) in enumerate(coordinates)
    )
    return SurfaceCodeDefinition(distance, checks, data, coordinates)
