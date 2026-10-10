"""T304: preinitialized patch semantics and complete physical dependency graphs.

No placement, start-up transport, measurement values, or runtime state is
created here. T/TDG use the real adaptive factory recipe, never a physical T
substitution on live data. All qualification remains explicit and scoped.
"""

from collections import Counter
from copy import deepcopy
from fractions import Fraction
from hashlib import sha256
import json
import math
from pathlib import Path
import re

from .factory import build_factory15to1_protocol, factory_stage_program
from .factory_primitives import Circuit
from .program import iter_physical_ops
from .surface17 import CHECKS, DATA, FORMALS, LOGICAL_X, LOGICAL_Z, _templates
from .logical_primitives import CODE_PROFILE

VERSION = "0.1.0"
PHYSICAL_DAG_SCHEMA = "PhysicalDAG/0.1.0"
SPEC_SCHEMA = "PatchOperationSpec/0.1.0"
OPERATIONS = {"SE", "H", "X", "Z", "S", "SDG", "T", "TDG", "CX", "CZ", "MEASURE", "RESET", "CLASSICAL_POSTPROCESS"}


class PhysicalDAGError(ValueError):
    def __init__(self, code, message, *, node_id=None, details=None):
        self.code, self.node_id, self.details = code, node_id, details or {}
        super().__init__(f"{code}: {message}; node={node_id}")


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _code_hashes():
    root = Path(__file__).resolve().parent
    return {name: sha256((root / name).read_bytes()).hexdigest() for name in
            ("physical_dag.py", "surface17.py", "program.py", "factory.py", "factory_primitives.py", "neutral_clifford.py", "geometry_variants.py")}


def _normalize_params(operation, params):
    if operation not in OPERATIONS:
        raise PhysicalDAGError("PATCH_OPERATION_UNSUPPORTED", f"unknown operation {operation}")
    p = deepcopy(params or {})
    if not isinstance(p, dict):
        raise PhysicalDAGError("PATCH_PARAMETERS", "params must be an object")
    if operation == "MEASURE":
        if set(p) - {"basis"} or p.get("basis", "Z") not in {"X", "Z"}:
            raise PhysicalDAGError("MEASUREMENT_BASIS", "only encoded X/Z destructive readout is implemented")
        return {"basis": p.get("basis", "Z")}
    if operation == "RESET":
        if set(p) - {"basis", "value"} or p.get("basis", "Z") != "Z" or p.get("value", 0) != 0:
            raise PhysicalDAGError("RESET_STATE", "RESET must reconstruct encoded logical zero")
        return {"basis": "Z", "value": 0}
    if operation == "CLASSICAL_POSTPROCESS":
        expected = {"function": "postprocess_phase", "N": 15, "a": 2,
                    "bits_msb_first": [f"phase[{i}]" for i in range(8)],
                    "failure_policy": "return_explicit_classical_failure"}
        if any(key not in expected or value != expected[key] for key, value in p.items()):
            raise PhysicalDAGError("POSTPROCESS_PROFILE", "only complete N15/a2/eight-bit postprocessing is implemented")
        return expected
    if "name" in p:
        if p.pop("name") != operation:
            raise PhysicalDAGError("GATE_NAME_MISMATCH", "DAG operation and source gate name disagree")
    if p and operation in {"SDG", "TDG"}:
        allowed = {"angle_pi", "angle_rad", "angle_unit", "phase_convention", "synthesis_status", "error_bound", "error_budget"}
        expected = Fraction(-1, 2 if operation == "SDG" else 4)
        angle = p.get("angle_pi", {})
        try:
            actual = Fraction(angle["numerator"], angle["denominator"])
        except (KeyError, TypeError, ZeroDivisionError):
            actual = None
        if (set(p) - allowed or actual != expected or p.get("angle_unit") != "rad"
                or not math.isclose(p.get("angle_rad", math.inf), float(expected) * math.pi, abs_tol=1e-14)
                or p.get("phase_convention") != "diag(1,exp(i*theta))"):
            raise PhysicalDAGError("GATE_ANGLE_MISMATCH", "source angle is not the named exact phase gate")
        p = {}
    if p:
        raise PhysicalDAGError("PATCH_PARAMETERS_UNSUPPORTED", f"unexplained parameters for {operation}: {sorted(p)}")
    return {}


