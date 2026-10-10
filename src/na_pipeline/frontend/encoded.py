"""Versioned encoded semantics; never a physical implementation or cache."""

from copy import deepcopy
import hashlib
import json
import re

from .program import FrontendError

ENCODED_SCHEMA = "EncodedLogicalProgram/0.1.0"
SEMANTIC_VERSION = "1.0.0"
CODE_PROFILE = {"code": "rotated_surface", "distance": 3,
                "convention": "surface17-row-major-x-vertical/1",
                "orientation": "x_vertical_z_horizontal"}
CHECKS = [f"{kind}{i}" for kind in ("x", "z") for i in range(4)]
DATA = [f"d{i}" for i in range(9)]
LABELS = {"execution_kind": "compile_plan", "quantum_state_simulated": False,
          "hardware_executed": False, "loss_enabled": False}
GATES = {"X": "logical_x", "Z": "logical_z", "H": "logical_h", "S": "logical_s",
         "SDG": "logical_sdg", "T": "logical_t", "TDG": "logical_tdg", "CX": "logical_cx", "CZ": "logical_cz"}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def encoded_operation_catalog() -> dict:
    """Semantic declarations, with no invented strategy availability."""
    specs = {
        "prepare": ({"state": ["0", "+"]}, ["block"], CHECKS, ["unprepared", "measured"], "live", "destroy_previous_information_and_encode", False),
        "syndrome_round": ({}, ["block"], CHECKS, ["live"], "live", "preserve_data_extract_eight_checks", False),
        "logical_cx": ({}, ["control", "target"], [], ["live"], "live", "CX_control_to_target", True),
        "logical_cz": ({}, ["left", "right"], [], ["live"], "live", "CZ_symmetric", True),
        "measure": ({"basis": ["Z", "X"]}, ["block"], ["value"], ["live"], "measured", "destructive_logical_observation_preserve_carriers", False),
        "reset": ({}, ["block"], [], ["live", "measured", "unprepared"], "unprepared", "destroy_encoded_information_preserve_carriers", False),
        "release": ({}, ["block"], [], ["measured", "unprepared"], "released", "release_binding_no_implicit_reset_or_atom_creation", False),
    }
    for gate in ("x", "z", "h", "s", "sdg", "t", "tdg"):
        specs["logical_" + gate] = ({}, ["block"], [], ["live"], "live", gate.upper(), True)
    operations = {}
    for name, (params, roles, writes, before, after, effect, conditional) in specs.items():
        operations[name] = {
            "name": name, "semantic_version": SEMANTIC_VERSION, "operand_roles": roles,
            "parameter_values": params, "result_slots": writes.copy(), "pre_lifecycle": before,
            "post_lifecycle": after, "logical_effect": effect, "classical_condition_supported": conditional,
            "repeat_supported": name == "syndrome_round", "semantic_defined": True,
            "strategy_available": False, "qualified": False, "executable": False,
            "frame_effect": "requires_explicit_strategy_and_runtime_frame_contract",
            "resource_requirements": ["encoded_magic_resource_consumption_protocol"] if name in ("logical_t", "logical_tdg") else [],
            "implementation_policy": "qualified_encoded_strategy_only_no_physical_gate_substitution",
        }
    return {"schema_version": "EncodedOperationCatalog/0.1.0", "artifact_id": "encoded-operations-v1",
            "producer_version": "na_pipeline.frontend.encoded/0.1.0", "provenance": {"owner": "R2", "task_id": "T203", "kb_revision": "kb-0005"},
            **LABELS, "operations": operations,
            "availability_scope": "semantic_registry_only_consume_explicit_strategy_snapshot"}


def logical_block_ref(logical_id: str, *, layout_profile_ref: str = "patch_home") -> dict:
    """Unbound logical handle; R5 owns actual atom/physical/frame/time state."""
    return {"logical_id": logical_id, "code_profile": deepcopy(CODE_PROFILE),
            "layout_profile_ref": layout_profile_ref, "port_ref": None,
            "physical_binding_ref": None, "atom_binding_ref": None,
            "frame_ref": None, "ready_ref": None, "runtime_binding_required": True,
            "initial_lifecycle": "unprepared", "initialization_evidence_ref": None}


