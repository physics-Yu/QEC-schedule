"""Translate validated atom actions and explicit cost channels into Stim."""

from collections import defaultdict
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
from typing import Any

from ..activity import ActivityEvent
from ..cost import model_for, prepare
from ..cost.base import result_hash
from ..serialization import decode_program
from .annotations import append_annotations
from .clifford import dependency, local_clifford


@dataclass(frozen=True)
class StimExport:
    """A Stim program plus explicit provenance, timing and excluded effects."""

    circuit: str
    report: dict[str, Any]


def _circuit_text(circuit: Any) -> str:
    """Retain binary64 channel probabilities instead of Stim's display rounding."""
    lines = []
    for instruction in circuit:
        text = str(instruction)
        args = instruction.gate_args_copy()
        if args:
            text = (
                instruction.name
                + "("
                + ", ".join(format(a, ".17g") for a in args)
                + ")"
                + text[text.index(")") + 1 :]
            )
        lines.append(text)
    return "\n".join(lines) + "\n"


def _channel(circuit: Any, channel: dict[str, Any], wires: dict[int, int]) -> None:
    circuit.append(
        channel["instruction"],
        [wires[a] for a in channel["atoms"]],
        channel["probabilities"],
    )


def _ideal(
    circuit: Any,
    event: ActivityEvent,
    wires: dict[int, int],
    records: dict[int, int],
    measurement_noise: dict[int, float],
) -> None:
    targets = [wires[a] for a in event.atoms]
    if event.kind in ("Rotation", "GlobalRY", "LocalU"):
        p = event.parameters
        local = (
            local_clifford("U", (p["theta"], p["phi"], p["lam"]))
            if event.kind == "LocalU"
            else local_clifford(p["axis"], (p["angle"],))
        )
        for target in targets:
            for instruction in local:
                circuit.append(
                    instruction.name,
                    [target] * len(instruction.targets_copy()),
                    instruction.gate_args_copy(),
                )
    elif event.kind == "CZPulse":
        circuit.append("CZ", [wires[a] for pair in event.pairs for a in pair])
    elif event.kind == "Reset":
        circuit.append("R", targets)
    elif event.kind == "Measure":
        for target, mid in zip(targets, event.measurement_ids, strict=True):
            if mid in records:
                raise ValueError(f"Duplicate measurement identity {mid}.")
            records[mid] = circuit.num_measurements
            circuit.append("M", [target], measurement_noise.get(mid, 0.0))
    elif event.kind not in ("Load", "Move", "Store", "Wait"):
        raise ValueError(f"Unsupported atom action {event.kind}.")


def translate(
    document: Mapping[str, Any],
    *,
    noise_params: Mapping[str, Any] | None = None,
    annotations: Mapping[str, Any] | None = None,
    allow_fixed_case: bool = False,
) -> StimExport:
    """Validate, evaluate noise/v1 once and export the compiled Clifford case.

    Cost parameters are explicit; previously attached cost reports are not selected
    implicitly. Returned metadata retains the complete new noise report.
    """
    stim = dependency("stim")
    activity = prepare(document)
    conditional = any(n.get("condition") is not None for n in document["dag"]["nodes"])
    if conditional and not allow_fixed_case:
        raise ValueError(
            "Conditional DAG requires explicit allow_fixed_case; "
            "missing branches cannot be reconstructed."
        )
    noise = model_for("noise/v1").evaluate(activity, document, noise_params or {})
    wires = {a.atom_id: i for i, a in enumerate(activity.per_atom)}
    circuit = stim.Circuit()
    initial = {a["id"]: a for a in document["entry_state"]["atoms"]}
    for atom, wire in wires.items():
        p = initial[atom]["position"]
        circuit.append("QUBIT_COORDS", [wire], [p["x"], p["y"]])
    before: dict[int, list[dict[str, Any]]] = defaultdict(list)
    after: dict[int, list[dict[str, Any]]] = defaultdict(list)
    readout: dict[int, float] = {}
    # Items sort by physical completion, then original step/action order.
    schedule: list[tuple[float, int, int, str, Any]] = []
    for channel in noise["noise"]["channels"]:
        if channel["placement"] == "measurement_argument":
            readout[channel["measurement_id"]] = channel["probabilities"][0]
        elif "event_id" in channel:
            (before if channel["placement"] == "before" else after)[
                channel["event_id"]
            ].append(channel)
        else:
            schedule.append(
                (
                    channel["start_us"] + channel["duration_us"],
                    -1,
                    0,
                    "channel",
                    channel,
                )
            )
    for index, event in enumerate(activity.events):
        schedule.append(
            (
                event.start_us + event.duration_us,
                event.step_index,
                event.action_index,
                "action",
                (index, event),
            )
        )
    timeline = []
    for index, (start, step) in enumerate(
        decode_program(document["program"]).timeline()
    ):
        end = start + step.duration_us
        schedule.append((end, index, len(step.actions), "tick", None))
        timeline.append({"step_index": index, "start_us": start, "end_us": end})
    records: dict[int, int] = {}
    for _, _, _, kind, value in sorted(schedule, key=lambda item: item[:3]):
        if kind == "tick":
            circuit.append("TICK")
        elif kind == "channel":
            _channel(circuit, value, wires)
        else:
            event_id, event = value
            for channel in before[event_id]:
                _channel(circuit, channel, wires)
            _ideal(circuit, event, wires, records, readout)
            for channel in after[event_id]:
                _channel(circuit, channel, wires)
    if annotations is not None:
        append_annotations(circuit, annotations, records, document, stim)
    text = _circuit_text(circuit)
    return StimExport(
        text,
        {
            "schema": "nadit.stim/1",
            "method": "stim/v1",
            "cost_model": "noise/v1",
            "result_hash": result_hash(document),
            "circuit_sha256": sha256(text.encode()).hexdigest(),
            "stim_version": stim.__version__,
            "scope": "pauli_readout_only",
            "branch_semantics": "fixed_case" if conditional else "unconditional",
            "atom_to_stim": {str(a): q for a, q in wires.items()},
            "measurement_records": {str(mid): index for mid, index in records.items()},
            "timeline": timeline,
            "duration_us": activity.duration_us,
            "counts": {
                "qubits": len(wires),
                "measurements": circuit.num_measurements,
                "detectors": circuit.num_detectors,
                "observables": circuit.num_observables,
            },
            "annotations": deepcopy(dict(annotations))
            if annotations is not None
            else None,
            "noise_report": noise,
            "excluded_from_stim": [
                "physical_atom_loss",
                "leakage",
                "coherent_non_pauli_effects",
            ],
        },
    )
