"""Exact-integer classical postprocessing; supplied bits are never sampled here."""

from fractions import Fraction
from math import gcd

from .program import FrontendError, _hash


def _convergents(numerator: int, denominator: int):
    h0, h1, k0, k1 = 0, 1, 1, 0
    while denominator:
        term, remainder = divmod(numerator, denominator)
        h0, h1 = h1, term * h1 + h0
        k0, k1 = k1, term * k1 + k0
        yield h1, k1
        numerator, denominator = denominator, remainder


def postprocess_phase(bits: list[int], *, N: int = 15, a: int = 2,
                      origin: str = "fake") -> dict:
    """Interpret phase[0..7] in MSB-first order and validate CF period candidates.

    No denominator-multiple search or hidden order/factor table. A non-coprime
    phase numerator can give a failed shot; report it rather than force success.
    N,a are exposed to verify that the postprocessor is not Shor-15 hardcoded.
    The returned period is verified by modular exponentiation, not asserted minimal.
    """
    if not isinstance(bits, list) or len(bits) != 8 or any(type(b) is not int or b not in (0, 1) for b in bits):
        raise FrontendError("INVALID_PHASE_BITS: expected eight integer bits, MSB first")
    if type(N) is not int or N < 3 or type(a) is not int or not 1 < a < N:
        raise FrontendError("INVALID_MODULAR_INPUT: require N >= 3 and 1 < a < N")
    if origin not in ("fake", "externally_supplied_unverified"):
        raise FrontendError("UNSUPPORTED_ORIGIN: no quantum or hardware sampling in this module")
    value = sum(bit << (7 - index) for index, bit in enumerate(bits))
    phase = Fraction(value, 256)
    input_config = {"bits_msb_first": bits, "N": N, "a": a, "origin": origin}
    result = {"schema_version": "PhasePostprocess/0.1.0", "origin": origin,
              "artifact_id": "phase-postprocess-" + _hash(input_config)[:16],
              "producer_version": "na_pipeline.frontend/0.1.0",
              "provenance": {"owner": "R2", "task_id": "T201", "fixture": False,
                             "input_origin": origin, "input_sha256": _hash(input_config),
                             "classification": "classical_computation_on_supplied_bits"},
              "execution_kind": "compile_plan", "computation_kind": "classical_postprocessing",
              "loss_enabled": False,
              "quantum_state_simulated": False, "hardware_executed": False,
              "input_bits_msb_first": bits.copy(), "N": N, "a": a,
              "phase_numerator": value, "phase_denominator": 256,
              "continued_fraction_convergents": [], "candidate_checks": [],
              "period": None, "minimal_order_proven": False,
              "factors": [], "status": "failed", "reason": None,
              "method": "continued_fractions_no_multiple_search"}
    common = gcd(a, N)
    if common != 1:
        result.update(status="success", reason="classical_gcd_precheck",
                      factors=sorted([common, N // common]))
        return result
    if value == 0:
        result["reason"] = "zero_phase_no_period_information"
        return result
    for p, q in _convergents(value, 256):
        result["continued_fraction_convergents"].append({"numerator": p, "denominator": q})
        if q < 2 or q >= N:
            continue
        check = {"numerator": p, "denominator": q, "modular_power": pow(a, q, N)}
        result["candidate_checks"].append(check)
        if abs(phase - Fraction(p, q)) > Fraction(1, 2 * q * q):
            check["rejection"] = "insufficient_phase_accuracy"
            continue
        if check["modular_power"] != 1:
            check["rejection"] = "not_a_period"
            continue
        if q % 2:
            check["rejection"] = "odd_period"
            continue
        half_power = pow(a, q // 2, N)
        check["half_power"] = half_power
        if half_power in (1, N - 1):
            check["rejection"] = "trivial_square_root"
            continue
        divisors = [gcd(half_power - 1, N), gcd(half_power + 1, N)]
        proper = [d for d in divisors if 1 < d < N]
        if not proper:
            check["rejection"] = "trivial_gcd"
            continue
        divisor = min(proper)
        result.update(status="success", reason="verified_period_and_nontrivial_gcd",
                      period=q, factors=sorted([divisor, N // divisor]))
        check["accepted"] = True
        return result
    result["reason"] = "no_useful_verified_period"
    return result
