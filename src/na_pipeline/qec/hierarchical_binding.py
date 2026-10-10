"""Finite carrier requirements and lazy LogicalDAG -> PhysicalDAG binding.

Only immutable circuit specifications are shared. No result, frame, token,
epoch ownership, geometry or runtime receipt is created by these functions.
"""

from collections import Counter
from copy import deepcopy
from hashlib import sha256

from .factory import build_factory15to1_protocol
from .factory_primitives import FACTORY_BLOCKS
from .physical_dag import (PhysicalDAGError, _hash, build_patch_operation_spec,
                           validate_physical_dag)
from .surface17 import FORMALS

BUNDLE_SCHEMA = "PhysicalDAGBundle/0.1.0"


def physical_resource_requirements(logical_dag, *, factory_id="factory0"):
    """Published slot proposal for R5 allocation and R4 whole-world placement.

    The single Y patch and probe are shared by S/SDG and factory protocols;
    holding the same exclusive mutex prevents concurrent reuse. R5 owns leases.
    """
    import re
    if not isinstance(factory_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]+", factory_id):
        raise PhysicalDAGError("FACTORY_ID", "factory identity must be namespace-safe")
    patches = {}
    for patch in logical_dag["patches"]:
        patches[patch["patch_id"]] = {"aod_group": "data", "basis": patch["initial_state"]["logical_basis"],
                                      "value": patch["initial_state"]["logical_value"], "role": "algorithm"}
    factory_patches = {b: f"{factory_id}:{b}" for b in FACTORY_BLOCKS}
    probe = f"{factory_id}:join_probe"
    if set(patches) & (set(factory_patches.values()) | {probe}):
        raise PhysicalDAGError("RESOURCE_SLOT_ALIAS", "algorithm and factory identities overlap")
    for block, ident in factory_patches.items():
        patches[ident] = {"aod_group": "magic", "basis": "Z", "value": 0,
                          "role": "factory", "factory_role": block,
                          "initial_state_is_magic_resource": False}
    qubits = [f"{p}/{q}" for p in patches for q in FORMALS] + [probe]
    mutex = f"{factory_id}:protocol_mutex"
    return {"schema_version": "PhysicalResourceRequirements/0.1.0", "owner": "R3", "lifecycle_owner": "R5",
            "kb_revision": "kb-0006", "entry_mode": "preinitialized", "factory_id": factory_id,
            "patches": patches, "factory_slots": factory_patches,
            "nonpatch_atoms": [{"physical_qubit_id": probe, "slot_id": probe, "aod_group": "magic",
                                "role": "probe", "qubit_role": "syndrome", "basis": "Z", "value": 0,
                                "geometry_requirement": "R1_declared_site_in_R4_complete_world_placement"}],
            "physical_qubit_ids": qubits, "physical_qubit_count": len(qubits),
            "counts": {"algorithm_patches": len(logical_dag["patches"]), "factory_patches": 7,
                       "factory_atoms": 120, "nonpatch_atoms": 1,
                       "data_aod_atoms": 17 * len(logical_dag["patches"]), "magic_aod_atoms": 120},
            "initial_ready_magic_tokens": [], "startup_actions": [], "dynamic_carrier_creation_allowed": False,
            "shared_phase_scratch": {"phase_aux": factory_patches["Y"], "bridge": probe,
                                     "exclusive_mutex": mutex, "additional_carriers": 0},
            "lease_rules": {
                "S_SDG": {"exclusive": [mutex, factory_patches["Y"], probe, "operand:block"],
                          "hold_until": "all_physical_operations_and_results_committed",
                          "release_state": "Y_and_probe_reset_by_real_operations"},
                "T_TDG": {"exclusive": [mutex, *factory_patches.values(), probe, "operand:block"],
                          "hold_until": "consumed_or_rejected_after_physical_cleanup",
                          "ready_token_carrier": factory_patches["W4"], "consume_once": True,
                          "new_epoch_requires_cleanup": True}},
            "limitations": ["slot_proposal_not_runtime_allocation", "R4_positions_unassigned",
                            "R5_must_lease_actual_carriers", "no_ready_resource_at_entry",
                            "all_inactive_algorithm_patches_remain_in_physical_world"]}


