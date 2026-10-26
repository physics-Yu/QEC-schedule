"""Binary raw-T acceptance from admitted distance-specific physical trajectories.

This producer evaluates explicit independent Pauli/readout noise. It returns
offline acceptance metadata, not measurement samples or canonical-class draws.
Loss, leakage, coherence, and accepted-output logical quality remain excluded.
"""

from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from nadit_physical_compiler.cost import model_for, prepare
from nadit_physical_compiler.cost.noise.config import resolve
from nadit_physical_compiler.device import Device
from nadit_physical_compiler.provenance import canonical_hash

from modules.codes._support.detector_probability import estimate_acceptance
from modules.codes._support.pauli_detector_events import detector_fault_channels
from modules.codes._support.raw_t_round_policy import (
    RAW_T_PROTOCOL_VERSION,
    resolve_postselection_rounds,
)
from modules.codes._support.raw_t_sequence import joint_raw_t_document
from modules.codes.contracts.component import MeasurementOutput, validate_sequence
from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.rotated_surface.components import SurfaceComponent
from modules.codes.rotated_surface.definition import definition
from modules.codes.rotated_surface.raw_t_postselection import RawTPostselectionExpansion


def _sources(distance: int, extra_rounds: int) -> tuple[str, ...]:
    return (
        SurfaceComponent("raw_t", distance).source_qasm,
        *(
            SurfaceComponent("se_round", distance).source_qasm
            for _ in range(extra_rounds)
        ),
    )


def _admit(sequence: RawTPostselectionExpansion, distance: int) -> None:
    """Require exact code identities, result roles, and deterministic predicates."""
    code = definition(distance)
    if len(sequence.parts) < 2:
        raise ValueError("Raw-T acceptance requires at least one additional SE round.")
    validate_sequence(sequence.parts)
    first = sequence.parts[0]
    if (
        len(first.wire_atoms) != code.atom_count
        or len(set(first.wire_atoms)) != code.atom_count
        or any(type(atom) is not int or atom < 0 for atom in first.wire_atoms)
    ):
        raise ValueError("Raw-T distance disagrees with its participant code roles.")
    resolve_postselection_rounds(
        distance, len(sequence.parts) - 1, round_policy=sequence.round_policy
    )
    for index, part in enumerate(sequence.parts):
        component = SurfaceComponent("raw_t" if index == 0 else "se_round", distance)
        if (
            part.description != component.description
            or part.wire_atoms != first.wire_atoms
            or part.block_id != first.block_id
            or part.exit_binding != first.exit_binding
        ):
            raise ValueError(
                "Raw-T distance/code component metadata or binding mismatch."
            )
        if tuple(m.port for m in part.measurements) != code.check_roles:
            raise ValueError(
                "Raw-T measurement ports do not match the distance-specific code."
            )
        if any(
            m.invocation_id != part.invocation_id
            or m.atom_id != part.wire_atoms[code.data_count + j]
            for j, m in enumerate(part.measurements)
        ):
            raise ValueError(
                "Raw-T result identities do not match their measured atom roles."
            )
        if any(m.value is not None for m in part.measurements):
            raise ValueError(
                "Offline raw-T probabilities require unobserved measurements."
            )
        ports = {m.port: m for m in part.measurements}
        expected_acceptance = tuple(
            (ports[p].result, 0) for p in component.acceptance_ports
        )
        if part.acceptance_conditions != expected_acceptance:
            raise ValueError(
                "Raw-T acceptance predicates differ from the approved code."
            )
    initial_ports = SurfaceComponent("raw_t", distance).acceptance_ports
    rounds = tuple({m.port: m for m in part.measurements} for part in sequence.parts)
    expected_detectors: tuple[tuple[str, tuple[MeasurementOutput, ...]], ...] = tuple(
        (f"boundary.{port}", (rounds[0][port],)) for port in initial_ports
    )
    expected_detectors += tuple(
        (f"round[{r}].{port}", (rounds[r - 1][port], rounds[r][port]))
        for r in range(1, len(rounds))
        for port in code.check_roles
    )
    if (
        tuple((d.name, d.measurements) for d in sequence.detectors)
        != expected_detectors
    ):
        raise ValueError(
            "Raw-T detector identities differ from the approved code sequence."
        )
    if (
        sequence.protocol_id != "raw_t_postselection"
        or sequence.version != RAW_T_PROTOCOL_VERSION
        or sequence.postselection_scope
        != "first_deterministic_and_adjacent_round_parities"
        or sequence.terminal_boundary != "open_after_last_se"
    ):
        raise ValueError("Raw-T detector protocol scope or version is unsupported.")