def _append_surface(c, template_id, block, prefix=""):
    for node in _templates()[template_id]["body"]:
        op = node["op"]
        condition = deepcopy(op["condition"])
        if condition:
            condition["bit"] = prefix + condition["bit"]
        c.add(prefix + op["id"], op["kind"], [f"{block}_{q}" for q in op["qubits"]], op["params"],
              reads=[prefix + b for b in op["reads"]], writes=[prefix + b for b in op["writes"]],
              after=[prefix + oid for oid in op["after"]], condition=condition, metadata=op.get("metadata"))
    for q in FORMALS[9:]:
        c.add(prefix + "service_reset_" + q, "reset", [f"{block}_{q}"], {"basis": "Z"},
              after=[prefix + "measure_" + q])


def _logical_h(c, block, prefix):
    for i in range(9):
        c.gate(f"{prefix}_h{i}", "H", [f"{block}_d{i}"])
    _logical_permutation(c, block, prefix)


def _logical_permutation(c, block, prefix):
    c.add(f"{prefix}_permutation", "permute", [f"{block}_d{i}" for i in range(9)],
          {"destination_indices": [2, 5, 8, 1, 4, 7, 0, 3, 6]},
          metadata={"protocol": "logical_H_transversal_plus_atom_transport", "permutation": "clockwise90",
                    "binding_contract": "code-site-permutation/0.1"})


def _program(circuit, role_map, operation):
    formal_map, qubits = {}, []
    for internal, role in role_map.items():
        if internal == "join_probe":
            formal_map[internal] = "bridge/probe"
            qubits.append({"id": "bridge/probe", "block_id": "bridge", "local_id": "probe", "role": "syndrome", "aod_group": "magic"})
            continue
        for q in FORMALS:
            formal_map[f"{internal}_{q}"] = f"{role}/{q}"
            qubits.append({"id": f"{role}/{q}", "block_id": role, "local_id": q,
                           "role": "data" if q in DATA else "syndrome", "aod_group": "magic" if role == "phase_aux" else "data"})
    used = {q for node in circuit.nodes for q in node["op"]["qubits"]}
    if not used <= formal_map.keys():
        raise PhysicalDAGError("UNBOUND_PHYSICAL_ROLE", "circuit uses an undeclared formal resource", details={"qubits": sorted(used - formal_map.keys())})
    tid = f"patch.{operation}.v1"
    template = {"template_id": tid, "qubits": list(formal_map), "body": deepcopy(circuit.nodes),
                "metadata": {"operation": operation, "code_profile": deepcopy(CODE_PROFILE),
                             "entry_mode": "preinitialized", "startup_transport": False}}
    return {"schema_version": "physical-program/0.2.0-draft", "artifact_id": f"formal-physical-{operation}",
            "producer_version": f"na_pipeline.qec.physical_dag/{VERSION}",
            "provenance": {"owner": "R3", "task_id": "T304", "kb_revision": "kb-0006", "fixture": False},
            "execution_kind": "compile_plan", "quantum_state_simulated": False, "hardware_executed": False, "loss_enabled": False,
            "entry_mode": "preinitialized", "qubits": qubits, "templates": {tid: template},
            "body": [{"kind": "call", "id": "physical", "template_id": tid, "bindings": formal_map, "repeat": 1,
                      "source_ids": [f"patch-operation:{operation}", "ADR-0008"]}]}


