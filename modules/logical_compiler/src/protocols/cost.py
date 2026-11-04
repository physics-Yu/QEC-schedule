"""Validated noise/v1 post-processing of selected, unobserved atom programs.

The physical result validator currently requires bit-valued measurement records.
Private zero placeholders bridge that structural API only after all unresolved
physical conditions and all actually observed outputs have been rejected. They
are never exported, sampled or used to select a protocol continuation.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import asdict, replace
from hashlib import sha256
from math import hypot, isclose, isfinite, pi, remainder
from numbers import Real
from typing import Any

from nadit_physical_compiler.activity import (
    ActivityEvent,
    AtomActivity,
    Interval,
    PerAtomActivity,
)
from nadit_physical_compiler.compiler import CompilationResult, MeasurementRecord
from nadit_physical_compiler.cost import model_for, prepare
from nadit_physical_compiler.cost.noise.config import resolve
from nadit_physical_compiler.frontend import loads_qasm
from nadit_physical_compiler.physical_ir import PhysicalDAG
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.serialization import (
    encode_dag,
    encode_device,
    encode_layout,
    encode_program,
    encode_result,
)
from nadit_physical_compiler.validation import validate_result
from qiskit import QuantumCircuit, qasm3

from .assembly import PhysicalBundle

_SCOPE = "selected_actions_unobserved_measurements"


class PhysicalCostError(ValueError):
    """Reject an unsupported, unvalidated or inconsistent cost input."""


def _validated_snapshot(bundle: PhysicalBundle) -> dict[str, Any]:
    if not isinstance(bundle, PhysicalBundle):
        raise PhysicalCostError("INVALID_COST_BUNDLE: expected a PhysicalBundle")
    if any(node.condition is not None for node in bundle.dag.nodes):
        raise PhysicalCostError(
            "UNSUPPORTED_PHYSICAL_CONDITION: structural bits cannot select branches"
        )
    if any(output.value is not None for output in bundle.pending_measurements):
        raise PhysicalCostError(
            "UNSUPPORTED_OBSERVED_MEASUREMENT: cost adapter requires pending outputs"
        )
    snapshot = bundle.to_dict()
    validation = snapshot.get("validation", {})
    if (
        snapshot.get("schema") != "nadit.logical_physical_program/1"
        or snapshot.get("artifact_kind") != "selected_atom_program"
        or snapshot.get("measurement_evidence") != "unobserved"
        or snapshot.get("physical_execution") is not False
        or validation.get("ok") is not True
        or validation.get("semantic") != "checked"
        or not {"pulse", "timing"} <= set(validation.get("checks", ()))
        or validation.get("scope") != _SCOPE
        or validation.get("measurement_values_verified") is not False
    ):
        raise PhysicalCostError(
            "UNVALIDATED_COST_BUNDLE: require semantic pulse/timing evidence for unobserved actions"
        )
    actual = {
        "program": encode_program(bundle.program),
        "dag": encode_dag(bundle.dag),
        "entry_state": encode_layout(bundle.entry_world),
        "exit_state": encode_layout(bundle.world),
        "device": encode_device(bundle.device),
        "operations": [asdict(operation) for operation in bundle.operations],
        "pending_measurements": [
            asdict(output) for output in bundle.pending_measurements
        ],
    }
    saved = {key: snapshot.get(key) for key in actual}
    if canonical_hash(actual) != canonical_hash(saved):
        raise PhysicalCostError(
            "BUNDLE_CONTENT_MISMATCH: runtime records differ from their validation snapshot"
        )
    return snapshot


def _generated_qasm(dag: PhysicalDAG) -> str:
    """Serialize the native selected circuit and verify its semantic round trip.

    Original source IDs and additional scheduling edges remain in the original
    DAG; this new text describes its ordered operations, not original user QASM.
    """
    circuit = QuantumCircuit(dag.num_qubits, dag.num_clbits)
    signatures = {
        "rx": (1, 0, 1),
        "ry": (1, 0, 1),
        "rz": (1, 0, 1),
        "cz": (2, 0, 0),
        "reset": (1, 0, 0),
        "measure": (1, 1, 0),
    }
    for node in dag.nodes:
        if (
            node.name == "barrier"
            and node.qubits
            and not node.params
            and not node.clbits
        ):
            circuit.barrier(*node.qubits)
            continue
        signature = (len(node.qubits), len(node.clbits), len(node.params))
        if signatures.get(node.name) != signature:
            raise PhysicalCostError(
                f"UNSUPPORTED_COST_GATE: cannot serialize {node.name!r} with signature {signature}"
            )
        if node.name in ("rx", "ry", "rz"):
            getattr(circuit, node.name)(node.params[0], node.qubits[0])
        elif node.name == "cz":
            circuit.cz(*node.qubits)
        elif node.name == "reset":
            circuit.reset(node.qubits[0])
        else:
            circuit.measure(node.qubits[0], node.clbits[0])
    # The installed Qiskit exporter drops QuantumCircuit.global_phase. Explicit
    # OpenQASM gphase is supported by the existing importer and retains it here.
    source: str = qasm3.dumps(circuit) + f"gphase({dag.global_phase!r});\n"
    restored = loads_qasm(source)
    if (restored.num_qubits, restored.num_clbits, len(restored.nodes)) != (
        dag.num_qubits,
        dag.num_clbits,
        len(dag.nodes),
    ):
        raise PhysicalCostError(
            "QASM_ROUNDTRIP_MISMATCH: wire or operation counts changed"
        )
    for original, decoded in zip(dag.nodes, restored.nodes, strict=True):
        if (
            (original.name, original.qubits, original.clbits)
            != (decoded.name, decoded.qubits, decoded.clbits)
            or len(original.params) != len(decoded.params)
            or any(
                not isclose(a, b, rel_tol=0, abs_tol=1e-12)
                for a, b in zip(original.params, decoded.params, strict=True)
            )
        ):
            raise PhysicalCostError(
                "QASM_ROUNDTRIP_MISMATCH: operation order or arguments changed"
            )
    if not isclose(
        remainder(restored.global_phase - dag.global_phase, 2 * pi),
        0,
        rel_tol=0,
        abs_tol=1e-12,
    ):
        raise PhysicalCostError("QASM_ROUNDTRIP_MISMATCH: global phase changed")
    return source


def _structural_document(
    bundle: PhysicalBundle, bundle_hash: str, generated_qasm: str
) -> dict[str, Any]:
    # No output value is read here. Availability and global result IDs are real;
    # the fixed zeros exist only within this private validation/cost projection.
    structural = CompilationResult(
        bundle.program,
        bundle.world,
        bundle.operations,
        tuple(
            MeasurementRecord(output.result, 0, output.available_at_us)
            for output in bundle.pending_measurements
        ),
        (),
    )
    checked = validate_result(
        structural,
        entry_state=bundle.entry_world,
        device=bundle.device,
        dag=bundle.dag,
    )
    if not checked["ok"]:
        raise PhysicalCostError(
            f"COST_PHYSICAL_VALIDATION_FAILED: {checked.get('failure')}"
        )
    return encode_result(
        structural,
        entry_state=bundle.entry_world,
        job={"strategy": {"kind": "nonzoned"}},
        provenance={
            "purpose": "unobserved_physical_cost_projection",
            "compiler": {
                "name": "logical_compiler.unobserved_cost_adapter",
                "version": "1",
            },
            "source_bundle_sha256": bundle_hash,
            "generated_from_selected_dag": True,
            "generated_qasm_roundtrip_checked": True,
            "structural_measurement_values_are_observations": False,
        },
        validation=checked,
        dag=bundle.dag,
        device=bundle.device,
        inputs={
            "qasm_sha256": sha256(generated_qasm.encode("utf-8")).hexdigest(),
            "device_sha256": canonical_hash(encode_device(bundle.device)),
        },
    )


def evaluate_physical_cost(
    bundle: PhysicalBundle, noise_params: Mapping[str, Any]
) -> dict[str, Any]:
    """Evaluate noise/v1 from the real validated actions and explicit parameters.

    Args:
        bundle: Complete selected-action bundle with unobserved physical outputs.
        noise_params: Explicit noise/v1 configuration; an empty mapping explicitly
            requests that model's defaults. No logical-error parameters are inferred.

    Returns:
        The physical noise report, source hashes and explicit scope annotations.
        ``logical_success`` is always None. Structural measurement bits and the
        temporary nadit.result/2 document are not returned or attached to the bundle.
        ``generated_qasm`` is new selected-DAG text, not the user's original source.

    Raises:
        PhysicalCostError: Input evidence, contents or unobserved semantics are invalid.
        ValueError: Physical revalidation, noise configuration or model evaluation fails.

    Native physical models retain their own approximation/leakage diagnostics.
    Neither no_fault_probability nor the physical fidelity proxy is logical success.
    """
    if not isinstance(noise_params, Mapping):
        raise PhysicalCostError("INVALID_COST_PARAMETERS: supply an explicit mapping")
    snapshot = _validated_snapshot(bundle)
    bundle_hash = canonical_hash(snapshot)
    generated_qasm = _generated_qasm(bundle.dag)
    document = _structural_document(bundle, bundle_hash, generated_qasm)
    # prepare decodes and revalidates the private v2 projection before deriving
    # actual activity, including pending-readout idle tails and spectator atoms.
    activity = prepare(document)
    report = model_for("noise/v1").evaluate(
        activity, document, deepcopy(dict(noise_params))
    )
    return _annotate_report(bundle, bundle_hash, generated_qasm, activity, report)


def _annotate_report(
    bundle: PhysicalBundle,
    bundle_hash: str,
    generated_qasm: str,
    activity: AtomActivity,
    report: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        **report,
        "scope": _SCOPE,
        "physical_execution": False,
        "measurement_evidence": "unobserved",
        "logical_success": None,
        "structural_measurement_values_exported": False,
        "source_bundle_sha256": bundle_hash,
        "source_dag_sha256": canonical_hash(encode_dag(bundle.dag)),
        "generated_from_selected_dag": True,
        "generated_qasm": generated_qasm,
        "generated_qasm_sha256": sha256(generated_qasm.encode("utf-8")).hexdigest(),
        "generated_qasm_roundtrip_checked": True,
        "source_ids_and_extra_edges_in_generated_qasm": False,
        "result_hash_scope": "private_structural_projection_with_unobserved_results",
        "activity_duration_us": activity.duration_us,
    }


def _include_intervals(
    intervals: Iterable[tuple[float, float]], horizon: float
) -> tuple[tuple[float, float], ...]:
    """Validate, sort and merge touching selections without adding exposure."""
    selected: list[tuple[float, float]] = []
    try:
        for pair in intervals:
            start, end = pair
            if any(
                isinstance(x, bool) or not isinstance(x, Real) for x in (start, end)
            ):
                raise ValueError("endpoints must be real numbers, not booleans")
            low, high = float(start), float(end)
            if not (isfinite(low) and isfinite(high) and 0 <= low < high <= horizon):
                raise ValueError("require 0 <= start < end <= source horizon")
            selected.append((low, high))
    except (TypeError, ValueError, OverflowError) as error:
        raise PhysicalCostError(f"INVALID_COST_INTERVAL: {error}") from error
    merged: list[tuple[float, float]] = []
    for start, end in sorted(selected):
        if merged and start < merged[-1][1]:
            raise PhysicalCostError("INVALID_COST_INTERVAL: intervals overlap")
        if merged and start == merged[-1][1]:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return tuple(merged)


def _clip_exposure(
    intervals: tuple[Interval, ...], selection: tuple[tuple[float, float], ...]
) -> tuple[Interval, ...]:
    return tuple(
        replace(
            interval,
            start_us=max(interval.start_us, start),
            end_us=min(interval.end_us, end),
        )
        for interval in intervals
        for start, end in selection
        if max(interval.start_us, start) < min(interval.end_us, end)
    )


def _atom_projection(
    atom: PerAtomActivity,
    selection: tuple[tuple[float, float], ...],
    events: tuple[ActivityEvent, ...],
) -> PerAtomActivity:
    busy, idle = (
        _clip_exposure(atom.busy, selection),
        _clip_exposure(atom.idle, selection),
    )
    counts: dict[str, int] = {}
    distance = 0.0
    for event in events:
        if atom.atom_id not in event.atoms:
            continue
        counts[event.kind] = counts.get(event.kind, 0) + 1
        if event.kind == "Move":
            index = event.atoms.index(atom.atom_id)
            source, target = event.starts[index], event.ends[index]
            distance += hypot(target[0] - source[0], target[1] - source[1])
    grouped: dict[str, float] = {}
    for interval in idle:
        key = interval.holder + ":" + "+".join(interval.roles)
        grouped[key] = grouped.get(key, 0) + interval.end_us - interval.start_us
    busy_us, end = 0.0, 0.0
    for interval in sorted(busy, key=lambda item: item.start_us):
        busy_us += max(0.0, interval.end_us - max(end, interval.start_us))
        end = max(end, interval.end_us)
    return replace(
        atom,
        busy=busy,
        idle=idle,
        busy_us=busy_us,
        idle_us=sum(grouped.values()),
        idle_by_holder_role=grouped,
        loads=counts.get("Load", 0),
        stores=counts.get("Store", 0),
        transfers=counts.get("Load", 0) + counts.get("Store", 0),
        move_count=counts.get("Move", 0),
        move_distance_um=distance,
        cz_count=counts.get("CZPulse", 0),
        rotation_count=sum(
            counts.get(kind, 0) for kind in ("Rotation", "LocalU", "GlobalRY")
        ),
        measure_count=counts.get("Measure", 0),
        reset_count=counts.get("Reset", 0),
    )


def _project_activity(
    activity: AtomActivity, selection: tuple[tuple[float, float], ...]
) -> tuple[AtomActivity, list[dict[str, Any]]]:
    events: list[ActivityEvent] = []
    index_map: list[dict[str, Any]] = []
    for index, event in enumerate(activity.events):
        finish = event.start_us + event.duration_us
        pieces: list[ActivityEvent] = []
        if event.duration_us == 0 and event.kind != "Wait":
            if any(event.start_us in (start, end) for start, end in selection):
                raise PhysicalCostError(
                    f"AMBIGUOUS_ZERO_DURATION_ACTION: source event {index} is on a selection boundary"
                )
            if any(start < event.start_us < end for start, end in selection):
                pieces.append(event)
        elif event.kind == "Wait":
            pieces.extend(
                replace(
                    event,
                    start_us=max(event.start_us, start),
                    duration_us=min(finish, end) - max(event.start_us, start),
                )
                for start, end in selection
                if max(event.start_us, start) < min(finish, end)
            )
        elif any(start <= event.start_us and finish <= end for start, end in selection):
            pieces.append(event)
        elif any(
            max(event.start_us, start) < min(finish, end) for start, end in selection
        ):
            raise PhysicalCostError(
                f"COST_INTERVAL_CROSSES_ACTION: source event {index} ({event.kind}) spans [{event.start_us}, {finish}]"
            )
        for piece in pieces:
            index_map.append(
                {
                    "selected_event_id": len(events),
                    "source_event_id": index,
                    "start_us": piece.start_us,
                    "duration_us": piece.duration_us,
                }
            )
            events.append(piece)
    selected_events = tuple(events)
    # Keep the absolute source horizon; selected duration is a separate metric.
    # In particular, do not derive a fresh latency tail for any selected piece.
    projected = AtomActivity(
        activity.duration_us,
        tuple(
            _atom_projection(atom, selection, selected_events)
            for atom in activity.per_atom
        ),
        selected_events,
    )
    return projected, index_map


def evaluate_physical_cost_intervals(
    bundle: PhysicalBundle,
    noise_params: Mapping[str, Any],
    *,
    include_intervals: Iterable[tuple[float, float]],
) -> dict[str, Any]:
    """Re-evaluate independent Pauli/rate noise on selected absolute-time pieces.

    The complete bundle is physically revalidated before activity is derived.
    Whole actions own their discrete gate, readout, reset and transport channels;
    only Wait and per-atom exposure intervals may be clipped. Every atom, including
    spectators, contributes exposure in selected intervals. Existing readout tails
    are clipped once. No physical measurements or probability events are sampled.

    Touching intervals merge, overlapping intervals fail, and empty selection has
    the neutral no-fault probability 1. Non-Wait actions crossing boundaries fail.
    A zero-duration non-Wait action on a selection boundary is ambiguous and fails.
    Exposure channels retain the original interval partition, intersected with
    the merged selection. Products of T2 identity probabilities across disconnected
    pieces are not claimed to equal the identity probability of an entire trace.

    The returned metrics.no_fault_probability already includes configured physical
    loss. It is a physical proxy, not logical success or a decoder result. The
    caller owns disjointness across separate requests and conditioned raw scopes.
    """
    if not isinstance(noise_params, Mapping):
        raise PhysicalCostError("INVALID_COST_PARAMETERS: supply an explicit mapping")
    params = resolve(deepcopy(dict(noise_params)))
    if any(
        config["backend"] != "pauli"
        for config in (
            params["single"],
            params["cz"],
            *params["single_overrides"].values(),
        )
    ):
        raise PhysicalCostError(
            "UNSUPPORTED_INTERVAL_NOISE_PROFILE: require independent Pauli gates and rates/v1"
        )
    snapshot = _validated_snapshot(bundle)
    bundle_hash = canonical_hash(snapshot)
    generated_qasm = _generated_qasm(bundle.dag)
    document = _structural_document(bundle, bundle_hash, generated_qasm)
    activity = prepare(document)
    selection = _include_intervals(include_intervals, activity.duration_us)
    projected, index_map = _project_activity(activity, selection)
    report = model_for("noise/v1").evaluate(projected, document, params)
    annotated = _annotate_report(bundle, bundle_hash, generated_qasm, activity, report)
    return {
        **annotated,
        "time_scope": "disjoint_include_intervals",
        "probability_kind": "physical_no_fault_proxy",
        "interval_selection": {
            "schema": "nadit.physical_cost_intervals/1",
            "time_basis": "absolute_us",
            "include_intervals": [list(interval) for interval in selection],
            "source_horizon_us": activity.duration_us,
            "selected_duration_us": sum(end - start for start, end in selection),
            "selected_event_indices": sorted(
                {entry["source_event_id"] for entry in index_map}
            ),
            "event_index_map": index_map,
            "source_activity_sha256": canonical_hash(activity.document()),
            "selected_activity_sha256": canonical_hash(projected.document()),
            "exposure_partition": "original_activity_interval_intersections_with_merged_include_intervals",
            "discrete_channels": "complete_action_ownership",
            "noise_profile": "independent_pauli_rates_v1",
            "full_trace_probability_equivalence_claimed": False,
        },
    }
