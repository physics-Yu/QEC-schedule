"""Formal physical inputs for complete reusable logical-operation strategies.

These inputs contain no actual atom binding, geometry, clock, or fake result.
R4 must compile and qualify the whole transport/EZ/MZ/return cycle separately.
"""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from .program import iter_physical_ops
from .surface17 import (CHECKS, CONVENTION, DATA, FORMALS, LOGICAL_X, LOGICAL_Z,
                        _op, _templates)

PRIMITIVE_VERSION = "0.1.0"
CONTRACT_SCHEMA = "strategy_contract/0.1"
ENCODING = {"family": "rotated_surface", "distance": 3,
            "orientation": "x_vertical_z_horizontal", "logical_convention": CONVENTION,
            "logical_x": [f"d{i}" for i in LOGICAL_X], "logical_z": [f"d{i}" for i in LOGICAL_Z]}
CODE_PROFILE = {"code": "rotated_surface", "distance": 3, "convention": CONVENTION,
                "orientation": "x_vertical_z_horizontal"}


class LogicalPrimitiveError(ValueError):
    def __init__(self, code, message, *, operation=None):
        self.code, self.operation = code, operation
        super().__init__(f"{code}: {message}; operation={operation}")


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                             allow_nan=False).encode("utf-8")).hexdigest()


def _source_identity():
    root = Path(__file__).resolve().parent
    return {name: sha256((root / name).read_bytes()).hexdigest()
            for name in ("surface17.py", "program.py", "logical_primitives.py")}


def logical_primitive_capabilities() -> dict:
    """Physical source availability only, never backend or execution eligibility."""
    return {"schema_version": "qec-primitive-capabilities/0.1", "producer_version": PRIMITIVE_VERSION,
            "encoding": deepcopy(ENCODING), "code_profile": deepcopy(CODE_PROFILE), "operations": {
                "prepare": {"params": {"state": ["0", "+"]}, "physical_input_available": True},
                "syndrome_round": {"params": {}, "physical_input_available": True},
                "logical_cx": {"params": {}, "physical_input_available": True},
                **{op: {"physical_input_available": False, "reason": "not_in_T303_core_profile"}
                   for op in ("measure", "reset", "release", "logical_x", "logical_z", "logical_h", "logical_s",
                              "logical_sdg", "logical_t", "logical_tdg", "logical_cz")}},
            "compiled_strategy_available": False, "enola_integrated": False, "qualified": False,
            "qualification_owner": "R4_R6_R0", "fake_values_cached": False}


def _parameters(operation, params):
    if operation not in {"prepare", "syndrome_round", "logical_cx"}:
        raise LogicalPrimitiveError("UNSUPPORTED_LOGICAL_PRIMITIVE", "no T303 physical input for this operation", operation=operation)
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise LogicalPrimitiveError("INVALID_PRIMITIVE_PARAMS", "params must be an object", operation=operation)
    if operation == "prepare":
        if set(params) != {"state"} or params["state"] not in ("0", "+"):
            raise LogicalPrimitiveError("INVALID_PREPARE_STATE", "prepare requires exactly state=0 or + as a string", operation=operation)
    elif params:
        raise LogicalPrimitiveError("UNSUPPORTED_PRIMITIVE_PARAMS", "round repetition and call conditions belong to the controller", operation=operation)
    return deepcopy(params)


def _physical_core(program):
    return {key: program[key] for key in ("qubits", "templates", "body")}


def _member(block, local):
    return {"physical_qubit_id": f"{block}/{local}", "atom_slot": f"atom:{block}/{local}",
            "formal_block": block, "local_role": local}


