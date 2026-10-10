"""R3 source-boundary closure and public R4 interface probe, not T000 acceptance."""

from hashlib import sha256
import io
import json
from pathlib import Path
import platform
import sys
import time
import unittest

from na_pipeline.qec import build_logical_primitive

ROOT = Path(__file__).resolve().parents[2]


def hashes():
    files = sorted((ROOT / "src/na_pipeline/qec").glob("*.py"))
    files += sorted((ROOT / "src/na_pipeline/backend").glob("*.py"))
    files += sorted((ROOT / "src/na_pipeline/device").glob("*.py"))
    files += sorted((ROOT / "tests/qec").glob("*.py"))
    files += [Path(__file__).resolve()]
    return {str(p.relative_to(ROOT)).replace("\\", "/"): sha256(p.read_bytes()).hexdigest() for p in files}


def write_json(path, value):
    data = (json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha256(data).hexdigest(), "bytes": len(data)}


def main():
    started = time.perf_counter()
    source_before = hashes()
    evidence = ROOT / "knowledge/roles/R3/evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    log = io.StringIO()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(unittest.defaultTestLoader.discover(str(ROOT / "tests/qec")))
    (evidence / "t802-source-tests.txt").write_bytes(log.getvalue().encode("utf-8"))
    references = ["knowledge/roles/R0/t802-integration-followup.md", "knowledge/roles/R8/enola-adaptation-review.md",
                  "knowledge/roles/R8/interface.md", "knowledge/roles/R8/facts.md", "knowledge/roles/R8/enola-review-cases.json"]
    reference_hashes = {path: sha256((ROOT / path).read_bytes()).hexdigest() for path in references}
    cases = json.loads((ROOT / references[-1]).read_bytes())
    from na_pipeline.backend import StrategyLibrary
    from na_pipeline.device import grouped_device
    library = StrategyLibrary(grouped_device())
    probes, strategies = [], {}
    for name, operation, params in (("prepare_zero", "prepare", {"state": "0"}),
                                    ("prepare_plus", "prepare", {"state": "+"}),
                                    ("syndrome", "syndrome_round", {}), ("cx", "logical_cx", {})):
        at = time.perf_counter()
        try:
            strategy = library.get_or_compile(build_logical_primitive(operation, params=params))
            strategies[name] = strategy
            artifact = write_json(ROOT / "examples/physical/t802_source_probe" / (name + ".strategy.json"), strategy)
            probes.append({"name": name, "status": "compiled_interface_probe", "artifact": artifact,
                           "strategy_hash": strategy["strategy_hash"], "backend_used": strategy["body"]["backend_used"],
                           "atom_actions": len(strategy["body"]["atom_program"]["actions"]),
                           "wall_seconds": time.perf_counter() - at})
        except Exception as exc:
            probes.append({"name": name, "status": "failed", "type": type(exc).__name__, "code": getattr(exc, "code", None),
                           "message": str(exc), "details": getattr(exc, "details", None), "wall_seconds": time.perf_counter() - at})
    warm = {"performed": False}
    if "syndrome" in strategies:
        before = library.stats
        repeated = library.get_or_compile(build_logical_primitive("syndrome_round"))
        after = library.stats
        warm = {"performed": True, "same_strategy_hash": repeated["strategy_hash"] == strategies["syndrome"]["strategy_hash"],
                "counter_delta": {key: after[key] - before[key] for key in before},
                "counter_source": "R4_public_library_stats", "independently_profiled": False}
    source_after = hashes()
    drift = source_before != source_after
    report = {"schema_version": "R3T802SourceClosure/0.1", "kb_revision": "kb-0005", "planning_revision": "plan-0007",
              "read_versions": {"R0-T802-HANDOFF-001": "0.1.0", "R8-ENOLA-REVIEW-001": "0.2.0",
                                "R8-IF-REVIEW-001": "0.2.0", "R8-FACTS-001": "0.10.0", "IF-STRATEGY-001": "0.1.0"},
              "scope": "R3_source_guards_derived_fixtures_and_R4_interface_probe",
              "tests": {"count": result.testsRun, "passed": result.wasSuccessful(), "failures": len(result.failures), "errors": len(result.errors)},
              "case_scope": {"E01_K01": "source_projection_guard", "E07_K05": "declared_17_members_and_R1_local_fixture",
                             "K04": "source_H_dependency_and_R1_local_readiness_fixture"},
              "R8_original_cases_executed": cases["provenance"]["executed"],
              "reference_sha256": reference_hashes, "source_before": source_before, "source_after": source_after,
              "source_changed_during_run": drift, "interface_probes": probes, "warm_syndrome_probe": warm,
              "library_stats": library.stats, "environment": {"python": sys.version, "executable": sys.executable, "host": platform.node()},
              "budget": {"workers": 1, "scope": "four_bounded_17_or_34_qubit_primitives", "full_shor_or_factory": False},
              "wall_seconds": time.perf_counter() - started,
              "quantum_state_simulated": False, "hardware_executed": False, "runtime_executed": False,
              "independent_strategy_qualification": "pending", "user_visual_acceptance": "pending",
              "T000_complete": False,
              "unverified": ["full_Enola_layout_integration", "independent_geometry_timing_and_group_validation",
                             "bound_runtime_instances", "CX_then_maintenance_in_shared_world", "user_visual_acceptance"]}
    write_json(evidence / "t802-source-closure.json", report)
    print(json.dumps({"tests": report["tests"], "source_drift": drift,
                      "probes": [{k: v for k, v in p.items() if k != "artifact"} for p in probes],
                      "warm": warm, "R8_cases_executed": report["R8_original_cases_executed"],
                      "T000_complete": False, "wall_seconds": report["wall_seconds"]}, ensure_ascii=False, indent=2))
    return 0 if result.wasSuccessful() and not drift else 1


if __name__ == "__main__":
    raise SystemExit(main())