def build_physical_dag_bundle(logical_dag, *, factory_id="factory0"):
    # Consume the public producer validator rather than private builder state.
    from na_pipeline.frontend import validate_logical_dag
    errors = validate_logical_dag(logical_dag)
    if errors:
        raise PhysicalDAGError("LOGICAL_DAG_INVALID", "R2 validation failed", details={"errors": errors})
    if logical_dag.get("entry_mode") != "preinitialized":
        raise PhysicalDAGError("ENTRY_MODE", "T304 requires a preinitialized logical input")
    library, instances, kinds = {}, {}, Counter()
    for node in logical_dag["nodes"]:
        key = node["operation"] + ":" + _hash(node["params"])[:16]
        if key not in library:
            spec = build_patch_operation_spec(node["operation"], params=node["params"])
            if spec["physical_dag"]:
                validate_physical_dag(spec["physical_dag"])
            library[key] = spec
        spec = library[key]
        if set(node["patch_operands"]) != set(spec["formal_operands"]):
            raise PhysicalDAGError("OPERAND_ROLE_MISMATCH", "logical operand roles differ from physical semantics", node_id=node["id"])
        if len(node["writes"]) != len(spec["public_results"]):
            raise PhysicalDAGError("RESULT_SLOT_MISMATCH", "logical writes differ from public result slots", node_id=node["id"])
        if node["operation"] == "CLASSICAL_POSTPROCESS" and node["reads"] != spec["params"]["bits_msb_first"]:
            raise PhysicalDAGError("POSTPROCESS_READ_ORDER", "phase input order is not MSB first", node_id=node["id"])
        if node.get("semantic_version") != "1.0.0":
            raise PhysicalDAGError("PATCH_SEMANTIC_VERSION", "unknown logical operation semantics", node_id=node["id"])
        public = dict(zip(spec["public_results"], node["writes"], strict=True))
        instances[node["id"]] = {"logical_node_id": node["id"], "spec_ref": key,
                                 "spec_hash": spec["spec_hash"], "patch_bindings": deepcopy(node["patch_operands"]),
                                 "public_result_bindings": public, "implementation_kind": spec["implementation_kind"],
                                 "logical_node": deepcopy(node)}
        kinds[spec["implementation_kind"]] += 1
    resources = physical_resource_requirements(logical_dag, factory_id=factory_id)
    result = {"schema_version": BUNDLE_SCHEMA, "artifact_id": logical_dag["artifact_id"] + "-physical-bundle",
              "provenance": {"owner": "R3", "task_id": "T304", "kb_revision": "kb-0006", "planning_revision": "plan-0008", "fixture": False},
              "entry_mode": "preinitialized", "execution_kind": "compile_plan", "quantum_state_simulated": False,
              "hardware_executed": False, "loss_enabled": False,
              "logical_dag": deepcopy(logical_dag), "logical_dag_sha256": _hash(logical_dag),
              "specifications": library, "instances": instances, "edges": deepcopy(logical_dag["edges"]),
              "resource_requirements": resources,
              "coverage": {"logical_nodes": len(logical_dag["nodes"]), "bound_nodes": len(instances),
                           "implementation_kinds": dict(kinds), "unbound_nodes": [],
                           "static_source_coverage": deepcopy(logical_dag["source_coverage"]),
                           "actual_executed_nodes": None, "factory_execution_verified": False},
              "capabilities_required": ["PhysicalDAG/0.1.0", "external_graph_guard", "grouped_ancilla_readout",
                                        "classical_xor_all_zero", "classical_postprocess_phase", "committed_atom_continuation",
                                        "finite_scratch_leases", "factory_same_carrier_single_use_token"],
              "qualification": {"scope": "complete_logical_source_binding_and_shared_circuit_library",
                                "physical_compilation": "pending", "independent_R6": "pending", "user_visual": "pending"}}
    result["bundle_hash"] = _hash(result)
    return result


