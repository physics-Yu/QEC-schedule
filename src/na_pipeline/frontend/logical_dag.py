"""R2 patch-level semantic DAG. Placement and scheduling belong to R4/R5.

The preinitialized boundary is explicit and source covered. No quantum state,
fake results, timings, atom positions, or magic inventory are manufactured here.
"""

from collections import Counter, defaultdict, deque
from copy import deepcopy
import hashlib
import json
import math

from .program import FrontendError, build_shor15, iter_logical_ops, require_clifford_t

SCHEMA = "LogicalDAG/0.1.0"
VERSION = "0.1.0"
CODE = {"code": "rotated_surface", "distance": 3,
        "convention": "surface17-row-major-x-vertical/1", "orientation": "x_vertical_z_horizontal"}
ARITIES = {**{name: ["block"] for name in ("SE", "H", "X", "Z", "S", "SDG", "T", "TDG", "MEASURE", "RESET")},
           "CX": ["control", "target"], "CZ": ["left", "right"], "CLASSICAL_POSTPROCESS": []}
FLAGS = {"execution_kind": "compile_plan", "quantum_state_simulated": False,
         "hardware_executed": False, "loss_enabled": False}


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _dependency_record(earlier, later, annotation=None, *, entry_dependency=False):
    """Classify this generator's mechanical after edge, never arbitrary protocols.

    Standard gates/reset/measurement instruments commute on disjoint quantum
    tensor factors when their classical read/write effects do not conflict.
    Hardware resource conflicts are separately resolved by the R5 scheduler.
    """
    shared = sorted(set(earlier["qubits"]) & set(later["qubits"]))
    classical = sorted((set(earlier["writes"]) & (set(later["reads"]) | set(later["writes"])))
                       | (set(earlier["reads"]) & set(later["writes"])))
    if annotation is not None:
        if not isinstance(annotation, dict) or annotation.get("kind") != "protocol" or not annotation.get("reason"):
            raise FrontendError("UNSUPPORTED_TYPED_SOURCE_DEPENDENCY")
        disposition = "preserved_explicit_protocol"
    elif entry_dependency:
        disposition = "covered_by_preinitialized_entry"
    elif shared:
        disposition = "covered_by_patch_order"
    elif classical:
        disposition = "preserved_classical_causality"
    elif earlier["kind"] in ("gate", "measure", "reset") and later["kind"] in ("gate", "measure", "reset"):
        disposition = "relaxed_generated_serialization"
    else:
        raise FrontendError("UNPROVEN_SOURCE_EDGE_RELAXATION")
    return {"source_operation_id": earlier["id"], "target_operation_id": later["id"],
            "disposition": disposition, "shared_patches": shared, "classical_conflicts": classical,
            "explicit_annotation": deepcopy(annotation),
            "proof_rule": "known_generator_order_plus_disjoint_instrument_commutation/1"}


def _patch(patch_id, role="algorithm"):
    return {"patch_id": patch_id, "logical_id": patch_id, "role": role, "code_profile": deepcopy(CODE),
            "initial_state": {"logical_basis": "Z", "logical_value": 0,
                              "encoding_status": "assumed_encoded_surface17",
                              "data_stabilizers": "+1", "ancilla_basis": "Z", "ancilla_value": 0,
                              "evidence_kind": "declared_precondition_not_simulated"},
            "physical_binding_ref": None, "atom_binding_ref": None,
            "local_geometry_ref": "R1/R3-patch-definition-required",
            "initial_placement": {"owner": "R4", "status": "unbound", "anchor_um": None},
            "runtime_binding_required": True}


def _node(ident, operation, patches, *, params=None, reads=None, writes=None, condition=None, source_ids=None):
    return {"id": ident, "operation": operation, "semantic_version": "1.0.0",
            "patch_operands": dict(zip(ARITIES[operation], patches)), "params": params or {},
            "reads": reads or [], "writes": writes or [], "condition": deepcopy(condition),
            "source_ids": source_ids or [ident], "resource_requests": [],
            "implementation_status": "requires_patch_operation_spec_and_qualification"}


