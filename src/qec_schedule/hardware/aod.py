"""Explicit crossed-AOD tones, trajectories, and feasibility planning."""
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import math
from types import MappingProxyType

from .geometry import Bounds, Position, finite_number


@dataclass(frozen=True)
class Translation:
    """A source/target movement used by both the new and migration planners."""

    atom: str
    source: Position
    target: Position

    def __post_init__(self):
        if not isinstance(self.atom, str) or not self.atom:
            raise ValueError("Translation requires an atom ID")
        if not isinstance(self.source, Position) or not isinstance(self.target, Position):
            raise ValueError("Translation endpoints must be Position values")
        for value in self.displacement:
            finite_number(value, "displacement")
        if self.source == self.target:
            raise ValueError("Zero-distance translation must be omitted")

    @property
    def displacement(self):
        return (self.target.x - self.source.x, self.target.y - self.source.y)


@dataclass(frozen=True)
class AODTone:
    id: str
    axis: str

    def __post_init__(self):
        if not isinstance(self.id, str) or not self.id or self.axis not in ("x", "y"):
            raise ValueError("AOD tone needs an ID and axis x/y")

    def to_dict(self):
        return {"id": self.id, "axis": self.axis}


@dataclass(frozen=True)
class AtomAODBinding:
    atom: str
    x_tone: str
    y_tone: str

    def __post_init__(self):
        if any(not isinstance(value, str) or not value for value in (self.atom, self.x_tone, self.y_tone)):
            raise ValueError("AOD binding requires atom, x tone, and y tone IDs")

    def to_dict(self):
        return {"atom": self.atom, "x_tone": self.x_tone, "y_tone": self.y_tone}


@dataclass(frozen=True)
class AxisTrajectory:
    tone_id: str
    axis: str
    start: float
    end: float
    start_time: float
    duration: float

    def __post_init__(self):
        if not isinstance(self.tone_id, str) or not self.tone_id or self.axis not in ("x", "y"):
            raise ValueError("Axis trajectory needs a tone ID and axis x/y")
        for name in ("start", "end", "start_time", "duration"):
            value = finite_number(getattr(self, name), name)
            object.__setattr__(self, name, value)
        if self.start_time < 0 or self.duration <= 0:
            raise ValueError("Trajectory start time must be nonnegative and duration positive")

    def to_dict(self):
        return {"tone_id": self.tone_id, "axis": self.axis, "start": self.start,
                "end": self.end, "start_time": self.start_time, "duration": self.duration}


@dataclass(frozen=True)
class AODProgram:
    bindings: tuple[AtomAODBinding, ...]
    x_trajectories: tuple[AxisTrajectory, ...]
    y_trajectories: tuple[AxisTrajectory, ...]
    atom_sources: Mapping[str, Position]
    atom_targets: Mapping[str, Position]
    duration: float
    axis_execution: str = "simultaneous"

    def __post_init__(self):
        object.__setattr__(self, "bindings", tuple(self.bindings))
        object.__setattr__(self, "x_trajectories", tuple(self.x_trajectories))
        object.__setattr__(self, "y_trajectories", tuple(self.y_trajectories))
        object.__setattr__(self, "atom_sources", MappingProxyType(dict(self.atom_sources)))
        object.__setattr__(self, "atom_targets", MappingProxyType(dict(self.atom_targets)))
        duration = finite_number(self.duration, "duration")
        if duration <= 0 or self.axis_execution not in ("simultaneous", "x_then_y", "y_then_x"):
            raise ValueError("Invalid AOD program duration or axis execution mode")
        object.__setattr__(self, "duration", duration)
        atoms = tuple(binding.atom for binding in self.bindings)
        if len(set(atoms)) != len(atoms) or set(atoms) != set(self.atom_sources) or set(atoms) != set(self.atom_targets):
            raise ValueError("AOD program bindings and atom endpoints must match")
        for trajectory in (*self.x_trajectories, *self.y_trajectories):
            if trajectory.axis not in ("x", "y"):
                raise ValueError("Invalid trajectory axis")

    @property
    def x_tones_used(self):
        return len({trajectory.tone_id for trajectory in self.x_trajectories})

    @property
    def y_tones_used(self):
        return len({trajectory.tone_id for trajectory in self.y_trajectories})

    @property
    def atoms(self):
        return tuple(binding.atom for binding in self.bindings)

    def to_dict(self):
        return {
            "axis_execution": self.axis_execution,
            "duration": self.duration,
            "bindings": [binding.to_dict() for binding in self.bindings],
            "x_trajectories": [trajectory.to_dict() for trajectory in self.x_trajectories],
            "y_trajectories": [trajectory.to_dict() for trajectory in self.y_trajectories],
            "atom_sources": {atom: position.to_list() for atom, position in self.atom_sources.items()},
            "atom_targets": {atom: position.to_list() for atom, position in self.atom_targets.items()},
            "x_tones_used": self.x_tones_used,
            "y_tones_used": self.y_tones_used,
        }


