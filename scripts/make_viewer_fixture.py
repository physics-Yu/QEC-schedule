"""Generate a tiny explicitly labelled viewer fixture, never a pipeline result."""
from __future__ import annotations
import argparse
from copy import deepcopy
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from na_pipeline.cli import canonical_hash, write_json
from viewer import export_view


def fixture():
    flags = {"quantum_state_simulated": False, "hardware_executed": False, "loss_enabled": False}
    atoms = [{"atom_id": a, "qubit_id": "q/" + a, "position_um": p, "carrier": "SLM", "trap_id": "s/" + a, "aod_group": g, "row_id": None, "column_id": None} for a, p, g in [("a0", [0, 0], "data"), ("a1", [10, 0], "data"), ("a2", [20, 20], "magic")]]
    actions = []
    def add(kind, start, end, payload, *, ids=None, condition=None):
        aid = f"fixture/{len(actions)}"
        action = {"id": aid, "kind": kind, "atoms": ids if ids is not None else ["a0"], "t_start_us": start, "t_end_us": end, "resources": ["fixture-only"], "source_ids": ["fixture/physical/" + str(len(actions))], "depends_on": [actions[-1]["id"]] if actions else [], "condition": condition, "payload": payload}
        actions.append(action)
        return action
    add("pickup", 0, 2, {"from_trap_id": "s/a0", "to_trap_id": "aod/data/0", "aod_group": "data", "row_id": "r0", "column_id": "c0", "position_um": [0, 0]})
    def move(start, end, begin, finish):
        add("move", start, end, {"aod_group": "data", "interpolation": "linear", "trajectories": [{"atom_id": "a0", "from_um": begin, "to_um": finish, "row_id": "r0", "column_id": "c0"}]})
    move(2, 10, [0, 0], [8, 0])
    add("gate", 10, 11, {"name": "CZ", "pairs": [["a0", "a1"]], "broadcast": True, "zone_id": "fixture/storage"}, ids=["a0", "a1"])
    move(11, 41, [8, 0], [8, 30])
    add("measure", 41, 46, {"basis": "Z", "result_id": "fixture/m0", "result_ready_us": 49, "origin": "fake"})
    add("wait", 46, 50, {"reason": "readout and feedback"})
    add("gate", 50, 51, {"name": "X", "params": {}}, condition={"bit": "fixture/m0", "equals": 0})
    add("reset", 51, 53, {"state": 0})
    add("drop", 53, 55, {"from_trap_id": "aod/data/0", "to_trap_id": "s/readout", "aod_group": "data", "row_id": "r0", "column_id": "c0", "position_um": [8, 30]})
    traps = [{"trap_id": a["trap_id"], "position_um": a["position_um"], "occupant": a["atom_id"], "zone_id": "fixture/storage"} for a in atoms] + [{"trap_id": "s/readout", "position_um": [8, 30], "occupant": None, "zone_id": "fixture/measurement"}]
    atom = {"schema_version": "AtomProgram/0.2.0-draft", "artifact_id": "R7-viewer-fixture", "execution_kind": "compile_plan", **flags, "provenance": {"fixture": True, "producer": "R7 viewer fixture; not R3/R4 output"}, "device_ref": "fixture-device", "complete": True, "initial_state": {"atoms": atoms, "slm_traps": traps, "aod_rows": [], "aod_columns": []}, "actions": actions, "source_map": {a["source_ids"][0]: [a["id"]] for a in actions}, "stats": {"duration_us": 55}}
    events = [{"action_id": a["id"], **{k: deepcopy(v) for k, v in a.items() if k != "id"}, "status": "skipped" if a["condition"] else "completed", "condition_reads": {"fixture/m0": {"value": 1, "origin": "fake", "ready_us": 49}} if a["condition"] else {}, "result_ids": ["fixture/m0"] if a["kind"] == "measure" else []} for a in actions]
    trace = {"schema_version": "EventTrace/0.2.0-draft", "artifact_id": "R7-viewer-fixture-run", "execution_kind": "fake_event_run", **flags, "provenance": {"fixture": True, "producer": "R7 handcrafted fixture; not R5 execution"}, "atom_program_ref": atom["artifact_id"], "input_hashes": {"atom_program": canonical_hash(atom)}, "events": events, "results": {"fixture/m0": {"value": 1, "origin": "fake", "ready_us": 49, "available_us": 49, "action_id": "fixture/4"}}, "illumination_counts": {"a0": 1, "a1": 1, "a2": 1}, "final_state": {}, "stats": {"duration_us": 55}}
    trace.update(measurement_origin="fake", sampled=False)
    return atom, trace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=ROOT / "viewer/examples/fixture")
    args = parser.parse_args()
    atom, trace = fixture()
    write_json(args.out / "atom.json", atom)
    write_json(args.out / "trace.json", trace)
    print(export_view(args.out / "atom.json", args.out / "viewer.html", trace_path=args.out / "trace.json"))


if __name__ == "__main__":
    main()
