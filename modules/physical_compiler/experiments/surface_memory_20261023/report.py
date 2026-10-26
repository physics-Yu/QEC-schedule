"""Aggregate complete shards and independently reconcile physical loss accounting."""

import csv
import json
import math
import sys
from collections import defaultdict
from pathlib import Path


def read(path):
    return json.loads(path.read_text())


def interval(failures, shots):
    z = 1.959963984540054
    p = failures / shots
    den = 1 + z * z / shots
    c = (p + z * z / (2 * shots)) / den
    h = z * math.sqrt(p * (1 - p) / shots + z * z / (4 * shots * shots)) / den
    return [max(0, c - h), min(1, c + h)]


def loss_stats(loss, roles):
    sources = ("load", "store", "move", "residence", "cz", "other")
    events = defaultdict(lambda: defaultdict(lambda: defaultdict(float)))
    for event in loss["events"]:
        source = {"holder_lifetime": "residence", "configured_cz_atom_loss": "cz"}.get(
            event["cause"], event["cause"]
        )
        source = source if source in sources else "other"
        # All frozen campaign hazards are finite.
        events[event["atom"]][event["start_us"] + event["duration_us"]][
            source
        ] += -math.log(event["survival_probability"])
    atoms = []
    for entry in loss["per_atom"]:
        survival = 1.0
        contribution = dict.fromkeys(sources, 0.0)
        for _, hazards in sorted(events[entry["atom"]].items()):
            total = sum(hazards.values())
            increment = survival * -math.expm1(-total)
            for source, hazard in hazards.items():
                contribution[source] += increment * hazard / total
            survival *= math.exp(-total)
        assert math.isclose(1 - survival, entry["loss_probability"], abs_tol=1e-10)
        assert math.isclose(
            sum(contribution.values()), entry["loss_probability"], abs_tol=1e-10
        )
        atoms.append(
            {
                "atom": entry["atom"],
                "role": roles[str(entry["atom"])],
                "loss": entry["loss_probability"],
                "sources": contribution,
            }
        )
    expected = sum(a["loss"] for a in atoms)
    assert math.isclose(expected, loss["expected_lost_atoms"], abs_tol=1e-9)
    groups = {}
    for role in ("data", "ancilla"):
        chosen = [a for a in atoms if a["role"] == role]
        groups[role] = {
            "count": len(chosen),
            "mean": sum(a["loss"] for a in chosen) / len(chosen),
            "maximum": max(a["loss"] for a in chosen),
        }
    return {
        "mean": expected / len(atoms),
        "expected_lost_atoms": expected,
        "maximum": max(atoms, key=lambda a: (a["loss"], -a["atom"])),
        "groups": groups,
        "mean_sources": {
            s: sum(a["sources"][s] for a in atoms) / len(atoms) for s in sources
        },
        "per_atom": atoms,
    }


def main(root):
    manifest = read(root / "manifest.json")
    budget = manifest["config"]["budget"]
    rows = []
    for case in manifest["cases"]:
        folder = root / "runs" / case["label"]
        row = {k: case[k] for k in ("label", "run_id", "distance", "basis", "backend")}
        statuses = [read(p) for p in sorted(folder.glob("*.status.json"))]
        failures = [s for s in statuses if s["status"] != "ok"]
        shards = []
        for i in range(budget["shards"]):
            p = folder / f"sample-{i:02d}.status.json"
            if p.exists() and read(p)["status"] == "ok":
                sample = read(folder / "shards" / f"{i:02d}.json")
                assert (
                    sample["seed"] == case["seeds"][i]
                    and sample["shots"] == budget["shots_per_shard"]
                )
                assert sample["run_id"] == case["run_id"] and sample["shard"] == i
                shards.append(sample)
        complete = len(shards) == budget["shards"] and not failures
        row.update(
            status="complete" if complete else "incomplete",
            completed_shards=len(shards),
            observed_shots=sum(s["shots"] for s in shards),
            failures=[
                {k: s[k] for k in ("phase", "shard", "status")} for s in failures
            ],
        )
        if (folder / "export.json").exists():
            export = read(folder / "export.json")
            doc = read(folder / "result.json")
            for s in shards:
                assert (
                    s["circuit_sha256"] == export["circuit_sha256"]
                    and s["noise_params_hash"] == manifest["noise_hash"]
                )
            losses = loss_stats(export["noise_report"]["noise"]["loss"], case["roles"])
            row["loss"] = losses
            row["compile_wall_s"] = read(folder / "compile-metrics.json")[
                "compile_wall_s"
            ]
            row["metrics"] = doc["metrics"]
            transport = {
                kind: sum(
                    a["duration_us"]
                    for step in doc["program"]["steps"]
                    for a in step["actions"]
                    if a["kind"] == kind
                )
                for kind in ("Load", "Move", "Store")
            }
            occupied = sum(
                max(
                    [
                        a["duration_us"]
                        for a in step["actions"]
                        if a["kind"] in transport
                    ]
                    or [0]
                )
                for step in doc["program"]["steps"]
            )
            assert math.isclose(
                sum(transport.values()),
                doc["metrics"]["transport_duration_us"],
                abs_tol=1e-7,
            )
            row.update(transport_us=transport, transport_occupied_us=occupied)
            if complete:
                n = sum(s["shots"] for s in shards)
                k = sum(s["failures"] for s in shards)
                row.update(
                    shots=n,
                    logical_failures=k,
                    logical_error_rate=k / n,
                    wilson_95=interval(k, n),
                )
        rows.append(row)
    result = {
        "schema": "nadit.surface-memory-report/1",
        "commit": manifest["commit"],
        "config": manifest["config"],
        "complete": all(r["status"] == "complete" for r in rows),
        "scope": "pauli_readout_only; loss is an independent model estimate",
        "runs": rows,
    }
    (root / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    columns = [
        "label",
        "status",
        "shots",
        "logical_failures",
        "logical_error_rate",
        "ci_low",
        "ci_high",
        "compile_wall_s",
        "transport_sum_us",
        "transport_occupied_us",
        "mean_loss",
        "max_loss",
        "expected_lost_atoms",
    ]
    with (root / "summary.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, columns)
        writer.writeheader()
        for r in rows:
            writer.writerow(
                {
                    **{k: r.get(k) for k in columns[:5]},
                    "ci_low": r.get("wilson_95", [None, None])[0],
                    "ci_high": r.get("wilson_95", [None, None])[1],
                    "compile_wall_s": r.get("compile_wall_s"),
                    "transport_sum_us": r.get("metrics", {}).get(
                        "transport_duration_us"
                    ),
                    "transport_occupied_us": r.get("transport_occupied_us"),
                    "mean_loss": r.get("loss", {}).get("mean"),
                    "max_loss": r.get("loss", {}).get("maximum", {}).get("loss"),
                    "expected_lost_atoms": r.get("loss", {}).get("expected_lost_atoms"),
                }
            )
    print(
        json.dumps(
            {
                "complete": result["complete"],
                "completed_points": sum(r["status"] == "complete" for r in rows),
                "observed_shots": sum(r["observed_shots"] for r in rows),
            }
        )
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