def _instance(bundle, node_id):
    if bundle.get("schema_version") != BUNDLE_SCHEMA or node_id not in bundle["instances"]:
        raise PhysicalDAGError("PHYSICAL_INSTANCE", "unknown bundle version or logical node", node_id=node_id)
    record = bundle["instances"][node_id]
    spec = bundle["specifications"][record["spec_ref"]]
    if record["spec_hash"] != spec["spec_hash"] or _hash({k: v for k, v in spec.items() if k != "spec_hash"}) != spec["spec_hash"]:
        raise PhysicalDAGError("PHYSICAL_SPEC_MUTATED", "shared circuit specification changed", node_id=node_id)
    return record, spec


def materialize_physical_node(bundle, node_id, *, epoch=0):
    """Bind static operations. Adaptive T requires materialize_factory_protocol.

    Does not authorize execution: graph guard, operands and resource leases
    are still checked by R5 against its current committed world.
    """
    record, spec = _instance(bundle, node_id)
    if type(epoch) is not int or epoch < 0:
        raise PhysicalDAGError("PHYSICAL_EPOCH", "epoch must be a nonnegative integer", node_id=node_id)
    if spec["implementation_kind"] == "adaptive_factory_protocol":
        raise PhysicalDAGError("ADAPTIVE_FACTORY_REQUIRED", "materialize the real factory protocol; no physical T substitute", node_id=node_id)
    node, dag = record["logical_node"], deepcopy(spec["physical_dag"])
    prefix = f"{node_id}/epoch{epoch}/"
    roles = deepcopy(record["patch_bindings"])
    resource = bundle["resource_requirements"]
    if spec["operation"] in {"S", "SDG"}:
        roles.update(phase_aux=resource["shared_phase_scratch"]["phase_aux"], bridge=resource["shared_phase_scratch"]["bridge"])
    qmap = {q["id"]: roles[q["block_id"]] if q["block_id"] == "bridge" else f"{roles[q['block_id']]}/{q['local_id']}" for q in dag["qubits"]}
    if len(set(qmap.values())) != len(qmap) or not set(qmap.values()) <= set(resource["physical_qubit_ids"]):
        raise PhysicalDAGError("PHYSICAL_RESOURCE_BINDING", "physical instance aliases or creates undeclared carriers", node_id=node_id)
    opmap = {op["id"]: prefix + op["id"] for op in dag["nodes"]}
    rmap = {bit: prefix + bit for bit in dag["result_producers"]}
    for slot, bit in spec["public_results"].items():
        rmap[bit] = record["public_result_bindings"][slot]
    # External reads retain the upstream result identity; only local writes are namespaced.
    def remap(value):
        if isinstance(value, str):
            return qmap.get(value, opmap.get(value, rmap.get(value, value)))
        if isinstance(value, list):
            return [remap(v) for v in value]
        if isinstance(value, dict):
            return {k: remap(v) for k, v in value.items()}
        return value
    for q in dag["qubits"]:
        q["id"] = qmap[q["id"]]
        q["block_id"] = roles[q["block_id"]]
    source_map = {}
    for op in dag["nodes"]:
        old = op["id"]
        for field in ("id", "qubits", "reads", "writes", "after", "condition"):
            op[field] = remap(op[field])
        op["source_ids"] = list(dict.fromkeys(op["source_ids"] + node["source_ids"] + [node_id]))
        source_map[op["id"]] = {"logical_node_id": node_id, "formal_physical_op_id": old,
                               "source_ids": deepcopy(op["source_ids"])}
    for field in ("edges", "roots", "terminals", "groups", "external_reads", "readout_services"):
        dag[field] = remap(dag[field])
    for group in dag["groups"]:
        group["group_id"] = prefix + group["group_id"]
        group["formal_block"] = roles[group["formal_block"]]
    for service in dag["readout_services"]:
        service["block_id"] = roles[service["block_id"]]
        if service["group_id"]:
            service["group_id"] = prefix + service["group_id"]
    dag["result_producers"] = {rmap[bit]: opmap[writer] for bit, writer in dag["result_producers"].items()}
    dag["result_types"] = {rmap[bit]: kind for bit, kind in dag["result_types"].items()}
    dag["source_map"] = source_map
    dag["execution_guard"] = deepcopy(node["condition"])
    dag["external_reads"] = list(dict.fromkeys(dag["external_reads"] + node["reads"]))
    dag["artifact_id"] = bundle["artifact_id"] + ":" + sha256(prefix.encode()).hexdigest()[:24]
    dag["logical_binding"] = {"logical_node_id": node_id, "epoch": epoch, "patch_bindings": roles,
                              "logical_source": deepcopy(node), "spec_hash": spec["spec_hash"],
                              "public_result_bindings": deepcopy(record["public_result_bindings"])}
    dag["entry_requirements"] = deepcopy(spec["entry_requirements"])
    dag["entry_requirements"].update(same_carriers_as_committed_snapshot=True, graph_guard_must_be_ready=True)
    dag["required_leases"] = [*node["patch_operands"].values()]
    if spec["operation"] in {"S", "SDG"}:
        dag["required_leases"] += [resource["shared_phase_scratch"]["exclusive_mutex"], roles["phase_aux"], roles["bridge"]]
    dag["world_resource_ref"] = {"schema_version": resource["schema_version"], "sha256": _hash(resource),
                                 "physical_qubit_count": resource["physical_qubit_count"], "inactive_carriers_remain_present": True}
    validate_physical_dag(dag)
    return dag


