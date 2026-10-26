"""Joint factory checks for iid accepted-input Z errors and ideal Clifford gates.

This is an assumed logical reference model, not a d3 circuit-level noise estimate.
The convention uses four initial A states, ten triple rotations, one quintuple
rotation, and the final X converting A-dagger into A. See Litinski (2019),
https://arxiv.org/html/1905.06903, Sec. 1. The finite convolution also retains the
hidden output-error mass, which is metadata and is never a feedback outcome.
"""

from collections.abc import Mapping
from itertools import combinations
from math import isfinite
from typing import Any

from ...contracts.event_probability import ProbabilityPort


def _error_distribution(p: float) -> tuple[float, ...]:
    """Propagate 15 independent Z errors to five output Pauli parities."""
    supports: list[tuple[int, ...]] = [(i,) for i in range(1, 5)]
    supports.extend(combinations(range(5), 3))
    supports.append(tuple(range(5)))
    distribution = [1.0] + [0.0] * 31
    for support in supports:
        mask = sum(1 << i for i in support)
        distribution = [
            (1 - p) * distribution[index] + p * distribution[index ^ mask]
            for index in range(32)
        ]
    return tuple(distribution)


def factory_mx_port(*, input_z_error: float = 0.0) -> ProbabilityPort:
    """Return the joint four-bit final logical-X event and conditional quality.

    Args:
        input_z_error: Assumed independent Z error of each accepted, canonical A
            input. This is NOT the raw preparation rejection probability.
    Returns:
        All 16 joint check outcomes. Only all-zero accepts. Output quality is a
        model property conditional on acceptance, not a controller-visible bit.
    Raises:
        ValueError: The parameter is not a finite real probability in [0, 1].

    For equatorial Z-error inputs, each consumption MZ bit is independent and
    fair, including conditional on the error pattern. Thus the table need not
    condition on earlier MZ bits. This fails for general noise/correlated inputs.
    """
    if (
        type(input_z_error) not in (int, float)
        or not isfinite(input_z_error)
        or not 0 <= input_z_error <= 1
    ):
        raise ValueError("input_z_error must be a finite probability in [0, 1]")
    distribution = _error_distribution(float(input_z_error))
    acceptance = distribution[0] + distribution[1]
    return ProbabilityPort.from_dict(
        {
            "schema": "nadit.event_probability/1",
            "port_id": "rotated_surface_d3.factory_15_to_1.final_mx",
            "protocol_id": "rotated_surface_d3.factory_15_to_1",
            "protocol_version": "1",
            "model": {
                "id": "factory_15_to_1.iid_input_z.ideal_clifford.v1",
                "kind": "ideal_exact" if input_z_error == 0 else "pauli_exact",
                "assumptions": [
                    "Assumed iid accepted canonical input mixture (1-p)A + p ZAZ",
                    "All Clifford gates, storage, and readout are ideal",
                    "Preparation rejection probability does not determine input p",
                    "No shared-world physical-noise estimate or FT certification",
                ],
                "parameters": {"input_z_error": input_z_error},
                "evidence": {
                    "calculation": "finite convolution over 15 input Pauli faults",
                    "acceptance_probability": acceptance,
                    "conditional_output_z_error": distribution[1] / acceptance,
                    "output_convention": "A_dagger then physical logical_X gives A",
                    "t_consumption_bits": (
                        "independent fair bits under this reference model"
                    ),
                    "reference": "https://arxiv.org/html/1905.06903",
                },
            },
            "outcomes": [
                {
                    "key": f"mx_{syndrome:04b}",
                    "probability": distribution[2 * syndrome]
                    + distribution[2 * syndrome + 1],
                    "values": {
                        "accepted": syndrome == 0,
                        **{f"m_w{i + 2}": (syndrome >> i) & 1 for i in range(4)},
                    },
                    "branch_id": "accepted" if syndrome == 0 else "rejected",
                }
                for syndrome in range(16)
            ],
            "branches": [
                {
                    "key": "accepted",
                    "transition": "deliver",
                    "steps": [
                        {"component_id": "logical_x", "participant_roles": ["W1"]}
                    ],
                },
                {"key": "rejected", "transition": "retry", "steps": []},
            ],
        }
    )


def preparation_quality(
    preparation: str, parameters: Mapping[str, object] | None = None
) -> dict[str, Any]:
    """Declare assumed quality of an accepted canonical raw A resource.

    Only input_z_error is supported; it is separate from raw rejection. Returns
    portable metadata and opaque parameters for a subsequent code-owned event.
    Raises ValueError for another preparation, unknown parameters or invalid p.
    """
    if preparation != "raw_t_postselection":
        raise ValueError("Resource quality requires raw_t_postselection preparation")
    params = {} if parameters is None else dict(parameters)
    if set(params) - {"input_z_error"}:
        raise ValueError("Unsupported preparation quality parameter")
    p = params.get("input_z_error", 0.0)
    if (
        isinstance(p, bool)
        or not isinstance(p, int | float)
        or not isfinite(p)
        or not 0 <= p <= 1
    ):
        raise ValueError("input_z_error must be a finite probability in [0, 1]")
    return {
        "model_id": "accepted_input.iid_z.ideal_clifford.v1",
        "status": "ideal_reference" if p == 0 else "assumed_reference",
        "condition": "raw preparation accepted and local relations canonicalized",
        "assumptions": [
            "Independent accepted logical A input with Z-error probability p",
            "p is an explicit assumption, not inferred from raw rejection",
            "No physical-noise or storage-quality claim",
        ],
        "consumption_parameters": {"input_z_error": p},
    }


def output_quality(factory_port: ProbabilityPort) -> dict[str, Any]:
    """Return accepted output quality for this exact code-owned reference model.

    Call only after final acceptance and output X. Unknown or changed models raise
    ValueError, including arbitrary fixture probabilities; no inference is made.
    """
    doc = factory_port.to_dict()
    model = doc["model"]
    p = model["parameters"].get("input_z_error")
    if (
        factory_port.protocol_id != "rotated_surface_d3.factory_15_to_1"
        or type(p) not in (int, float)
        or factory_mx_port(input_z_error=p).content_sha256
        != factory_port.content_sha256
    ):
        raise ValueError("Output quality requires the exact factory reference port")
    return {
        "model_id": model["id"],
        "status": "ideal_reference" if p == 0 else "assumed_reference",
        "source_port_sha256": factory_port.content_sha256,
        "condition": "factory accepted and output canonicalized",
        "assumptions": model["assumptions"],
        "consumption_parameters": {
            "input_z_error": model["evidence"]["conditional_output_z_error"]
        },
    }