def _readout_group(ops, block):
    members = []
    for local, basis, _, _ in CHECKS:
        q = f"{block}/{local}"
        couplings = [op for op in ops if op["kind"] == "gate" and op["params"]["name"] == "CX" and q in op["qubits"]]
        measure = next(op for op in ops if op["kind"] == "measure" and op["qubits"] == [q])
        basis_op = next((op for op in ops if op["id"].endswith("/read_basis_" + local)), None)
        initial_reset = next(op for op in ops if op["id"].endswith("/reset_" + local))
        post_reset = next(op for op in ops if op["id"].endswith("/service_reset_" + local))
        input_h = next((op for op in ops if op["id"].endswith("/prepare_" + local)), None)
        ready = [couplings[-1]["id"]]
        if basis_op:
            ready.append(basis_op["id"])
        members.append({**_member(block, local), "check_id": local, "check_type": basis,
                        "measurement_basis": "Z", "last_coupling_op_id": couplings[-1]["id"],
                        "basis_change_op_id": basis_op["id"] if basis_op else None,
                        "prepare_op_ids": [initial_reset["id"]] + ([input_h["id"]] if input_h else []),
                        "transport_after_op_ids": ready, "readout_after_op_ids": ready,
                        "measurement_op_id": measure["id"], "result_id": measure["writes"][0], "encoded_result_slot": local,
                        "post_readout_reset_op_id": post_reset["id"],
                        "return_after_op_ids": [post_reset["id"]], "mz_slot_role": local})
    return {"group_id": f"maintenance.{block}.r0", "purpose": "maintenance_readout", "formal_block": block,
            "round_slot": "r0", "members": members, "source_layout_profile_role": "patch_home",
            "target_layout_profile_role": "syndrome_mz", "readout_resource_profile_role": "patch_group_z_readout",
            "source_layout_id": "patch_home", "target_layout_id": "ancilla_readout", "return_layout_id": "patch_home",
            "return_layout_profile_role": "patch_home", "return_required": True,
            "transport_policy": "compatible_groups_allow_early_members",
            "readout_policy": "earliest_common_feasible_start", "scope": "one_patch_one_round",
            "split_policy": "explicit_constraint_reason_required", "numeric_synchronization_tolerance_us": None}


def _initialization_group(ops, block):
    members = []
    for local in FORMALS:
        q = f"{block}/{local}"
        first = next(op for op in ops if q in op["qubits"])
        assert first["kind"] == "reset"
        members.append({**_member(block, local), "prepare_before_op_ids": [first["id"]],
                        "transport_after_op_ids": [], "requires_present_carrier": True,
                        "source_slot_role": local, "target_slot_role": local})
    return {"group_id": f"initialization.{block}", "purpose": "patch_initialization_transport", "formal_block": block,
            "round_slot": "initialization", "members": members, "source_layout_profile_role": "initialization_entry",
            "target_layout_profile_role": "patch_home", "transport_policy": "complete_patch_group",
            "source_layout_id": "patch_initialization", "target_layout_id": "patch_home", "return_layout_id": None,
            "scope": "one_patch", "required_member_count": 17,
            "split_policy": "explicit_constraint_reason_required", "destination_is_measurement_zone": False,
            "initial_state_may_not_skip_transport": True}


