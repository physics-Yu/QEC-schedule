"""All Cartesian AOD intersections exist, even when unoccupied."""
from math import isclose
from neutral_atom_env.domain.errors import ValidationError

# User-specified model floor, not an experimentally derived resonance threshold.
AOD_TRAP_DISTANCE_FLOOR_UM = 1.01


def minimum_trap_spacing(hardware):
    return max(AOD_TRAP_DISTANCE_FLOOR_UM,hardware.minimum_axis_spacing_um)


def validate_trap_spacing(aod,hardware):
    """Nearest distinct Cartesian traps share a row or column.

    For the shared monotone progress used by both backends, every adjacent
    axis gap is a convex combination of its endpoint gaps. Checking both
    configurations therefore certifies the entire segment, including empty traps.
    """
    config=aod.configuration();limit=minimum_trap_spacing(hardware)
    for name,axis in (('column',config.x_um),('row',config.y_um)):
        for i,(left,right) in enumerate(zip(axis,axis[1:])):
            gap=right-left
            if gap<=limit or isclose(gap,limit,rel_tol=0,abs_tol=1e-12):
                raise ValidationError('AOD_AXIS_SPACING',
                    f'AOD {name} {i}/{i+1} trap centres are {gap:.12g} um apart; '
                    f'every AOD trap (including empty ones) must be strictly farther than {limit:g} um')