def materialize_factory_protocol(bundle, node_id, *, epoch):
    """Concrete complete adaptive recipe. Does not mint/accept/reserve a token."""
    record, spec = _instance(bundle, node_id)
    if spec["implementation_kind"] != "adaptive_factory_protocol":
        raise PhysicalDAGError("NOT_FACTORY_NODE", "logical node is not T/TDG", node_id=node_id)
    node, resource = record["logical_node"], bundle["resource_requirements"]
    request = node["resource_requests"]
    if len(request) != 1 or request[0]["target_patch_id"] != node["patch_operands"]["block"]:
        raise PhysicalDAGError("FACTORY_REQUEST_BINDING", "request must bind this live-data patch", node_id=node_id)
    safe_request = "logical-" + sha256(request[0]["request_id"].encode()).hexdigest()
    protocol = build_factory15to1_protocol(data_block_id=node["patch_operands"]["block"], request_id=safe_request,
                                          gate=node["operation"], epoch=epoch, factory_id=resource["factory_id"])
    if not {q["id"] for q in protocol["qubits"]} <= set(resource["physical_qubit_ids"]):
        raise PhysicalDAGError("FACTORY_RESOURCE_BINDING", "factory protocol requests undeclared carriers", node_id=node_id)
    protocol["logical_binding"] = {"logical_node_id": node_id, "logical_request_id": request[0]["request_id"],
                                   "logical_source": deepcopy(node), "spec_hash": spec["spec_hash"]}
    protocol["execution_guard"] = deepcopy(node["condition"])
    protocol["required_leases"] = [resource["shared_phase_scratch"]["exclusive_mutex"], *resource["factory_slots"].values(),
                                   resource["nonpatch_atoms"][0]["physical_qubit_id"], node["patch_operands"]["block"]]
    protocol["world_resource_ref"] = {"sha256": _hash(resource), "physical_qubit_count": resource["physical_qubit_count"],
                                      "protocol_participant_count": len(protocol["qubits"]), "inactive_carriers_remain_present": True}
    protocol["entry_requirements"].update(initial_ready_magic_inventory=0, graph_guard_must_be_ready=True,
                                         exclusive_pool_lease_required=True, complete_world_snapshot_required=True)
    return protocol