def _maintenance_groups(ops):
    groups = {}
    positions = {op["id"]: i for i, op in enumerate(ops)}
    by_id = {op["id"]: op for op in ops}
    for op in ops:
        if op["kind"] != "measure":
            continue
        match = re.fullmatch(r"(.*measure_)([xz][0-3])", op["id"])
        if not match:
            continue
        base, check = match[1][:-len("measure_")], match[2]
        q = op["qubits"][0]
        block = q.rsplit("/", 1)[0]
        groups.setdefault((base, block), {})[check] = op
    result = []
    for (base, block), members_by_check in groups.items():
        if set(members_by_check) != set(FORMALS[9:]):
            continue
        members = []
        for check in FORMALS[9:]:
            measure = members_by_check[check]
            q = measure["qubits"][0]
            earlier = ops[:positions[measure["id"]]]
            last = next(op for op in reversed(earlier) if q in op["qubits"] and op["params"].get("name") == "CX")
            basis_id = base + "read_basis_" + check if check.startswith("x") else None
            prep_id = base + "reset_" + check
            post_id = base + "service_reset_" + check
            members.append({"physical_qubit_id": q, "local_id": check, "check_type": check[0].upper(),
                            "measurement_basis": "Z", "last_coupling_op_id": last["id"], "basis_change_op_id": basis_id,
                            "prepare_op_ids": [prep_id], "transport_after_op_ids": [last["id"]] + ([basis_id] if basis_id else []),
                            "measurement_op_id": measure["id"], "result_id": measure["writes"][0],
                            "post_readout_reset_op_id": post_id if post_id in by_id else None})
        result.append({"group_id": f"maintenance:{base}:{block}", "purpose": "maintenance_readout", "formal_block": block,
                       "members": members, "readout_policy": "earliest_common_resource_feasible_start",
                       "target_layout_id": "ancilla_readout", "mz_coordinate_frame": "global_device_zone_bank_x",
                       "entry_geometry": "current_compiler_snapshot", "exit_geometry": "compiler_reported",
                       "numeric_synchronization_tolerance_us": None})
    return result


def _readout_services(ops, qubits, groups):
    """Every physical readout, including gauge probes and destructive data.

    These are semantic port requirements. R4 assigns an actual MZ destination
    and legal transport; no time or position is implied by this list.
    """
    inventory = {q["id"]: q for q in qubits}
    grouped = {m["measurement_op_id"]: g["group_id"] for g in groups for m in g["members"]}
    previous, services = {}, []
    for op in ops:
        if op["kind"] == "measure":
            q = op["qubits"][0]
            services.append({"measurement_op_id": op["id"], "physical_qubit_id": q,
                             "block_id": inventory[q].get("block_id"), "qubit_role": inventory[q]["role"],
                             "group_id": grouped.get(op["id"]), "result_id": op["writes"][0],
                             "measurement_basis": op["params"]["basis"],
                             "transport_after_op_ids": [previous[q]] if q in previous else [],
                             "port_role": "measurement_receiver", "coordinate_frame": "global_device_MZ",
                             "post_measurement_state": "measured_until_next_explicit_operation",
                             "reset_or_release_implied": False})
        for q in op["qubits"]:
            previous[q] = op["id"]
    return services