def _joint_document(
    sequence: RawTPostselectionExpansion, device: Device, *, distance: int
) -> dict[str, Any]:
    """Admit code semantics then revalidate the complete rebased physical segment."""
    _admit(sequence, distance)
    code = definition(distance)
    return joint_raw_t_document(
        sequence,
        device,
        sources=_sources(distance, len(sequence.parts) - 1),
        participant_count=code.atom_count,
        measurements_per_round=code.check_count,
    )


def _estimator_sources() -> dict[str, str]:
    """Fingerprint the mathematical, timeline, detector and physical noise code."""
    codes = Path(__file__).resolve().parents[2]
    modules = codes.parent
    files = [
        path
        for path in (codes / "rotated_surface").rglob("*.py")
        if "tests" not in path.parts
    ]
    files += [
        codes / "_support" / name
        for name in (
            "raw_t_sequence.py",
            "raw_t_round_policy.py",
            "pauli_detector_events.py",
            "detector_probability.py",
        )
    ]
    files += list(
        (modules / "physical_compiler/src/nadit_physical_compiler").rglob("*.py")
    )
    return {
        path.relative_to(modules).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in sorted(set(files))
    }


def _port(distance: int, probability: float, model: dict[str, Any]) -> ProbabilityPort:
    return ProbabilityPort.from_dict(
        {
            "schema": "nadit.event_probability/1",
            "port_id": f"rotated_surface_d{distance}.raw_t_postselection.acceptance",
            "protocol_id": f"rotated_surface_d{distance}.raw_t_postselection",
            "protocol_version": RAW_T_PROTOCOL_VERSION,
            "model": model,
            "outcomes": [
                {
                    "key": "accepted",
                    "probability": probability,
                    "values": {"accepted": True},
                    "branch_id": "deliver",
                },
                {
                    "key": "rejected",
                    "probability": 1 - probability,
                    "values": {"accepted": False},
                    "branch_id": "retry",
                },
            ],
            "branches": [
                {"key": "deliver", "transition": "deliver", "steps": []},
                {"key": "retry", "transition": "retry", "steps": []},
            ],
        }
    )


