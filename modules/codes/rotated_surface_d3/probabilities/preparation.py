"""Ideal joint preparation events, separate from unresolved physical records."""

from ..._support.raw_t_round_policy import (
    RAW_T_PROTOCOL_VERSION,
    resolve_postselection_rounds,
)
from ...contracts.event_probability import ProbabilityPort

PREPARATION_BITS = {
    "initialize_0": ("X0", "X1", "X2", "X3"),
    "initialize_plus": ("Z0", "Z1", "Z2", "Z3"),
    "raw_t_postselection": ("X1", "X2", "Z1", "Z2"),
}


def preparation_port(
    preparation: str, *, extra_rounds: int | None = None, round_policy: str = "distance"
) -> ProbabilityPort:
    """Return 16 equiprobable accepted local-byproduct classes under ideal gates.

    Args:
        preparation: Full measured initialization or complete raw-T postselection.
        extra_rounds: Raw follow-up count; normal d3 requires two additional rounds.
        round_policy: distance by default; explicit_control labels historical counts.
    Returns:
        Joint event with little-endian byproduct class and acceptance. Individual
        physical measurement values remain unresolved. Normal raw has 20 detectors.
    Raises:
        ValueError: The preparation is not supported; raw T alone is insufficient.

    Ideal source and actual-action branch enumerations are checked independently
    in test_components, test_raw_t_postselection_quantum and test_canonicalization.
    This port makes no claim about a noisy acceptance/byproduct joint table.
    """
    if preparation not in PREPARATION_BITS:
        raise ValueError(f"Unsupported canonical preparation {preparation!r}")
    raw = preparation == "raw_t_postselection"
    if not raw and (extra_rounds is not None or round_policy != "distance"):
        raise ValueError("SE round parameters apply only to raw_t_postselection.")
    extra = (
        resolve_postselection_rounds(3, extra_rounds, round_policy=round_policy)
        if raw
        else 0
    )
    version = RAW_T_PROTOCOL_VERSION if raw else "1"
    protocol = f"rotated_surface_d3.{preparation}"
    return ProbabilityPort.from_dict(
        {
            "schema": "nadit.event_probability/1",
            "port_id": f"{protocol}.canonical_preparation",
            "protocol_id": protocol,
            "protocol_version": version,
            "model": {
                "id": f"{preparation}.ideal_joint.v{version}",
                "kind": "ideal_exact",
                "assumptions": [
                    "Ideal gates, reset, and measurements; no loss",
                    "Known local preparation relations applied physically before use",
                    "A coarse class does not populate individual physical records",
                    *(
                        [
                            f"Raw T includes its first full SE and {extra} additional full SE rounds"
                        ]
                        if raw
                        else []
                    ),
                ],
                "parameters": {
                    "preparation": preparation,
                    **(
                        {
                            "distance": 3,
                            "extra_rounds": extra,
                            "total_rounds": extra + 1,
                            "round_policy": round_policy,
                        }
                        if raw
                        else {}
                    ),
                },
                "evidence": {
                    "class_bit_order": list(PREPARATION_BITS[preparation]),
                    "class_encoding": "little_endian",
                    "calculation": "all 16 ideal source and atom-action branches",
                    "detectors": 4 + 8 * extra if raw else 0,
                },
            },
            "outcomes": [
                {
                    "key": f"accepted_{index}",
                    "probability": 1 / 16,
                    "values": {"accepted": True, "byproduct_class": index},
                    "branch_id": "canonicalize",
                }
                for index in range(16)
            ]
            + [
                {
                    "key": "rejected",
                    "probability": 0,
                    "values": {"accepted": False, "byproduct_class": None},
                    "branch_id": "retry",
                }
            ],
            "branches": [
                {"key": "canonicalize", "transition": "continue", "steps": []},
                {"key": "retry", "transition": "retry", "steps": []},
            ],
        }
    )
