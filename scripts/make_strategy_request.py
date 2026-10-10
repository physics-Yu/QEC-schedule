"""Adapt actual R2 logical calls and R1 entry layouts to R5 public registration.

This creates explicit inputs, not execution or strategy qualification evidence.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from na_pipeline.cli import canonical_hash, write_json
from na_pipeline.device import grouped_device, group_layout
from na_pipeline.frontend import build_t000_program, iter_encoded_calls, validate_encoded_program, logical_block_ref, make_encoded_call, make_encoded_program


def request_for(case):
    if case == "coupled":
        encoded = build_t000_program(rounds=3)
    else:
        blocks = [logical_block_ref(f"L{i}") for i in range(1 if case == "single" else 2)]
        calls = []
        for block in blocks:
            lid = block["logical_id"]
            prep = make_encoded_call("prepare." + lid, "prepare", {"block": lid}, params={"state": "0"})
            maintenance = make_encoded_call("memory." + lid, "syndrome_round", {"block": lid}, repeat=3, after=[prep["id"]])
            calls.extend((prep, maintenance))
        encoded = make_encoded_program(blocks, calls)
    if errors := validate_encoded_program(encoded, require_executable=False):
        raise ValueError(f"ENCODED_INPUT_INVALID: {errors}")
    device = grouped_device()
    world = {"atoms": [], "slm_traps": [], "aod_rows": [], "aod_columns": [], "time_us": 0}
    registrations, offsets = [], {}
    for i, block in enumerate(encoded["blocks"]):
        lid = block["logical_id"]
        offsets[lid] = [100.0 * i, 0.0]  # explicit input geometry, checked by R4 binding
        layouts = {name: group_layout(device, name, offset_um=offsets[lid]) for name in ("patch_initialization", "patch_home", "ancilla_readout")}
        qubits = {slot: lid + "/" + slot for slot in layouts["patch_initialization"]["slots"]}
        for name, layout in layouts.items():
            for slot, data in layout["slots"].items():
                qid = qubits[slot]
                aid = "atom:" + qid
                tid = "slm:" + name + ":" + qid
                world["slm_traps"].append({"trap_id": tid, "position_um": data["position_um"], "zone_id": layout["zone_id"], "occupant": aid if name == "patch_initialization" else None})
                if name == "patch_initialization":
                    world["atoms"].append({"atom_id": aid, "qubit_id": qid, "position_um": data["position_um"], "carrier": "SLM", "trap_id": tid, "aod_group": "data", "row_id": None, "column_id": None})
        registrations.append({"logical_id": lid, "qubits": qubits, "data_slots": [f"d{i}" for i in range(9)], "code_profile": block["code_profile"], "layout_profile": block["layout_profile_ref"], "lifecycle": "unprepared", "offset_um": offsets[lid]})
    expanded = list(iter_encoded_calls(encoded))
    # R4 local template IDs exclude '/'. Retain a complete explicit bijection.
    id_map = {call["id"]: f"call{index:03d}" for index, call in enumerate(expanded)}
    queued = []
    for call in expanded:
        if call["condition"] is not None or call["reads"]:
            raise ValueError("UNSUPPORTED_LOGICAL_CONDITION: cannot discard encoded feedback")
        first = call["operands"].get("control", call["operands"].get("block"))
        queued.append({"operation": call["operation"], "operands": call["operands"], "call_id": id_map[call["id"]], "params": call["params"], "offset_um": offsets[first], "after": [id_map[dep] for dep in call["after"]], "source_ids": [*call["source_ids"], call["id"], encoded["artifact_id"]]})
    return {"schema_version": "r7-logical-run-request/0.1.0", "run_id": "T703-" + case, "device": device, "initial_state": world, "blocks": registrations, "calls": queued, "encoded_program": encoded, "encoded_call_bindings": id_map, "provenance": {"fixture": False, "producer": "R7 adapter of public R2/R1 inputs", "encoded_canonical_sha256": canonical_hash(encoded), "status": "unexecuted_input; no strategy or geometry acceptance implied", "logical_scope": case, "namespace_adapter": "explicit bijection from original expanded call IDs to R4-compatible template IDs; original IDs remain in source_ids", "patch_offset_rule": "100 um in x per block; explicit input choice, not hardware isolation threshold"}}


def encoded_request_for(case):
    request = request_for(case)
    request.pop("calls")
    request.pop("encoded_call_bindings")
    request["controller_input"] = "encoded_program"
    request["provenance"]["namespace_adapter"] = "R5 public queue_encoded_program; exact original R2 program passed intact"
    return request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=("single", "two", "coupled"), default="coupled")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    value = encoded_request_for(args.case)
    out = args.out or ROOT / f"scripts/outputs/T703/requests/{args.case}.json"
    write_json(out, value)
    print(f"{out}: {len(value['blocks'])} blocks, {len(list(iter_encoded_calls(value['encoded_program'])))} native encoded calls, unexecuted input")


if __name__ == "__main__":
    main()
