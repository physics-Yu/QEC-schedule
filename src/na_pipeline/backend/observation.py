"""External raw-call collection for D07; R4 tooling, independently auditable by R6.

This observer reads only actual function arguments/returns and source hashes.
It never copies author decisions as if they were observed original returns.
"""
from collections import Counter
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import sys
import time
import gzip
import json

from .enola_kernel import digest


class RawCompilerObserver:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.sources = {
            str((self.root/"third_party/enola/upstream/enola/scheduler/gate_scheduler.py").resolve()): ("enola/scheduler/gate_scheduler.py", "pinned_upstream", {"gate_scheduling", "graph_coloring_rustworkx"}),
            str((self.root/"third_party/enola/upstream/enola/router/router_mis.py").resolve()): ("enola/router/router_mis.py", "pinned_upstream", {"compatible_2D", "maximalis_solve_sort"}),
            str((self.root/"src/na_pipeline/backend/enola_kernel.py").resolve()): ("src/na_pipeline/backend/enola_kernel.py", "project_route_adapter", {"group_route"}),
        }
        self.names = {n for _, _, names in self.sources.values() for n in names}
        self.records, self.pending, self.paths = {}, {}, {}
        self.calls = Counter()

    def _profile(self, frame, event, output):
        if self.previous is not None: self.previous(frame, event, output)
        name = frame.f_code.co_name
        if name not in self.names: return
        filename = frame.f_code.co_filename
        if filename not in self.paths: self.paths[filename] = str(Path(filename).resolve())
        entry = self.sources.get(self.paths[filename])
        if entry is None or name not in entry[2]: return
        source, kind, _ = entry
        if event == "call":
            self.calls[source+":"+name] += 1
            inputs = {key: deepcopy(frame.f_locals[key]) for key in frame.f_code.co_varnames[:frame.f_code.co_argcount]}
            caller = frame.f_back.f_code.co_name if frame.f_back else None
            self.pending[id(frame)] = (source, kind, name, inputs, caller, time.perf_counter())
        elif event == "return" and id(frame) in self.pending:
            source, kind, name, inputs, caller, begin = self.pending.pop(id(frame))
            input_hash, output_hash = digest(inputs), digest(output)
            ident = digest({"source": source, "function": name, "input": input_hash, "output": output_hash, "caller": caller})
            if ident not in self.records:
                self.records[ident] = {"record_id": ident, "source_file": source, "source_kind": kind, "function": name,
                    "caller_function": caller, "first_line": frame.f_code.co_firstlineno, "inputs": inputs,
                    "output": deepcopy(output), "input_sha256": input_hash, "output_sha256": output_hash,
                    "count": 0, "total_wall_seconds": 0.}
            self.records[ident]["count"] += 1
            self.records[ident]["total_wall_seconds"] += time.perf_counter()-begin

    def __enter__(self):
        self.previous = sys.getprofile()
        self.hashes = {v[0]: sha256(Path(p).read_bytes()).hexdigest() for p, v in self.sources.items()}
        sys.setprofile(self._profile); return self

    def __exit__(self, *args):
        sys.setprofile(self.previous)
        self.unchanged = all(sha256(Path(p).read_bytes()).hexdigest() == self.hashes[v[0]] for p, v in self.sources.items())

    def evidence(self):
        return {"schema_version": "ExternalCompilerObservation/0.1", "producer": "R4-D07-external-tooling", "fixture": False,
                "method": "sys.setprofile on exact original source filenames; raw args and return values; identical calls counted",
                "source_hashes": deepcopy(self.hashes), "source_unchanged": self.unchanged, "call_counts": dict(self.calls),
                "records": deepcopy(list(self.records.values())), "independent_acceptance_owner": "R6",
                "quantum_state_simulated": False, "hardware_executed": False}


def save_observation(directory, kind, payload):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode("utf-8")
    packed = gzip.compress(raw, mtime=0)
    byte_hash = sha256(packed).hexdigest()
    path = directory/(kind+"-"+byte_hash[:24]+".json.gz")
    if path.exists() and path.read_bytes() != packed: raise ValueError("IMMUTABLE_OBSERVATION_COLLISION")
    if not path.exists(): path.write_bytes(packed)
    return {"schema_version": "CompilerObservationFileRef/0.1", "path": directory.name+"/"+path.name,
            "relative_to": "evidence_directory_parent", "byte_sha256": byte_hash, "bytes": len(packed), "kind": kind}


