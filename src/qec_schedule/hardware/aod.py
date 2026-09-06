"""MVP TRANSLATE compatibility; no crossed-AOD line dynamics or atom-capacity cap."""
from dataclasses import dataclass
from itertools import combinations
import math

from .geometry import Bounds, Position, finite_number


@dataclass(frozen=True)
class Translation:
    atom: str
    source: Position
    target: Position

    def __post_init__(self):
        if not isinstance(self.atom, str) or not self.atom:
            raise ValueError("Translation requires an atom ID")
        for value in self.displacement:
            finite_number(value, "displacement")
        if self.source == self.target:
            raise ValueError("Zero-distance translation must be omitted")

    @property
    def displacement(self):
        return (self.target.x - self.source.x, self.target.y - self.source.y)


@dataclass(frozen=True)
class AODController:
    max_x_tones: int
    max_y_tones: int
    allowed_region: Bounds
    allowed_primitives: tuple[str, ...] = ("TRANSLATE",)
    displacement_tolerance: float = 1e-9  # Absolute um, never relative tolerance.

    def __post_init__(self):
        object.__setattr__(self, "allowed_primitives", tuple(self.allowed_primitives))
        for count in (self.max_x_tones, self.max_y_tones):
            if type(count) is not int or count <= 0:
                raise ValueError("AOD tone limits must be positive integers")
        if not isinstance(self.allowed_region, Bounds):
            raise ValueError("allowed_region must be Bounds")
        if self.allowed_primitives != ("TRANSLATE",):
            raise ValueError("This version implements only TRANSLATE")
        tolerance = finite_number(self.displacement_tolerance, "displacement_tolerance")
        if tolerance < 0:
            raise ValueError("Displacement tolerance must be nonnegative")
        object.__setattr__(self, "displacement_tolerance", tolerance)

    @staticmethod
    def tone_counts(translations):
        """Conservative distinct-coordinate counts at both endpoints."""
        translations = tuple(translations)
        return tuple(max(len({getattr(getattr(t, endpoint), axis) for t in translations})
                         for endpoint in ("source", "target")) for axis in ("x", "y"))

    def incompatibility(self, translations) -> str | None:
        translations = tuple(translations)
        if not translations:
            return "empty epoch"
        if len({t.atom for t in translations}) != len(translations):
            return "duplicate atom"
        if any(not self.allowed_region.contains(p) for t in translations for p in (t.source, t.target)):
            return "outside AOD allowed region"
        if len({t.source for t in translations}) != len(translations) or len({t.target for t in translations}) != len(translations):
            return "duplicate source or destination position"
        # Pairwise comparison avoids approximate-equality chaining (A~B~C).
        for left, right in combinations(translations, 2):
            if any(not math.isclose(a, b, abs_tol=self.displacement_tolerance, rel_tol=0)
                   for a, b in zip(left.displacement, right.displacement)):
                return "different displacement vectors"
        x, y = self.tone_counts(translations)
        if x > self.max_x_tones or y > self.max_y_tones:
            return "x/y tone budget exceeded"
        return None

    def compatible(self, translations) -> bool:
        return self.incompatibility(translations) is None

    def to_dict(self):
        return {"max_x_tones": self.max_x_tones, "max_y_tones": self.max_y_tones,
                "allowed_region": self.allowed_region.to_list(), "allowed_primitives": list(self.allowed_primitives),
                "displacement_tolerance": self.displacement_tolerance}
