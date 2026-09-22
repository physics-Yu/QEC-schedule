"""Fit disabled spare axes without changing occupied-axis order or world bounds."""
from math import floor
from neutral_atom_env.domain.errors import ValidationError


def bounded_spare_axes(start, end, count, lower, upper, minimum_spacing):
    """Same active indices at both endpoints; all gaps exceed the hardware floor.

    Spare axes can go before, between or after occupied axes. Each interval's
    capacity is the smaller of its capacities at the two endpoints. The caller
    still verifies full Cartesian capture and every continuous movement.
    """
    needed = count - len(start)
    if needed < 0 or not start or len(start) != len(end):
        raise ValueError('Invalid occupied-axis dimensions')
    if any(v[0] < lower or v[-1] > upper for v in (start, end)):
        raise ValidationError('AXIS_BOUNDS', 'Occupied axes leave world bounds')
    # Keep enough separation for the existing 2.5 um corridor portals whenever
    # possible. Immediately packing to the hardware floor can collapse those
    # portals even though endpoint spacing itself is legal.
    for pitch in (10., 2.5, minimum_spacing + .01):
        if pitch <= minimum_spacing:
            continue
        needed = count - len(start)
        capacity = [max(0, floor(min(start[0]-lower, end[0]-lower)/pitch))]
        capacity += [max(0, floor(min(start[i]-start[i-1], end[i]-end[i-1])/pitch)-1)
                     for i in range(1, len(start))]
        capacity += [max(0, floor(min(upper-start[-1], upper-end[-1])/pitch))]
        allocation = [0] * len(capacity)
        # Prefer extension at the right, then left, then existing interior gaps.
        for i in [len(capacity)-1, 0, *range(1, len(capacity)-1)]:
            allocation[i] = min(needed, capacity[i])
            needed -= allocation[i]
        if not needed:
            break
    if needed:
        raise ValidationError('AXIS_BOUNDS', 'No common bounded embedding for full-capacity spare axes')
    def pad(values):
        out = [values[0]-pitch*i for i in range(allocation[0],0,-1)]
        for i, value in enumerate(values):
            out.append(value)
            out.extend(value+pitch*j for j in range(1,allocation[i+1]+1))
        return tuple(out)
    return pad(start), pad(end)
