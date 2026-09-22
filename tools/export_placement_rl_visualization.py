"""Export saved placement-RL witnesses as an audited, self-contained UI fragment.

This reads an existing run; it never trains, recompiles, or executes a physical
environment. Event payload interning removes repetition without rounding times,
coordinates, gate identities, or terminal positions. The browser expands each
``[start_us, duration_us, payload_index]`` using ``event_pool`` before replay.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from math import isclose, isfinite
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from neutral_atom_strategies.placement_rl.compiler import audit_result
from neutral_atom_strategies.placement_rl.model import (
    Circuit, CompileResult, CompilerConfig, Hardware, Scenario,
)


EVENT_NAMES = {
    "kind": "k", "start_us": "t", "duration_us": "d", "group": "g",
    "qubits": "q", "positions": "p", "sources": "s", "phase": "ph",
    "layer": "l", "gate_indices": "gi", "pairs": "pairs",
}
TEMPLATE = ROOT / "src/neutral_atom_app/visualization/placement_rl_inline.html"
SCRIPT = TEMPLATE.with_suffix(".js")
DEFAULT_RUN = ROOT / "artifacts/placement-rl/pilot-20260922-attempt2"
DEFAULT_AUDIT = ROOT / "artifacts/placement-rl/visualization-20260922/data-audit.json"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _compact(value: Any) -> Any:
    """Encode 10.0 as 10 while preserving the exact numerical value."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {key: _compact(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_compact(item) for item in value]
    return value


