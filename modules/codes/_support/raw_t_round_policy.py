"""Shared raw-T temporal policy, independent of any code or compiler runtime."""

RAW_T_PROTOCOL_VERSION = "2"
ROUND_POLICIES = ("distance", "explicit_control")


def resolve_postselection_rounds(
    distance: int,
    extra_rounds: int | None = None,
    *,
    round_policy: str = "distance",
) -> int:
    """Resolve additional SE rounds; the raw-T primitive already contains one.

    Args:
        distance: Odd code distance at least three.
        extra_rounds: Additional rounds, or None for the normal distance policy.
        round_policy: distance requires exactly d total rounds. explicit_control
            requires an explicit positive count for labeled historical controls.
    Returns:
        A positive integer count of additional ordinary SE rounds.
    Raises:
        ValueError: If the distance/count/policy is invalid or a normal call
            attempts a round count different from d without a control label.
    """
    if type(distance) is not int or distance < 3 or distance % 2 == 0:
        raise ValueError("Raw-T distance must be an odd integer at least three.")
    if round_policy not in ROUND_POLICIES:
        raise ValueError(f"Raw-T round_policy must be one of {ROUND_POLICIES}.")
    if extra_rounds is None:
        if round_policy == "explicit_control":
            raise ValueError(
                "explicit_control requires an explicit extra_rounds count."
            )
        return distance - 1
    if type(extra_rounds) is not int or extra_rounds < 1:
        raise ValueError("Raw-T use requires an integer extra_rounds of at least one.")
    if round_policy == "distance" and extra_rounds != distance - 1:
        raise ValueError(
            f"Normal d={distance} postselection requires total_rounds={distance} "
            f"(extra_rounds={distance - 1}); use round_policy='explicit_control' "
            "only for a deliberately labeled control."
        )
    return extra_rounds


def distance_from_code_id(code_id: str) -> int:
    """Read a concrete rotated-surface identity or reject an unrelated profile."""
    prefix = "rotated_surface_d"
    if not code_id.startswith(prefix) or not code_id[len(prefix) :].isdigit():
        raise ValueError(
            "Raw-T rounds require a concrete rotated-surface code identity."
        )
    distance = int(code_id[len(prefix) :])
    resolve_postselection_rounds(distance)
    if code_id != f"{prefix}{distance}":
        raise ValueError("Raw-T code identity must use canonical distance notation.")
    return distance
