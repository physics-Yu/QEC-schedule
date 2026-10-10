"""Actual R1/R3/R4/R5/R6 strategy chain with observed Enola calls.

No quantum state. This is a reproducible T404 qualification workload, not an
alternate backend or a replacement for R0's independent T000 acceptance.
"""
from __future__ import annotations

from copy import deepcopy
import gzip
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
import time

from na_pipeline.backend import StrategyLibrary
from na_pipeline.device import grouped_device, group_layout
from na_pipeline.qec import build_logical_primitive
from na_pipeline.frontend import build_t000_program, iter_encoded_calls
from na_pipeline.runtime import LogicalBlockController, make_scenario
from na_pipeline.validation import validate_strategy, validate_strategy_run
from na_pipeline.validation.strategy_observer import EnolaCallObserver

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "third_party/enola/upstream/enola/router/router_mis.py"


class ObservedLibrary(StrategyLibrary):
    """Observe public operations; never inspect backend or controller internals."""
    def __init__(self, device):
        super().__init__(device)
        self.observations = {}
        self.binding_observations = {}
        self.strategies = {}

    def get_or_compile(self, physical):
        with EnolaCallObserver(SOURCE) as observed:
            strategy = super().get_or_compile(physical)
        evidence = observed.evidence()
        if evidence["record_count"]:
            self.observations[strategy["strategy_hash"]] = evidence
        self.strategies[strategy["strategy_id"]] = strategy
        return strategy

    def bind(self, strategy, binding):
        with EnolaCallObserver(SOURCE) as observed:
            bound = super().bind(strategy, binding)
        self.binding_observations[binding["call_id"]] = observed.evidence()
        return bound


def make_world(device):
    atoms, traps, blocks = [], [], {}
    code = build_logical_primitive("syndrome_round")["strategy_contract"]["operation"]["code_profile"]
    for block, dx in (("L0", 0.), ("L1", 100.)):
        qubits = {}
        for profile in ("patch_initialization", "patch_home", "ancilla_readout"):
            layout = group_layout(device, profile, offset_um=(dx, 0.))
            for slot, point in layout["slots"].items():
                aid, qid = f"atom:{block}/{slot}", f"{block}/{slot}"
                tid = f"slm:{profile}:{block}/{slot}"
                traps.append({"trap_id": tid, "position_um": list(point["position_um"]), "zone_id": layout["zone_id"],
                              "occupant": aid if profile == "patch_initialization" else None})
                if profile == "patch_initialization":
                    qubits[slot] = qid
                    atoms.append({"atom_id": aid, "qubit_id": qid, "position_um": list(point["position_um"]),
                                  "carrier": "SLM", "trap_id": tid, "aod_group": "data", "row_id": None, "column_id": None})
        blocks[block] = {"qubits": qubits, "data_slots": [f"d{i}" for i in range(9)], "code_profile": deepcopy(code),
                         "layout_profile": "patch_initialization", "offset_um": [dx, 0.]}
    return {"atoms": atoms, "slm_traps": traps, "aod_rows": [], "aod_columns": [], "time_us": 0.}, blocks


def workload(device, library, *, value=0):
    world, blocks = make_world(device)
    controller = LogicalBlockController(device, world, run_id=f"T404-fake-{value}", strategy_library=library)
    for name, kwargs in blocks.items():
        controller.register_block(name, **kwargs)
    encoded = build_t000_program(rounds=3)
    calls = list(iter_encoded_calls(encoded))
    # The two prepares have disjoint operands and no mutual semantic dependency.
    # Move the second branch's prepare ahead of the first branch's maintenance,
    # then retain all source dependencies. No call/gate/result is removed.
    schedule = [c for c in calls if c["operation"] == "prepare"] + [c for c in calls if c["operation"] != "prepare"]
    mapping = {c["id"]: "ec-"+c["id"].encode("utf-8").hex() for c in calls}
    at = 0.; first_prepare = None
    for index, source in enumerate(schedule):
        operation, operands = source["operation"], source["operands"]
        origin = operands["control"] if operation == "logical_cx" else operands["block"]
        dx = blocks[origin]["offset_um"][0]
        if index == 1:
            # Actual first strategy has released every AOD line before its final
            # 1q correction. Start the other patch's transfer in that last 1 us.
            # The controller and full-world verifier must accept this unchanged
            # pair of schedules; this is not a claim of maximum concurrency.
            at = first_prepare["end_us"]-device["timings_us"]["gate_1q"]
        request = controller.queue_call(operation, operands, call_id=mapping[source["id"]], params=source["params"], offset_um=(dx, 0.),
            start_time_us=at, after=[mapping[d] for d in source["after"]], source_ids=source["source_ids"])
        if index == 0: first_prepare = request
        at = request["end_us"]
    plan = controller.pending_program()
    scenario = make_scenario(plan, value=value)
    result = controller.execute_pending(scenario)
    result["encoded_program"] = encoded
    result["encoded_call_map"] = mapping
    instance_by_id = {i["call_id"]: i for i in result["instances"]}
    result["encoded_result_map"] = {c["id"]+"/"+r["encoded_result_slot"]: r["result_id"]
        for c in calls for r in instance_by_id[mapping[c["id"]]]["physical_program"]["strategy_contract"]["formal_bindings"]["result_slots"]}
    result["workload_schedule_policy"] = "explicit source-safe call order; two prepares overlap one real gate interval; no optimality claim"
    return result, scenario