class _Builder:
    def __init__(self, patches, source=None):
        self.dag = {"schema_version": SCHEMA, "artifact_id": "pending", "producer_version": "na_pipeline.frontend.logical_dag/" + VERSION,
                    "provenance": {"owner": "R2", "task_id": "T204", "kb_revision": "kb-0006", "plan_revision": "plan-0008",
                                   "interface_ref": "IF-HIERARCHICAL-DAG-001/0.1.0", "fixture": False},
                    **FLAGS, "entry_mode": "preinitialized", "patches": [_patch(p) for p in patches],
                    "entry": {"startup_transport_required": False, "initialization_zone": None,
                              "source_preconditions": [], "assumptions_are_not_hardware_receipts": True},
                    "nodes": [], "edges": [], "result_types": {}, "source_coverage": {},
                    "source_program_ref": None, "branch_global_phases": [],
                    "resource_policy": {"magic_initial_ready_inventory": 0, "magic_factory_count": 1,
                                        "max_ready_magic_outputs": 1, "protocol": "single-level-15-to-1",
                                        "supply_status": "requires_R3_factory_and_R5_lifecycle"},
                    "dependency_policy": "typed_semantic_dependencies_with_audited_serialization_relaxation",
                    "source_dependency_audit": [],
                    "engineering_validation": "pending_R6", "user_visual_acceptance": "pending"}
        if source is not None:
            self.dag["source_program"] = deepcopy(source)
            self.dag["source_program_ref"] = {"artifact_id": source["artifact_id"], "schema_version": source["schema_version"],
                                                "canonical_sha256": _hash(source)}
        self.last_patch, self.source_nodes, self.producers = {}, {}, {}
        self.source_ops = {} if source is None else {op["id"]: op for op in iter_logical_ops(source)}
        self.source_annotations = {} if source is None else source.get("dependency_annotations", {})
        self.edge_keys = set()

    def edge(self, source, target, kind, **details):
        key = (source, target, kind, _hash(details))
        if key not in self.edge_keys:
            self.edge_keys.add(key)
            self.dag["edges"].append({"source": source, "target": target, "kind": kind, **details})

    def add(self, node, *, source_after=(), protocol_after=()):
        ident = node["id"]
        for dep in source_after:
            mapped = self.source_nodes.get(dep)
            if mapped is None and dep not in self.dag["source_coverage"]:
                raise FrontendError("MISSING_SOURCE_PREDECESSOR: " + dep)
            source_op = node["source_operation"]
            annotation = self.source_annotations.get(source_op["id"], {}).get(dep)
            record = _dependency_record(self.source_ops[dep], source_op, annotation, entry_dependency=mapped is None)
            self.dag["source_dependency_audit"].append(record)
            if record["disposition"] == "preserved_explicit_protocol" and mapped is not None:
                self.edge(mapped, ident, "protocol", reason=annotation["reason"], source_dependency=dep)
            elif record["disposition"] == "preserved_classical_causality":
                # The exact producer-ready edge is added for reads below; this
                # explicit edge also retains any declared anti/write dependence.
                self.edge(mapped, ident, "protocol", reason="source_classical_causality", source_dependency=dep)
        for dep in protocol_after:
            self.edge(dep, ident, "protocol", reason="declared_maintenance_boundary")
        for patch in node["patch_operands"].values():
            if patch in self.last_patch:
                self.edge(self.last_patch[patch], ident, "quantum", patch_id=patch)
            self.last_patch[patch] = ident
        for bit in node["reads"]:
            if bit not in self.producers:
                raise FrontendError("MISSING_RESULT_PRODUCER: " + bit)
            self.edge(self.producers[bit], ident, "classical_ready", result_id=bit)
        for bit in node["writes"]:
            if bit in self.producers:
                raise FrontendError("DUPLICATE_RESULT: " + bit)
            self.producers[bit] = ident
            self.dag["result_types"][bit] = "postprocess_record" if node["operation"] == "CLASSICAL_POSTPROCESS" else "bit"
        self.dag["nodes"].append(node)
        return ident

    def se(self, patch, phase, *, after=()):
        ident = f"maintenance/{phase}/{patch}"
        slots = [f"{kind}{i}" for kind in ("x", "z") for i in range(4)]
        node = _node(ident, "SE", [patch], writes=[ident + "/" + q for q in slots],
                     source_ids=["maintenance-policy:phase-round-boundaries/1", ident])
        node["groups"] = [{"purpose": "maintenance_readout", "patch_id": patch,
                           "group_id": ident + "/readout", "members": [
                               {"role": q, "check_type": q[0].upper(), "measurement_basis": "Z",
                                "result_id": ident + "/" + q} for q in slots],
                           "physical_binding_status": "requires_R3_physical_dependencies_and_R4_routing"}]
        node["data_effect"] = "preserve_live_data_no_data_reset"
        return self.add(node, protocol_after=after)

    def finish(self):
        self.dag["artifact_id"] = "logical-dag-" + _hash({k: self.dag[k] for k in ("patches", "nodes", "edges", "entry")})[:20]
        self.dag["input_hashes"] = {"logical_source": (self.dag["source_program_ref"] or {}).get("canonical_sha256"),
                                    "semantic_graph": _hash({k: self.dag[k] for k in ("patches", "nodes", "edges", "entry")})}
        self.dag["operation_counts"] = dict(sorted(Counter(n["operation"] for n in self.dag["nodes"]).items()))
        self.dag["patch_interaction_graph"] = patch_interaction_graph(self.dag)
        return self.dag


