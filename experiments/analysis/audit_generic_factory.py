"""Independently audit saved factory schedules and recompute aggregate results."""

import argparse
import csv
import json
from collections import defaultdict
from math import isclose
from pathlib import Path
from statistics import fmean


def audit(directory: Path) -> dict:
    """Check persisted timing, resource, acceptance and paired-control evidence."""
    report = json.loads((directory / "summary.json").read_text(encoding="utf-8"))
    inspected_calls = 0
    paired = {}
    for row in report["results"]:
        prefix = f"d{row['distance']}-n{row['factory_count']}-{row['hardware']}"
        samples = json.loads(
            (directory / f"{prefix}.samples.json").read_text(encoding="utf-8")
        )
        assert [s["seed"] for s in samples] == report["plan"]["seeds"]
        assert row["outputs"] == sum(s["outputs"] for s in samples)
        elapsed = sum(s["makespan_us"] for s in samples)
        assert isclose(row["mean_makespan_us"], elapsed / len(samples))
        assert isclose(
            row["observed_outputs_per_second"], 1e6 * row["outputs"] / elapsed
        )
        assert row["atoms"] == 6 * row["factory_count"] * (2 * row["distance"] ** 2 - 1)
        for sample in samples:
            assert sample["physical_validation_run"] is False
            assert sample["actual_output_error"] is None
            assert sample["growth_calls"] == sum(
                line["raw_accepted_events"] for line in sample["lines"].values()
            )
        identity = (row["distance"], row["factory_count"])
        outcomes = [
            (s["outputs"], s["raw_attempts"], s["raw_rejections"], s["growth_calls"])
            for s in samples
        ]
        if identity in paired:
            assert paired[identity] == outcomes
        else:
            paired[identity] = outcomes
        case = json.loads((directory / row["witness"]).read_text(encoding="utf-8"))
        calls = case["execution"]["calls"]
        by_id = {c["invocation_id"]: c for c in calls}
        assert len(calls) == len(by_id)
        inspected_calls += len(calls)
        assert isclose(max(c["action_end_us"] for c in calls), case["duration_us"])
        with (directory / f"{prefix}.schedule.csv").open(
            encoding="utf-8", newline=""
        ) as stream:
            records = list(csv.DictReader(stream))
        assert len(records) == len(calls)
        occupancy = defaultdict(list)
        for record, call in zip(records, calls, strict=True):
            assert record["invocation"] == call["invocation_id"]
            for field in ("start_us", "action_end_us", "results_ready_us"):
                assert float(record[field]) == call[field]
            assert call["start_us"] <= call["action_end_us"]
            for resource in (*call["participant_blocks"], *call["reserved_resources"]):
                occupancy[resource].append((call["start_us"], call["action_end_us"]))
        for intervals in occupancy.values():
            ordered = sorted(intervals)
            assert all(
                a[1] <= b[0] + 1e-7 for a, b in zip(ordered, ordered[1:], strict=False)
            )
        accepted = set()
        for event in case["events"]:
            assert event["released_at_us"] >= event["available_at_us"] - 1e-7
            for dependency in event["dependencies"]:
                source = by_id[dependency["invocation_id"]]
                assert event["released_at_us"] >= source["action_end_us"] - 1e-7
                if (
                    source["component_id"] == "raw_t_postselection"
                    and event["values"]["accepted"]
                ):
                    accepted.add(
                        source["invocation_id"].removesuffix("/body") + "/canonicalize"
                    )
        growth = {
            c["invocation_id"]
            for c in calls
            if c["component_id"] == "raw_t_postselection/canonicalize"
        }
        assert growth == accepted
        consumed = [
            c["consumed_token_id"] for c in case["calls"] if c["consumed_token_id"]
        ]
        assert len(consumed) == len(set(consumed))
    result = {
        "passed": True,
        "seeded_trajectories": sum(
            r["independent_seed_count"] for r in report["results"]
        ),
        "witness_schedules": len(report["results"]),
        "witness_calls": inspected_calls,
        "mean_software_seconds": fmean(
            r["mean_software_seconds"] for r in report["results"]
        ),
        "checks": [
            "seed coverage",
            "aggregate output/time arithmetic",
            "paired hardware outcomes",
            "atom budgets",
            "CSV matches execution records",
            "exclusive resource and patch intervals",
            "event release after dependencies",
            "accepted-only growth",
            "single-use consumed tokens",
        ],
        "scope": "saved logical estimates; does not establish physical joint factory feasibility or output LER",
    }
    (directory / "audit.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    print(json.dumps(audit(parser.parse_args().directory), indent=2))
