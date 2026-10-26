"""Compare joint SE, serial control, and every complete-world solo control."""

from math import fsum, isclose, isfinite
from typing import Any

from .standard import STANDARD_ID

_CASE_SCHEMA = "nadit.msd.parallel_se/1"
_CASE_SCOPE = "joint SE round; not a complete distillation production cycle"


def _mapping(row: dict[str, Any], key: str) -> dict[str, Any]:
    value = row.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"SE comparison requires mapping {key!r}.")
    return value


def _duration(value: object, context: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{context} must be a finite numeric duration.")
    numeric = float(value)
    if not isfinite(numeric) or numeric < 0 or (positive and numeric == 0):
        raise ValueError(
            f"{context} must be finite and {'positive' if positive else 'nonnegative'}."
        )
    return numeric


def _validate_row(
    row: dict[str, Any],
    *,
    mode: str,
    parameters: dict[str, Any],
    hashes: dict[str, str],
) -> tuple[tuple[int, ...], float, dict[str, float]]:
    if (
        row.get("schema") != _CASE_SCHEMA
        or row.get("standard") != STANDARD_ID
        or row.get("scope") != _CASE_SCOPE
        or row.get("active_patch_role") != "W1"
        or row.get("mode") != mode
    ):
        raise ValueError(f"SE comparison requires the exact {mode!r} W1 case scope.")
    if _mapping(row, "parameters") != parameters:
        raise ValueError("SE comparison parameters must match across every control.")
    for key, expected_hash in hashes.items():
        if row.get(key) != expected_hash:
            raise ValueError(f"SE comparison requires identical {key} across controls.")
    indices = row.get("factory_indices")
    count = parameters["pipelines"]
    if (
        not isinstance(indices, tuple | list)
        or not indices
        or any(type(index) is not int or not 0 <= index < count for index in indices)
    ):
        raise ValueError("SE comparison requires valid factory_indices.")
    selected = tuple(indices)
    expected = 1 if mode == "solo" else count
    if len(selected) != expected or len(set(selected)) != expected:
        raise ValueError(
            f"SE comparison requires exactly {expected} distinct {mode} instances."
        )
    if mode != "solo" and selected != tuple(range(count)):
        raise ValueError(
            "Joint and serial controls must select every factory in order."
        )
    if type(row.get("se_instances")) is not int or row["se_instances"] != expected:
        raise ValueError(
            "SE comparison instance count disagrees with its factory scope."
        )
    measurements = expected * (parameters["distance"] ** 2 - 1)
    if (
        type(row.get("expected_measurements")) is not int
        or row["expected_measurements"] != measurements
    ):
        raise ValueError(
            "SE comparison measurement count disagrees with its code scope."
        )
    metrics = _mapping(row, "metrics")
    elapsed = _duration(
        metrics.get("execution_duration_us"), "SE execution duration", positive=True
    )
    partition = _mapping(_mapping(row, "scheduler"), "time_partition_us")
    if not partition or any(not isinstance(key, str) or not key for key in partition):
        raise ValueError("SE phase partition needs named categories.")
    phases = {
        key: _duration(value, f"SE phase {key!r}") for key, value in partition.items()
    }
    if not isclose(fsum(phases.values()), elapsed, abs_tol=1e-8, rel_tol=1e-12):
        raise ValueError("SE phase partition does not sum to its execution duration.")
    return selected, elapsed, phases


def compare_cases(
    joint: dict[str, Any], serial: dict[str, Any], solos: tuple[dict[str, Any], ...]
) -> dict[str, Any]:
    """Return matched-control timing and signed phase-by-phase differences.

    Args:
        joint: Exactly N jointly scheduled W1 SE instances in the full world.
        serial: The same N instances with explicit serial-control dependencies.
        solos: One W1 solo control for every factory, in the same complete world.
    Returns:
        SE-round rates and G=slowest_solo-top_solo, J=joint-slowest_solo. The
        same slowest factory supplies every phase of both decompositions.
    Raises:
        ValueError: If identities, scopes, controls, durations, or partitions
            disagree, or if either signed decomposition fails conservation.
    """
    parameters = _mapping(joint, "parameters")
    count, distance = parameters.get("pipelines"), parameters.get("distance")
    if (
        type(count) is not int
        or count < 1
        or type(distance) is not int
        or distance < 3
        or distance % 2 != 1
    ):
        raise ValueError(
            "SE comparison needs a positive pipeline count and odd distance >=3."
        )
    hashes = {}
    for key in ("device_sha256", "source_tree_sha256"):
        value = joint.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"SE comparison requires nonempty {key}.")
        hashes[key] = value
    _, joint_time, joint_phases = _validate_row(
        joint, mode="joint", parameters=parameters, hashes=hashes
    )
    _, serial_time, _ = _validate_row(
        serial, mode="serial", parameters=parameters, hashes=hashes
    )
    if len(solos) != count:
        raise ValueError("SE comparison requires one solo control for every factory.")
    controls = {}
    for row in solos:
        indices, elapsed, phases = _validate_row(
            row, mode="solo", parameters=parameters, hashes=hashes
        )
        index = indices[0]
        if index in controls:
            raise ValueError("SE comparison repeats a solo factory control.")
        controls[index] = (elapsed, phases)
    if set(controls) != set(range(count)):
        raise ValueError("SE comparison is missing a solo factory control.")
    slowest = min(controls, key=lambda index: (-controls[index][0], index))
    top_time, top_phases = controls[0]
    slow_time, slow_phases = controls[slowest]
    categories = sorted(set(joint_phases) | set(top_phases) | set(slow_phases))
    position = {
        key: slow_phases.get(key, 0.0) - top_phases.get(key, 0.0) for key in categories
    }
    net_joint = {
        key: joint_phases.get(key, 0.0) - slow_phases.get(key, 0.0)
        for key in categories
    }
    position_effect, joint_effect = slow_time - top_time, joint_time - slow_time
    if not isclose(
        fsum(position.values()), position_effect, abs_tol=1e-8, rel_tol=1e-12
    ):
        raise ValueError("SE position phase differences do not conserve total G.")
    if not isclose(fsum(net_joint.values()), joint_effect, abs_tol=1e-8, rel_tol=1e-12):
        raise ValueError("SE joint phase differences do not conserve signed total J.")
    return {
        "schema": "nadit.msd.parallel_se_comparison/1",
        "standard": STANDARD_ID,
        "parameters": dict(parameters),
        **hashes,
        "se_instances": count,
        "joint_round_us": joint_time,
        "serial_round_us": serial_time,
        "top_solo_us": top_time,
        "slowest_solo_us": slow_time,
        "slowest_factory": slowest,
        "position_effect_us": position_effect,
        "net_joint_effect_us": joint_effect,
        "serial_speedup": serial_time / joint_time,
        "rounds_per_second": count * 1e6 / joint_time,
        "throughput_unit": "completed SE rounds per second; not accepted magic states",
        "position_by_phase_us": position,
        "joint_by_phase_us": net_joint,
        "attribution_note": (
            "Matched-control differences for the implemented scheduler. G compares "
            "the same slowest-total solo factory with the top solo; J compares the "
            "joint execution with that same solo. Signed phase effects are retained. "
            "J combines batching, placement, scheduling and shared-resource effects; "
            "it is not pure AOD contention and is not a physical bound."
        ),
    }