def build_logical_dag(logical_program: dict | None = None) -> dict:
    """Complete eight-round Shor DAG; startup reset sources become preconditions.

    The existing algorithm is retained verbatim for coverage and error auditing.
    Five pre-initialization resets are covered by the declared encoded-zero entry.
    Every other operation remains an executable requirement, including all T words.
    """
    source = build_shor15() if logical_program is None else deepcopy(logical_program)
    if source.get("capability_profile") != "shor15-semiclassical-qpe8/full-permutation-v1":
        raise FrontendError("UNSUPPORTED_DAG_SOURCE_PROFILE")
    require_clifford_t(source)
    # Only this exact generator's mechanical serialization is eligible for
    # relaxation. A caller can protect an existing edge with a typed protocol
    # annotation; an unrelated or changed generator is not silently relaxed.
    source_core = deepcopy(source)
    annotations = source_core.pop("dependency_annotations", {})
    canonical_source = build_shor15(synthesis_error_budget=source["algorithm"]["synthesis_error_budget"])
    if source_core != canonical_source:
        raise FrontendError("SOURCE_GENERATOR_NOT_QUALIFIED_FOR_EDGE_RELAXATION")
    source_op_index = {op["id"]: op for op in iter_logical_ops(source)}
    for target, declarations in annotations.items():
        if target not in source_op_index or not set(declarations).issubset(source_op_index[target]["after"]):
            raise FrontendError("UNKNOWN_SOURCE_DEPENDENCY_ANNOTATION")
    patches = [q["id"] for q in source["qubits"]]
    if patches != ["ctrl", "w0", "w1", "w2", "w3"]:
        raise FrontendError("UNSUPPORTED_SHOR_PATCH_ORDER")
    builder = _Builder(patches, source)
    graph = builder.dag
    graph["maintenance_policy"] = {"id": "phase-round-boundaries/1", "entry_rounds_per_patch": 1,
                                    "work_rounds_after_each_phase_readout": 1,
                                    "scope": "explicit_engineering_policy_not_fault_tolerance_claim"}
    graph["synthesis"] = deepcopy(source["synthesis"])
    graph["algorithm"] = deepcopy(source["algorithm"])
    graph["phase_bit_order"] = deepcopy(source["bit_order"])
    graph["rounds"] = deepcopy(source["rounds"])
    startup = {f"init/reset_w{i}" for i in range(4)} | {"round7/reset"}
    touched = set()
    entry_se = False
    for op in iter_logical_ops(source):
        source_id = op["id"]
        if source_id in startup:
            if (op["kind"] != "reset" or op["params"] != {"basis": "Z", "value": 0}
                    or op["condition"] is not None or len(op["qubits"]) != 1
                    or op["qubits"][0] in touched):
                raise FrontendError("UNSAFE_ENTRY_RESET_ABSORPTION: " + source_id)
            graph["entry"]["source_preconditions"].append({"source_operation": deepcopy(op),
                "patch_id": op["qubits"][0], "declared_logical_state": "0_L",
                "reason": "first-use reset supplied by explicit preinitialized entry"})
            graph["source_coverage"][source_id] = {"kind": "entry_precondition", "patch_id": op["qubits"][0]}
            for dep in op["after"]:
                annotation = annotations.get(source_id, {}).get(dep)
                if annotation is not None:
                    raise FrontendError("PROTOCOL_CONSTRAINED_RESET_CANNOT_MOVE_TO_ENTRY")
                graph["source_dependency_audit"].append(_dependency_record(source_op_index[dep], op, entry_dependency=True))
            continue
        if not entry_se:
            for patch in patches:
                builder.se(patch, "entry")
            entry_se = True
        touched.update(op["qubits"])
        if op["kind"] == "gate":
            operation = op["params"]["name"]
            params = {}  # Clifford+T names fix their angles; full target metadata remains below.
        elif op["kind"] == "measure":
            operation, params = "MEASURE", deepcopy(op["params"])
        elif op["kind"] == "reset":
            operation, params = "RESET", deepcopy(op["params"])
        else:
            raise FrontendError("UNSUPPORTED_DAG_SOURCE_OPERATION: " + source_id)
        if operation not in ARITIES:
            raise FrontendError("UNSUPPORTED_DAG_GATE: " + operation)
        node = _node("logical/" + source_id, operation, op["qubits"], params=params,
                     reads=op["reads"].copy(), writes=op["writes"].copy(), condition=op["condition"],
                     source_ids=list(dict.fromkeys(op["source_ids"] + [source_id])))
        node["source_operation"] = deepcopy(op)
        node["source_parameters"] = deepcopy(op["params"])
        if "branch_global_phase_pi" in op:
            node["branch_global_phase_pi"] = deepcopy(op["branch_global_phase_pi"])
            graph["branch_global_phases"].append({"first_node_id": node["id"],
                "source_operation_id": op["synthesis_instance_id"], "condition": deepcopy(op["condition"]),
                "global_phase_pi": deepcopy(op["branch_global_phase_pi"]),
                "scope": "classical_branch_global_not_quantum_control"})
        if operation in ("T", "TDG"):
            node["resource_requests"] = [{"request_id": "magic/" + source_id,
                "kind": "accepted_encoded_A", "target_patch_id": op["qubits"][0],
                "requested_logical_gate": operation, "quantity": 1,
                "condition": deepcopy(op["condition"]), "protocol": "single-level-15-to-1",
                "requires_live_data": True, "initial_inventory_allowed": False,
                "fulfillment_status": "unfulfilled_compile_request"}]
        builder.add(node, source_after=op["after"])
        builder.source_nodes[source_id] = node["id"]
        graph["source_coverage"][source_id] = {"kind": "node", "node_id": node["id"]}
        if operation == "MEASURE" and source_id.startswith("round"):
            phase = source_id.split("/")[0]
            for patch in ("w0", "w1", "w2", "w3"):
                builder.se(patch, "after-" + phase, after=[node["id"]])
    if set(c["source_operation"]["id"] for c in graph["entry"]["source_preconditions"]) != startup:
        raise FrontendError("INCOMPLETE_SHOR_ENTRY_BOUNDARY")
    builder.add(_node("classical/postprocess", "CLASSICAL_POSTPROCESS", [],
                     params={"function": "postprocess_phase", "N": 15, "a": 2, "bits_msb_first": [f"phase[{i}]" for i in range(8)],
                             "failure_policy": "return_explicit_classical_failure"},
                     reads=[f"phase[{i}]" for i in range(8)], writes=["postprocess/result"],
                     source_ids=["shor15:classical-postprocess", source["artifact_id"]]))
    return builder.finish()