def _groups(call_id, operation, operands):
    if operation not in ("prepare", "syndrome_round"):
        return []
    block = operands["block"]
    readout = {"group_id": call_id + "/readout", "purpose": "maintenance_readout",
               "logical_block_id": block, "call_id": call_id, "round_slot": "instance_round",
               "members": [{"role": q, "check_type": q[0].upper(), "measurement_basis": "Z",
                            "result_slot": q, "last_coupling_ref": None,
                            "basis_change_ref": None, "preparation_ref": None} for q in CHECKS],
               "source_layout_profile_ref": "$strategy.ez_exit", "target_layout_profile_ref": "$device.mz_group",
               "return_layout_profile_ref": "$strategy.local_entry", "readout_resource_profile_ref": "$device.readout_group",
               "physical_binding_status": "requires_strategy_lowering", "preserve_data": True}
    if operation == "syndrome_round":
        return [readout]
    initialization = {"group_id": call_id + "/initialization", "purpose": "patch_initialization_transport",
                      "logical_block_id": block, "call_id": call_id, "round_slot": "instance_round",
                      "members": [{"role": q} for q in DATA + CHECKS],
                      "source_layout_profile_ref": "$runtime.initialization_entry",
                      "target_layout_profile_ref": "$strategy.prepared_exit", "return_layout_profile_ref": None,
                      "physical_binding_status": "requires_strategy_lowering", "preserve_data": False}
    return [initialization, readout]


def _call(call_id, operation, operands, *, params=None, repeat=1, after=None,
          condition=None, source_ids=None):
    if operation not in encoded_operation_catalog()["operations"]:
        raise FrontendError("UNDEFINED_OPERATION: " + str(operation))
    spec = encoded_operation_catalog()["operations"][operation]
    return {"kind": "logical_call", "id": call_id, "operation": operation,
            "semantic_version": SEMANTIC_VERSION, "operands": dict(operands),
            "params": params or {}, "repeat": repeat, "after": after or [],
            "reads": [] if condition is None else [condition["bit"]], "writes": spec["result_slots"].copy(),
            "condition": deepcopy(condition), "source_ids": source_ids or [f"t000:{call_id}"],
            "groups": _groups(call_id, operation, operands)}


def make_encoded_call(call_id, operation, operands, *, params=None, repeat=1,
                      after=None, condition=None, source_ids=None):
    """Construct semantic slots/groups; validate in their full program context."""
    return _call(call_id, operation, operands, params=params, repeat=repeat,
                 after=after, condition=condition, source_ids=source_ids)


def _program(blocks, body, source_ref=None):
    return {"schema_version": ENCODED_SCHEMA, "artifact_id": "encoded-" + _digest([blocks, body])[:16],
            "producer_version": "na_pipeline.frontend.encoded/0.1.0",
            "provenance": {"owner": "R2", "task_id": "T203", "kb_revision": "kb-0005", "plan_revision": "plan-0007", "fixture": False,
                           "interfaces": {"IF-LOGICAL-OPS-001": "0.3.0", "IF-PATCH-GROUP-001": "0.2.0", "IF-STRATEGY-001": "0.1.0"}},
            **LABELS, "device_profile_ref": "t000-device-profile-unbound",
            "blocks": blocks, "body": body, "source_program_ref": source_ref,
            "input_hashes": {"semantic_input": _digest([blocks, body, source_ref])},
            "scope": "encoded_semantic_input_not_compiled_strategy",
            "strategy_qualification": "not_asserted", "expected_final_lifecycle": {}}


def build_t000_program(rounds: int = 3) -> dict:
    if type(rounds) is not int or not 1 <= rounds <= 10000:
        raise FrontendError("INVALID_ROUNDS: expected 1..10000")
    blocks = [logical_block_ref("L0"), logical_block_ref("L1")]
    body = []
    for block, state in (("L0", "+"), ("L1", "0")):
        body.append(_call(f"prepare.{block}", "prepare", {"block": block}, params={"state": state}))
        body.append(_call(f"before.{block}", "syndrome_round", {"block": block}, repeat=rounds, after=[f"prepare.{block}"]))
    body.append(_call("couple", "logical_cx", {"control": "L0", "target": "L1"}, after=["before.L0", "before.L1"]))
    for block in ("L0", "L1"):
        body.append(_call(f"after.{block}", "syndrome_round", {"block": block}, after=["couple"]))
    result = _program(blocks, body)
    result["expected_final_lifecycle"] = {"L0": "live", "L1": "live"}
    return result