def physical_dag_from_program(program, *, operation, groups=None):
    ops = list(iter_physical_ops(program))
    # New grouped readout service requires an explicit measured-ancilla reset.
    # Historical factory templates omitted this when a later round resets it.
    # Add the real operation here, with source evidence and predecessor rewiring;
    # do not mutate or silently reinterpret those historical templates.
    service = {}
    for group in _maintenance_groups(ops):
        for member in group["members"]:
            if member["post_readout_reset_op_id"] is None:
                mid = member["measurement_op_id"]
                service[mid] = mid.rsplit("measure_", 1)[0] + "service_reset_" + member["local_id"]
    completed = []
    for op in ops:
        op["after"] = list(dict.fromkeys(op["after"] + [service[d] for d in op["after"] if d in service]))
        completed.append(op)
        if op["id"] in service:
            completed.append({"id": service[op["id"]], "kind": "reset", "qubits": op["qubits"].copy(),
                              "params": {"basis": "Z"}, "reads": [], "writes": [], "after": [op["id"]],
                              "condition": None, "source_ids": op["source_ids"] + ["T304:grouped_readout_service_reset"],
                              "metadata": {**deepcopy(op.get('metadata', {})), "derivation": "post_measurement_ancilla_service", "measurement_source_id": op["id"]}})
    ops = completed
    by_id, writers, edges = {}, {}, []
    for op in ops:
        for dep in op["after"]:
            common = sorted(set(op["qubits"]) & set(by_id[dep]["qubits"]))
            edges.append({"source": dep, "target": op["id"], "kind": "quantum" if common else "protocol", "qubits": common})
        for bit in op["reads"]:
            if bit not in writers:
                raise PhysicalDAGError("PHYSICAL_READ_WITHOUT_PRODUCER", "physical program read lacks a local producer", node_id=op["id"])
            edges.append({"source": writers[bit], "target": op["id"], "kind": "classical_ready", "result_id": bit})
        for bit in op["writes"]:
            writers[bit] = op["id"]
        by_id[op["id"]] = op
    parents = {edge["target"] for edge in edges}
    sources = {edge["source"] for edge in edges}
    result = {"schema_version": PHYSICAL_DAG_SCHEMA, "artifact_id": f"physical-dag-{operation}-" + _hash(program)[:20],
              "producer_version": f"na_pipeline.qec.physical_dag/{VERSION}",
              "provenance": {"owner": "R3", "task_id": "T304", "kb_revision": "kb-0006", "fixture": bool(program["provenance"].get("fixture"))},
              "execution_kind": "compile_plan", "quantum_state_simulated": False, "hardware_executed": False, "loss_enabled": False,
              "entry_mode": "preinitialized", "operation": operation, "qubits": deepcopy(program["qubits"]),
              "nodes": ops, "edges": edges, "roots": [op["id"] for op in ops if op["id"] not in parents],
              "terminals": [op["id"] for op in ops if op["id"] not in sources],
              "groups": _maintenance_groups(ops) if groups is None else deepcopy(groups),
              "result_producers": writers, "external_reads": [], "execution_guard": None,
              "input_hashes": {"physical_program": _hash(program)},
              "source_map": {op["id"]: {"physical_source_op_id": op["id"], "source_ids": op["source_ids"]} for op in ops}}
    result["readout_services"] = _readout_services(ops, result["qubits"], result["groups"])
    result["result_types"] = {bit: "bit" for bit in writers}
    return result


