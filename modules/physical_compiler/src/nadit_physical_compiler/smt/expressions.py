"""Finite numeric tables keep geometry and timing out of nonlinear arithmetic."""

from collections.abc import Sequence
from fractions import Fraction
from math import ceil, sqrt

import z3

from ..device import Region, Timing


def maximum(values: Sequence[z3.ArithRef]) -> z3.ArithRef:
    """Return an exact SMT maximum, with zero for an empty sequence."""
    result = z3.RealVal(0)
    for value in values:
        result = z3.If(value > result, value, result)
    return result


def ticks(duration: float, quantum: float) -> int:
    """Round a declared duration upwards, avoiding floating boundary noise."""
    return ceil(Fraction(str(duration)) / Fraction(str(quantum)))


def table(values: Sequence[float | int | Fraction]) -> z3.ArrayRef:
    """Return a constant integer-indexed rational lookup array."""
    result = z3.K(z3.IntSort(), z3.RealVal(0))
    for index, value in enumerate(values):
        result = z3.Store(result, index, z3.RealVal(str(value)))
    return result


def squared_differences(values: tuple[float, ...]) -> z3.ArrayRef:
    """Map a pair of coordinate indices to squared physical separation."""
    return table(
        [(Fraction(str(a)) - Fraction(str(b))) ** 2 for a in values for b in values]
    )


def distance_table(
    xs: tuple[float, ...], ys: tuple[float, ...], timing: Timing, quantum: float
) -> z3.ArrayRef:
    """Map each attainable squared displacement to rounded movement time."""
    x2 = {(Fraction(str(a)) - Fraction(str(b))) ** 2 for a in xs for b in xs}
    y2 = {(Fraction(str(a)) - Fraction(str(b))) ** 2 for a in ys for b in ys}
    result = z3.K(z3.RealSort(), z3.IntVal(0))
    for distance in sorted({a + b for a in x2 for b in y2}):
        result = z3.Store(
            result,
            z3.RealVal(str(distance)),
            ticks(timing.move_duration(sqrt(float(distance))), quantum),
        )
    return result


def inside(x: z3.ArithRef, y: z3.ArithRef, region: Region) -> z3.BoolRef:
    """Closed rectangle containment at declared exact coordinates."""
    return z3.And(
        x >= region.x_min, x <= region.x_max, y >= region.y_min, y <= region.y_max
    )


def segment_tables(
    values: tuple[float, ...], minimum: float, maximum_: float
) -> tuple[z3.ArrayRef, z3.ArrayRef]:
    """Exact slab time intervals for every directed endpoint pair."""
    lows, highs = [], []
    lower, upper = Fraction(str(minimum)), Fraction(str(maximum_))
    for origin in values:
        for end in values:
            start, delta = (
                Fraction(str(origin)),
                Fraction(str(end)) - Fraction(str(origin)),
            )
            if delta == 0:
                lo, hi = (
                    (Fraction(0), Fraction(1))
                    if lower <= start <= upper
                    else (Fraction(1), Fraction(0))
                )
            else:
                first, last = sorted(((lower - start) / delta, (upper - start) / delta))
                lo, hi = max(Fraction(0), first), min(Fraction(1), last)
            lows.append(lo)
            highs.append(hi)
    return table(lows), table(highs)
