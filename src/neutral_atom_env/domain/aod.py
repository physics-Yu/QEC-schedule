"""Ordered Cartesian AOD axes in physical micrometres, independent of SLM sites."""
from dataclasses import dataclass
from math import isfinite
from .errors import ValidationError
from .models import Position2D


@dataclass(frozen=True)
class AODConfiguration:
    x_um: tuple[float, ...]
    y_um: tuple[float, ...]

    def __post_init__(self):
        for name in ('x_um', 'y_um'):
            values = tuple(getattr(self, name))
            object.__setattr__(self, name, values)
            if not values or any(not isfinite(v) for v in values):
                raise ValidationError('INVALID_AOD_AXES', 'AOD axes must be nonempty and finite')
            if any(b <= a for a, b in zip(values, values[1:])):
                raise ValidationError('AOD_AXIS_ORDER', 'AOD rows/columns must stay strictly ordered; no merging or crossing')

    def position(self, cell):
        return Position2D(self.x_um[cell.column], self.y_um[cell.row])

    def translated(self, dx, dy):
        return AODConfiguration(tuple(x+dx for x in self.x_um), tuple(y+dy for y in self.y_um))


def motion_target(operation):
    return operation.target_configuration if operation.target_configuration is not None else operation.target_pose
