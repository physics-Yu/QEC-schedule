"""Two-dimensional geometry. Hardware lengths are in micrometres (um)."""
from dataclasses import dataclass
import math


def finite_number(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")
    return float(value)


@dataclass(frozen=True)
class Position:
    x: float
    y: float

    def __post_init__(self):
        object.__setattr__(self, "x", finite_number(self.x, "x"))
        object.__setattr__(self, "y", finite_number(self.y, "y"))

    def distance_to(self, other: "Position") -> float:
        return math.hypot(self.x - other.x, self.y - other.y)

    def to_list(self):
        return [self.x, self.y]


@dataclass(frozen=True)
class Bounds:
    xmin: float
    ymin: float
    xmax: float
    ymax: float

    def __post_init__(self):
        for name in ("xmin", "ymin", "xmax", "ymax"):
            object.__setattr__(self, name, finite_number(getattr(self, name), name))
        if self.xmin >= self.xmax or self.ymin >= self.ymax:
            raise ValueError("Zone bounds must have positive width and height")

    def contains(self, position: Position) -> bool:
        return self.xmin <= position.x <= self.xmax and self.ymin <= position.y <= self.ymax

    def overlaps(self, other: "Bounds") -> bool:
        """Positive area overlap; adjacent zone boundaries may touch."""
        return (max(self.xmin, other.xmin) < min(self.xmax, other.xmax)
                and max(self.ymin, other.ymin) < min(self.ymax, other.ymax))

    def to_list(self):
        return [self.xmin, self.ymin, self.xmax, self.ymax]
