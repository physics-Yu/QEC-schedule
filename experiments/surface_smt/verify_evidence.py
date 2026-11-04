"""Recheck saved depth witnesses and lower-bound provenance without new searches."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.visualization import build_result_trace, write_html

from .depth.lowering import checks_metadata, export
from .depth.model import Problem, Witness
from .depth.validation import validate

EVIDENCE = Path(__file__).with_name("evidence")


def read(path: Path) -> Any:
    """Read an archived JSON record without rewriting it."""
    return json.loads(path.read_text(encoding="utf-8"))


def require_subdomain(smaller: dict[str, Any], larger: dict[str, Any]) -> None:
    """Check the precise inclusion used to inherit fixed-model UNSAT responses."""
    dimensions = {"rows", "columns"}
    if {k: v for k, v in smaller.items() if k not in dimensions} != {
        k: v for k, v in larger.items() if k not in dimensions
    }:
        raise ValueError("Lower-bound transfer changes the problem constraints.")
    if not (
        smaller["rows"] <= larger["rows"] and smaller["columns"] <= larger["columns"]
    ):
        raise ValueError("Lower-bound transfer requires a coordinate subdomain.")
    if (2 * smaller["columns"]).bit_length() != (
        2 * larger["columns"]
    ).bit_length() or smaller["rows"].bit_length() != larger["rows"].bit_length():
        raise ValueError("Lower-bound transfer has different bit-vector widths.")


def verify_catalog(
    directory: Path = EVIDENCE, output: Path | None = None
) -> dict[str, Any]:
    """Check archive bytes, witness geometry, lowering, and recorded bound provenance.

    UNSAT records are authenticated historical solver responses. This function
    does not independently prove UNSAT or launch Z3 searches.
    """
    catalog = read(directory / "catalog.json")
    cases = catalog["cases"]
    for key, record in cases.items():
        for name, expected in record["files_sha256"].items():
            if (
                hashlib.sha256((directory / key / name).read_bytes()).hexdigest()
                != expected
            ):
                raise ValueError(f"Evidence bytes changed: {key}/{name}")
        model_hash = hashlib.sha256(
            (directory / record["model_file"]).read_bytes()
        ).hexdigest()
        manifest = read(directory / key / "manifest.json")
        if (
            model_hash != record["model_sha256"]
            or model_hash
            != manifest["source_hashes"]["experiments/surface_smt/depth/model.py"]
        ):
            raise ValueError(f"Model identity differs: {key}")
        for name, expected in manifest["input_hashes"].items():
            if (
                hashlib.sha256((directory / key / name).read_bytes()).hexdigest()
                != expected
            ):
                raise ValueError(f"Original input manifest differs: {key}/{name}")
    reports = {}
    traces = []
    for key, record in cases.items():
        raw = read(directory / key / "problem.json")
        problem = Problem(
            **{
                **raw,
                "layers": tuple(
                    tuple(tuple(p) for p in layer) for layer in raw["layers"]
                ),
            }
        )
        data = read(directory / key / record["witness"])
        witness = Witness(
            tuple(tuple(tuple(p) for p in state) for state in data["positions"]),
            tuple(tuple(group) for group in data["carriers"]),
            tuple(data["gate_states"]),
        )
        errors = validate(problem, witness)
        if errors:
            raise ValueError(f"Witness {key}: {errors}")
        depth = record["minimum_move_depth"]
        if len(witness.carriers) != depth:
            raise ValueError(f"Witness depth differs: {key}")
        statuses = {
            a["depth"]: a["status"]
            for a in read(directory / key / "status.json")["attempts"]
        }
        if statuses.get(depth) != "sat":
            raise ValueError(f"Missing original SAT response: {key}")
        inherited = record["lower_bound_case"]
        if inherited is not None:
            parent = cases[inherited]
            require_subdomain(raw, read(directory / inherited / "problem.json"))
            if parent["model_sha256"] != record["model_sha256"]:
                raise ValueError("Lower-bound transfer requires identical model bytes.")
            if (
                read(directory / key / "manifest.json")["input_hashes"]["circuit.qasm3"]
                != read(directory / inherited / "manifest.json")["input_hashes"][
                    "circuit.qasm3"
                ]
            ):
                raise ValueError("Lower-bound transfer changes the source circuit.")
            for attempt in read(directory / inherited / "status.json")["attempts"]:
                if attempt["status"] == "unsat":
                    statuses.setdefault(attempt["depth"], "unsat")
        # Initially isolated atoms and four distinct whole-field matchings rule
        # out depths below four. All remaining lower depths need solver evidence.
        if (
            not problem.initially_idle
            or len(problem.layers) != 4
            or any(set(a) == set(b) for a, b in zip(problem.layers, problem.layers[1:]))
            or any(statuses.get(d) != "unsat" for d in range(4, depth))
        ):
            raise ValueError(f"Incomplete lower-bound evidence: {key}")
        document, checks = export(problem, witness)
        if (
            canonical_hash(document["program"]) != record["expected_program_sha256"]
            or document["metrics"] != record["expected_metrics"]
        ):
            raise ValueError(f"Re-lowering changed the recorded program/metrics: {key}")
        reports[key] = {
            "minimum_move_depth": depth,
            "sat_witness_revalidated": True,
            "lower_bound_provenance_checked": True,
            "new_solver_queries": 0,
            "checks": checks,
        }
        if output is not None:
            output.mkdir(parents=True, exist_ok=True)
            (output / f"{key}.result.json").write_text(
                json.dumps(document, indent=2), encoding="utf-8"
            )
            traces.append(
                build_result_trace(document, title=key, qec=checks_metadata())
            )
    if output is not None:
        write_html(traces, output / "index.html")
        (output / "traces.json").write_text(
            json.dumps({"schema_version": 1, "traces": traces}), encoding="utf-8"
        )
    return {"verified": True, "cases": reports, "scope": catalog["scope"]}


def main() -> None:
    """Optionally regenerate the QEC-aware viewer from the saved witnesses."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_catalog(output=args.output), indent=2))


if __name__ == "__main__":
    main()
