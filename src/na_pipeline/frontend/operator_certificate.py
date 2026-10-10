"""Outward-rounded 2x2 interval certificates using only the standard library.

This is static operator checking. It never stores, evolves, or measures a state.
The certified Frobenius bound also bounds the operator 2-norm. No optimization
over global phase is performed: the supplied rational phase is included exactly.
"""

from decimal import Decimal, localcontext, ROUND_FLOOR, ROUND_CEILING
from fractions import Fraction
import hashlib
import json
import math

PRECISION = 70


def _rounded(fn, rounding):
    with localcontext() as ctx:
        ctx.prec = PRECISION
        ctx.rounding = rounding
        return +fn()


class Interval:
    def __init__(self, lo, hi=None):
        self.lo = Decimal(lo)
        self.hi = Decimal(lo if hi is None else hi)

    @classmethod
    def rational(cls, value):
        value = Fraction(value)
        fn = lambda: Decimal(value.numerator) / Decimal(value.denominator)
        return cls(_rounded(fn, ROUND_FLOOR), _rounded(fn, ROUND_CEILING))

    def __add__(self, other):
        return Interval(_rounded(lambda: self.lo + other.lo, ROUND_FLOOR),
                        _rounded(lambda: self.hi + other.hi, ROUND_CEILING))

    def __neg__(self):
        # Decimal unary '-' also uses the active context; copy_negate is exact.
        return Interval(self.hi.copy_negate(), self.lo.copy_negate())

    def __sub__(self, other):
        return self + (-other)

    def __mul__(self, other):
        pairs = [(a, b) for a in (self.lo, self.hi) for b in (other.lo, other.hi)]
        return Interval(min(_rounded(lambda: a * b, ROUND_FLOOR) for a, b in pairs),
                        max(_rounded(lambda: a * b, ROUND_CEILING) for a, b in pairs))

    def divide_int(self, divisor):
        if type(divisor) is not int or divisor <= 0:
            raise ValueError("positive integer divisor required")
        return Interval(_rounded(lambda: self.lo / divisor, ROUND_FLOOR),
                        _rounded(lambda: self.hi / divisor, ROUND_CEILING))


ZERO, ONE = Interval(0), Interval(1)


def _atan_bounds(inverse):
    # Alternating series: after N terms, error is between zero and next term.
    count = 110
    partial = sum((Fraction((-1) ** n, (2 * n + 1) * inverse ** (2 * n + 1))
                   for n in range(count)), Fraction(0))
    next_term = Fraction((-1) ** count, (2 * count + 1) * inverse ** (2 * count + 1))
    return min(partial, partial + next_term), max(partial, partial + next_term)


def _pi_interval():
    a0, a1 = _atan_bounds(5)
    b0, b1 = _atan_bounds(239)
    lower, upper = 16 * a0 - 4 * b1, 16 * a1 - 4 * b0
    return Interval(Interval.rational(lower).lo, Interval.rational(upper).hi)


PI = _pi_interval()  # Machin identity pi=16 atan(1/5)-4 atan(1/239).
_SCALE = 10 ** (PRECISION + 10)
_ROOT_FLOOR = math.isqrt(2 * _SCALE * _SCALE)
SQRT2 = Interval(Interval.rational(Fraction(_ROOT_FLOOR, _SCALE)).lo,
                 Interval.rational(Fraction(_ROOT_FLOOR + 1, _SCALE)).hi)


def _trig(angle_pi):
    coefficient = Fraction(angle_pi) % 2
    if coefficient > 1:
        coefficient -= 2
    x = PI * Interval.rational(coefficient)
    minus_x2 = -(x * x)
    sin_term, cos_term = x, ONE
    sine, cosine = x, ONE
    for n in range(1, 64):
        sin_term = (sin_term * minus_x2).divide_int((2 * n) * (2 * n + 1))
        cos_term = (cos_term * minus_x2).divide_int((2 * n - 1) * (2 * n))
        sine, cosine = sine + sin_term, cosine + cos_term
    # Degree-127 Taylor remainder on |x| <= pi < 4: <= 4^128/128!.
    # Cosine's x^127 coefficient is zero, so the same remainder applies.
    remainder = Interval.rational(Fraction(4 ** 128, math.factorial(128))).hi
    allowance = Interval(remainder.copy_negate(), remainder)
    return sine + allowance, cosine + allowance