def build_patch_dag_example() -> dict:
    """Four-patch nontrivial interaction graph with independent SE roots."""
    patches = [f"P{i}" for i in range(4)]
    builder = _Builder(patches)
    builder.dag["provenance"]["purpose"] = "nontrivial_patch_placement_semantic_input"
    for patch in patches:
        builder.se(patch, "entry")
    for index, (gate, control, target) in enumerate((
            ("CX", "P0", "P3"), ("CZ", "P1", "P2"),
            ("CX", "P0", "P2"), ("CX", "P0", "P3"))):
        builder.add(_node(f"example/couple{index}", gate, [control, target],
                          source_ids=[f"patch-example:{index}"]))
    for patch in patches:
        builder.se(patch, "after-coupling")
    return builder.finish()


def patch_interaction_graph(dag: dict) -> dict:
    edges = {}
    for node in dag["nodes"]:
        if node["operation"] not in ("CX", "CZ"):
            continue
        operands = node["patch_operands"]
        pair = list(operands.values())
        key = tuple(sorted(pair))
        edge = edges.setdefault(key, {"patches": list(key), "weight": 0, "interactions": []})
        edge["weight"] += 1
        edge["interactions"].append({"node_id": node["id"], "operation": node["operation"],
                                     "patch_operands": deepcopy(operands), "condition": deepcopy(node["condition"]),
                                     "source_ids": node["source_ids"].copy()})
    return {"schema_version": "PatchInteractionGraph/0.1.0", "artifact_id": dag["artifact_id"] + "-interactions",
            "provenance": {"owner": "R2", "task_id": "T204", "logical_dag_id": dag["artifact_id"]},
            **FLAGS, "patch_ids": [p["patch_id"] for p in dag["patches"]],
            "weight_semantics": "static_potential_two_patch_call_count_no_fake_branch_prediction",
            "edges": [edges[key] for key in sorted(edges)], "placement_owner": "R4",
            "coordinates_assigned": False,
            "resource_patch_extensions_required": any(n["resource_requests"] or n["operation"] in ("S", "SDG") for n in dag["nodes"]),
            "resource_demands": [deepcopy(request) for n in dag["nodes"] for request in n["resource_requests"]],
            "patch_scope": "declared_algorithm_patches_resource_strategy_patches_require_R3_binding"}


def patch_placement_inputs(dag: dict) -> dict:
    """Exact public R1/R4 input shape; no placement algorithm is run here."""
    errors = validate_logical_dag(dag)
    if errors:
        raise FrontendError("INVALID_PLACEMENT_DAG: " + json.dumps(errors))
    nodes, parents, _, order = _graph_index(dag)
    depth = {}
    for ident in order:
        depth[ident] = max((depth[p] + 1 for p in parents[ident]), default=0)
    interactions = [{"node_id": node["id"], "patch_operands": list(node["patch_operands"].values()),
                     "layer": depth[node["id"]]} for node in dag["nodes"] if node["operation"] in ("CX", "CZ")]
    return {"schema_version": "LogicalPatchPlacementInput/0.1.0", "artifact_id": dag["artifact_id"] + "-placement-input",
            "provenance": {"owner": "R2", "task_id": "T204", "consumer_interface": "R4-HIERARCHICAL-IF-001/0.1.0-draft"},
            **FLAGS, "logical_dag_ref": {"artifact_id": dag["artifact_id"], "canonical_sha256": _hash(dag)},
            "patches": {p["patch_id"]: {"aod_group": "data", "basis": p["initial_state"]["logical_basis"],
                                       "value": p["initial_state"]["logical_value"]} for p in dag["patches"]},
            "interactions": interactions, "layer_semantics": "logical_dependency_depth_not_microseconds",
            "resource_patch_extensions_required": dag["patch_interaction_graph"]["resource_patch_extensions_required"],
            "resource_demands": deepcopy(dag["patch_interaction_graph"]["resource_demands"]),
            "scope": "declared_algorithm_patch_placement_input_not_a_full_factory_world",
            "placement_executed": False, "owner_of_placement_execution": "R4"}