def build_patch_operation_spec(operation, *, params=None):
    p = _normalize_params(operation, params)
    operands = ["control", "target"] if operation == "CX" else ["left", "right"] if operation == "CZ" else [] if operation == "CLASSICAL_POSTPROCESS" else ["block"]
    base = {"schema_version": SPEC_SCHEMA, "producer_version": VERSION, "operation": operation, "semantic_version": "1.0.0",
            "params": p, "formal_operands": operands, "code_profile": deepcopy(CODE_PROFILE), "entry_mode": "preinitialized",
            "entry_requirements": {"encoded_input": operation not in {"RESET", "CLASSICAL_POSTPROCESS"}, "initial_magic_inventory": 0,
                                   "geometry": "current_explicit_snapshot", "startup_actions": []},
            "exit_effects": {"data_binding": "preserved", "geometry": "compiler_reported_exit", "fixed_home_required": False,
                             "lifecycle": "measured" if operation == "MEASURE" else "live", "frame": "explicit_physical_corrections_only"},
            "resource_requirements": {"operand_patches": operands, "scratch_patches": [], "scratch_atoms": []},
            "provenance": {"owner": "R3", "task_id": "T304", "kb_revision": "kb-0006", "planning_revision": "plan-0008", "fixture": False},
            "qualification": {"source": "implemented", "independent": "pending", "physical_compilation": "pending",
                              "fault_tolerance": "not_claimed", "quantum_state_simulated": False}}
    if operation in {"T", "TDG"}:
        base.update(implementation_kind="adaptive_factory_protocol", physical_dag=None,
                    protocol_ref={"schema_version": "factory-protocol/0.1.0-draft", "builder": "na_pipeline.qec.build_factory15to1_protocol",
                                  "stage_builder": "na_pipeline.qec.build_factory_physical_dag", "gate": operation,
                                  "raw_input_count": 15, "same_output_block": "W4", "requires_accepted_token": True,
                                  "single_use": True, "live_data_must_not_be_reset": True})
        base["resource_requirements"].update(factory_count=1, maximum_ready_outputs=1, factory_patch_count=7, factory_probe_count=1)
        base["public_results"] = {}
    elif operation == "CLASSICAL_POSTPROCESS":
        node = {"id": "classical/postprocess", "kind": "classical", "qubits": [], "params": {"operation": "postprocess_phase", **p},
                "reads": [f"phase[{i}]" for i in range(8)], "writes": ["report"], "after": [], "condition": None,
                "source_ids": ["patch-operation:CLASSICAL_POSTPROCESS"]}
        base.update(implementation_kind="classical_protocol", physical_dag={"schema_version": PHYSICAL_DAG_SCHEMA,
                    "artifact_id": "physical-dag-postprocess", "entry_mode": "preinitialized", "operation": operation,
                    "qubits": [], "nodes": [node], "edges": [], "roots": [node["id"]], "terminals": [node["id"]],
                    "groups": [], "result_producers": {"report": node["id"]}, "external_reads": node["reads"], "execution_guard": None,
                    "readout_services": [], "result_types": {"report": "postprocess_record"},
                    "source_map": {node["id"]: {"source_ids": node["source_ids"]}},
                    "provenance": deepcopy(base["provenance"]), "execution_kind": "compile_plan", "quantum_state_simulated": False,
                    "hardware_executed": False, "loss_enabled": False}, public_results={"report": "report"})
        base["resource_requirements"]["classical_duration_ref"] = "timings_us.classical"
    else:
        c, roles, public = Circuit(), {"D": "block"}, {}
        if operation == "SE":
            _append_surface(c, "s17.syndrome.v1", "D")
            public = {q: f"physical/r0/m_{q}" for q in FORMALS[9:]}
        elif operation == "RESET":
            _append_surface(c, "s17.prepare_zero.v1", "D")
        elif operation in {"X", "Z"}:
            for i in LOGICAL_X if operation == "X" else LOGICAL_Z:
                c.gate(f"logical_{operation}_{i}", operation, [f"D_d{i}"])
        elif operation == "H":
            _logical_h(c, "D", "logical_H")
        elif operation in {"CX", "CZ"}:
            roles = {"A": operands[0], "B": operands[1]}
            if operation == "CZ":
                # A quarter-turn pairing maps each X check to a Z check of
                # the other canonical code. Same-index bare CZ is invalid.
                # Placement may align these ports at t=0; no runtime swap is
                # part of the logical gate. The atom router checks feasibility.
                for i, j in enumerate((2, 5, 8, 1, 4, 7, 0, 3, 6)):
                    c.gate(f"logical_CZ_{i}", "CZ", [f"A_d{i}", f"B_d{j}"],
                           metadata={"logical_pairing": "surface17-quarter-turn/1"})
            else:
                c.transversal("A", "B", "logical_CX")
        elif operation in {"S", "SDG"}:
            c.clifford_phase("D", 1 if operation == "S" else -1, "phase")
        elif operation == "MEASURE":
            if p["basis"] == "X":
                for q in DATA:
                    c.gate("basis_" + q, "H", [f"D_{q}"])
            for q in DATA:
                c.add("read_" + q, "measure", [f"D_{q}"], {"basis": "Z"}, writes=["m_" + q])
            c.xor("logical_readout", [f"m_d{i}" for i in (LOGICAL_X if p["basis"] == "X" else LOGICAL_Z)], "value")
            public = {"value": "physical/r0/value"}
        program = _program(c, roles, operation)
        dag = physical_dag_from_program(program, operation=operation)
        base.update(implementation_kind="static_physical_dag", physical_dag=dag, public_results=public)
        base["physical_program_ref"] = {"artifact_id": program["artifact_id"], "sha256": _hash(program)}
    nodes = base["physical_dag"]["nodes"] if base["physical_dag"] else []
    base["summary"] = {"physical_operation_count": len(nodes) if base["physical_dag"] else None,
                       "operation_counts": dict(Counter(op["params"].get("name", op["kind"]) for op in nodes)),
                       "duration_us": None, "duration_status": "requires_R4_actual_compilation",
                       "resource_intervals": None, "port_roles": ["data_coupling", "ancilla_departure", "measurement_receiver"],
                       "shared_constraints": ["AOD_rows_columns", "global_broadcast", "MZ_bank_capacity"],
                       "independent_patches_do_not_imply_independent_device_resources": True}
    base["source_sha256"] = _code_hashes()
    base["spec_hash"] = _hash(base)
    return base


