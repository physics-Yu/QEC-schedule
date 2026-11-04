"""Standard rotated-memory benchmark inputs for existing physical compilers."""

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from ..frontend import loads_qasm
from .clifford import dependency


def _source(reference: Any) -> tuple[str, dict[str, Any], dict[int, list[float]]]:
    coordinates = reference.get_final_qubit_coordinates()
    qubits = {q: i for i, q in enumerate(sorted(coordinates))}
    lines = [
        "OPENQASM 3.0;",
        'include "stdgates.inc";',
        f"qubit[{len(qubits)}] q;",
        f"bit[{reference.num_measurements}] m;",
    ]
    measured = 0
    detectors, observables = [], []
    for instruction in reference.flattened():
        name = instruction.name
        targets = instruction.targets_copy()
        if name == "QUBIT_COORDS":
            continue
        if name in ("DETECTOR", "OBSERVABLE_INCLUDE"):
            ids = [measured + t.value for t in targets]
            if name == "DETECTOR":
                detectors.append(
                    {
                        "measurement_ids": ids,
                        "coordinates": instruction.gate_args_copy(),
                    }
                )
            else:
                observables.append(
                    {
                        "measurement_ids": ids,
                        "index": int(instruction.gate_args_copy()[0]),
                    }
                )
            continue
        if name == "TICK":
            lines.append("barrier q;")
            continue
        qs = [qubits[t.value] for t in targets]
        if name == "CX":
            lines.extend(
                f"cx q[{a}], q[{b}];" for a, b in zip(qs[::2], qs[1::2], strict=True)
            )
        elif name == "H":
            lines.extend(f"h q[{q}];" for q in qs)
        elif name in ("R", "RX"):
            lines.extend(f"reset q[{q}];" for q in qs)
            if name == "RX":
                lines.extend(f"h q[{q}];" for q in qs)
        elif name in ("M", "MX", "MR"):
            if name == "MX":
                lines.extend(f"h q[{q}];" for q in qs)
            for q in qs:
                lines.append(f"m[{measured}] = measure q[{q}];")
                measured += 1
            if name == "MR":
                lines.extend(f"reset q[{q}];" for q in qs)
        else:
            raise ValueError(f"Unsupported standard-memory instruction {name}.")
    source = "\n".join(lines) + "\n"
    dag = loads_qasm(source)
    identities = {
        node.clbits[0]: node.result.measurement_id
        for node in dag.nodes
        if node.result is not None
    }
    for parity in [*detectors, *observables]:
        parity["measurement_ids"] = [identities[m] for m in parity["measurement_ids"]]
    annotations = {
        "schema": "nadit.stim.annotations/1",
        "qasm_sha256": sha256(source.encode()).hexdigest(),
        "measurement_ids": [identities[i] for i in range(measured)],
        "detectors": detectors,
        "observables": observables,
    }
    return source, annotations, {qubits[q]: xy for q, xy in coordinates.items()}


def _architecture(distance: int, backend: str, pitch: float) -> dict[str, Any]:
    side = 2 * distance + 1
    width = side * pitch
    gate_y = width + 20
    readout_y = (width if backend == "nonzoned" else gate_y + 6 * distance) + 20
    pair = {
        "id": "shared" if backend == "nonzoned" else "entanglement",
        "position": {"x": 0, "y": 0 if backend == "nonzoned" else gate_y},
        "rows": side if backend == "nonzoned" else distance,
        "pairs_per_row": side,
        "pitch": {"x": pitch, "y": pitch if backend == "nonzoned" else 6},
        "separation": 2,
        "left_prefix": "home" if backend == "nonzoned" else "gate_left",
        "right_prefix": "guest" if backend == "nonzoned" else "gate_right",
    }
    params: dict[str, Any] = {
        "name": f"surface-d{distance}-{backend}",
        "cz": {
            "channel": "rydberg",
            "radius_um": 4.6,
            "duration_us": 0.5,
            "holder_pairs": [["slm", "slm"]],
            "allow_spectators": backend == "nonzoned",
        },
        "local": {
            "channel": "local",
            "rotation_us": 1,
            "reset_us": 5,
            "holders": ["slm", "aod"],
        },
        "timing": {"load_us": 10, "store_us": 10, "move_us_per_um": 1},
        "aod": {"id": "transport", "motion": "flexible", "min_spacing": 1},
        "measurement": {
            "id": "readout",
            "position": {"x": 0, "y": readout_y},
            "bounds": {"x_min": 0, "y_min": 0, "x_max": width, "y_max": 20},
            "readout": {
                "channel": "camera",
                "duration_us": 10,
                "latency_us": 500,
                "min_spacing_um": 5,
                "retain_atoms": True,
                "holders": ["aod"],
                "max_atoms": None,
            },
        },
    }
    if backend == "nonzoned":
        params["shared_arrays"] = [pair]
    else:
        params["storage"] = [
            {
                "id": "storage",
                "prefix": "home",
                "origin": {"x": 0, "y": 0},
                "rows": side,
                "columns": side,
                "pitch": {"x": pitch, "y": pitch},
            }
        ]
        params["gate_zones"] = [pair]
    return {
        "family": "shared/v1" if backend == "nonzoned" else "zoned/v1",
        "params": params,
    }