def make_encoded_program(blocks: list[dict], calls: list[dict], *, source_program_ref=None) -> dict:
    result = _program(deepcopy(blocks), deepcopy(calls), deepcopy(source_program_ref))
    errors = validate_encoded_program(result, require_executable=False)
    if errors:
        raise FrontendError("INVALID_ENCODED_SEMANTICS: " + json.dumps(errors, ensure_ascii=False))
    return result


def iter_encoded_calls(program: dict):
    """Repeat binding only; no routing, timings, simulation or result values."""
    if program.get("schema_version") != ENCODED_SCHEMA:
        raise FrontendError("UNSUPPORTED_ENCODED_SCHEMA")
    tails = {}
    for source in program["body"]:
        if source["kind"] != "logical_call" or source["id"] in tails:
            raise FrontendError("INVALID_OR_DUPLICATE_LOGICAL_CALL")
        if source["operation"] not in encoded_operation_catalog()["operations"]:
            raise FrontendError("UNDEFINED_OPERATION: " + str(source["operation"]))
        repeat = source["repeat"]
        if type(repeat) is not int or not 1 <= repeat <= 10000:
            raise FrontendError("INVALID_REPEAT")
        if repeat != 1 and source["operation"] != "syndrome_round":
            raise FrontendError("UNSUPPORTED_REPEAT_OPERATION")
        deps = []
        for dep in source["after"]:
            if dep not in tails:
                raise FrontendError("NONCAUSAL_LOGICAL_DEPENDENCY: " + str(dep))
            deps.append(tails[dep])
        for index in range(repeat):
            call = deepcopy(source)
            call["id"] = f"{source['id']}/r{index}"
            call["source_call_id"] = source["id"]
            call["round_index"] = index
            call["repeat"] = 1
            call["after"] = deps.copy() if index == 0 else [f"{source['id']}/r{index-1}"]
            call["writes"] = [f"{call['id']}/{slot}" for slot in source["writes"]]
            call["source_ids"] = list(dict.fromkeys(source["source_ids"] + [source["id"], call["id"]]))
            for group in call["groups"]:
                group["group_id"] = call["id"] + "/" + group["group_id"].rsplit("/", 1)[-1]
                group["call_id"], group["round_slot"] = call["id"], index
                for member in group["members"]:
                    if "result_slot" in member:
                        member["result_id"] = f"{call['id']}/{member['result_slot']}"
            yield call
        tails[source["id"]] = f"{source['id']}/r{repeat-1}"


def _capability_errors(call, blocks, program, capabilities):
    if capabilities is None:
        return [("STRATEGY_UNAVAILABLE", "no explicit strategy capability snapshot")]
    if (capabilities.get("schema_version") != "EncodedStrategyCapabilities/0.1.0"
            or capabilities.get("device_profile_ref") != program["device_profile_ref"]):
        return [("CAPABILITY_PROFILE_MISMATCH", "schema or device profile differs")]
    if capabilities.get("interface_versions") != program["provenance"]["interfaces"]:
        return [("CAPABILITY_CONTRACT_MISMATCH", "logical/group/strategy interface versions must match this program")]
    profiles = {role: {"code_profile": blocks[block]["code_profile"], "layout_profile_ref": blocks[block]["layout_profile_ref"]}
                for role, block in call["operands"].items()}
    candidates = [entry for entry in capabilities.get("entries", [])
                  if entry.get("operation") == call["operation"]
                  and entry.get("semantic_version") == call["semantic_version"]
                  and entry.get("params") == call["params"] and entry.get("operand_profiles") == profiles]
    if not candidates:
        return [("STRATEGY_UNAVAILABLE", "no matching operation/parameters/direction/profile")]
    failures = []
    for entry in candidates:
        local = []
        if entry.get("strategy_available") is not True or not entry.get("strategy_id"):
            local.append(("STRATEGY_UNAVAILABLE", "strategy is not available"))
        digest = entry.get("strategy_hash", "")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest):
            local.append(("INVALID_STRATEGY_IDENTITY", "SHA-256 strategy identity required"))
        if entry.get("backend_used") not in ("enola", "enola_function_kernel") or not re.fullmatch(r"[a-f0-9]{40}", str(entry.get("enola_pin", ""))):
            local.append(("ENOLA_PROVENANCE_REQUIRED", "actual Enola backend and source commit required"))
        qualification = entry.get("qualification", {})
        if (qualification.get("passed") is not True or qualification.get("strategy_hash") != digest
                or not isinstance(qualification.get("report_ref"), str) or not qualification["report_ref"]):
            local.append(("STRATEGY_NOT_QUALIFIED", "qualification must refer to the same strategy hash"))
        if call["operation"] in ("logical_t", "logical_tdg") and not entry.get("resource_protocol_ref"):
            local.append(("MAGIC_RESOURCE_STRATEGY_REQUIRED", "encoded resource consumption protocol missing"))
        if call["condition"] is not None and entry.get("supports_classical_condition") is not True:
            local.append(("CONDITIONAL_STRATEGY_UNAVAILABLE", "unconditional strategy cannot erase a source condition"))
        if not local:
            return []
        failures.extend(local)
    return list(dict.fromkeys(failures))