def build_factory_physical_dag(protocol, stage_id):
    program = factory_stage_program(protocol, stage_id)
    dag = physical_dag_from_program(program, operation="FACTORY_STAGE")
    dag["protocol_binding"] = {"protocol_id": protocol["artifact_id"], "epoch": protocol["epoch"],
                               "stage_id": stage_id, "request_id": protocol["request_id"], "data_block_id": protocol["data_block_id"]}
    if protocol.get('production_mode'):dag['protocol_binding']['mode']='independent_producer'
    dag["entry_requirements"] = {"same_carriers_as_committed_snapshot": True, "may_not_reinitialize_live_data": True,
                                 "initial_magic_inventory": 0, "startup_actions": []}
    dag["protocol_branch"] = deepcopy(protocol["stages"][stage_id].get("branch"))
    for port in ('entry_magic_input','prepared_magic_output'):
        if port in protocol['stages'][stage_id]:
            dag[port]=deepcopy(protocol['stages'][stage_id][port])
    dag["window_contract"] = deepcopy(program["window_contract"])
    if "logical_binding" in protocol:
        dag["logical_binding"] = deepcopy(protocol["logical_binding"])
        dag["execution_guard"] = deepcopy(protocol["execution_guard"])
        dag["external_reads"] = deepcopy(protocol["logical_binding"]["logical_source"]["reads"])
        dag["required_leases"] = deepcopy(protocol["required_leases"])
        dag["world_resource_ref"] = deepcopy(protocol["world_resource_ref"])
        source = protocol["logical_binding"]["logical_source"]
        for op in dag["nodes"]:
            op["source_ids"] = list(dict.fromkeys(op["source_ids"] + source["source_ids"] + [source["id"]]))
            dag["source_map"][op["id"]].update(logical_node_id=source["id"], source_ids=deepcopy(op["source_ids"]))
    if 'fleet_logical_source' in protocol:
        source=protocol['fleet_logical_source']
        dag['fleet_logical_source']=deepcopy(source)
        dag['execution_guard']=deepcopy(source.get('condition'))
        dag['external_reads']=list(dict.fromkeys(dag['external_reads']+source.get('reads',[])))
        for op in dag['nodes']:
            op['source_ids']=list(dict.fromkeys(op['source_ids']+source['source_ids']+[source['id']]))
            dag['source_map'][op['id']].update(logical_node_id=source['id'],source_ids=deepcopy(op['source_ids']))
    return dag


