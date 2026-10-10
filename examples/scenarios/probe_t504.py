"""Real public R1/R3/R4 -> R5 probe; failures remain failures, no fallback."""
import argparse
import hashlib
import gzip
import json
import platform
from pathlib import Path
import sys
import time

from na_pipeline.device import grouped_device, group_layout
from na_pipeline.backend import StrategyLibrary
from na_pipeline.qec import build_logical_primitive
from na_pipeline.runtime import LogicalBlockController, make_scenario

ROOT = Path(__file__).resolve().parents[2]


def source_hashes():
    paths = [*ROOT.glob("src/na_pipeline/runtime/*.py"), *ROOT.glob("src/na_pipeline/backend/*.py"),
             *ROOT.glob("src/na_pipeline/qec/*.py"), *ROOT.glob("src/na_pipeline/device/*.py"),
             *ROOT.glob("src/na_pipeline/validation/strategy*.py"), Path(__file__).resolve()]
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode("utf-8"))


class ObservedLibrary:
    """Use the R6 qualification observer around the public R4 boundaries."""
    def __init__(self, device):
        from na_pipeline.validation.strategy_observer import EnolaCallObserver
        self.observer_type = EnolaCallObserver
        self.library = StrategyLibrary(device)
        pin = json.loads((ROOT / "third_party/enola/pin.json").read_text(encoding="utf-8"))
        self.source = ROOT / pin["source_root"] / "enola/router/router_mis.py"
        self.evidence = {"pin": pin, "observations": {}, "binding_observations": {}}

    @property
    def stats(self):
        return self.library.stats

    def get_or_compile(self, program):
        with self.observer_type(self.source) as observer:
            strategy = self.library.get_or_compile(program)
        self.evidence["observations"].setdefault(strategy["strategy_hash"], observer.evidence())
        return strategy

    def bind(self, strategy, binding):
        observer = self.observer_type(self.source)
        try:
            with observer:
                return self.library.bind(strategy, binding)
        finally:
            record = observer.evidence()
            previous = self.evidence["binding_observations"].get(binding["call_id"])
            if previous:
                record["record_count"] += previous["record_count"]
                record["records"] += previous["records"]
                record["attempt_count"] = previous.get("attempt_count", 1)+1
                for key, value in previous.get("project_search_counts", {}).items():
                    record["project_search_counts"][key] = record["project_search_counts"].get(key, 0)+value
                record["project_sources_unchanged"] = record.get("project_sources_unchanged") is True and previous.get("project_sources_unchanged") is True
            else:
                record["attempt_count"] = 1
            self.evidence["binding_observations"][binding["call_id"]] = record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "examples/scenarios/T504-native")
    parser.add_argument("--blocks", type=int, choices=(1, 2), default=1)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--binding-attempts", type=int, default=4096)
    args = parser.parse_args()
    started = time.perf_counter()
    before_hashes = source_hashes()
    device = grouped_device()
    profile = build_logical_primitive("syndrome_round")["strategy_contract"]["operation"]["code_profile"]
    world = {"time_us": 0, "atoms": [], "slm_traps": [], "aod_rows": [], "aod_columns": []}
    bindings = {}
    for i in range(args.blocks):
        lid = f"L{i}"
        layout = group_layout(device, "patch_initialization", offset_um=(i*100, 0))
        bindings[lid] = {}
        for slot, entry in layout["slots"].items():
            qid, aid, tid = f"{lid}/{slot}", f"atom:{lid}/{slot}", f"slm:{lid}/init/{slot}"
            bindings[lid][slot] = qid
            world["atoms"].append(dict(atom_id=aid, qubit_id=qid, position_um=entry["position_um"], carrier="SLM", trap_id=tid, aod_group="data", row_id=None, column_id=None))
            world["slm_traps"].append(dict(trap_id=tid, position_um=entry["position_um"], zone_id=layout["zone_id"], occupant=aid))
    library = ObservedLibrary(device)
    controller = LogicalBlockController(device, world, run_id="T504-native", strategy_library=library, binding_retry_budget=args.binding_attempts)
    for i, (lid, mapping) in enumerate(bindings.items()):
        controller.register_block(lid, qubits=mapping, data_slots=[f"d{j}" for j in range(9)], code_profile=profile,
                                  layout_profile="patch_initialization", offset_um=(i*100, 0))
    stage = "queue"
    report = {"fixture": False, "host": platform.node(), "python": sys.version, "kb_revision": "kb-0005", "plan_revision": "plan-0007",
              "scope": "T504 real compiled strategy calls, not whole Shor or factory", "budget": {"parallelism": 1, "wall_seconds_guidance": 600, "binding_attempts_per_call": args.binding_attempts}}
    try:
        if args.blocks == 2:
            from na_pipeline.frontend import build_t000_program
            controller.queue_encoded_program(build_t000_program(rounds=args.rounds))
        else:
            lid = "L0"
            controller.queue_call("prepare", {"block": lid}, call_id=lid+"-prepare", params={"state": "0"})
            for i in range(args.rounds):
                controller.queue_call("syndrome_round", {"block": lid}, call_id=f"{lid}-round{i}")
        stage = "runtime"
        program = controller.pending_program()
        scenario = make_scenario(program, value=0)
        scenario["provenance"]["fixture"] = False
        scenario["provenance"]["description"] = "Explicit configured zero bits for a real compiled strategy path; not sampling"
        outcome = controller.execute_pending(scenario)
        write(args.out / "device.json", device)
        write(args.out / "scenario.json", scenario)
        write(args.out / "run.json", outcome)
        report.update(runtime_completed=True, action_count=len(program["actions"]), result_count=len(outcome["event_trace"]["results"]),
                      duration_us=outcome["event_trace"]["stats"]["duration_us"], group_metrics=outcome["group_metrics"])
        stage = "independent_validation"
        try:
            from na_pipeline.validation import validate_strategy_run
        except ImportError:
            report.update(independent_validation="entry_unavailable", passed=False)
        else:
            validation = validate_strategy_run(outcome, device, strategies=outcome["strategies"], enola_evidence=library.evidence)
            write(args.out / "validation.json", validation)
            report.update(independent_validation="executed", passed=validation["passed"], failures=validation["failures"][:5], unverified=validation["unverified"])
    except Exception as exc:
        report.update(runtime_completed=False, passed=False, failed_stage=stage, error_type=type(exc).__name__, error=str(exc),
                      error_code=getattr(exc, "code", None), details=getattr(exc, "details", None))
    report.update(wall_seconds=time.perf_counter()-started, library_stats=library.stats, snapshot=controller.snapshot(), user_visual_acceptance="pending")
    args.out.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.out / "enola-evidence.json.gz", "wb") as stream:
        stream.write(json.dumps(library.evidence, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))
    report["source_sha256_before"] = before_hashes
    report["source_sha256_after"] = source_hashes()
    report["sources_stable_during_run"] = before_hashes == report["source_sha256_after"]
    write(args.out / "report.json", report)
    print(json.dumps({k: report.get(k) for k in ("runtime_completed", "passed", "failed_stage", "error", "library_stats", "wall_seconds", "independent_validation")}, ensure_ascii=False))
    return 0 if report.get("runtime_completed") and report.get("passed") else 2


if __name__ == "__main__": raise SystemExit(main())
