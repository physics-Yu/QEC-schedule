"""Bind workload parity annotations to actual compiled measurement records."""

from collections.abc import Mapping
from typing import Any


def append_annotations(
    circuit: Any,
    annotations: Mapping[str, Any],
    records: dict[int, int],
    document: Mapping[str, Any],
    stim: Any,
) -> None:
    """Append detector/observable parities using stable source measurement IDs."""
    if annotations.get("schema") != "nadit.stim.annotations/1":
        raise ValueError("Expected nadit.stim.annotations/1 annotations.")
    if annotations.get("qasm_sha256") != document["inputs"]["qasm_sha256"]:
        raise ValueError("Annotations do not match the circuit source hash.")
    declared = annotations.get("measurement_ids", [])
    if len(declared) != len(set(declared)) or set(declared) != set(records):
        raise ValueError("Annotation measurement identities differ from the result.")
    count = circuit.num_measurements
    for name, key in (("DETECTOR", "detectors"), ("OBSERVABLE_INCLUDE", "observables")):
        for parity in annotations.get(key, []):
            try:
                targets = [
                    stim.target_rec(records[mid] - count)
                    for mid in parity["measurement_ids"]
                ]
            except KeyError as error:
                raise ValueError(
                    f"Unknown measurement identity in {name}: {error}"
                ) from error
            args = (
                parity.get("coordinates", [])
                if name == "DETECTOR"
                else [parity["index"]]
            )
            circuit.append(name, targets, args)