def _axis_key(translation: Translation, axis: str):
    source = getattr(translation.source, axis)
    target = getattr(translation.target, axis)
    return ("static",) if math.isclose(source, target, abs_tol=1e-12, rel_tol=0) else (source, target)


def _legacy_incompatibility(controller, translations):
    """Compatibility predicate retained only for LegacyMovementPlanner."""
    translations = tuple(translations)
    if not translations:
        return "empty epoch"
    if len({t.atom for t in translations}) != len(translations):
        return "duplicate atom"
    if any(not controller.allowed_region.contains(p) for t in translations for p in (t.source, t.target)):
        return "outside AOD allowed region"
    if len({t.source for t in translations}) != len(translations) or len({t.target for t in translations}) != len(translations):
        return "duplicate source or destination position"
    for left in translations[1:]:
        if any(not math.isclose(a, b, abs_tol=controller.displacement_tolerance, rel_tol=0)
               for a, b in zip(left.displacement, translations[0].displacement)):
            return "different displacement vectors"
    x_count = max(len({getattr(getattr(translation, endpoint), "x") for translation in translations})
                  for endpoint in ("source", "target"))
    y_count = max(len({getattr(getattr(translation, endpoint), "y") for translation in translations})
                  for endpoint in ("source", "target"))
    if x_count > controller.max_x_tones or y_count > controller.max_y_tones:
        return "x/y tone budget exceeded"
    return None


