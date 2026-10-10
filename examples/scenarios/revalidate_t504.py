"""Revalidate saved actual artifacts without recompiling or replaying execution."""
from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import time

from na_pipeline.validation import validate_strategy_run

ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "examples/scenarios/T504-encoded-observed"
OUTPUT = ROOT / "knowledge/roles/R5/evidence/T504"


def source_hashes():
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT / "src/na_pipeline/validation").glob("*.py")}


def main():
    before = source_hashes()
    run = json.loads((INPUT / "run.json").read_text(encoding="utf-8"))
    device = json.loads((INPUT / "device.json").read_text(encoding="utf-8"))
    with gzip.open(INPUT / "enola-evidence.json.gz", "rb") as stream: observations = json.load(stream)
    started = time.perf_counter()
    result = validate_strategy_run(run, device, strategies=run["strategies"], enola_evidence=observations)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "native-revalidation.json").write_bytes((json.dumps(result, ensure_ascii=False, indent=2)+"\n").encode("utf-8"))
    counters = []
    for instance in run["instances"]:
        retries = instance["composition_retries"]
        before_stats, after_stats = instance["library_stats_before"], instance["library_stats_after"]
        expected_composition = 1+len(retries)
        expected_binding = 1+sum(r["code"].startswith("JOINT_") for r in retries)
        actual_composition = after_stats["composition_check_count"]-before_stats["composition_check_count"]
        actual_binding = after_stats["bind_count"]-before_stats["bind_count"]
        counters.append({"call_id": instance["call_id"], "expected_composition": expected_composition, "actual_composition": actual_composition,
                         "expected_successful_R4_bindings": expected_binding, "actual_successful_R4_bindings": actual_binding,
                         "matched": expected_composition == actual_composition and expected_binding == actual_binding})
    summary = {"execution_replayed": False, "compiled_again": False, "validation_passed": result["passed"],
               "failure_codes": dict(Counter(f["code"] for f in result["failures"])), "unverified": result["unverified"],
               "author_retry_counter_check_passed": all(c["matched"] for c in counters), "counter_checks": counters,
               "validation_wall_seconds": time.perf_counter()-started, "validator_hashes_before": before, "validator_hashes_after": source_hashes(),
               "input_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (INPUT/"run.json", INPUT/"device.json", INPUT/"enola-evidence.json.gz")},
               "boundary": "R5 retry-counter author audit is separate from R6 independent acceptance."}
    summary["validator_sources_stable"] = before == summary["validator_hashes_after"]
    (OUTPUT / "native-revalidation-summary.json").write_bytes((json.dumps(summary, ensure_ascii=False, indent=2)+"\n").encode("utf-8"))
    print(json.dumps({k: summary[k] for k in ("validation_passed", "failure_codes", "unverified", "author_retry_counter_check_passed", "validator_sources_stable")}, ensure_ascii=False))
    return 0 if result["passed"] else 2


if __name__ == "__main__": raise SystemExit(main())