def _cadd(a, b):
    return a[0] + b[0], a[1] + b[1]


def _cmul(a, b):
    return a[0] * b[0] - a[1] * b[1], a[0] * b[1] + a[1] * b[0]


def _matmul(a, b):
    return [[_cadd(_cmul(a[i][0], b[0][j]), _cmul(a[i][1], b[1][j]))
             for j in range(2)] for i in range(2)]


def _matrices():
    z, o, h = (ZERO, ZERO), (ONE, ZERO), (SQRT2.divide_int(2), ZERO)
    t = (SQRT2.divide_int(2), SQRT2.divide_int(2))
    return {
        "H": [[h, h], [h, (-h[0], ZERO)]], "X": [[z, o], [o, z]],
        "Z": [[o, z], [z, (-ONE, ZERO)]],
        "S": [[o, z], [z, (ZERO, ONE)]], "SDG": [[o, z], [z, (ZERO, -ONE)]],
        "T": [[o, z], [z, t]], "TDG": [[o, z], [z, (t[0], -t[1])]],
    }


def _fraction(spec):
    if (type(spec.get("numerator")) is not int or type(spec.get("denominator")) is not int
            or spec["denominator"] <= 0):
        raise ValueError("invalid rational pi angle")
    return Fraction(spec["numerator"], spec["denominator"])


def certify_rotation(gates: list[str], angle_pi: dict, global_phase_pi: dict) -> dict:
    """Prove ||exp(i beta) word - P(theta)||_2 <= the returned bound.

    Bounds derive from directed Decimal arithmetic, integer sqrt bracketing,
    Machin's identity and explicit Taylor remainders. The operator is evaluated
    on all matrix entries; no initial-state or expected-outcome shortcut exists.
    """
    if not isinstance(gates, list) or not gates or len(gates) > 1000:
        raise ValueError("certificate accepts 1..1000 one-qubit gates")
    matrices = _matrices()
    z, o = (ZERO, ZERO), (ONE, ZERO)
    result = [[o, z], [z, o]]
    for gate in gates:
        if gate not in matrices:
            raise ValueError("unsupported certificate gate: " + str(gate))
        result = _matmul(matrices[gate], result)
    sine, cosine = _trig(_fraction(global_phase_pi))
    scalar = cosine, sine
    result = [[_cmul(scalar, entry) for entry in row] for row in result]
    sine, cosine = _trig(_fraction(angle_pi))
    target = [[o, z], [z, (cosine, sine)]]
    upper_squared = Decimal(0)
    intervals = []
    for i in range(2):
        row = []
        for j in range(2):
            entry = result[i][j]
            row.append({"real": [str(entry[0].lo), str(entry[0].hi)],
                        "imag": [str(entry[1].lo), str(entry[1].hi)]})
            for component in range(2):
                delta = entry[component] - target[i][j][component]
                maximum = max(delta.lo.copy_abs(), delta.hi.copy_abs())
                upper_squared = _rounded(lambda: upper_squared + maximum * maximum, ROUND_CEILING)
        intervals.append(row)
    with localcontext() as ctx:
        ctx.prec = PRECISION
        # Decimal.sqrt is correctly rounded; next_plus is an outward upper bound.
        upper = ctx.next_plus(upper_squared.sqrt())
    return {
        "method": "directed_decimal_interval_frobenius_v1", "decimal_precision": PRECISION,
        "phase_sensitive": True, "phase_optimized": False,
        "metric": "operator_2_norm_bounded_by_frobenius",
        "angle_pi": dict(angle_pi), "global_phase_pi": dict(global_phase_pi),
        "gate_word_sha256": hashlib.sha256(json.dumps(gates, separators=(",", ":")).encode()).hexdigest(),
        "gate_count": len(gates), "t_count": gates.count("T"), "tdg_count": gates.count("TDG"),
        "operator_error_upper_bound": str(upper), "corrected_matrix_intervals": intervals,
        "bound_scope": "static_2x2_operator_not_quantum_state_execution",
    }