def build_logical_primitive(operation: str, *, params: dict | None = None) -> dict:
    """Return a stable formal PhysicalProgram and its complete-cycle requirements."""
    if not isinstance(operation, str):
        raise LogicalPrimitiveError("INVALID_PRIMITIVE_NAME", "operation must be a string")
    params = _parameters(operation, params)
    operands = ["control", "target"] if operation == "logical_cx" else ["block"]
    library = _templates()
    if operation == "prepare":
        key = "s17.prepare_zero.v1" if params["state"] == "0" else "s17.prepare_plus.v1"
    else:
        key = "s17.syndrome.v1" if operation == "syndrome_round" else "s17.transversal_cx.v1"
    physical_template = deepcopy(library[key])
    tid = f"s17.logical.{operation}.{params.get('state', 'default').replace('+', 'plus')}.v1"
    physical_template["template_id"] = tid
    if operation != "logical_cx":
        # Readout service completes the cycle before the strategy returns home.
        # The next round retains its explicit initial reset as a conservative
        # preparation guarantee; both costs remain visible in the source.
        physical_template["body"] += [_op(f"service_reset_{q}", "reset", [q], {"basis": "Z"},
                                           after=[f"measure_{q}"]) for q in FORMALS[9:]]
        bindings = {q: f"block/{q}" for q in FORMALS}
    else:
        bindings = {f"{p}{i}": f"{block}/d{i}" for p, block in (("c", "control"), ("t", "target")) for i in range(9)}
    physical_template["metadata"]["logical_primitive"] = {"name": operation, "params": params, "version": PRIMITIVE_VERSION}
    qubits = [{"id": f"{block}/{q}", "block_id": block, "local_id": q, "role": "data" if q in DATA else "syndrome",
               "aod_group": "data", "formal": True}
              for block in operands for q in FORMALS]
    program = {"schema_version": "physical-program/0.2.0-draft", "artifact_id": "pending-formal-id",
               "producer_version": f"na_pipeline.qec.logical_primitives/{PRIMITIVE_VERSION}",
               "provenance": {"producer": "R3", "task_id": "T303", "kb_revision": "kb-0005", "planning_revision": "plan-0007",
                              "interface_version": "IF-STRATEGY-001/0.1.0", "fixture": False, "binding_scope": "formal"},
               "execution_kind": "compile_plan", "quantum_state_simulated": False, "hardware_executed": False,
               "loss_enabled": False, "device_ref": None, "device_ref_reason": "R4 resolves R1 full-cycle profiles",
               "qubits": qubits, "templates": {tid: physical_template},
               "body": [{"kind": "call", "id": "primitive", "template_id": tid, "bindings": bindings, "repeat": 1,
                         "source_ids": [f"R3:T303:{operation}", "surface17-circuit-convention/1"]}]}
    physical_hash = _hash(_physical_core(program))
    program["artifact_id"] = f"logical-primitive-{operation}-{physical_hash[:16]}"
    ops = list(iter_physical_ops(program))
    groups = []
    if operation == "prepare":
        groups.append(_initialization_group(ops, "block"))
    if operation != "logical_cx":
        groups.append(_readout_group(ops, "block"))
    physical_roles = [_member(block, q) for block in operands for q in FORMALS]
    results = [{"result_id": bit, "encoded_result_slot": op["qubits"][0].split("/")[-1],
                "producer_op_id": op["id"], "physical_qubit_id": op["qubits"][0],
                "measurement_basis": "Z", "check_type": "X" if op["qubits"][0].split("/")[-1].startswith("x") else "Z"}
               for op in ops for bit in op["writes"]]
    replacing = operation == "prepare"
    entry = {"layout_profile_role": "initialization_entry" if replacing else "patch_home",
             "layout_profile_id": "patch_initialization" if replacing else "patch_home",
             "formal_blocks": operands, "orientation": ENCODING["orientation"], "carrier": "SLM",
             "occupancy": "all_17_members_present_per_patch", "aod_occupancy": "empty_for_bound_members",
             "requires_encoded_data": not replacing, "allows_data_destruction": replacing,
             "requires_lifecycle_authorization": "prepare_uninitialized_or_explicit_discard" if replacing else "live_encoded_block"}
    exit = {"layout_profile_role": "patch_home", "layout_profile_id": "patch_home", "formal_blocks": operands, "orientation": ENCODING["orientation"],
            "carrier": "SLM", "occupancy": "same_carriers_as_entry", "aod_occupancy": "empty_for_bound_members",
            "data_effect": f"prepared_{params['state']}_L" if replacing else "logical_cx" if operation == "logical_cx" else "preserved_unmeasured",
            "ancilla_effect": "preserved" if operation == "logical_cx" else "reset_zero_and_returned",
            "results_effect": "new_independent_ready_slots" if results else "no_results",
            "frame_effect": "explicit_prepare_sign_corrections" if replacing else "no_decoder_update",
            "requires_completed_actions_and_published_results": True,
            "home_relation": "declared_target_home" if replacing else "same_formal_home_as_entry",
            "next_local_primitive": "syndrome_round"}
    contract = {"schema_version": CONTRACT_SCHEMA, "producer_version": PRIMITIVE_VERSION,
                "operation": {"name": operation, "semantic_version": "1.0.0", "params": params,
                              "formal_operands": operands, "direction": {"control": "control", "target": "target"} if operation == "logical_cx" else None,
                              "encoding": deepcopy(ENCODING), "code_profile": deepcopy(CODE_PROFILE),
                              "encoded_result_slots": [q for q in FORMALS[9:]] if results else []},
                "formal_bindings": {"physical_qubits": physical_roles, "result_slots": results,
                                    "source_ids": list(dict.fromkeys(s for op in ops for s in op["source_ids"]))},
                "entry": entry, "exit": exit, "groups": groups,
                "physical_input_hash": physical_hash, "qec_source_sha256": _source_identity(),
                "profile_resolution": {"owner": "R1_R4", "status": "requires_device_profile_binding",
                                       "grouped_profile_schema": "grouped-device-profile/0.1", "grouped_profile_id": "surface17-grouped-v1",
                                       "producer_contract": "R1-GROUP-IF-001/0.1.0",
                                       "readout_profile_pointer": "/grouped_profile/readout",
                                       "cache_must_bind": ["layout_profiles", "group_profiles", "device", "enola_pin", "compiler_rules"]},
                "unsupported_conditions": ["whole_call_condition", "non_d3_or_changed_encoding", "mirrored_or_rotated_convention",
                                           "missing_carrier", "unknown_layout_or_group_profile", "real_decoder_noise_loss"],
                "protocol_source": ["R3-QEC-001/0.1.0", "IF-PATCH-GROUP-001/0.2.0", "R8-FACT-013@0.1.0", "R8-FACT-017@0.1.0"],
                "qualification": {"physical_input": "implemented", "compiled_strategy": "not_qualified",
                                  "enola": "not_asserted_by_R3", "runtime": "not_qualified",
                                  "independent_validation": "pending", "user_visual": "pending"}}
    contract["contract_hash"] = _hash(contract)
    program["strategy_contract"] = contract
    program["input_hashes"] = {"physical_input": physical_hash, "strategy_contract": contract["contract_hash"]}
    return program


