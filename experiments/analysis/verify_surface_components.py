"""Independently read back a complete saved surface-component production bundle."""

import argparse
import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from nadit_physical_compiler.cost import prepare
from nadit_physical_compiler.provenance import canonical_hash


def verify(directory: Path) -> dict[str, Any]:
    """Revalidate saved actions and check algebraic counts and H carrier exits."""
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    source_map = json.loads(
        (directory / "source-snapshot.json").read_text(encoding="utf-8")
    )
    if canonical_hash(source_map) != manifest["source_tree_sha256"]:
        raise ValueError("Source manifest identity mismatch.")
    rows = []
    for case in manifest["cases"]:
        d = case["distance"]
        target = directory / f"d{d}"
        if len(case["operations"]) != 16 or case["world_atoms"] != 6 * (2 * d * d - 1):
            raise ValueError("Incomplete component catalog or world allocation.")
        files = sorted(target.rglob("result.json"))
        expected = 15 + 3 + d
        if len(files) != expected:
            raise ValueError("Missing physical component or conditional-stage result.")
        for file in files:
            doc = json.loads(file.read_text(encoding="utf-8"))
            activity = prepare(doc)
            expansion = json.loads(
                file.with_name("expansion.json").read_text(encoding="utf-8")
            )
            template = json.loads(
                file.with_name("template.json").read_text(encoding="utf-8")
            )
            template_hash = template.pop("content_sha256")
            if (
                canonical_hash(template) != template_hash
                or expansion["template_content_sha256"] != template_hash
            ):
                raise ValueError(f"Template mismatch: {file}")
            source = file.with_name("source.qasm3").read_text(encoding="utf-8")
            if sha256(source.encode()).hexdigest() != template["source_sha256"]:
                raise ValueError(f"Source mismatch: {file}")
            if any(m["value"] is not None for m in expansion["measurements"]):
                raise ValueError("Export turned structural values into observed bits.")
            if len(doc["entry_state"]["atoms"]) != case["world_atoms"]:
                raise ValueError("An occupied spectator was omitted.")
            timing = doc["device"]["timing"]
            if timing["load_us"] != 10 or timing["store_us"] != 10:
                raise ValueError("Incorrect transfer timing.")
            if file.parent.name == "logical_h":
                incoming = {a["id"]: a for a in doc["entry_state"]["atoms"]}
                outgoing = {a["id"]: a for a in doc["exit_state"]["atoms"]}
                atoms = expansion["wire_atoms"]
                canonical = expansion["exit_binding"]["atom_ids"]
                for q in range(d * d):
                    rotated = (q % d) * d + d - 1 - q // d
                    if (
                        outgoing[atoms[q]]["position"]
                        != incoming[atoms[rotated]]["position"]
                        or canonical[rotated] != atoms[q]
                    ):
                        raise ValueError(
                            "H physical endpoint/canonical binding mismatch."
                        )
            rows.append(
                {
                    "path": file.relative_to(directory).as_posix(),
                    "duration_us": activity.duration_us,
                    "atom_count": len(activity.per_atom),
                    "measurements": len(expansion["measurements"]),
                    "template_sha256": template_hash,
                }
            )
        operations = case["operations"]
        if operations["raw_t"]["measurement_count"] != 8 + d * (d * d - 1):
            raise ValueError("Raw-T must retain one d3 SE plus d target rounds.")
        selected = operations["raw_t_postselection"]
        if (
            selected["measurement_count"] != 24 + d * (d * d - 1)
            or selected["injection_detectors"] != 20
        ):
            raise ValueError("Postselection must remain confined to three d3 rounds.")
        if (target / "se_round/source.qasm3").read_text(encoding="utf-8").count(
            "cx "
        ) != 4 * d * (d - 1):
            raise ValueError("SE interaction count disagrees with patch geometry.")
        if (target / "transversal_cnot/source.qasm3").read_text(encoding="utf-8").count(
            "cx "
        ) != d * d:
            raise ValueError("CNOT is missing corresponding data pairs.")
    return {
        "schema": "nadit.surface_component_readback/1",
        "source_tree_sha256": manifest["source_tree_sha256"],
        "verified_result_count": len(rows),
        "cases": rows,
        "measurement_evidence": "unobserved",
        "physical_execution": False,
        "logical_error_rate_estimated": False,
    }


def main() -> None:
    """Verify an existing output without invoking its component generator."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.directory)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"verified_result_count": result["verified_result_count"]}))


if __name__ == "__main__":
    main()
