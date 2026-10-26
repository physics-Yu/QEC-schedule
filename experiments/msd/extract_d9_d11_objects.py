"""Project saved d9/d11 templates into numeric objects, with no compiler imports.

This is an explicit offline migration, never called by an estimator or scan.
It reads existing JSON only; it does not construct atoms, expand a circuit,
execute a probability estimator, or regenerate missing source artifacts.
"""

import argparse
import json
from collections import Counter
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "modules/codes/rotated_surface/configs/object_d7_reference.json"


def _hash(value: Any) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _read(path: Path, hashes: dict[str, str], root: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    hashes[path.relative_to(root).as_posix()] = sha256(raw).hexdigest()
    value: dict[str, Any] = json.loads(raw)
    return value


def _project(template: dict[str, Any], distance: int) -> dict[str, Any]:
    """Keep every saved parallel step and classify its resource/distance cost."""
    fields = {k: v for k, v in template.items() if k != "content_sha256"}
    if _hash(fields) != template["content_sha256"]:
        raise ValueError("SAVED_TEMPLATE_HASH_MISMATCH")
    if (
        sha256(template["source_qasm"].encode()).hexdigest()
        != template["source_sha256"]
    ):
        raise ValueError("SAVED_SOURCE_HASH_MISMATCH")
    if template["timing_profile"] != [
        {"load_us": 10, "store_us": 10, "move_us_per_um": 1, "move_profile": "linear"},
        1,
        5,
        0.5,
        100,
        0,
    ]:
        raise ValueError("SAVED_TIMING_CONVENTION_MISMATCH")
    categories = {
        "Reset": ("reset", "local"),
        "Rotation": ("gate", "local"),
        "CZPulse": ("gate", "rydberg"),
        "Load": ("load", "aod"),
        "Store": ("store", "aod"),
        "Move": ("movement", "aod"),
        "Measure": ("measurement", "camera"),
    }
    rows = []
    kinds = []
    held = False
    component = template["description"]["component_id"]
    for step in template["relative_program"]["steps"]:
        actions = step["actions"]
        types = {a["kind"] for a in actions}
        if len(types) != 1 or not types <= set(categories):
            raise ValueError("UNSUPPORTED_SAVED_MIXED_STEP")
        kind = next(iter(types))
        if kind in ("Load", "Store"):
            if (kind == "Store") != held:
                raise ValueError("INVALID_SAVED_AOD_LEASE")
            held = not held
        elif kind in ("Move", "Measure") and not held:
            raise ValueError("SAVED_READOUT_REQUIRES_AOD")
        duration = max(a["duration_us"] for a in actions)
        measured = sum(len(a["results"]) for a in actions) if kind == "Measure" else 0
        rows.append([duration, *categories[kind], measured, None])
        kinds.append(kind)
    if held:
        raise ValueError("UNRELEASED_SAVED_AOD")
    for i, kind in enumerate(kinds):
        if kind == "Move":
            if component == "transversal_cnot":
                if rows[i][0] != 20 * distance + 40 + 2:
                    raise ValueError("SAVED_CNOT_REFERENCE_DISPLACEMENT_MISMATCH")
                rows[i][0], rows[i][4] = 0.0, "cnot"
            elif (i and kinds[i - 1] == "Measure") or (
                i + 1 < len(kinds) and kinds[i + 1] == "Measure"
            ):
                rows[i][4] = "readout"
    counts = Counter(
        n["name"] for n in template["dag"]["nodes"] if n["name"] != "barrier"
    )
    return {
        "phases": rows,
        "primitive_counts": dict(counts),
        "correction_envelope": False,
    }


def extract(source: Path, output: Path) -> list[dict[str, Any]]:
    """Write fresh d9/d11 catalogs from a complete saved bundle, or raise.

    Missing files, hash/timing/coverage mismatches and existing output files are
    errors. Partial files must not be used after any migration error.
    """
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    audits = []
    for distance in (9, 11):
        hashes: dict[str, str] = {}
        manifest = _read(source / "manifest.json", hashes, source)
        noise = _read(source / "noise.json", hashes, source)
        if (
            noise != reference["noise_params"]
            or _hash(noise) != manifest["noise_sha256"]
        ):
            raise ValueError("SAVED_NOISE_MISMATCH")
        case = next(c for c in manifest["cases"] if c["distance"] == distance)
        protocol = _read(
            source / f"d{distance}/raw_t_postselection/protocol.json", hashes, source
        )
        entries = {}
        template_hashes: dict[str, str] = {}

        def component(
            path: str,
            distance: int = distance,
            hashes: dict[str, str] = hashes,
            template_hashes: dict[str, str] = template_hashes,
        ) -> dict[str, Any]:
            template = _read(
                source / f"d{distance}/{path}/template.json", hashes, source
            )
            template_hashes[path] = template["content_sha256"]
            return _project(template, distance)

        for name in (
            "initialize_plus",
            "logical_mx",
            "logical_mz",
            "logical_s",
            "logical_x",
            "transversal_cnot",
            "se_round",
        ):
            entries[name] = component(name)
            if template_hashes[name] != case["operations"][name]["template_sha256"]:
                raise ValueError("MANIFEST_TEMPLATE_MISMATCH")
        raw_parts = [component(f"raw_t_postselection/injection-{i}") for i in range(3)]
        growth_parts = [
            component(f"raw_t_postselection/growth-{i}") for i in range(distance)
        ]
        stage_paths = [f"raw_t_postselection/injection-{i}" for i in range(3)] + [
            f"raw_t_postselection/growth-{i}" for i in range(distance)
        ]
        if [template_hashes[p] for p in stage_paths] != [
            s["template_sha256"] for s in protocol["stages"]
        ]:
            raise ValueError("SAVED_PROTOCOL_STAGE_HASH_MISMATCH")
        for name, parts, expected in (
            ("raw_t_postselection", raw_parts, protocol["injection_duration_us"]),
            (
                "raw_t_postselection/canonicalize",
                growth_parts,
                protocol["growth_duration_us"],
            ),
        ):
            counts: Counter[str] = Counter()
            for part in parts:
                counts.update(part["primitive_counts"])
            rows = [row for part in parts for row in part["phases"]]
            if abs(sum(row[0] for row in rows) - expected) > 1e-7:
                raise ValueError("SAVED_PROTOCOL_DURATION_MISMATCH")
            entries[name] = {
                "phases": rows,
                "primitive_counts": dict(counts),
                "correction_envelope": name.endswith("canonicalize"),
            }
        # Retain the existing one-parallel-Pauli-layer factory correction envelope.
        correction = {
            "phases": [[1, "gate", "local", 0, None]],
            "primitive_counts": {"ry": distance**2},
            "correction_envelope": True,
        }
        entries["initialize_plus/canonicalize"] = correction
        growth = entries["raw_t_postselection/canonicalize"]
        growth["phases"].extend(deepcopy(correction["phases"]))
        growth["primitive_counts"]["ry"] += distance**2
        for name, entry in entries.items():
            entry["syndrome_rounds"] = (
                3
                if name == "raw_t_postselection"
                else distance
                if name == "raw_t_postselection/canonicalize"
                else int(name in ("initialize_plus", "logical_s", "se_round"))
            )
            entry["growth_rounds"] = (
                distance if name == "raw_t_postselection/canonicalize" else 0
            )
        port = _read(
            source / f"d{distance}/raw_t_postselection/acceptance.port.json",
            hashes,
            source,
        )
        original_port_hash = _hash(port)
        evidence = port["model"]["evidence"]
        if evidence["part_template_content_sha256"] != [
            template_hashes[f"raw_t_postselection/injection-{i}"] for i in range(3)
        ]:
            raise ValueError("SAVED_PROBABILITY_TEMPLATE_MISMATCH")
        if evidence["preparation_sha256"] != protocol["template_sha256"]:
            raise ValueError("SAVED_PREPARATION_HASH_MISMATCH")
        if evidence["estimator"]["probability"] != protocol["acceptance_probability"]:
            raise ValueError("SAVED_PROBABILITY_VALUE_MISMATCH")
        # Retain sufficient provenance rather than importing per-atom loss logs.
        port["model"]["evidence"] = {
            k: deepcopy(evidence[k])
            for k in (
                "estimator",
                "preparation_sha256",
                "noise_params_hash",
                "part_template_content_sha256",
                "activity_duration_us",
                "detector_count",
                "detectors_sha256",
                "channel_signatures_sha256",
            )
        }
        port["model"]["evidence"].update(
            source_port_sha256=original_port_hash,
            scope="Existing exact acceptance cache; detailed loss/atom logs retained in hashed source, not used by object scheduling",
        )
        document = deepcopy(reference)
        document.update(
            distance=distance,
            protocol=protocol["protocol"],
            raw_port=port,
            reference_origin_y_um=-20 * distance,
            entries=entries,
        )
        document["source"] = {
            "path_label": source.name + f"/d{distance}",
            "source_tree_sha256": manifest["source_tree_sha256"],
            "source_file_sha256": hashes,
            "template_content_sha256": template_hashes,
            "raw_source_port_sha256": original_port_hash,
            "extraction": "Saved JSON steps projected once; no compilation, atom construction/expansion or probability calculation",
            "correction_envelope": "Retained one parallel Y layer over target data, 1 us; not a sampled decoder frame",
            "plus_probability_source": "Retained generic_surface_factory.supply.v1 ideal initialize-plus probability 1",
        }
        document["plus_port"]["model"]["evidence"] = {
            "template_sha256": template_hashes["initialize_plus"]
        }
        output.mkdir(parents=True, exist_ok=True)
        target = output / f"object_d{distance}_reference.json"
        with target.open("x", encoding="utf-8") as stream:
            stream.write(
                json.dumps(document, separators=(",", ":"), allow_nan=False) + "\n"
            )
        audits.append(
            {
                "distance": distance,
                "input_files": len(hashes),
                "catalog_fingerprint": _hash(document),
                "output_file_sha256": sha256(target.read_bytes()).hexdigest(),
                "objects": len(entries),
                "raw_us": sum(r[0] for r in entries["raw_t_postselection"]["phases"]),
                "growth_correction_us": sum(r[0] for r in growth["phases"]),
                "raw_probability": protocol["acceptance_probability"],
            }
        )
    return audits


def main() -> None:
    """Convert an explicitly supplied saved bundle; never locate or build one."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audits = extract(args.source, args.output)
    print(json.dumps(audits, indent=2))


if __name__ == "__main__":
    main()