def _graph_index(dag):
    nodes = {node["id"]: node for node in dag["nodes"]}
    if len(nodes) != len(dag["nodes"]):
        raise FrontendError("DUPLICATE_LOGICAL_NODE")
    parents, children = {n: set() for n in nodes}, {n: set() for n in nodes}
    for edge in dag["edges"]:
        start, end = edge["source"], edge["target"]
        if start not in nodes or end not in nodes:
            raise FrontendError("MISSING_EDGE_NODE")
        parents[end].add(start)
        children[start].add(end)
    degrees = {n: len(parents[n]) for n in nodes}
    queue = deque(n for n in nodes if not degrees[n])
    order = []
    while queue:
        n = queue.popleft()
        order.append(n)
        for child in children[n]:
            degrees[child] -= 1
            if degrees[child] == 0:
                queue.append(child)
    if len(order) != len(nodes):
        raise FrontendError("LOGICAL_DAG_CYCLE")
    return nodes, parents, children, order


def validate_logical_dag(dag: dict, *, check_source: bool = True) -> list[dict]:
    errors = []
    def fail(code, source, message):
        errors.append({"code": code, "source_id": source, "message": message})
    try:
        if dag["schema_version"] != SCHEMA or dag["entry_mode"] != "preinitialized":
            raise FrontendError("UNSUPPORTED_LOGICAL_DAG_OR_ENTRY")
        for key, value in FLAGS.items():
            if dag.get(key) != value or type(dag.get(key)) is not type(value):
                fail("INVALID_EVIDENCE_LABEL", "dag", key)
        if dag["entry"].get("startup_transport_required") is not False or dag["entry"].get("initialization_zone") is not None:
            fail("FORBIDDEN_STARTUP_TRANSPORT", "entry", "preinitialized entry has no initialization-zone route")
        if (type(dag["resource_policy"].get("magic_initial_ready_inventory")) is not int
                or dag["resource_policy"]["magic_initial_ready_inventory"] != 0):
            fail("UNAUTHORIZED_INITIAL_MAGIC_INVENTORY", "entry", "prepared does not mean free A resources")
        if (dag["resource_policy"].get("magic_factory_count") != 1
                or dag["resource_policy"].get("max_ready_magic_outputs") != 1
                or dag["resource_policy"].get("protocol") != "single-level-15-to-1"):
            fail("UNSUPPORTED_MAGIC_SUPPLY_POLICY", "dag", "single factory, single ready output and 15-to-1 required")
        patches = {p["patch_id"]: p for p in dag["patches"]}
        if len(patches) != len(dag["patches"]):
            fail("DUPLICATE_PATCH", "patches", "stable patch IDs must be unique")
        for p in patches.values():
            if p["code_profile"] != CODE or p["initial_state"] != _patch(p["patch_id"])["initial_state"]:
                fail("UNSUPPORTED_INITIAL_PATCH_STATE", p["patch_id"], "this profile requires declared encoded logical zero")
            if p["initial_placement"]["anchor_um"] is not None:
                fail("FRONTEND_FIXED_PLACEMENT", p["patch_id"], "actual placement belongs to R4")
        nodes, parents, _, order = _graph_index(dag)
        producers, quantum_edges, classical_edges = {}, set(), set()
        for edge in dag["edges"]:
            if edge["kind"] == "quantum":
                p = edge["patch_id"]
                if p not in nodes[edge["source"]]["patch_operands"].values() or p not in nodes[edge["target"]]["patch_operands"].values():
                    fail("QUANTUM_EDGE_PATCH_MISMATCH", edge["target"], p)
                quantum_edges.add((edge["source"], edge["target"], p))
            elif edge["kind"] == "classical_ready":
                classical_edges.add((edge["source"], edge["target"], edge["result_id"]))
            elif edge["kind"] != "protocol":
                fail("UNKNOWN_EDGE_KIND", edge["target"], edge["kind"])
        last_patch, lifecycle, resource_ids = {}, {p: "live" for p in patches}, set()
        for node in dag["nodes"]:
            ident, operation = node["id"], node["operation"]
            known_fields = {"id", "operation", "semantic_version", "patch_operands", "params", "reads", "writes", "condition",
                            "source_ids", "resource_requests", "implementation_status", "source_operation", "source_parameters",
                            "branch_global_phase_pi", "groups", "data_effect", "metadata"}
            if set(node) - known_fields:
                fail("UNKNOWN_LOGICAL_NODE_FIELD", ident, str(sorted(set(node) - known_fields)))
            if operation not in ARITIES:
                fail("UNKNOWN_LOGICAL_OPERATION", ident, str(operation))
                continue
            operands = node["patch_operands"]
            if set(operands) != set(ARITIES[operation]) or len(set(operands.values())) != len(operands):
                fail("INVALID_PATCH_DIRECTION", ident, str(operands))
            if node.get("semantic_version") != "1.0.0" or not node.get("source_ids"):
                fail("MISSING_OPERATION_SEMANTICS", ident, "semantic version and nonempty source_ids required")
            for patch in operands.values():
                if patch not in patches:
                    fail("UNKNOWN_PATCH", ident, patch)
                if patch in last_patch and (last_patch[patch], ident, patch) not in quantum_edges:
                    fail("MISSING_PATCH_ORDER", ident, patch)
                last_patch[patch] = ident
                if operation == "RESET":
                    lifecycle[patch] = "live"
                elif lifecycle.get(patch) != "live":
                    fail("PATCH_NOT_LIVE", ident, patch)
                elif operation == "MEASURE":
                    lifecycle[patch] = "measured"
            if operation in ("SE", "H", "X", "Z", "S", "SDG", "T", "TDG", "CX", "CZ") and node["params"] != {}:
                fail("UNSUPPORTED_OPERATION_PARAMETERS", ident, "fixed named gate or single SE has no tunable params")
            if operation == "RESET" and (node["params"] != {"basis": "Z", "value": 0} or node["condition"] is not None):
                fail("UNSUPPORTED_LOGICAL_RESET", ident, "unconditional logical-zero re-preparation required")
            if operation == "MEASURE" and (node["params"] not in ({"basis": "Z"}, {"basis": "X"}) or len(node["writes"]) != 1 or node["condition"] is not None):
                fail("UNSUPPORTED_LOGICAL_MEASUREMENT", ident, "unconditional one-result X/Z observation required")
            for result in node["writes"]:
                if result in producers:
                    fail("DUPLICATE_RESULT_PRODUCER", ident, result)
                producers[result] = ident
            condition = node["condition"]
            if condition is not None and (set(condition) != {"bit", "equals"} or type(condition.get("equals")) is not int
                                          or condition["equals"] not in (0, 1) or condition["bit"] not in node["reads"]):
                fail("INVALID_CLASSICAL_CONDITION", ident, str(condition))
            if operation == "SE":
                if len(node["writes"]) != 8 or node.get("data_effect") != "preserve_live_data_no_data_reset":
                    fail("INVALID_SE_SEMANTICS", ident, "SE must preserve data and produce eight distinct syndrome bits")
                groups = node.get("groups", [])
                expected_roles = {f"{q}{i}" for q in ("x", "z") for i in range(4)}
                if (len(groups) != 1 or groups[0].get("purpose") != "maintenance_readout"
                        or {m["role"] for m in groups[0]["members"]} != expected_roles
                        or len(groups[0]["members"]) != 8
                        or any(m["measurement_basis"] != "Z" or m["result_id"] not in node["writes"] for m in groups[0]["members"])):
                    fail("INVALID_SE_GROUP", ident, "four X plus four Z ancillas with individual Z readouts required")
            if operation in ("T", "TDG"):
                requests = node["resource_requests"]
                if (len(requests) != 1 or requests[0].get("kind") != "accepted_encoded_A"
                        or requests[0].get("target_patch_id") != operands.get("block")
                        or requests[0].get("requested_logical_gate") != operation
                        or requests[0].get("condition") != condition or type(requests[0].get("quantity")) is not int or requests[0]["quantity"] != 1
                        or requests[0].get("requires_live_data") is not True or requests[0].get("initial_inventory_allowed") is not False
                        or requests[0].get("protocol") != "single-level-15-to-1"
                        or requests[0].get("fulfillment_status") != "unfulfilled_compile_request"):
                    fail("MISSING_MAGIC_RESOURCE_REQUIREMENT", ident, "T/TDG cannot be a free physical gate")
                for request in requests:
                    if not request.get("request_id") or request["request_id"] in resource_ids:
                        fail("DUPLICATE_MAGIC_REQUEST_ID", ident, str(request.get("request_id")))
                    resource_ids.add(request["request_id"])
        for node in dag["nodes"]:
            for result in node["reads"]:
                producer = producers.get(result)
                if producer is None:
                    fail("MISSING_RESULT_PRODUCER", node["id"], result)
                elif (producer, node["id"], result) not in classical_edges:
                    fail("MISSING_CLASSICAL_READY_EDGE", node["id"], result)
        for producer, consumer, result in classical_edges:
            if producers.get(result) != producer or result not in nodes[consumer]["reads"]:
                fail("INVALID_CLASSICAL_READY_EDGE", consumer, result)
        if set(dag["result_types"]) != set(producers):
            fail("RESULT_TYPE_COVERAGE", "dag", "every produced result needs its declared type")
        projection = patch_interaction_graph(dag)
        recorded_projection = dag.get("patch_interaction_graph", {})
        required_projection_fields = {"schema_version", "artifact_id", "patch_ids", "weight_semantics", "edges", "placement_owner", "coordinates_assigned"}
        optional_projection_fields = {"resource_patch_extensions_required", "resource_demands", "patch_scope"}
        if (any(recorded_projection.get(k) != projection[k] for k in required_projection_fields)
                or any(k in recorded_projection and recorded_projection[k] != projection[k] for k in optional_projection_fields)):
            fail("INTERACTION_GRAPH_MISMATCH", "dag", "interaction projection must cover actual coupling nodes")
        if check_source and dag.get("source_program") is not None:
            source = dag["source_program"]
            require_clifford_t(source)
            core = deepcopy(source)
            core.pop("dependency_annotations", None)
            if core != build_shor15(synthesis_error_budget=source["algorithm"]["synthesis_error_budget"]):
                fail("UNQUALIFIED_SOURCE_SERIALIZATION_PROFILE", "dag", "source is not this exact mechanical-order generator")
            if dag["source_program_ref"]["canonical_sha256"] != _hash(source):
                fail("SOURCE_HASH_MISMATCH", "dag", "source program changed")
            source_ops = {op["id"]: op for op in iter_logical_ops(source)}
            audit = {(r["source_operation_id"], r["target_operation_id"]): r for r in dag["source_dependency_audit"]}
            expected_dependency_keys = {(dep, op["id"]) for op in source_ops.values() for dep in op["after"]}
            if len(audit) != len(dag["source_dependency_audit"]) or set(audit) != expected_dependency_keys:
                fail("SOURCE_DEPENDENCY_AUDIT_COVERAGE", "dag", "every old after edge requires a disposition and proof")
            def precedes(earlier, later):
                stack, seen = list(parents[later]), set()
                while stack:
                    current = stack.pop()
                    if current == earlier:
                        return True
                    if current not in seen:
                        seen.add(current)
                        stack.extend(parents[current])
                return False
            if set(dag["source_coverage"]) != set(source_ops):
                fail("SOURCE_COVERAGE_MISMATCH", "dag", "all original operations must have exactly one coverage record")
            entry_ops = {p["source_operation"]["id"]: p for p in dag["entry"]["source_preconditions"]}
            startup = {f"init/reset_w{i}" for i in range(4)} | {"round7/reset"}
            if set(entry_ops) != startup:
                fail("UNSAFE_ENTRY_COVERAGE", "entry", "only five first-use reset preconditions allowed")
            for source_id, op in source_ops.items():
                coverage = dag["source_coverage"].get(source_id, {})
                if coverage.get("kind") == "entry_precondition":
                    if (source_id not in startup or entry_ops.get(source_id, {}).get("source_operation") != op
                            or coverage.get("patch_id") != op["qubits"][0]
                            or entry_ops.get(source_id, {}).get("patch_id") != op["qubits"][0]):
                        fail("ENTRY_SOURCE_CHANGED", source_id, "entry precondition must exactly retain the source reset")
                    for dep in op["after"]:
                        expected = _dependency_record(source_ops[dep], op, entry_dependency=True)
                        if audit.get((dep, source_id)) != expected:
                            fail("ENTRY_DEPENDENCY_PROOF_CHANGED", source_id, dep)
                elif coverage.get("kind") == "node":
                    node = nodes.get(coverage.get("node_id"), {})
                    operation = op["params"]["name"] if op["kind"] == "gate" else op["kind"].upper()
                    if (node.get("source_operation") != op or node.get("operation") != operation
                            or list(node.get("patch_operands", {}).values()) != op["qubits"]
                            or node.get("reads") != op["reads"] or node.get("writes") != op["writes"]
                            or node.get("condition") != op["condition"] or node.get("source_parameters") != op["params"]
                            or node.get("branch_global_phase_pi") != op.get("branch_global_phase_pi")):
                        fail("SOURCE_OPERATION_CHANGED", source_id, "gate, direction, parameters, control and source must survive")
                    for dep in op["after"]:
                        dep_node = dag["source_coverage"].get(dep, {}).get("node_id")
                        annotation = source.get("dependency_annotations", {}).get(source_id, {}).get(dep)
                        record = _dependency_record(source_ops[dep], op, annotation, entry_dependency=dep_node is None)
                        if audit.get((dep, source_id)) != record:
                            fail("SOURCE_DEPENDENCY_PROOF_CHANGED", source_id, dep)
                        if dep_node and record["disposition"] != "relaxed_generated_serialization" and not precedes(dep_node, coverage["node_id"]):
                            fail("SOURCE_DEPENDENCY_DROPPED", source_id, dep)
                        if record["disposition"] == "preserved_explicit_protocol" and dep_node:
                            if not any(e["source"] == dep_node and e["target"] == coverage["node_id"] and e["kind"] == "protocol" and e.get("reason") == annotation["reason"] for e in dag["edges"]):
                                fail("EXPLICIT_PROTOCOL_EDGE_DROPPED", source_id, dep)
                else:
                    fail("SOURCE_OPERATION_UNCOVERED", source_id, str(coverage))
            expected_phases = [{"first_node_id": dag["source_coverage"][op["id"]]["node_id"],
                                "source_operation_id": op["synthesis_instance_id"], "condition": op["condition"],
                                "global_phase_pi": op["branch_global_phase_pi"], "scope": "classical_branch_global_not_quantum_control"}
                               for op in source_ops.values() if "branch_global_phase_pi" in op]
            if dag["branch_global_phases"] != expected_phases:
                fail("BRANCH_PHASE_COVERAGE", "dag", "all conditional scalar phases must remain exactly")
    except (KeyError, TypeError, ValueError, AttributeError, IndexError) as exc:
        code = str(exc).split(":", 1)[0] if isinstance(exc, FrontendError) else "INVALID_LOGICAL_DAG"
        fail(code, "dag", str(exc))
    return errors


