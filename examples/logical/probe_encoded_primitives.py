"""Consume actual R3 public inputs and check R2 field/slot/group correspondence.

No compiled strategies, routing or runtime are produced by this probe.
"""

import argparse
import hashlib
import json
from pathlib import Path

from na_pipeline.frontend import build_t000_program, iter_encoded_calls, validate_encoded_program
from na_pipeline.qec import build_logical_primitive, validate_primitive_contract


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def probe():
    program = build_t000_program()
    assert not validate_encoded_program(program, require_executable=False)
    physical_inputs, mappings = {}, []
    blocks = {block["logical_id"]: block for block in program["blocks"]}
    for call in iter_encoded_calls(program):
        key = call["operation"] + ":" + json.dumps(call["params"], sort_keys=True)
        if key not in physical_inputs:
            physical_inputs[key] = build_logical_primitive(call["operation"], params=call["params"])
        physical = physical_inputs[key]
        assert not validate_primitive_contract(physical)
        contract = physical["strategy_contract"]
        operation = contract["operation"]
        assert operation["name"] == call["operation"]
        assert operation["params"] == call["params"]
        assert operation["semantic_version"] == call["semantic_version"]
        assert list(call["operands"]) == operation["formal_operands"]
        assert all(blocks[b]["code_profile"] == operation["code_profile"] for b in call["operands"].values())
        slots = {slot["encoded_result_slot"]: slot["result_id"] for slot in contract["formal_bindings"]["result_slots"]}
        assert set(call["writes"]) == {call["id"] + "/" + slot for slot in slots}
        groups = []
        for group in call["groups"]:
            formal = next(role for role, actual in call["operands"].items() if actual == group["logical_block_id"])
            matches = [g for g in contract["groups"] if g["formal_block"] == formal and g["purpose"] == group["purpose"]]
            assert len(matches) == 1
            match = matches[0]
            assert {m["role"] for m in group["members"]} == {m["local_role"] for m in match["members"]}
            if group["purpose"] == "maintenance_readout":
                by_role = {m["local_role"]: m for m in match["members"]}
                for member in group["members"]:
                    peer = by_role[member["role"]]
                    assert peer["check_type"] == member["check_type"]
                    assert peer["measurement_basis"] == member["measurement_basis"]
                    assert peer["encoded_result_slot"] == member["result_slot"]
            groups.append({"encoded_group_id": group["group_id"], "formal_group_id": match["group_id"], "members": len(group["members"])})
        mappings.append({"encoded_call_id": call["id"], "operation": call["operation"],
                         "formal_physical_artifact_id": physical["artifact_id"], "formal_physical_sha256": digest(physical),
                         "formal_contract_sha256": digest(contract), "groups": groups,
                         "result_slot_mapping": {call["id"] + "/" + slot: result for slot, result in slots.items()},
                         "binding_note": "R5 must further bind run/call/atom/time; formal result IDs are not live results"})
    return {"schema_version": "R2R3PrimitiveFieldProbe/0.1.0", "artifact_id": "T203-R3-field-probe",
            "provenance": {"owner": "R2", "task_id": "T203", "kb_revision": "kb-0005", "fixture": False},
            "execution_kind": "compile_plan", "quantum_state_simulated": False, "hardware_executed": False, "loss_enabled": False,
            "scope": "actual_R2_and_R3_public_semantic_inputs_only", "field_correspondence_passed": True,
            "encoded_program_sha256": digest(program), "distinct_formal_physical_inputs": len(physical_inputs),
            "calls": mappings, "strategy_compile_or_search_measured": False, "enola_executed": False,
            "runtime_executed": False, "T000_qualification_passed": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    output = Path(__file__).resolve().parent / "t000/primitive_interface_probe.json"
    report = probe()
    data = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()
    if args.check:
        if output.read_bytes() != data:
            raise SystemExit("producer field probe changed")
    else:
        output.write_bytes(data)
    print(json.dumps({"calls_checked": len(report["calls"]), "actual_producer": "R3",
                      "fields_passed": True, "strategy_or_runtime_qualification": False}))