def validate_encoded_program(program: dict, *, capabilities=None, require_executable=True) -> list[dict]:
    """Static semantics and optional explicit capability assertions, not R6 QA."""
    errors = []
    def fail(code, source, message):
        errors.append({"code": code, "source_id": source, "message": message})
    try:
        if type(require_executable) is not bool:
            raise ValueError("require_executable must be boolean")
        for key in ("artifact_id", "producer_version", "provenance", "input_hashes"):
            if not program.get(key):
                fail("MISSING_ENVELOPE", "program", key)
        for key, value in LABELS.items():
            if program.get(key) != value or type(program.get(key)) is not type(value):
                fail("INVALID_EVIDENCE_LABEL", "program", key)
        specs = encoded_operation_catalog()["operations"]
        blocks, states = {}, {}
        for block in program["blocks"]:
            logical_id = block["logical_id"]
            if not isinstance(logical_id, str) or not logical_id or logical_id in blocks:
                fail("INVALID_BLOCK_ID", "program", str(logical_id))
            blocks[logical_id] = block
            if block["code_profile"] != CODE_PROFILE:
                fail("UNSUPPORTED_CODE_OR_ORIENTATION", logical_id, "only the declared d3 convention is defined")
            if not isinstance(block["layout_profile_ref"], str) or not block["layout_profile_ref"]:
                fail("MISSING_LAYOUT_PROFILE", logical_id, "entry layout reference required")
            state = block["initial_lifecycle"]
            if state not in ("unprepared", "live") or (state == "live" and not block.get("initialization_evidence_ref")):
                fail("INVALID_INITIAL_LIFECYCLE", logical_id, "live import needs explicit initialization evidence")
            for field in ("physical_binding_ref", "atom_binding_ref", "frame_ref", "ready_ref", "port_ref"):
                if field not in block or (block[field] is not None and not isinstance(block[field], str)):
                    fail("INVALID_BLOCK_BINDING_REF", logical_id, field)
            if block.get("runtime_binding_required") is not True:
                fail("RUNTIME_BINDING_REQUIRED", logical_id, "front-end references do not replace runtime checks")
            states[logical_id] = state
        raw_ids = set()
        for source in program["body"]:
            source_id = source["id"]
            allowed_fields = {"kind", "id", "operation", "semantic_version", "operands", "params", "repeat",
                              "after", "reads", "writes", "condition", "source_ids", "groups", "source_operation", "metadata"}
            if set(source) - allowed_fields:
                fail("UNKNOWN_CALL_FIELD", source_id, str(sorted(set(source) - allowed_fields)))
            if not isinstance(source_id, str) or not source_id or source_id in raw_ids:
                fail("DUPLICATE_CALL_ID", str(source_id), "call IDs must be unique nonempty strings")
            raw_ids.add(source_id)
            name = source["operation"]
            if name not in specs:
                fail("UNDEFINED_OPERATION", source_id, str(name))
                continue
            spec = specs[name]
            if source["semantic_version"] != SEMANTIC_VERSION:
                fail("UNSUPPORTED_SEMANTIC_VERSION", source_id, str(source["semantic_version"]))
            if set(source["operands"]) != set(spec["operand_roles"]):
                fail("INVALID_OPERAND_DIRECTION", source_id, "expected named roles " + str(spec["operand_roles"]))
            values = list(source["operands"].values())
            if len(set(values)) != len(values) or not all(value in blocks for value in values):
                fail("INVALID_LOGICAL_OPERAND", source_id, "unknown or aliased logical blocks")
            params = source["params"]
            if set(params) != set(spec["parameter_values"]) or any(params.get(k) not in allowed for k, allowed in spec["parameter_values"].items()):
                fail("UNSUPPORTED_PARAMETERS", source_id, str(params))
            if source["writes"] != spec["result_slots"]:
                fail("INVALID_RESULT_SLOTS", source_id, "result semantics/slot order must be complete")
            if not isinstance(source["source_ids"], list) or not source["source_ids"] or any(not isinstance(s, str) or not s for s in source["source_ids"]):
                fail("MISSING_SOURCE", source_id, "nonempty source references required")
            condition = source["condition"]
            if condition is not None:
                if not spec["classical_condition_supported"]:
                    fail("CONDITIONAL_LIFECYCLE_UNSUPPORTED", source_id, name)
                if set(condition) != {"bit", "equals"} or type(condition.get("equals")) is not int or condition["equals"] not in (0, 1):
                    fail("INVALID_CLASSICAL_CONDITION", source_id, str(condition))
                if condition["bit"] not in source["reads"]:
                    fail("MISSING_CONDITION_READ", source_id, condition["bit"])
            if set(source["operands"]) == set(spec["operand_roles"]) and all(v in blocks for v in values):
                expected = _groups(source_id, name, source["operands"])
                if source["groups"] != expected:
                    fail("GROUP_INTENT_MISMATCH", source_id, "missing/changed members, basis, slots or transport intent")
                if require_executable:
                    for code, message in _capability_errors(source, blocks, program, capabilities):
                        fail(code, source_id, message)
        # A malformed call cannot participate in lifecycle/causal interpretation.
        if any(e["code"] not in ("STRATEGY_UNAVAILABLE", "STRATEGY_NOT_QUALIFIED", "ENOLA_PROVENANCE_REQUIRED", "CAPABILITY_PROFILE_MISMATCH", "CAPABILITY_CONTRACT_MISMATCH", "CONDITIONAL_STRATEGY_UNAVAILABLE", "INVALID_STRATEGY_IDENTITY", "MAGIC_RESOURCE_STRATEGY_REQUIRED") for e in errors):
            return errors
        parents, producers, last_calls = {}, {}, {}
        def precedes(first, last):
            stack, seen = list(parents[last]), set()
            while stack:
                node = stack.pop()
                if node == first:
                    return True
                if node not in seen:
                    seen.add(node)
                    stack.extend(parents[node])
            return False
        for call in iter_encoded_calls(program):
            ident, name = call["id"], call["operation"]
            parents[ident] = set(call["after"])
            spec = specs[name]
            for bit in call["reads"]:
                if bit not in producers or not precedes(producers[bit], ident):
                    fail("READ_WITHOUT_PRODUCER_DEPENDENCY", ident, str(bit))
            for bit in call["writes"]:
                if bit in producers:
                    fail("RESULT_INSTANCE_REUSE", ident, bit)
                producers[bit] = ident
            for block in call["operands"].values():
                if block in last_calls and not precedes(last_calls[block], ident):
                    fail("MISSING_BLOCK_ORDER", ident, block)
                if states[block] not in spec["pre_lifecycle"]:
                    fail("INVALID_LIFECYCLE", ident, f"{block}: {states[block]} -> {name}")
                states[block] = spec["post_lifecycle"]
                last_calls[block] = ident
        for block, expected in program.get("expected_final_lifecycle", {}).items():
            if states.get(block) != expected:
                fail("FINAL_LIFECYCLE_MISMATCH", block, str(expected))
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        fail("MALFORMED_ENCODED_PROGRAM", "program", str(exc))
    return errors