@dataclass(frozen=True)
class AODController:
    """Configurable crossed-AOD controller with explicit feasibility checks."""

    max_x_tones: int
    max_y_tones: int
    allowed_region: Bounds
    axis_execution: str = "simultaneous"
    min_tone_spacing: float | None = None
    max_speed_x: float = 1.0
    max_speed_y: float = 1.0
    ordering_rule: str = "preserve_order"
    allowed_primitives: tuple[str, ...] = ("TRANSLATE",)
    displacement_tolerance: float = 1e-9

    def __post_init__(self):
        object.__setattr__(self, "allowed_primitives", tuple(self.allowed_primitives))
        for count in (self.max_x_tones, self.max_y_tones):
            if type(count) is not int or count <= 0:
                raise ValueError("AOD tone limits must be positive integers")
        if not isinstance(self.allowed_region, Bounds):
            raise ValueError("allowed_region must be Bounds")
        if self.allowed_primitives != ("TRANSLATE",):
            raise ValueError("This version implements only TRANSLATE")
        if self.axis_execution not in ("simultaneous", "x_then_y", "y_then_x"):
            raise ValueError("axis_execution must be simultaneous, x_then_y, or y_then_x")
        if self.ordering_rule not in ("preserve_order", "none"):
            raise ValueError("ordering_rule must be preserve_order or none")
        if self.min_tone_spacing is not None:
            spacing = finite_number(self.min_tone_spacing, "min_tone_spacing")
            if spacing <= 0:
                raise ValueError("min_tone_spacing must be positive or None")
            object.__setattr__(self, "min_tone_spacing", spacing)
        for name in ("max_speed_x", "max_speed_y"):
            speed = finite_number(getattr(self, name), name)
            if speed <= 0:
                raise ValueError("AOD speeds must be positive")
            object.__setattr__(self, name, speed)
        tolerance = finite_number(self.displacement_tolerance, "displacement_tolerance")
        if tolerance < 0:
            raise ValueError("Displacement tolerance must be nonnegative")
        object.__setattr__(self, "displacement_tolerance", tolerance)

    @staticmethod
    def _tone_keys(translations, axis):
        return tuple(dict.fromkeys(_axis_key(translation, axis) for translation in translations))

    @classmethod
    def tone_counts(cls, translations):
        translations = tuple(translations)
        return tuple(sum(key != ("static",) for key in cls._tone_keys(translations, axis))
                     for axis in ("x", "y"))

    def _check_spacing(self, keys, axis):
        if self.min_tone_spacing is None:
            return None
        active = [key for key in keys if key != ("static",)]
        for endpoint in (0, 1):
            values = sorted({key[endpoint] for key in active})
            if any(right - left + 1e-12 < self.min_tone_spacing for left, right in zip(values, values[1:])):
                return f"{axis.upper()}_TONE_SPACING"
        return None

    def _check_ordering(self, translations, axis):
        if self.ordering_rule == "none":
            return None
        for index, left in enumerate(translations):
            left_source = getattr(left.source, axis)
            left_target = getattr(left.target, axis)
            for right in translations[index + 1:]:
                right_source = getattr(right.source, axis)
                right_target = getattr(right.target, axis)
                if left_source < right_source and left_target > right_target:
                    return "AOD_ORDERING"
                if right_source < left_source and right_target > left_target:
                    return "AOD_ORDERING"
        return None

    def incompatibility(self, translations) -> str | None:
        try:
            self.build_program(translations)
        except ValueError as exc:
            return str(exc).split(":", 1)[0]
        return None

    def compatible(self, translations) -> bool:
        return self.incompatibility(translations) is None

    def legacy_incompatibility(self, translations):
        return _legacy_incompatibility(self, translations)

    def legacy_compatible(self, translations):
        return self.legacy_incompatibility(translations) is None

    def build_program(self, translations: Iterable[Translation]) -> AODProgram:
        translations = tuple(translations)
        if not translations:
            raise ValueError("EMPTY_EPOCH")
        if any(not isinstance(translation, Translation) for translation in translations):
            raise ValueError("INVALID_TRANSLATION")
        if len({translation.atom for translation in translations}) != len(translations):
            raise ValueError("ATOM_CONFLICT")
        if any(not self.allowed_region.contains(position)
               for translation in translations for position in (translation.source, translation.target)):
            raise ValueError("OUT_OF_BOUNDS")
        if len({translation.source for translation in translations}) != len(translations):
            raise ValueError("DUPLICATE_SOURCE")
        if len({translation.target for translation in translations}) != len(translations):
            raise ValueError("DUPLICATE_TARGET")
        for axis in ("x", "y"):
            reason = self._check_ordering(translations, axis) or self._check_spacing(self._tone_keys(translations, axis), axis)
            if reason:
                raise ValueError(reason)
        x_keys, y_keys = self._tone_keys(translations, "x"), self._tone_keys(translations, "y")
        x_count, y_count = self.tone_counts(translations)
        if x_count > self.max_x_tones:
            raise ValueError("TONE_BUDGET_X")
        if y_count > self.max_y_tones:
            raise ValueError("TONE_BUDGET_Y")

        dx = max(abs(translation.displacement[0]) for translation in translations)
        dy = max(abs(translation.displacement[1]) for translation in translations)
        x_duration = dx / self.max_speed_x
        y_duration = dy / self.max_speed_y
        if self.axis_execution == "simultaneous":
            duration = max(x_duration, y_duration)
            x_start, y_start = 0.0, 0.0
        elif self.axis_execution == "x_then_y":
            duration = x_duration + y_duration
            x_start, y_start = 0.0, x_duration
        else:
            duration = x_duration + y_duration
            x_start, y_start = y_duration, 0.0
        duration = max(duration, 1e-12)
        x_ids = {key: f"x-tone-{index:03d}" for index, key in enumerate(x_keys)}
        y_ids = {key: f"y-tone-{index:03d}" for index, key in enumerate(y_keys)}
        bindings = tuple(AtomAODBinding(translation.atom, x_ids[_axis_key(translation, "x")],
                                        y_ids[_axis_key(translation, "y")])
                         for translation in translations)
        x_trajectories = tuple(
            AxisTrajectory(tone_id, "x", key[0], key[1], x_start, max(x_duration, 1e-12))
            for key, tone_id in x_ids.items() if key != ("static",)
        )
        y_trajectories = tuple(
            AxisTrajectory(tone_id, "y", key[0], key[1], y_start, max(y_duration, 1e-12))
            for key, tone_id in y_ids.items() if key != ("static",)
        )
        return AODProgram(bindings, x_trajectories, y_trajectories,
                          {translation.atom: translation.source for translation in translations},
                          {translation.atom: translation.target for translation in translations},
                          duration, self.axis_execution)

    def to_dict(self):
        return {"max_x_tones": self.max_x_tones, "max_y_tones": self.max_y_tones,
                "allowed_region": self.allowed_region.to_list(), "axis_execution": self.axis_execution,
                "min_tone_spacing": self.min_tone_spacing, "max_speed_x": self.max_speed_x,
                "max_speed_y": self.max_speed_y, "ordering_rule": self.ordering_rule,
                "allowed_primitives": list(self.allowed_primitives),
                "displacement_tolerance": self.displacement_tolerance}


class AODPlanner:
    """Small facade that returns a feasible multi-atom AOD program."""

    def __init__(self, controller: AODController):
        if not isinstance(controller, AODController):
            raise ValueError("AODPlanner needs an AODController")
        self.controller = controller

    def plan(self, translations: Iterable[Translation]) -> AODProgram:
        return self.controller.build_program(translations)
