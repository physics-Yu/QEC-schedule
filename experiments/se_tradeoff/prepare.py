"""Generate frozen surface-memory inputs and the v1 SE trade-off experiment spec.

Run from the repository root with the physical compiler environment:

    python -m experiments.se_tradeoff.prepare --distance 3 --output experiments/se_tradeoff/inputs/d3

The output directory must not exist. Only inputs are written; nothing compiles.
"""

import argparse
import hashlib
import json
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

from nadit_physical_compiler.frontend.native import DEFAULT_GATE_SET
from nadit_physical_compiler.methods.surface_memory import prepare_memory

ROUNDS = (1, 2, 3)
MOTIONS = ["flexible", "rigid"]
# Batch readout requires flexible retained AOD readout, so rigid uses singleton
# readout; flexible singleton isolates the transport effect from batching.
READOUT_PATH = "measurement.readout.max_atoms"
READOUT_AXES = {"aod.motion": MOTIONS, READOUT_PATH: [None, 1]}
READOUT_EXCLUDE = [{"aod.motion": "rigid", READOUT_PATH: None}]


def _read(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write(path: Path, document: Any) -> None:
    path.write_text(
        json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


def build(output: Path, distance: int) -> dict[str, Any]:
    """Write per-round circuits, a pinned suite and the experiment spec."""
    output = output.resolve()
    if output.exists():
        raise ValueError(f"{output} already exists; choose a new directory.")
    jobs: dict[int, dict[str, dict[str, Any]]] = {}
    circuits = []
    output.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as scratch:
        for rounds in ROUNDS:
            generated = prepare_memory(
                Path(scratch) / f"r{rounds}", distance=distance, rounds=rounds
            )
            stem = f"d{distance}_r{rounds}"
            qasm = Path(generated["qasm"]).read_bytes()
            (output / f"{stem}.qasm3").write_bytes(qasm)
            (output / f"{stem}.stim").write_bytes(
                Path(generated["reference"]).read_bytes()
            )
            (output / f"{stem}.annotations.json").write_bytes(
                Path(generated["annotations"]).read_bytes()
            )
            jobs[rounds] = {k: _read(v) for k, v in generated["jobs"].items()}
            circuits.append(
                {
                    "id": stem,
                    "file": f"{stem}.qasm3",
                    "sha256": hashlib.sha256(qasm).hexdigest(),
                    "qubits": len(jobs[rounds]["qec"]["entry"]["atoms"]),
                }
            )
    reference = jobs[ROUNDS[0]]
    for rounds in ROUNDS[1:]:
        for backend in ("qec", "nonzoned"):
            for key in ("device", "entry"):
                if jobs[rounds][backend][key] != reference[backend][key]:
                    raise ValueError(f"r{rounds} {backend} {key} differs from r1.")
    if reference["qec"]["entry"] != reference["nonzoned"]["entry"]:
        raise ValueError("Zoned and shared backends must share explicit homes.")
    entry = reference["qec"]["entry"]
    qec = reference["qec"]["strategy"]
    reuse = {**deepcopy(qec), "cross_layer_reuse": True, "reuse": {"kind": "matching"}}
    _write(
        output / "suite.json",
        {
            "schema": "nadit.suite/1",
            "name": f"surface-memory-d{distance}",
            "circuits": circuits,
            "gate_set": list(DEFAULT_GATE_SET.names),
            "source": "stim rotated_memory_z via methods.surface_memory",
        },
    )
    zoned = reference["qec"]["device"]["architecture"]
    shared = reference["nonzoned"]["device"]["architecture"]
    spec = {
        "schema": "nadit.experiment/1",
        "name": f"se-tradeoff-d{distance}",
        "suite": "suite.json",
        "architectures": [
            {
                "family": shared["family"],
                "params": shared["params"],
                "sweep": READOUT_AXES,
                "exclude": READOUT_EXCLUDE,
            },
            {
                "family": zoned["family"],
                "params": zoned["params"],
                "sweep": {"gate_zones[0].rows": [1, distance], **READOUT_AXES},
                "exclude": READOUT_EXCLUDE,
            },
        ],
        "strategies": {
            "ss-qec": {"strategy": qec, "entry": entry},
            "ss-qec-reuse": {"strategy": reuse, "entry": entry},
            "nonzoned": {"strategy": {"kind": "nonzoned"}, "entry": entry},
        },
        "cases": {"seeds": [17]},
        "cost": [{"model": "additive", "params": {}}],
        "budget": {"timeout_s": 600},
        "validate": "required",
        "store": "all",
    }
    _write(output / "experiment.json", spec)
    return {"output": str(output), "circuits": [c["id"] for c in circuits]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--distance", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.output, args.distance), indent=2))


if __name__ == "__main__":
    main()
