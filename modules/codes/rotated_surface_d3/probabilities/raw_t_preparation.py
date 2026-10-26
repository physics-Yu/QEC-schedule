"""Frozen raw-T joint acceptance/byproduct events under independent Pauli noise.

For the approved product seed, each of the sixteen first-round bulk branches is
an isometry of the central qubit with squared norm 1/16. The declared local
corrections identify the same encoded state in every branch, up to global phase.
This is checked on both computational basis columns, including their relative
phase, for source SE and the actual geometry-derived atom-action SE.

For a fixed Pauli/readout fault history, all operations except the isolated seed
T are Clifford, resets or Pauli measurements. Immediately before T the ideal
central state is |+>: X**x Z**z |+> equals Z**z |+> up to phase. Because T commutes
with Z, pre-T faults therefore become a Pauli on the real T|+> seed. This is a
state-specific identity, not a Clifford replacement or an arbitrary-input gate
channel. Pauli covariance shifts the four uniform bulk bits and the detector
bits by constants for each history. Independent, unconditional channel weights
do not depend on those bulk bits, so P(accept, class=b) = P(accept)/16 exactly.

The result ends before physical canonicalization. Passing the detectors can
leave a residual syndrome: two readout flips on the same bulk check in adjacent
rounds pass while requesting a wrong correction. No accepted-state density,
logical-error channel, or downstream factory quality follows from this table.
"""

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from nadit_physical_compiler.device import Device

from ...contracts.component import CorrectionRelation
from ...contracts.event_probability import ProbabilityPort
from ..components.injection import CORRECTIONS
from ..definition import ROLES
from ..protocols.raw_t_postselection import RawTPostselectionExpansion
from .preparation import PREPARATION_BITS
from .raw_t import raw_t_pauli_port


def _validate_corrections(sequence: RawTPostselectionExpansion) -> None:
    """Require exactly the frozen first-round relations defining class bits."""
    first = sequence.parts[0]
    outputs = {output.port: output.result for output in first.measurements}
    expected = tuple(
        CorrectionRelation(
            first.block_id,
            outputs[term.measurement_port],
            tuple(
                (first.wire_atoms[ROLES.index(role)], basis)
                for role, basis in term.pauli_roles
            ),
        )
        for term in CORRECTIONS
    )
    if sequence.correction_relations != expected:
        raise ValueError(
            "Raw-T joint events require the frozen local correction relations."
        )


def raw_t_preparation_port(
    sequence: RawTPostselectionExpansion,
    device: Device,
    *,
    noise_params: Mapping[str, Any],
) -> ProbabilityPort:
    """Return seventeen exclusive acceptance/byproduct outcomes for actual actions.

    The existing detector producer admits the complete source/action timeline and
    independent noise/v1 Pauli/readout model. Its loss exclusions, occupied-world
    scope and open final temporal boundary remain unchanged. The sixteen accepted
    classes use little-endian first-round (X1, X2, Z1, Z2) recorded bits. These
    coarse classes do not populate individual physical measurement records.
    """
    _validate_corrections(sequence)
    acceptance = raw_t_pauli_port(sequence, device, noise_params=noise_params)
    acceptance_document = acceptance.to_dict()
    model = acceptance_document["model"]
    probability = acceptance.outcome("accepted").probability
    protocol = "rotated_surface_d3.raw_t_postselection"
    return ProbabilityPort.from_dict(
        {
            "schema": "nadit.event_probability/1",
            "port_id": f"{protocol}.canonical_preparation",
            "protocol_id": protocol,
            "protocol_version": "1",
            "model": {
                "id": "raw_t_postselection.pauli_joint_preparation.v1",
                "kind": "pauli_exact",
                "assumptions": [
                    *model["assumptions"],
                    "Frozen product seed and first-round local correction relations",
                    "For every fixed fault history the four bulk bits remain uniform",
                    "First-round recorded bulk bits label the local correction class",
                    "This event precedes physical canonicalization and its noise",
                    "A coarse class does not populate individual physical records",
                ],
                "parameters": {
                    "preparation": "raw_t_postselection",
                    **model["parameters"],
                },
                "evidence": {
                    **model["evidence"],
                    "acceptance_port_sha256": acceptance.content_sha256,
                    "joint_estimator_source_sha256": sha256(
                        Path(__file__).read_bytes()
                    ).hexdigest(),
                    "class_bit_order": list(PREPARATION_BITS["raw_t_postselection"]),
                    "class_encoding": "little_endian",
                    "joint_uniformity_proof": {
                        "scope": "frozen_product_seed_independent_pauli_readout",
                        "seed_isometry": (
                            "K_b^dagger K_b = I/16 and C_b K_b = phase_b K_0 "
                            "for all sixteen branches, for arbitrary central seed"
                        ),
                        "pre_t_identity": (
                            "T X^x Z^z |+> = global_phase Z^z T|+>; "
                            "the center is not entangled before its unique T"
                        ),
                        "fixed_fault_history": (
                            "Recorded bulk B = R xor delta_B(f), detectors D = "
                            "delta_D(f); R is uniform and fault weights "
                            "independent of R"
                        ),
                        "conclusion": "P(accepted, B=b) = P(accepted)/16",
                        "verification": (
                            "test_raw_t_preparation: source/actual isometry columns, "
                            "real-T seed fault and double-readout-flip branches"
                        ),
                        "not_generalized_to": [
                            "coherent_noise",
                            "state_dependent_or_branch_conditioned_channels",
                            "arbitrary_pre_t_center_states",
                            "physical_canonicalization_noise",
                        ],
                    },
                    "accepted_quality": {
                        "status": "unsupported",
                        "reason": (
                            "Acceptance can leave a nonzero stabilizer sector; "
                            "this event table does not determine a conditional "
                            "density matrix or an iid logical-Z mixture"
                        ),
                        "physical_canonicalization_included": False,
                        "downstream_storage_included": False,
                    },
                },
            },
            "outcomes": [
                {
                    "key": f"accepted_{index}",
                    "probability": probability / 16,
                    "values": {"accepted": True, "byproduct_class": index},
                    "branch_id": "canonicalize",
                }
                for index in range(16)
            ]
            + [
                {
                    "key": "rejected",
                    "probability": acceptance.outcome("rejected").probability,
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