def ready_logical_nodes(dag: dict, completed, *, results: dict | None = None, now_us: float = 0.0) -> list[dict]:
    """Semantic ready/skip candidates only; shared resource selection is R5's."""
    nodes, parents, _, _ = _graph_index(dag)
    completed = set(completed)
    if not completed.issubset(nodes):
        raise FrontendError("UNKNOWN_COMPLETED_NODE")
    if any(not parents[n].issubset(completed) for n in completed):
        raise FrontendError("NONCAUSAL_COMPLETION_SET")
    if type(now_us) not in (int, float) or not math.isfinite(now_us) or now_us < 0:
        raise FrontendError("INVALID_READY_QUERY_TIME")
    published = {} if results is None else results
    producers = {result: node["id"] for node in dag["nodes"] for result in node["writes"]}
    for result_id, record in published.items():
        if (result_id not in producers or record.get("producer_node_id") != producers[result_id]
                or producers[result_id] not in completed):
            raise FrontendError("RESULT_WITHOUT_COMPLETED_PRODUCER: " + result_id)
        if (record.get("origin") != "fake" or type(record.get("ready_us")) not in (int, float)
                or not math.isfinite(record["ready_us"]) or record["ready_us"] < 0):
            raise FrontendError("INVALID_RESULT_OR_READY_TIME: " + result_id)
        if dag["result_types"][result_id] == "bit" and (type(record.get("value")) is not int or record["value"] not in (0, 1)):
            raise FrontendError("INVALID_PUBLISHED_BIT: " + result_id)
    candidates = []
    for node in dag["nodes"]:
        ident = node["id"]
        if ident in completed or not parents[ident].issubset(completed):
            continue
        if any(bit not in published or published[bit]["ready_us"] > now_us for bit in node["reads"]):
            continue
        decision = "execute"
        if node["condition"] is not None:
            condition = node["condition"]
            decision = "execute" if published[condition["bit"]]["value"] == condition["equals"] else "skip"
        candidates.append({"node_id": ident, "decision": decision, "patch_operands": deepcopy(node["patch_operands"]),
                           "resources_checked": False, "placement_checked": False,
                           "scope": "semantic_candidate_not_scheduled_or_committed"})
    return candidates