def map_raw_calls_to_strategy(strategy, evidence):
    """An inspectable mapping certificate, not an independent acceptance report."""
    plan = strategy["body"]["template_plan"]
    records = evidence["records"]
    scheduler, selections, routes = [], [], []
    def one(function, inputs, output):
        found = [r for r in records if r["function"] == function and r["input_sha256"] == digest(inputs) and r["output_sha256"] == digest(output)]
        if not found: raise ValueError("RAW_RETURN_NOT_FOUND:"+function)
        return found[0]["record_id"]
    for receipt in plan["enola"]["schedule_decisions"]:
        ref = one("gate_scheduling", {"n_qubit": len(receipt["qubit_index"]), "list_gate": receipt["pairs"]}, receipt["raw_layers"])
        scheduler.append({"raw_record_id": ref, "scheduler_receipt_sha256": receipt["sha256"], "physical_layers": receipt["layers"]})
    actions = plan["atom_program"]["actions"]
    by_action = {a["id"]: a for a in actions}
    for receipt in plan["enola"]["route_decisions"]:
        ref = one("maximalis_solve_sort", {"n": len(receipt["candidates"]), "edges": [tuple(e) for e in receipt["conflicts"]]}, receipt["selected_indices"])
        used = receipt.get("accepted", False)
        if used:
            pulse = by_action[receipt["pulse_action_id"]]
            if pulse["payload"]["enola_decision_hash"] != receipt["decision_hash"]: raise ValueError("RAW_SELECTION_UNUSED")
        selections.append({"raw_record_id": ref, "decision_hash": receipt["decision_hash"], "accepted": used,
                           "selected_candidate_indices": receipt["selected_indices"],
                           "pulse_action_id": receipt.get("pulse_action_id"), "action_ids": receipt["action_ids"]})
    for i, pickup in enumerate(actions):
        if pickup['kind']!='pickup':continue
        drop_index=next(j for j in range(i+1,len(actions)) if actions[j]['kind']=='drop' and set(actions[j]['atoms'])==set(pickup['atoms']))
        drop=actions[drop_index]
        segments=[];current=[]
        for action in actions[i+1:drop_index]:
            if action['kind']=='move' and set(action['atoms'])<=set(pickup['atoms']):current.append(action)
            elif current:segments.append(current);current=[]
        if current:segments.append(current)
        if not segments:segments=[[]]
        for segment in segments:
            starts=({t['atom_id']:t['from_um'] for t in segment[0]['payload']['trajectories']} if segment else
                    {v['atom_id']:v['position_um'] for v in pickup['payload']['bindings']})
            goals=({t['atom_id']:t['to_um'] for t in segment[-1]['payload']['trajectories']} if segment else
                   {v['atom_id']:v['position_um'] for v in drop['payload']['bindings']})
            actual_path=[{t['atom_id']:t['to_um'] for t in action['payload']['trajectories']} for action in segment]
            candidates=[]
            for record in records:
                if record['function']!='group_route' or record['caller_function'] not in {'transfer','entangle','qualify','route_arrays'} or record['output'] is None:continue
                initial={a['atom_id']:a['position_um'] for a in record['inputs']['atoms']}
                if record['inputs']['goals']==goals and all(initial[a]==pos for a,pos in starts.items()) and record['output'][0]==actual_path:candidates.append(record)
            if not candidates:raise ValueError('RAW_ROUTE_UNUSED_OR_MISSING:'+pickup['id'])
            routes.append({'raw_record_id':candidates[0]['record_id'],'pickup_action_id':pickup['id'],
                           'move_action_ids':[a['id'] for a in segment],'drop_action_id':drop['id'],
                           'segment_start_us':segment[0]['t_start_us'] if segment else pickup['t_end_us'],
                           'segment_end_us':segment[-1]['t_end_us'] if segment else drop['t_start_us'],
                           'shared_capture_cycle_segments':len(segments),'path_sha256':digest(actual_path)})
    return {"schema_version": "RawCompilerPlanMapping/0.2", "strategy_id": strategy["strategy_id"],
            "scheduler": scheduler, "endpoint_selections": selections, "project_routes": routes,
            "upstream_full_router_called": False, "independent_validation": "pending_R6"}