def _json(value: Any) -> str:
    return json.dumps(_compact(value), ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def build_data(run: Path) -> dict[str, Any]:
    """Load, independently audit, cross-check and losslessly intern saved data."""
    manifest = _load(run / "manifest.json")
    summary = _load(run / "summary.json")
    _require(summary["status"] == "completed", "Run is not completed")
    for name, expected in manifest["source_sha256"].items():
        snapshot = run / "source-snapshot" / name
        _require(snapshot.is_file() and sha256(snapshot.read_bytes()).hexdigest() == expected,
                 f"Frozen source mismatch: {name}")
        normalized = name.replace("\\", "/")
        if normalized.endswith(("/placement_rl/model.py", "/placement_rl/compiler.py")):
            _require(sha256((ROOT / name).read_bytes()).hexdigest() == expected,
                     f"Current audit model differs from run: {name}")

    cases = []
    case_by_id = {}
    for split in ("test", "size_holdout"):
        for original in manifest["splits"][split]:
            digest = sha256(json.dumps(original["circuit"], sort_keys=True).encode()).hexdigest()
            _require(digest == original["digest"], f"Circuit digest mismatch: {original['id']}")
            row = dict(original, split=split, baseline=[])
            cases.append(row)
            case_by_id[row["id"]] = row

    event_pool: list[dict[str, Any]] = []
    event_index: dict[str, int] = {}
    replays: dict[str, Any] = {}
    replay_index: dict[str, str] = {}
    variants = []
    witnesses_checked = events_checked = gates_checked = 0
    source_witness_hashes = []

    for run_summary in summary["results"]:
        expected_training = run_summary["training"]
        mode, seed = expected_training["mode"], expected_training["seed"]
        variant_id = f"{mode}-seed-{seed}"
        folder = run / variant_id
        training = _load(folder / "training.json")
        evaluation = _load(folder / "evaluation.json")
        _require(training["summary"] == expected_training,
                 f"Training summary mismatch: {variant_id}")
        selected = min(training["summary"]["validations"], key=lambda item: item["score"])
        _require(selected["step"] == training["summary"]["selected_step"],
                 f"Checkpoint selection mismatch: {variant_id}")
        final_step = max(item["step"] for item in training["history"])
        variant = {
            "id": variant_id, "mode": mode, "seed": seed,
            "training": training["summary"], "final_step": final_step,
            "aggregate": evaluation["summary"]["aggregate"],
            "evaluation": {key: value for key, value in evaluation["summary"].items()
                           if key != "aggregate"},
            "adversary_diagnostic": {
                "actor_step": training["summary"]["selected_step"],
                "adversary_step": final_step,
                "note": "Selected actor and final adversary; not necessarily a joint checkpoint",
            },
            "cases": {},
        }
        _require({row["id"] for row in evaluation["cases"]} == set(case_by_id),
                 f"Evaluation case set mismatch: {variant_id}")
        for measured in evaluation["cases"]:
            case_id = measured["id"]
            case = case_by_id[case_id]
            _require(measured["digest"] == case["digest"], f"Evaluation digest mismatch: {case_id}")
            probabilities = measured["adversary_probabilities"]
            _require(len(probabilities) == len(manifest["scenarios"])
                     and all(isfinite(p) and 0 <= p <= 1 for p in probabilities)
                     and isclose(sum(probabilities), 1, abs_tol=1e-6),
                     f"Invalid scenario probabilities: {variant_id}/{case_id}")
            variant_case = {key: value for key, value in measured.items()
                            if key not in {"id", "split", "family", "digest"}}
            variant_case["replays"] = []
            for method in ("interaction", "trained_greedy"):
                measurement = measured["measurements"][method]
                replay_ids = []
                for scene_index, scenario in enumerate(manifest["scenarios"]):
                    witness_path = folder / "witnesses" / case_id / f"{method}-{scene_index}.json"
                    raw = _load(witness_path)
                    label = str(witness_path.relative_to(run))
                    source_witness_hashes.append((label, sha256(witness_path.read_bytes()).hexdigest()))
                    _require(raw["circuit"] == case["circuit"], f"Witness circuit mismatch: {label}")
                    _require(raw["scenario"] == scenario, f"Witness scenario mismatch: {label}")
                    _require(raw["mapping"] == measurement["mapping"], f"Witness mapping mismatch: {label}")
                    if "hardware" in case:
                        _require(raw["hardware"] == case["hardware"], f"Geometry mismatch: {label}")
                    else:
                        case["hardware"] = raw["hardware"]
                    circuit, hardware = Circuit(**raw["circuit"]), Hardware(**raw["hardware"])
                    result = CompileResult(**raw["result"])
                    check = audit_result(circuit, hardware, tuple(raw["mapping"]), result,
                                         Scenario(**scenario), CompilerConfig(**raw["compiler"]))
                    _require(result.status == "completed" and check["status"] == "passed",
                             f"Discrete witness audit failed: {label}: {check}")
                    _require(result.status == measurement["statuses"][scene_index]
                             and result.duration_us == measurement["modeled_duration_us"][scene_index],
                             f"Evaluation timing/status mismatch: {label}")
                    _require(raw["audit"]["status"] == "passed" and raw["audit"]["ok"],
                             f"Saved audit was not passed: {label}")
                    _require(result.trace and result.trace[-1]["start_us"]
                             + result.trace[-1]["duration_us"] == result.duration_us,
                             f"Trace end-time mismatch: {label}")

                    encoded_events = []
                    for event in result.trace:
                        _require(set(event) <= set(EVENT_NAMES), f"Unrecognized trace fields: {label}")
                        payload = {EVENT_NAMES[key]: value for key, value in event.items()
                                   if key not in {"start_us", "duration_us"}}
                        payload_key = _json(payload)
                        if payload_key not in event_index:
                            event_index[payload_key] = len(event_pool)
                            event_pool.append(payload)
                        index = event_index[payload_key]
                        encoded_events.append([event["start_us"], event["duration_us"], index])
                        restored = {key: event_pool[index][short] for key, short in EVENT_NAMES.items()
                                    if short in event_pool[index]}
                        restored.update(start_us=event["start_us"], duration_us=event["duration_us"])
                        _require(restored == event, f"Lossless event round-trip failed: {label}")

                    replay = {
                        "mapping": raw["mapping"], "status": result.status,
                        "duration_us": result.duration_us, "metrics": result.metrics,
                        "final_positions": result.final_positions, "events": encoded_events,
                    }
                    replay_key = _json(replay)
                    if replay_key not in replay_index:
                        replay_id = f"r{len(replays)}"
                        replay_index[replay_key] = replay_id
                        replays[replay_id] = replay
                    replay_ids.append(replay_index[replay_key])
                    witnesses_checked += 1
                    events_checked += len(result.trace)
                    gates_checked += check["gates_checked"]
                if method == "interaction":
                    if case["baseline"]:
                        _require(case["baseline"] == replay_ids, f"Baseline varies between training modes: {case_id}")
                    else:
                        case["baseline"] = replay_ids
                else:
                    variant_case["replays"] = replay_ids
            variant["cases"][case_id] = variant_case
        variants.append(variant)

    expected = len(variants) * len(cases) * len(manifest["scenarios"]) * 2
    _require(witnesses_checked == expected, "Export witness count mismatch")
    result = {
        "schema": "placement-rl-visualization/1", "run": run.name,
        "scope": manifest["scope"], "scenarios": manifest["scenarios"],
        "config": manifest["config"], "cases": cases, "variants": variants,
        "replays": replays, "event_pool": event_pool,
        "verification": {
            "status": "passed", "witnesses_checked": witnesses_checked,
            "unique_replays": len(replays), "source_events_checked": events_checked,
            "gates_checked": gates_checked, "unique_event_payloads": len(event_pool),
            "event_roundtrip": "exact", "evaluation_duration_match": "exact",
            "terminal_state": "independently audited from each complete witness",
            "source_files_checked": len(manifest["source_sha256"]),
            "source_witness_manifest_sha256": sha256(_json(source_witness_hashes).encode()).hexdigest(),
            "physical_validation": "not_run",
        },
    }
    # Check the serialized representation as well, including normalized coordinates.
    serialized = _json(result)
    _require(json.loads(serialized) == _compact(result), "JSON serialization changed values")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, default=DEFAULT_RUN)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--data-only", action="store_true", help="Write JSON without requiring UI templates")
    parser.add_argument("--audit-output", type=Path, default=DEFAULT_AUDIT)
    args = parser.parse_args()
    data = build_data(args.run.resolve())
    serialized = _json(data)
    if args.data_only:
        output = serialized
    else:
        template = TEMPLATE.read_text(encoding="utf-8")
        script = SCRIPT.read_text(encoding="utf-8")
        _require(template.count("__PLACEMENT_DATA__") == 1
                 and template.count("__PLACEMENT_SCRIPT__") == 1,
                 "Template must contain each placement placeholder exactly once")
        _require("</script" not in script.lower(), "JS contains a closing script tag")
        safe_json = serialized.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
        output = template.replace("__PLACEMENT_DATA__", safe_json).replace("__PLACEMENT_SCRIPT__", script)
        _require(len(output.encode("utf-8")) < 1_000_000, "Inline fragment exceeds 1 MB")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(output, encoding="utf-8", newline="\n")
    report = dict(data["verification"], data_bytes=len(serialized.encode("utf-8")),
                  output_bytes=len(output.encode("utf-8")), output=str(args.output.resolve()),
                  output_sha256=sha256(output.encode("utf-8")).hexdigest(),
                  data_only=args.data_only)
    args.audit_output.parent.mkdir(parents=True, exist_ok=True)
    args.audit_output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
