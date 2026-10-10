"""T204 actual producer probes; --full-bundle is intended for a budgeted server job.

Default probes finite operation specifications and resource declarations only.
It does not compile a full physical graph or execute any factory/quantum state.
"""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import sys
import time

from na_pipeline.frontend import validate_logical_dag, logical_dag_requirements
from na_pipeline.qec import (build_patch_operation_spec, physical_resource_requirements,
                             build_physical_dag_bundle, materialize_physical_node, validate_physical_dag)


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def write(path, data):
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logical", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--full-bundle", action="store_true")
    parser.add_argument("--small-logical", type=Path)
    parser.add_argument("--placement-run", type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    dag = json.loads(args.logical.read_bytes())
    errors = validate_logical_dag(dag)
    if errors:
        raise SystemExit("INVALID_LOGICAL_INPUT: " + str(errors))
    requirements = logical_dag_requirements(dag)
    specs, failures, checks = {}, [], []
    for requirement in requirements["requirements"]:
        for params in requirement["params_variants"]:
            operation = requirement["operation"]
            try:
                spec = build_patch_operation_spec(operation, params=params)
                if spec["schema_version"] != "PatchOperationSpec/0.1.0" or spec["operation"] != operation or spec["semantic_version"] != "1.0.0" or spec["params"] != params:
                    raise ValueError("SPEC_SEMANTIC_MISMATCH")
                if spec["formal_operands"] != requirement["operand_roles"]:
                    raise ValueError("SPEC_OPERAND_DIRECTION_MISMATCH")
                specs[spec["spec_hash"]] = spec
                checks.append({"operation": operation, "params": params, "node_count": requirement["node_count"],
                               "spec_hash": spec["spec_hash"], "implementation_kind": spec["implementation_kind"],
                               "producer_qualification": spec["qualification"], "field_match": True})
            except (ValueError, KeyError, TypeError) as exc:
                failures.append({"operation": operation, "params": params, "error": str(exc)})
    inventory = physical_resource_requirements(dag)
    write(args.out / "operation_specs.json", specs)
    write(args.out / "resource_requirements.json", inventory)
    available = {row["operation"] for row in checks}
    resolved = logical_dag_requirements(dag, available_operations=available)
    write(args.out / "requirements_resolved.json", resolved)
    small_probe = None
    if args.small_logical:
        small = json.loads(args.small_logical.read_bytes())
        bundle = build_physical_dag_bundle(small)
        probes = []
        for node in small["nodes"]:
            physical = materialize_physical_node(bundle, node["id"])
            validation = validate_physical_dag(physical)
            probes.append({"logical_node_id": node["id"], "operation": node["operation"],
                           "physical_schema": physical["schema_version"], "physical_node_count": len(physical["nodes"]),
                           "physical_dag_sha256": digest(physical), "producer_validation": validation})
            if not isinstance(validation, dict) or validation.get("passed") is not True:
                failures.append({"logical_node_id": node["id"], "producer_validation": validation})
        small_probe = {"logical_dag_sha256": digest(small), "bundle_hash": bundle["bundle_hash"], "instances": probes,
                       "scope": "actual_small_R3_materialization_not_routing_or_runtime"}
        write(args.out / "small_physical_binding_probe.json", small_probe)
    full_bundle = None
    if args.full_bundle:
        full_bundle = build_physical_dag_bundle(dag)
        write(args.out / "full_physical_dag_bundle.json", full_bundle)
    placement_probe = None
    if args.placement_run:
        upstream_dag = json.loads((args.placement_run / "logical_dag.json").read_bytes())
        placement = json.loads((args.placement_run / "patch_placement.json").read_bytes())
        initial = json.loads((args.placement_run / "initial_state.json").read_bytes())
        observed_errors = validate_logical_dag(upstream_dag)
        placement_probe = {"source_directory": str(args.placement_run), "logical_dag_sha256": digest(upstream_dag),
                           "current_frontend_validation_errors": observed_errors,
                           "placement_artifact_id": placement["artifact_id"], "placement_sha256": digest(placement),
                           "actual_enola_record": placement.get("enola"), "cost": placement.get("cost"),
                           "initial_atom_count": len(initial["atoms"]), "startup_actions": initial.get("startup_actions"),
                           "scope": "read_actual_R7_server_artifacts_no_new_placement_run_or_qualification"}
        write(args.out / "server_placement_read_probe.json", placement_probe)
        if observed_errors:
            failures.append({"producer": "R7 frozen graph", "errors": observed_errors})
    manifest_files = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(args.out.glob("*.json")) if p.name != "receipt.json"}
    report = {"schema_version": "R2DAGProducerProbe/0.1.0", "artifact_id": "T204-actual-producer-probe",
              "provenance": {"owner": "R2", "task_id": "T204", "kb_revision": "kb-0006", "fixture": False},
              "execution_kind": "compile_plan", "quantum_state_simulated": False, "hardware_executed": False, "loss_enabled": False,
              "logical_dag_sha256": digest(dag), "host": platform.node(), "python_executable": sys.executable,
              "probe_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "logical_input_byte_sha256": hashlib.sha256(args.logical.read_bytes()).hexdigest(),
              "elapsed_seconds": time.perf_counter() - started, "specifications": checks,
              "resource_counts": inventory["counts"], "failures": failures, "interface_probe_passed": not failures,
              "small_binding_probe_performed": small_probe is not None, "server_placement_read_performed": placement_probe is not None,
              "full_bundle_built": full_bundle is not None,
              "full_bundle_coverage": None if full_bundle is None else full_bundle["coverage"],
              "new_placement_or_routing_executed": False, "runtime_executed": False,
              "full_shor_completed": False,
              "files_sha256": manifest_files,
              "unverified": ["whole_205_carrier_world_placement_and_binding", "adaptive_factory_T_consumption",
                             "all_eight_round_physical_fake_run", "R6_independent_checks", "user_visual_acceptance"]}
    write(args.out / "receipt.json", report)
    print(json.dumps({"specifications": len(checks), "failures": failures, "full_bundle_built": full_bundle is not None,
                      "small_instances": None if small_probe is None else len(small_probe["instances"]), "elapsed_seconds": report["elapsed_seconds"]}))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