def adapt_logical_program(program: dict, block_map: dict, *, capabilities=None) -> dict:
    """Bounded source adapter; all-or-error, never a physical gate substitution.

    Full Shor composition is deliberately outside T203. Its existing source,
    synthesis and artifacts remain untouched. This adapter accepts explicit
    initialization, declared gate semantics and Z measurement in smaller inputs.
    """
    from .program import iter_logical_ops, validate_logical
    if str(program.get("capability_profile", "")).startswith("shor15-") or program.get("branch_global_phases"):
        raise FrontendError("SHOR_ADAPTER_NOT_ENABLED_IN_T203: keep the full algorithm source for later composition")
    errors = validate_logical(program)
    if errors:
        raise FrontendError("INVALID_ALGORITHM_SOURCE: " + json.dumps(errors))
    qubits = [q["id"] for q in program["qubits"]]
    if set(block_map) != set(qubits) or len(set(block_map.values())) != len(qubits):
        raise FrontendError("INVALID_LOGICAL_BLOCK_MAP")
    blocks = [logical_block_ref(block_map[q]) for q in qubits]
    body, operation_tails, result_aliases, live = [], {}, {}, set()
    for op in iter_logical_ops(program):
        targets = [block_map[q] for q in op["qubits"]]
        deps = [operation_tails[dep] for dep in op["after"]]
        condition = None
        if op["condition"] is not None:
            bit = op["condition"]["bit"]
            if bit not in result_aliases:
                raise FrontendError("UNSUPPORTED_ALGORITHM_RESULT_REFERENCE: " + bit)
            condition = {"bit": result_aliases[bit], "equals": op["condition"]["equals"]}
        source_ids = list(dict.fromkeys(op["source_ids"] + [op["id"], program["artifact_id"]]))
        call_id = op["id"] + "/encoded"
        if op["kind"] == "reset":
            if condition is not None:
                raise FrontendError("CONDITIONAL_LIFECYCLE_UNSUPPORTED")
            if targets[0] in live:
                discard = _call(call_id + "/discard", "reset", {"block": targets[0]}, after=deps, source_ids=source_ids)
                body.append(discard)
                deps = [discard["id"]]
            call = _call(call_id, "prepare", {"block": targets[0]}, params={"state": "0"}, after=deps, source_ids=source_ids)
            live.add(targets[0])
        elif op["kind"] == "measure":
            if condition is not None:
                raise FrontendError("CONDITIONAL_LIFECYCLE_UNSUPPORTED")
            call = _call(call_id, "measure", {"block": targets[0]}, params={"basis": op["params"]["basis"]}, after=deps, source_ids=source_ids)
            result_aliases[op["writes"][0]] = call_id + "/r0/value"
            live.discard(targets[0])
        elif op["kind"] == "gate":
            name = op["params"].get("name")
            if name not in GATES or set(op["params"]) != {"name"}:
                raise FrontendError("UNSUPPORTED_ALGORITHM_GATE_OR_PARAMETERS: " + op["id"])
            encoded_name = GATES[name]
            roles = encoded_operation_catalog()["operations"][encoded_name]["operand_roles"]
            call = _call(call_id, encoded_name, dict(zip(roles, targets)), after=deps, condition=condition, source_ids=source_ids)
        else:
            raise FrontendError("UNSUPPORTED_ALGORITHM_OPERATION: " + op["id"])
        call["source_operation"] = deepcopy(op)
        if any(bit not in result_aliases for bit in op["reads"]):
            raise FrontendError("UNSUPPORTED_ALGORITHM_READ")
        call["reads"] = [result_aliases[bit] for bit in op["reads"]]
        body.append(call)
        operation_tails[op["id"]] = call["id"]
    result = _program(blocks, body, {"artifact_id": program["artifact_id"], "schema_version": program["schema_version"], "canonical_sha256": _digest(program)})
    result["algorithm_result_aliases"] = result_aliases
    result["provenance"]["fixture"] = bool(program.get("provenance", {}).get("fixture")
                                           or (capabilities or {}).get("fixture"))
    result["capability_snapshot_ref"] = None if capabilities is None else {
        "schema_version": capabilities.get("schema_version"), "canonical_sha256": _digest(capabilities),
        "fixture": capabilities.get("fixture", False), "scope": "assertion_consistency_not_independent_qualification"}
    errors = validate_encoded_program(result, capabilities=capabilities)
    if errors:
        raise FrontendError("ENCODED_ADAPTATION_REJECTED: " + json.dumps(errors, ensure_ascii=False))
    return result