def save(path, value, compress=False):
    raw = (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)+"\n").encode("utf-8")
    data = gzip.compress(raw, mtime=0) if compress else raw
    path.write_bytes(data)
    return {"path": path.name, "bytes": len(data), "sha256": sha256(data).hexdigest(), "uncompressed_bytes": len(raw)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent / "qualification")
    parser.add_argument("--fake-value", type=int, choices=(0, 1), default=1)
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(exist_ok=True)
    began = time.perf_counter()
    def sources():
        values = {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest() for folder in
                   ("backend", "qec", "device", "runtime", "validation") for p in (ROOT/"src/na_pipeline"/folder).glob("*.py")}
        values[Path(__file__).resolve().relative_to(ROOT).as_posix()] = sha256(Path(__file__).read_bytes()).hexdigest()
        return values
    source_before = sources()
    device = grouped_device(); library = ObservedLibrary(device)
    run, scenario = workload(device, library, value=args.fake_value)
    actual_overlaps = []
    events = {e["action_id"]: e for e in run["event_trace"]["events"]}
    for index, left in enumerate(run["instances"]):
        for right in run["instances"][index+1:]:
            if set(left["operands"].values()) & set(right["operands"].values()): continue
            if max(left["start_us"], right["start_us"]) >= min(left["end_us"], right["end_us"]): continue
            for a in left["atom_program"]["actions"]:
                if events[a["id"]]["status"] != "completed" or a["kind"] in {"wait", "classical"}: continue
                for b in right["atom_program"]["actions"]:
                    if events[b["id"]]["status"] != "completed" or b["kind"] in {"wait", "classical"}: continue
                    overlap = min(a["t_end_us"], b["t_end_us"])-max(a["t_start_us"], b["t_start_us"])
                    if overlap > 0 and not set(a["atoms"]) & set(b["atoms"]):
                        actual_overlaps.append({"calls": [left["call_id"], right["call_id"]], "actions": [a["id"], b["id"]],
                                                "kinds": [a["kind"], b["kind"]], "overlap_us": overlap, "event_statuses": ["completed", "completed"]})
    run["executed_independent_overlap"] = actual_overlaps
    evidence = {"pin": json.loads((ROOT/"third_party/enola/pin.json").read_text(encoding="utf-8")),
                "observations": library.observations, "binding_observations": library.binding_observations}
    reports = {s["strategy_id"]: validate_strategy(s, device, enola_evidence=evidence) for s in library.strategies.values()}
    run_report = validate_strategy_run(run, device, enola_evidence=evidence)
    files = [save(output/"device.json", device), save(output/"run.json.gz", run, True),
             save(output/"scenario.json", scenario), save(output/"enola-observation.json.gz", evidence, True),
             save(output/"strategy-reports.json", reports), save(output/"run-report.json", run_report)]
    sample_strategy = next(s for s in library.strategies.values() if s["body"]["strategy_contract"]["operation"]["name"] == "syndrome_round")
    files.append(save(output/"syndrome-strategy.json", sample_strategy))
    transfer = next(a for a in run["atom_program"]["actions"] if a["kind"] == "pickup" and len(a["atoms"]) == 17)
    invalid = deepcopy(transfer); invalid["payload"]["bindings"].pop()
    files.append(save(output/"interface-examples.json", {"scope": "Extracts from actual complete run, not independently executable plans",
        "valid_binding": run["instances"][0]["binding"], "valid_group_pickup": transfer,
        "valid_shared_cz": next(a for a in run["atom_program"]["actions"] if a["kind"] == "gate" and len(a["payload"].get("pairs", [])) == 9),
        "rejected_incomplete_bindings": invalid, "rejection_reason": "bindings no longer covers every action atom; no capture masking permitted"}))
    source_after = sources()
    summary = {"task": "T404", "fixture": False, "backend_used": "enola_function_kernel", "enola_commit": evidence["pin"]["commit"],
               "python": sys.version, "executable": sys.executable, "wall_seconds": time.perf_counter()-began,
               "strategy_count": len(library.strategies), "library_stats": library.stats,
               "fake_value": args.fake_value, "actual_completed_action_overlap": actual_overlaps,
               "strategy_reports_passed": all(r["passed"] for r in reports.values()), "run_report_passed": run_report["passed"],
               "run_failures": run_report["failures"][:20], "run_unverified": run_report["unverified"],
               "source_hashes_before": source_before, "source_hashes_after": source_after,
               "source_unchanged": source_before == source_after,
               "files": files, "user_visual_acceptance": "pending", "R0_integration_acceptance": "pending"}
    save(output/"summary.json", summary)
    print(json.dumps({k: summary[k] for k in ("wall_seconds", "strategy_count", "library_stats", "strategy_reports_passed", "run_report_passed", "run_failures", "run_unverified")}, ensure_ascii=False))
    if not run_report["passed"] or source_before != source_after or not actual_overlaps:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