def prepare_memory(
    output: Path,
    *,
    distance: int,
    rounds: int | None = None,
    basis: str = "z",
    pitch_um: float = 8.0,
) -> dict[str, Any]:
    """Write standard QASM, measurement annotations and two editable backend jobs.

    This creates inputs only, never runs a physical compiler or experiment.
    The output directory must not already contain any generated destination.
    """
    if distance not in (3, 5, 7, 9) or basis not in ("x", "z"):
        raise ValueError("Supported memory distances are 3,5,7,9; basis is x or z.")
    rounds = distance if rounds is None else rounds
    if rounds < 1 or pitch_um <= 6.6:
        raise ValueError(
            "rounds must be positive; "
            "pitch_um must exceed radius + pair separation (6.6)."
        )
    stim = dependency("stim")
    reference = stim.Circuit.generated(
        f"surface_code:rotated_memory_{basis}", distance=distance, rounds=rounds
    )
    source, annotations, coordinates = _source(reference)
    annotations["workload"] = {
        "kind": "rotated_surface_memory",
        "distance": distance,
        "rounds": rounds,
        "basis": basis,
        "stim_version": stim.__version__,
    }
    output = output.resolve()
    files = {
        "circuit.qasm3": source,
        "reference.stim": str(reference) + "\n",
        "annotations.json": json.dumps(annotations, indent=2) + "\n",
    }
    for backend in ("nonzoned", "qec"):
        strategy = (
            {"kind": "nonzoned"}
            if backend == "nonzoned"
            else {
                "kind": "search_smarter",
                "mode": "qec",
                "scheduler": {"kind": "ready", "max_cz_gates": "catalog"},
                "placement": {"kind": "ids", "trials": 4, "max_nodes": 100000},
                "transport": {"kind": "strict"},
                "emitter": {"kind": "whole_layer"},
                "reuse": {"kind": "none"},
            }
        )
        job = {
            "schema": "nadit.job/1",
            "circuit": {"qasm": "circuit.qasm3"},
            "device": {"architecture": _architecture(distance, backend, pitch_um)},
            "aod": "transport",
            "strategy": strategy,
            "case": {"seed": 17},
            "entry": {
                "kind": "explicit",
                "atoms": [
                    [q, f"home_r{int(xy[1])}_c{int(xy[0])}", q]
                    for q, xy in sorted(coordinates.items())
                ],
            },
        }
        files[f"{backend}.job.json"] = json.dumps(job, indent=2) + "\n"
    if any((output / name).exists() for name in files):
        raise ValueError(
            "Memory input destination already exists; choose a new directory."
        )
    output.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (output / name).write_text(text, encoding="utf-8", newline="\n")
    return {
        "reference": str(output / "reference.stim"),
        "qasm": str(output / "circuit.qasm3"),
        "annotations": str(output / "annotations.json"),
        "jobs": {
            backend: str(output / f"{backend}.job.json")
            for backend in ("nonzoned", "qec")
        },
    }
