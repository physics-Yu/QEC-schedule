"""Code-owned finite raw-T acceptance ports; no event sampling or frame state.

The ideal port is analytic. The explicit Pauli route revalidates a complete
actual-action timeline, evaluates noise/v1 once, and proves detector independence
from the real T seed before exact finite convolution. Loss is reported separately.
"""

import json
import re
from collections.abc import Mapping
from dataclasses import replace
from hashlib import sha256
from math import isfinite
from pathlib import Path
from typing import Any

from nadit_physical_compiler.atom_ir import AtomProgram, AtomStep, Measure, Wait
from nadit_physical_compiler.compiler import (
    CompilationResult,
    CompiledOperation,
    MeasurementRecord,
)
from nadit_physical_compiler.cost import model_for, prepare
from nadit_physical_compiler.cost.noise.config import resolve
from nadit_physical_compiler.device import Device
from nadit_physical_compiler.frontend import loads_qasm
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.serialization import encode_device, encode_result
from nadit_physical_compiler.validation import validate_result

from ..._support.raw_t_round_policy import (
    RAW_T_PROTOCOL_VERSION,
    resolve_postselection_rounds,
)
from ...contracts.event_probability import ProbabilityPort
from ..components.circuits import source_qasm
from ..components.injection import RawTComponent
from ..protocols.raw_t_postselection import RawTPostselectionExpansion
from .raw_t_detectors import MAX_DETECTORS, detector_fault_channels, xor_distribution


def _sequence_parameters(sequence: RawTPostselectionExpansion) -> dict[str, Any]:
    extra = resolve_postselection_rounds(
        3, len(sequence.parts) - 1, round_policy=sequence.round_policy
    )
    if sequence.version != RAW_T_PROTOCOL_VERSION:
        raise ValueError("Raw-T probability requires the current protocol version.")
    return {
        "distance": 3,
        "extra_rounds": extra,
        "total_rounds": extra + 1,
        "round_policy": sequence.round_policy,
    }