def raw_t_acceptance_port(
    sequence: RawTPostselectionExpansion,
    device: Device,
    *,
    distance: int,
    noise_params: Mapping[str, Any],
    method: str = "auto",
    shots: int = 262144,
    seed: int = 0,
    batch_size: int = 65536,
) -> ProbabilityPort:
    """Calculate binary acceptance under explicit independent Pauli/readout noise.

    Args:
        sequence: Unobserved actual raw-T plus repeated-SE component expansions.
        device: The exact device used by all participant and spectator actions.
        distance: Approved odd code distance; must match every source and role.
        noise_params: Explicit noise/v1 parameters; {} explicitly selects zero noise.
        method: auto, exact, or monte_carlo; never falls back to an ideal model.
        shots: Monte Carlo trials, when selected by the bounded probability engine.
        seed: Reproducible estimator RNG seed, not a runtime measurement seed.
        batch_size: Memory-bounded Monte Carlo batch size.
    Returns:
        An immutable accepted/rejected ProbabilityPort with full evidence. Model
        kind is pauli_exact or estimated; accepted-output quality is not estimated.
    Raises:
        ValueError: If code/source/detectors, noise, trajectories, or estimator
            controls are invalid, or a non-Pauli model is requested.
    """
    if not isinstance(noise_params, Mapping):
        raise ValueError("Raw-T acceptance requires explicit noise_params mapping.")
    if method not in ("auto", "exact", "monte_carlo"):
        raise ValueError("Raw-T method must be auto, exact, or monte_carlo.")
    params = resolve(noise_params)
    gate_models = [params["single"], params["cz"], *params["single_overrides"].values()]
    if any(model["backend"] != "pauli" for model in gate_models):
        raise ValueError(
            "Raw-T acceptance requires explicit independent Pauli gate models."
        )
    document = _joint_document(sequence, device, distance=distance)
    activity = prepare(document)
    noise = model_for("noise/v1").evaluate(activity, document, params)
    detectors = tuple(
        tuple(m.result.measurement_id for m in d.measurements)
        for d in sequence.detectors
    )
    atoms = sequence.parts[0].wire_atoms
    seed_atom = atoms[definition(distance).data_count // 2]
    channels, proof = detector_fault_channels(
        activity,
        noise["noise"]["channels"],
        detectors,
        wire_atoms=atoms,
        seed_atom=seed_atom,
        world_atom_ids=tuple(atom.atom_id for atom in activity.per_atom),
    )
    estimate = estimate_acceptance(
        len(detectors),
        channels,
        method=method,
        shots=shots,
        seed=seed,
        batch_size=batch_size,
    )
    estimated = estimate["kind"] == "estimated"
    sampling = (
        {
            key: estimate[key]
            for key in ("method", "shots", "accepted", "seed", "batch_size")
        }
        if estimated
        else None
    )
    evidence = {
        **proof,
        "estimator": estimate,
        "scope": "pauli_readout_only",
        "conditioning": (
            "Computational subspace with retained atoms; loss is not propagated"
        ),
        "terminal_boundary": sequence.terminal_boundary,
        "postselection_scope": sequence.postselection_scope,
        "protocol_version": RAW_T_PROTOCOL_VERSION,
        "distance": distance,
        "extra_rounds": len(sequence.parts) - 1,
        "total_rounds": len(sequence.parts),
        "round_policy": sequence.round_policy,
        "template_content_sha256": sequence.template_content_sha256,
        "part_template_content_sha256": [
            p.template_content_sha256 for p in sequence.parts
        ],
        "source_profile_sha256": canonical_hash(
            {"sources": list(_sources(distance, len(sequence.parts) - 1))}
        ),
        "result_hash": noise["result_hash"],
        "source_qasm_sha256": document["inputs"]["qasm_sha256"],
        "device_sha256": document["inputs"]["device_sha256"],
        "noise_model": {
            "registered_id": "noise/v1",
            "model": noise["model"],
            "version": noise["version"],
        },
        "noise_params_hash": noise["params_hash"],
        "noise_report_sha256": canonical_hash(noise),
        "detectors_sha256": canonical_hash({"detectors": [list(d) for d in detectors]}),
        "channel_signatures_sha256": canonical_hash(
            {"channels": [[list(branch) for branch in channel] for channel in channels]}
        ),
        "estimator_sources_sha256": canonical_hash(_estimator_sources()),
        "activity_duration_us": activity.duration_us,
        "world_atom_ids": [atom.atom_id for atom in activity.per_atom],
        "participant_atom_ids": list(atoms),
        "seed_atom_id": seed_atom,
        "segment_start_us": sequence.parts[0].start_us,
        "segment_action_end_us": sequence.action_end_us,
        "segment_results_ready_us": sequence.results_ready_us,
        "quality_horizon": {
            "kind": "results_ready",
            "absolute_time_us": sequence.results_ready_us,
            "quality_estimated": False,
        },
        "accepted_output_quality": "not_estimated",
        "canonical_class_distribution": "not_provided",
        "canonical_classes_sampled": False,
        "prefix_exposure_included": False,
        "post_horizon_storage_included": False,
        "exposure_semantics": (
            "noise/v1 T2 applies to idle/configured transport, "
            "not busy gates/reset/readout"
        ),
        "initial_world_quantum_state": (
            "Participants are reset; spectator states are unspecified "
            "with no ideal participant coupling"
        ),
        "physical_loss": noise["noise"]["loss"],
        "excluded_effects": [
            "physical_atom_loss",
            "leakage",
            "coherent_non_pauli_effects",
        ],
        "calculation": estimate["method"],
        "sampling": sampling,
        "statistical_uncertainty": (
            {
                "ci95": estimate["ci95"],
                "confidence_level": 0.95,
                "method": estimate["ci_method"],
            }
            if estimated
            else None
        ),
        "normalization_absolute_tolerance": estimate[
            "normalization_absolute_tolerance"
        ],
        "logical_error_rate_claimed": False,
        "structural_validation_bits_are_samples": False,
    }
    return _port(
        distance,
        estimate["probability"],
        {
            "id": (
                f"rotated_surface_d{distance}.raw_t_postselection.pauli_acceptance.v2"
            ),
            "kind": "estimated" if estimated else "pauli_exact",
            "assumptions": [
                "Approved unobserved distance-specific raw-T and complete SE rounds",
                "Independent noise/v1 Pauli/readout channels; alternatives exclusive",
                "Acceptance only; accepted does not imply an error-free logical output",
                "Physical loss, leakage and non-Pauli coherence excluded",
                "Final temporal boundary remains open after the last SE",
                "Include actual segment exposure, round gaps and final result delivery",
                "No common-mode noise, runtime draws, or canonicalization inferred",
                "No cross-invocation noise correlation is modeled",
            ],
            "parameters": {
                "distance": distance,
                "extra_rounds": len(sequence.parts) - 1,
                "total_rounds": len(sequence.parts),
                "round_policy": sequence.round_policy,
                "noise": noise["params"],
                "requested_method": method,
                "requested_shots": shots,
                "requested_seed": seed,
                "requested_batch_size": batch_size,
            },
            "evidence": evidence,
        },
    )