def validate_physical_dag(dag):
    """Structural/source checks, independent of geometry and quantum state.

    Raises a precise error on invalid input; returns a compact successful audit.
    Local `after` and typed edges must agree. Classical external reads are only
    inputs, not precomputed results; R5 must publish them before execution.
    """
    def fail(code, message, node=None):
        raise PhysicalDAGError(code, message, node_id=node)
    if dag.get("schema_version") != PHYSICAL_DAG_SCHEMA or dag.get("entry_mode") != "preinitialized":
        fail("PHYSICAL_DAG_SCHEMA", "unsupported schema or entry mode")
    nodes = {n["id"]: n for n in dag["nodes"]}
    if not nodes or len(nodes) != len(dag["nodes"]):
        fail("PHYSICAL_NODE_ID", "empty graph or duplicate node identity")
    qubits = {q["id"] for q in dag["qubits"]}
    if len(qubits) != len(dag["qubits"]):
        fail("PHYSICAL_QUBIT_ALIAS", "physical carriers must have unique identities")
    parents, children = {n: set() for n in nodes}, {n: set() for n in nodes}
    edges = set()
    for edge in dag["edges"]:
        source, target = edge["source"], edge["target"]
        if source not in nodes or target not in nodes or edge["kind"] not in {"quantum", "classical_ready", "protocol"}:
            fail("PHYSICAL_EDGE", "invalid edge endpoint or kind", target)
        parents[target].add(source)
        children[source].add(target)
        edges.add((source, target, edge["kind"], edge.get("result_id")))
    writers, external = {}, set(dag.get("external_reads", []))
    for node in nodes.values():
        if not set(node["qubits"]) <= qubits or len(set(node["qubits"])) != len(node["qubits"]):
            fail("PHYSICAL_QUBIT_BINDING", "unknown or aliased operation qubit", node["id"])
        if set(node["after"]) != parents[node["id"]]:
            fail("PHYSICAL_AFTER_EDGE_MISMATCH", "after and typed edges disagree", node["id"])
        if not node.get("source_ids") or node["id"] not in dag.get("source_map", {}):
            fail("PHYSICAL_SOURCE_MISSING", "every operation needs inspectable provenance", node["id"])
        if node.get("condition") and node["condition"]["bit"] not in node["reads"]:
            fail("PHYSICAL_CONDITION_READ", "condition is absent from reads", node["id"])
        for bit in node["writes"]:
            if bit in writers or bit in external:
                fail("PHYSICAL_RESULT_ALIAS", "result has multiple producers or aliases an input", node["id"])
            writers[bit] = node["id"]
    for node in nodes.values():
        for bit in node["reads"]:
            if bit in external:
                continue
            if bit not in writers or (writers[bit], node["id"], "classical_ready", bit) not in edges:
                fail("PHYSICAL_CLASSICAL_READY_MISSING", "read needs its typed producer-ready edge", node["id"])
    if writers != dag["result_producers"]:
        fail("PHYSICAL_RESULT_MAP", "result map differs from actual writes")
    remaining = {n: len(p) for n, p in parents.items()}
    ready = [n for n, count in remaining.items() if count == 0]
    visited = 0
    while ready:
        current = ready.pop()
        visited += 1
        for target in children[current]:
            remaining[target] -= 1
            if remaining[target] == 0:
                ready.append(target)
    if visited != len(nodes):
        fail("PHYSICAL_DAG_CYCLE", "dependency graph contains a cycle")
    if set(dag["roots"]) != {n for n in nodes if not parents[n]} or set(dag["terminals"]) != {n for n in nodes if not children[n]}:
        fail("PHYSICAL_FRONTIER", "roots or terminals disagree with edges")
    guard = dag.get("execution_guard")
    if guard and (guard.get("bit") not in external or guard.get("equals") not in (0, 1)):
        fail("PHYSICAL_GUARD", "graph guard must be a declared external ready bit")
    for group in dag["groups"]:
        if group["purpose"] != "maintenance_readout" or len(group["members"]) != 8:
            fail("PHYSICAL_GROUP", "only real eight-ancilla maintenance groups are supported")
        if {m["local_id"] for m in group["members"]} != set(FORMALS[9:]):
            fail("PHYSICAL_GROUP", "group must contain all eight distinct checks")
        for member in group["members"]:
            m = nodes.get(member["measurement_op_id"], {})
            q = member["physical_qubit_id"]
            if m.get("kind") != "measure" or m.get("qubits") != [q] or m.get("writes") != [member["result_id"]]:
                fail("PHYSICAL_GROUP_MEMBER", "readout member differs from its source operation")
            refs = member["transport_after_op_ids"] + member["prepare_op_ids"]
            refs += [member["post_readout_reset_op_id"]] if member["post_readout_reset_op_id"] else []
            if any(ref not in nodes or q not in nodes[ref]["qubits"] for ref in refs):
                fail("PHYSICAL_GROUP_REFERENCE", "readout prerequisite refers to another carrier or missing operation")
    return {"passed": True, "scope": "R3_source_structure_only", "nodes": len(nodes), "edges": len(dag["edges"]),
            "groups": len(dag["groups"]), "physical_compilation_verified": False}
