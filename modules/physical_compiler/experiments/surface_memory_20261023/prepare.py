"""Materialize the approved campaign using the frozen package, without compilation."""

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from nadit_physical_compiler.cost.noise.config import resolve
from nadit_physical_compiler.job import load_job
from nadit_physical_compiler.methods.surface_memory import prepare_memory
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.serialization import encode_device, encode_layout


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    root = Path(sys.argv[1]).resolve()
    source = Path(sys.argv[2]).resolve()
    config = json.loads((Path(__file__).parent / "campaign.json").read_text())
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=source, text=True
    ).strip()
    assert commit.startswith(config["compiler_commit"])
    if (root / "manifest.json").exists():
        raise ValueError("Campaign already materialized; use run.py to resume.")
    noise = resolve(config["noise"])
    write(root / "noise.json", noise)
    cases = []
    for distance in config["distances"]:
        for basis in config["bases"]:
            folder = root / "inputs" / f"d{distance}-{basis}"
            paths = prepare_memory(folder, distance=distance, basis=basis)
            reference = __import__("stim").Circuit.from_file(paths["reference"])
            coordinates = reference.get_final_qubit_coordinates()
            roles = {
                str(q): "data" if int(xy[0]) % 2 and int(xy[1]) % 2 else "ancilla"
                for q, (_, xy) in enumerate(sorted(coordinates.items()))
            }
            entries = []
            for backend in config["backends"]:
                path = Path(paths["jobs"][backend])
                document = json.loads(path.read_text())
                p = document["device"]["architecture"]["params"]
                h = config["homes"]
                if backend == "nonzoned":
                    block = p["shared_arrays"][0]
                    block.update(rows=h["rows"], pairs_per_row=h["columns"])
                else:
                    p["storage"][0].update(rows=h["rows"], columns=h["columns"])
                    g = config["gate_array"]
                    p["gate_zones"][0].update(
                        rows=g["rows"],
                        pairs_per_row=g["pairs_per_row"],
                        position={"x": g["x"], "y": g["y"]},
                    )
                    document["strategy"]["placement"] = deepcopy(config["placement"])
                p["name"] = f"fixed-large-zones-{backend}"
                r = config["readout"]
                p["measurement"].update(
                    position={"x": r["x"], "y": r["y"]},
                    bounds={
                        "x_min": 0,
                        "y_min": 0,
                        "x_max": r["width_um"],
                        "y_max": r["height_um"],
                    },
                )
                p["aod"].update(
                    workspace=config["workspace"], max_rows=None, max_columns=None
                )
                document["case"]["seed"] = config["case_seed"]
                write(path, document)
                job = load_job(path)
                entries.append(encode_layout(job.entry_state))
                label = f"d{distance}-{basis}-{backend}"
                run_id = canonical_hash(
                    {
                        "campaign": config,
                        "job": document,
                        "qasm": job.inputs["qasm_sha256"],
                        "commit": commit,
                    }
                )
                seeds = [
                    int.from_bytes(
                        hashlib.sha256(f"{run_id}:{i}".encode()).digest()[:8], "big"
                    )
                    for i in range(config["budget"]["shards"])
                ]
                write(folder / f"{backend}.resolved.json", job.document)
                write(folder / f"{backend}.device.json", encode_device(job.device))
                cases.append(
                    {
                        "label": label,
                        "run_id": run_id,
                        "distance": distance,
                        "basis": basis,
                        "backend": backend,
                        "job": str(path.relative_to(root)),
                        "annotations": str(
                            Path(paths["annotations"]).relative_to(root)
                        ),
                        "roles": roles,
                        "seeds": seeds,
                        "device_hash": job.inputs["device_sha256"],
                        "qasm_hash": job.inputs["qasm_sha256"],
                    }
                )
            # Holder site IDs, coordinates, atom IDs and wire bindings must match.
            assert entries[0] == entries[1]
    assert len(cases) == 16
    assert len({seed for case in cases for seed in case["seeds"]}) == 256
    for backend in config["backends"]:
        assert len({c["device_hash"] for c in cases if c["backend"] == backend}) == 1
    files = [*sorted((root / "inputs").rglob("*")), root / "noise.json"]
    inputs = {str(p.relative_to(root)): digest(p) for p in files if p.is_file()}
    tracked = subprocess.check_output(
        [
            "git",
            "ls-files",
            "modules/physical_compiler/src",
            "modules/physical_compiler/pyproject.toml",
            "modules/physical_compiler/uv.lock",
        ],
        cwd=source,
        text=True,
    ).splitlines()
    source_hashes = {p: digest(source / p) for p in tracked}
    harness = {
        p.name: digest(p)
        for p in Path(__file__).parent.iterdir()
        if p.suffix in (".py", ".json", ".md")
    }
    write(
        root / "manifest.json",
        {
            "config": config,
            "commit": commit,
            "noise_hash": canonical_hash(noise),
            "source": str(source),
            "source_hashes": source_hashes,
            "harness_hashes": harness,
            "inputs": inputs,
            "cases": cases,
        },
    )
    print(
        json.dumps(
            {
                "cases": len(cases),
                "shots": 16 * 16 * 65536,
                "manifest": str(root / "manifest.json"),
            }
        )
    )


if __name__ == "__main__":
    main()