def _json_hash(value: Any) -> str:
    """Hash a finite JSON array or object with the shared canonical encoding."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _port(acceptance: float, model: dict[str, Any]) -> ProbabilityPort:
    return ProbabilityPort.from_dict(
        {
            "schema": "nadit.event_probability/1",
            "port_id": "rotated_surface_d3.raw_t_postselection.acceptance",
            "protocol_id": "rotated_surface_d3.raw_t_postselection",
            "protocol_version": RAW_T_PROTOCOL_VERSION,
            "model": model,
            "outcomes": [
                {
                    "key": "accepted",
                    "probability": acceptance,
                    "values": {"accepted": True},
                    "branch_id": "deliver",
                },
                {
                    "key": "rejected",
                    "probability": 1 - acceptance,
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


def _sources(extra_rounds: int) -> tuple[str, ...]:
    return (
        RawTComponent().source_qasm,
        *(source_qasm("se_round") for _ in range(extra_rounds)),
    )


def _shift_measurements(body: str, offset: int) -> str:
    """Give each concatenated round distinct classical source wires."""
    return re.sub(r"m\[(\d+)\]", lambda match: f"m[{int(match[1]) + offset}]", body)


def raw_t_ideal_port(
    extra_rounds: int | None = None, *, round_policy: str = "distance"
) -> ProbabilityPort:
    """Return ideal acceptance for normal three-round d3 preparation or a control.

    A retry repeats the full protocol at its physical cost. This coarse event
    neither resolves random bulk signs nor claims an implemented frame update.
    """
    extra_rounds = resolve_postselection_rounds(
        3, extra_rounds, round_policy=round_policy
    )
    return _port(
        1.0,
        {
            "id": "raw_t_postselection.ideal.v2",
            "kind": "ideal_exact",
            "assumptions": [
                "Ideal raw T|+> center injection and complete ordinary SE rounds",
                "Four first-boundary and every adjacent-round parity are zero",
                "No physical noise or loss; no intermediate Pauli correction",
                "Acceptance does not resolve the random first-round bulk signs",
            ],
            "parameters": {
                "distance": 3,
                "extra_rounds": extra_rounds,
                "total_rounds": extra_rounds + 1,
                "round_policy": round_policy,
            },
            "evidence": {
                "source_profile_sha256": _json_hash(list(_sources(extra_rounds))),
                "detector_count": 4 + 8 * extra_rounds,
                "postselection_scope": "first_boundary_and_adjacent_round_parities",
                "terminal_boundary": "open_after_last_se",
                "calculation": (
                    "Ideal deterministic stabilizer boundary and repeated parities"
                ),
                "logical_error_rate_claimed": False,
            },
        },
    )


def _joint_document(
    sequence: RawTPostselectionExpansion, device: Device
) -> dict[str, Any]:
    """Join original physical parts and revalidate one complete v2 timeline.

    Value-zero records are structural validation placeholders, never sampled or
    used to construct probabilities. Only the unobserved detector identities are
    consumed. One activity derivation prevents duplicate per-part idle tails.
    The complete occupied world is retained for semantic validation and cost;
    the seventeen DAG wires refer only to this raw preparation's participants.
    The segment is rebased to its first action, excluding earlier world history.
    """
    _sequence_parameters(sequence)
    if any(record.value is not None for record in sequence.measurements):
        raise ValueError(
            "Offline model construction requires unobserved measurement ports."
        )
    if len(sequence.parts[0].wire_atoms) != 17:
        raise ValueError("Raw-T estimation requires seventeen participant roles.")
    sources = _sources(len(sequence.parts) - 1)
    bodies: list[str] = []
    steps: list[AtomStep] = []
    operations: list[CompiledOperation] = []
    measurements: list[MeasurementRecord] = []
    node_base = 0
    previous_end = sequence.parts[0].start_us
    cursor = 0.0
    latency = device.readout.latency_us if device.readout is not None else 0.0
    for index, (part, source) in enumerate(zip(sequence.parts, sources, strict=True)):
        expected = loads_qasm(source)
        local_ids = {
            i: m.result.measurement_id for i, m in enumerate(part.measurements)
        }
        expected = replace(
            expected,
            nodes=tuple(
                replace(node, source_id=local_ids[node.clbits[0]])
                if node.result is not None
                else node
                for node in expected.nodes
            ),
        )
        if expected != part.dag:
            raise ValueError("Unapproved raw-T/SE source profile in estimator input.")
        lines = source.splitlines()
        if lines[:4] != [
            "OPENQASM 3.0;",
            'include "stdgates.inc";',
            "qubit[17] q;",
            "bit[8] m;",
        ]:
            raise ValueError("Unrecognized source register profile.")
        bodies.append(_shift_measurements("\n".join(lines[4:]), 8 * index))
        gap = part.start_us - previous_end
        if gap < -1e-9:
            raise ValueError("Raw-T component action timelines overlap.")
        if gap > 1e-9:
            steps.append(AtomStep((Wait(duration_us=gap),)))
            cursor += gap
        # Rebase private records using the same ordered additions as this joined
        # program. Subtracting a large absolute clock can exceed the validator's
        # tolerance even when the original source records are exactly correct.
        offset = cursor
        time_map = {0.0: cursor}
        absolute_cursor = part.start_us
        absolute_ready: dict[int, float] = {}
        local_ready: dict[int, float] = {}
        for local_start, step in part.program.timeline():
            time_map[local_start] = cursor
            for action in step.actions:
                time_map[local_start + action.duration_us] = cursor + action.duration_us
                if isinstance(action, Measure):
                    for _, reference in action.results:
                        absolute_ready[reference.measurement_id] = (
                            absolute_cursor + action.duration_us + latency
                        )
                        local_ready[reference.measurement_id] = (
                            cursor + action.duration_us + latency
                        )
            steps.append(
                replace(
                    step,
                    actions=tuple(
                        replace(
                            action,
                            source_ids=tuple(n + node_base for n in action.source_ids),
                        )
                        for action in step.actions
                    ),
                )
            )
            cursor += step.duration_us
            absolute_cursor += step.duration_us
            time_map[local_start + step.duration_us] = cursor
        operations.extend(
            replace(
                operation,
                operation_id=operation.operation_id + node_base,
                start_us=time_map.get(operation.start_us, offset + operation.start_us),
                end_us=time_map.get(operation.end_us, offset + operation.end_us),
            )
            for operation in part.operations
        )
        for measurement in part.measurements:
            identity = measurement.result.measurement_id
            delay = measurement.available_at_us - absolute_ready[identity]
            if not isfinite(delay):
                raise ValueError("Source measurement availability must be finite.")
            if delay < -1e-9:
                raise ValueError(
                    "Source measurement precedes actual result availability."
                )
            # Preserve an explicit delivery delay, but never rewrite the public
            # measurement/event time or infer extra delay from clock rebasing.
            measurements.append(
                MeasurementRecord(
                    measurement.result, 0, local_ready[identity] + max(0.0, delay)
                )
            )
        node_base += len(part.dag.nodes)
        previous_end = part.action_end_us
    joined_source = "\n".join(
        [
            "OPENQASM 3.0;",
            'include "stdgates.inc";',
            "qubit[17] q;",
            f"bit[{len(sequence.measurements)}] m;",
            *bodies,
            "",
        ]
    )
    dag = loads_qasm(joined_source)
    ids = {i: m.result.measurement_id for i, m in enumerate(sequence.measurements)}
    dag = replace(
        dag,
        nodes=tuple(
            replace(n, source_id=ids[n.clbits[0]]) if n.result is not None else n
            for n in dag.nodes
        ),
    )
    entry = replace(
        sequence.parts[0].entry_state, qubit_to_atom=sequence.parts[0].wire_atoms
    )
    exit_state = replace(
        sequence.exit_state, qubit_to_atom=sequence.parts[0].wire_atoms
    )
    program = AtomProgram(
        tuple(steps), sum(part.program.global_phase for part in sequence.parts)
    )
    result = CompilationResult(
        program,
        exit_state,
        tuple(operations),
        tuple(measurements),
        (),
    )
    validation = validate_result(result, entry_state=entry, device=device, dag=dag)
    if not validation["ok"]:
        raise ValueError(f"Combined raw-T semantic admission failed: {validation}")
    return encode_result(
        result,
        entry_state=entry,
        job={"strategy": {"kind": "nonzoned"}},
        provenance={"purpose": "offline_raw_t_detector_probability"},
        validation=validation,
        dag=dag,
        device=device,
        inputs={
            "qasm_sha256": sha256(joined_source.encode()).hexdigest(),
            "device_sha256": canonical_hash(encode_device(device)),
        },
    )


def raw_t_pauli_port(
    sequence: RawTPostselectionExpansion,
    device: Device,
    *,
    noise_params: Mapping[str, Any],
) -> ProbabilityPort:
    """Calculate exact acceptance for explicitly supplied independent Pauli noise.

    The scope is Pauli/readout only: physical loss for the complete occupied world
    is reported separately and no heralded-loss rejection is invented. This is
    an isolated preparation segment, including inter-round gaps and the final
    result-ready wait, not a factory quality estimate. Earlier world history,
    later storage and canonicalization are excluded. Native coherent/twirled
    models and more than 20 detectors are unsupported. No decoder is invoked.
    """
    count = len(sequence.detectors)
    if count > MAX_DETECTORS:
        raise ValueError("Exact raw-T detector table is bounded to twenty detectors.")
    params = resolve(noise_params)
    gate_models = [params["single"], params["cz"], *params["single_overrides"].values()]
    if any(model["backend"] != "pauli" for model in gate_models):
        raise ValueError(
            "This estimator requires independent Pauli gate models; "
            "native twirling is not implicit."
        )
    document = _joint_document(sequence, device)
    activity = prepare(document)
    noise = model_for("noise/v1").evaluate(activity, document, params)
    detectors = tuple(
        tuple(m.result.measurement_id for m in d.measurements)
        for d in sequence.detectors
    )
    channels, proof = detector_fault_channels(
        activity,
        noise["noise"]["channels"],
        detectors,
        wire_atoms=sequence.parts[0].wire_atoms,
        world_atom_ids=tuple(atom.atom_id for atom in activity.per_atom),
    )
    distribution = xor_distribution(count, channels)
    evidence = {
        **proof,
        "scope": "pauli_readout_only",
        "conditioning": (
            "Computational subspace with retained atoms; "
            "physical loss is not propagated"
        ),
        "terminal_boundary": sequence.terminal_boundary,
        "postselection_scope": sequence.postselection_scope,
        "template_content_sha256": sequence.template_content_sha256,
        "part_template_content_sha256": [
            p.template_content_sha256 for p in sequence.parts
        ],
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
        "detectors_sha256": _json_hash([list(d) for d in detectors]),
        "channel_signatures_sha256": _json_hash(
            [[list(branch) for branch in channel] for channel in channels]
        ),
        "estimator_sources_sha256": canonical_hash(
            {
                p.name: sha256(p.read_bytes()).hexdigest()
                for p in (
                    Path(__file__),
                    Path(__file__).with_name("raw_t_detectors.py"),
                    Path(__file__).parents[2] / "_support" / "pauli_detector_events.py",
                    Path(__file__).parents[2] / "_support" / "raw_t_round_policy.py",
                    Path(__file__).parents[2] / "_support" / "detector_probability.py",
                )
            }
        ),
        "activity_duration_us": activity.duration_us,
        "world_atom_ids": [atom.atom_id for atom in activity.per_atom],
        "participant_atom_ids": list(sequence.parts[0].wire_atoms),
        "segment_start_us": sequence.parts[0].start_us,
        "segment_action_end_us": sequence.action_end_us,
        "segment_results_ready_us": sequence.results_ready_us,
        "quality_horizon": {
            "kind": "results_ready",
            "absolute_time_us": sequence.results_ready_us,
            "quality_estimated": False,
        },
        "prefix_exposure_included": False,
        "post_horizon_storage_included": False,
        "exposure_semantics": (
            "noise/v1 T2 applies to idle and configured transport intervals, "
            "not gate, reset or measurement busy intervals"
        ),
        "initial_world_quantum_state": (
            "Raw participants are explicitly reset before use; spectator quantum "
            "states are unspecified and have no ideal coupling to participants"
        ),
        "physical_loss": noise["noise"]["loss"],
        "excluded_effects": [
            "physical_atom_loss",
            "leakage",
            "coherent_non_pauli_effects",
        ],
        "calculation": (
            "Finite XOR convolution of exclusive Pauli/readout channel branches"
        ),
        "sampling": None,
        "statistical_uncertainty": None,
        "normalization_absolute_tolerance": 1e-12,
        "logical_error_rate_claimed": False,
        "structural_validation_bits_are_samples": False,
    }
    return _port(
        distribution[0],
        {
            "id": "raw_t_postselection.pauli_detector_exact.v2",
            "kind": "pauli_exact",
            "assumptions": [
                "Approved unobserved raw-T plus ordinary SE action sequence",
                (
                    "Independent noise/v1 Pauli channels; "
                    "alternatives within each channel exclusive"
                ),
                (
                    "Detector acceptance only; "
                    "accepted does not imply an error-free logical state"
                ),
                "Physical loss and leakage excluded from the acceptance event",
                "Final temporal boundary remains open after the last SE",
                (
                    "Only the actual isolated preparation segment is modeled; "
                    "no prior world noise, later storage or canonicalization "
                    "is inferred"
                ),
                (
                    "State-independent Markov Pauli/readout channels; "
                    "no common-mode noise or cross-invocation correlations"
                ),
            ],
            "parameters": {
                **_sequence_parameters(sequence),
                "noise": noise["params"],
            },
            "evidence": evidence,
        },
    )