def logical_dag_requirements(dag: dict, available_operations=None) -> dict:
    """Static R3 closure checklist; availability never means qualification."""
    available = set(available_operations or [])
    counts = Counter(node["operation"] for node in dag["nodes"])
    requirements = []
    for operation in sorted(counts):
        selected = [n for n in dag["nodes"] if n["operation"] == operation]
        requirements.append({"operation": operation, "semantic_version": "1.0.0", "node_count": counts[operation],
                             "operand_roles": ARITIES[operation], "has_classical_conditions": any(n["condition"] is not None for n in selected),
                             "params_variants": list({json.dumps(n["params"], sort_keys=True): n["params"] for n in selected}.values()),
                             "physical_spec_declared_available": operation in available,
                             "qualified": False, "example_node_id": selected[0]["id"]})
    return {"schema_version": "LogicalDAGRequirements/0.1.0", "artifact_id": dag["artifact_id"] + "-requirements",
            "provenance": {"owner": "R2", "task_id": "T204"}, **FLAGS,
            "requirements": requirements, "unsupported_operations": [r["operation"] for r in requirements if not r["physical_spec_declared_available"]],
            "magic_requests_static_upper_bound": sum(len(n["resource_requests"]) for n in dag["nodes"]),
            "complete_physical_execution_qualified": False}