def validate_primitive_contract(program) -> list[dict]:
    """Strict author qualification of the supported formal primitive recipes."""
    errors = []
    def fail(code, path, message):
        errors.append({"code": code, "path": path, "message": message})
    try:
        contract = program["strategy_contract"]
        if contract.get("schema_version") != CONTRACT_SCHEMA:
            fail("STRATEGY_CONTRACT_VERSION", "/strategy_contract/schema_version", "unsupported contract schema")
            return errors
        expected = build_logical_primitive(contract["operation"]["name"], params=contract["operation"]["params"])
        if set(program) != set(expected):
            fail("UNSUPPORTED_PRIMITIVE_FIELDS", "/", "formal input fields are versioned; runtime results, frames and bindings belong outside the cached source")
        for key in ("schema_version", "execution_kind", "quantum_state_simulated", "hardware_executed", "loss_enabled", "device_ref"):
            if program.get(key) != expected[key]:
                fail("PRIMITIVE_EVIDENCE_SCOPE", "/" + key, "formal compile input cannot claim runtime, hardware or state execution")
        if program.get("provenance", {}).get("binding_scope") != "formal":
            fail("FORMAL_BINDING_SCOPE", "/provenance/binding_scope", "this validator qualifies formal source, not a bound call")
        for key, code in (("qubits", "FORMAL_QUBITS_CHANGED"), ("templates", "PHYSICAL_SOURCE_CHANGED"), ("body", "FORMAL_CALL_CHANGED")):
            if program[key] != expected[key]:
                fail(code, "/" + key, "formal primitive differs from the versioned physical recipe")
        for key in ("operation", "formal_bindings", "entry", "exit", "groups", "profile_resolution", "unsupported_conditions", "protocol_source", "qualification"):
            if contract.get(key) != expected["strategy_contract"][key]:
                fail("GROUP_CONTRACT_CHANGED" if key == "groups" else "STRATEGY_SEMANTICS_CHANGED", "/strategy_contract/" + key,
                     "field differs from supported complete-cycle requirements")
        if contract.get("qec_source_sha256") != expected["strategy_contract"]["qec_source_sha256"]:
            fail("QEC_SOURCE_CHANGED", "/strategy_contract/qec_source_sha256", "producer code differs; requalify source")
        physical_hash = _hash(_physical_core(program))
        if contract.get("physical_input_hash") != physical_hash:
            fail("PHYSICAL_INPUT_HASH", "/strategy_contract/physical_input_hash", "source hash mismatch")
        without_hash = {k: v for k, v in contract.items() if k != "contract_hash"}
        if contract.get("contract_hash") != _hash(without_hash):
            fail("STRATEGY_CONTRACT_HASH", "/strategy_contract/contract_hash", "contract hash mismatch")
        if program.get("input_hashes") != {"physical_input": physical_hash, "strategy_contract": contract.get("contract_hash")}:
            fail("ENVELOPE_HASH", "/input_hashes", "envelope hashes do not bind this input")
        list(iter_physical_ops(program))
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        fail("INVALID_PRIMITIVE_CONTRACT", "/", str(exc))
    return errors
