"""Prepare shared N=15 and N=21 compiler inputs for the offline shot labs."""

from __future__ import annotations

import json
from pathlib import Path

from experiments.small_circuit.run_shor_l2 import SHOR, prepare_physical_template
from experiments.small_circuit.shor.semiclassical import semiclassical_source
from experiments.small_shor_algorithm.quantum_checks import source_trajectory

BUILD = Path(__file__).resolve().parent / "build"


def main() -> None:
    """Write the compiled results, adaptive QASM, and a seeded example branch."""
    from nadit_physical_compiler.serialization import decode_dag

    sources = BUILD / "semiclassical"
    results = BUILD / "results"
    sources.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    cases = []
    for n in (15, 21):
        coherent = (SHOR / "inputs" / f"n{n}.qasm3").read_text(encoding="utf-8")
        (sources / f"n{n}.qasm3").write_bytes(semiclassical_source(coherent).encode())
        document, _ = prepare_physical_template(n)
        (results / f"n{n}.json").write_bytes(json.dumps(document).encode())
        seed = 17
        outcomes = source_trajectory(decode_dag(document["dag"]), seed=seed)[0]
        cases.append(
            {
                **document["source_provenance"],
                "ideal_reference_seed": seed,
                "ideal_reference_outcomes": outcomes,
            }
        )
    path = BUILD / "manifest.json"
    path.write_text(json.dumps({"cases": cases}, indent=2) + "\n", encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
