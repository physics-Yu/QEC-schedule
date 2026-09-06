"""Illustrative action durations (us) and transport speed (um/us)."""
from dataclasses import dataclass, fields

from .geometry import finite_number


@dataclass(frozen=True)
class ActionTiming:
    move_speed: float = 1.0
    pickup_duration: float = 1.0
    dropoff_duration: float = 1.0
    single_qubit_duration: float = 1.0
    entangle_duration: float = 1.0
    measurement_duration: float = 20.0
    prepare_duration: float = 1.0
    reset_duration: float = 1.0

    def __post_init__(self):
        for field in fields(self):
            value = finite_number(getattr(self, field.name), field.name)
            if value <= 0:
                raise ValueError(f"{field.name} must be positive")
            object.__setattr__(self, field.name, value)

    def to_dict(self):
        return {field.name: getattr(self, field.name) for field in fields(self)}
