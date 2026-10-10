"""A fixed-plan discrete event executor with instance-local fake results.

The queue only contains the supplied atom window. It never expands a physical
template or a quantum state. At equal times completion precedes publication,
which precedes action starts. Zero-duration classical dependencies are resolved
at the same timestamp without reading a future result.
"""

from copy import deepcopy
import hashlib
import heapq
import json
import math
import time

from .errors import fail
from .scenario import output_ids
from .state import RuntimeState

EPS = 1e-9
VERSION = "0.1.0"


def digest(value):
    try:
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    except (ValueError, TypeError) as exc:
        fail("INVALID_JSON", str(exc))


def number(value, label, action=None):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        fail("INVALID_TIME", f"{label} must be a finite number", action)
    if value < 0:
        fail("INVALID_TIME", f"{label} must be nonnegative", action)
    return value


def evidence(value, label):
    for key in ("quantum_state_simulated", "hardware_executed", "loss_enabled", "sampled"):
        if value.get(key, False) is not False:
            fail("UNSUPPORTED_EVIDENCE", f"{label}.{key} must be false")
    for key in ("schema_version", "artifact_id", "provenance"):
        if key not in value:
            fail("MISSING_FIELD", f"{label}.{key} is required")
    if not isinstance(value["provenance"], dict) or any(not isinstance(value[k], str) or not value[k] for k in ("schema_version", "artifact_id")):
        fail("INVALID_ENVELOPE", f"{label} needs string IDs and object provenance")


def run(atom_program, scenario, device):
    """Execute one fake scenario or raise RuntimeContractError; inputs stay intact."""
    started = time.perf_counter()
    for name, obj in (("AtomProgram", atom_program), ("ScenarioInput", scenario), ("DeviceSpec", device)):
        if not isinstance(obj, dict):
            fail("INVALID_ARTIFACT", f"{name} must be an object")
        evidence(obj, name)
        if obj["schema_version"] != f"{name}/0.2.0-draft":
            fail("UNSUPPORTED_SCHEMA", f"Unsupported {name} schema")
    if atom_program.get("complete") is not True:
        fail("INCOMPLETE_PLAN", "Only explicitly complete bounded atom plans may run")
    if atom_program.get("execution_kind") != "compile_plan" or scenario.get("execution_kind") != "scenario":
        fail("UNSUPPORTED_EVIDENCE", "Expected compile_plan and scenario evidence kinds")
    if not isinstance(atom_program.get("initial_state"), dict):
        fail("INVALID_INITIAL_STATE", "AtomProgram.initial_state must be an object")
    hashes = {"atom_program": digest(atom_program), "scenario": digest(scenario), "device": digest(device)}
    if atom_program.get("device_ref") != device["artifact_id"]:
        fail("DEVICE_MISMATCH", "AtomProgram.device_ref does not match DeviceSpec.artifact_id")
    if "device" in atom_program.get("input_hashes", {}) and atom_program["input_hashes"]["device"] != hashes["device"]:
        fail("DEVICE_HASH_MISMATCH", "Device content differs from the compiled input")
    configured = scenario.get("results")
    if not isinstance(configured, dict):
        fail("INVALID_SCENARIO", "ScenarioInput.results must be an object")
    for result_id, record in configured.items():
        if not isinstance(record, dict) or record.get("origin") != "fake" or type(record.get("value")) is not int or record["value"] not in (0, 1):
            fail("INVALID_FAKE_VALUE", "Scenario entries must contain origin=fake and integer bit", result_id=result_id)
        if "ready_us" in record:
            number(record["ready_us"], "scenario.ready_us")
    actions = atom_program.get("actions")
    if not isinstance(actions, list):
        fail("INVALID_ACTIONS", "AtomProgram.actions must be a list for this bounded window")
    by_id, producers = {}, {}
    for action in actions:
        if not isinstance(action, dict):
            fail("INVALID_ACTION", "Action must be an object")
        for key in ("id", "kind", "atoms", "t_start_us", "t_end_us", "resources", "source_ids", "depends_on", "payload"):
            if key not in action:
                fail("MISSING_FIELD", f"Action.{key} is required", action)
        if not isinstance(action["id"], str) or not action["id"] or action["id"] in by_id:
            fail("DUPLICATE_ACTION_ID", "Action IDs must be unique nonempty strings", action)
        for key in ("atoms", "resources", "source_ids", "depends_on"):
            if not isinstance(action[key], list) or any(not isinstance(item, str) for item in action[key]) or len(action[key]) != len(set(action[key])):
                fail("INVALID_ACTION", f"{key} must be a unique string list", action)
        if not action["source_ids"] or not isinstance(action["payload"], dict):
            fail("INVALID_ACTION", "Source IDs must be nonempty and payload an object", action)
        t0 = number(action["t_start_us"], "t_start_us", action)
        t1 = number(action["t_end_us"], "t_end_us", action)
        if t1 < t0 or (t1 == t0 and action["kind"] not in ("wait", "classical")):
            fail("INVALID_INTERVAL", "Physical actions need a positive duration", action)
        if action["kind"] not in ("pickup", "move", "drop", "gate", "measure", "reset", "wait", "classical", "rebind"):
            fail("UNSUPPORTED_ACTION", f"Unsupported action kind {action['kind']!r}", action)
        condition = action.get("condition")
        if condition is not None and (not isinstance(condition, dict) or set(condition) != {"bit", "equals"} or not isinstance(condition["bit"], str) or type(condition["equals"]) is not int or condition["equals"] not in (0, 1)):
            fail("UNSUPPORTED_CONDITION", "Only {bit, equals: 0|1} is supported", action)
        by_id[action["id"]] = action
        for result_id in output_ids(action):
            if not isinstance(result_id, str) or not result_id or result_id in producers:
                fail("DUPLICATE_RESULT_ID", "Outputs require unique instance-local string IDs", action,
                     result_id=result_id)
            producers[result_id] = action["id"]
    for action in actions:
        for dependency in action["depends_on"]:
            if dependency not in by_id:
                fail("UNKNOWN_DEPENDENCY", f"Unknown dependency {dependency}", action)
            if by_id[dependency]["t_end_us"] > action["t_start_us"] + EPS:
                fail("DEPENDENCY_NOT_COMPLETE", f"Dependency {dependency} ends after action starts", action)
    transfer_groups = {}
    for action in actions:
        group = action["payload"].get("group_transport_id")
        if group is not None and action["kind"] in ("pickup", "drop"):
            if not isinstance(group, str) or not group:
                fail("TRANSFER_GROUP_MISMATCH", "Group transport identity must be a nonempty string", action)
            transfer_groups.setdefault((group, action["kind"], action["t_start_us"]), []).append(action)
    checked_groups = set()
    state = RuntimeState(atom_program["initial_state"], device)
    start_time = number(atom_program["initial_state"].get("time_us", 0), "initial_state.time_us")
    events, completed, results, pending, used = [], {}, {}, {}, set()
    leases = {}
    queue, serial = [], 0

    def enqueue(at, phase, kind, item):
        nonlocal serial
        serial += 1
        heapq.heappush(queue, (at, phase, serial, kind, item))

    for action in actions:
        if action["t_start_us"] < start_time:
            fail("PAST_ACTION", "Action starts before initial state", action)
        enqueue(action["t_start_us"], 2, "start", action)

    def read(result_id, at, action):
        if result_id not in results:
            code = "RESULT_NOT_READY" if result_id in pending or result_id in producers else "UNKNOWN_RESULT_ID"
            fail(code, "Result is unavailable at action start", action, result_id=result_id)
        record = results[result_id]
        if record["ready_us"] > at + EPS:
            fail("RESULT_NOT_READY", "Cannot consume a future result", action, result_id=result_id)
        return {"result_id": result_id, "value": record["value"], "origin": record["origin"],
                "ready_us": record["ready_us"], "action_id": record["action_id"]}

    def finish(action, event, at):
        state.finish(action)
        event["state_after"] = state.snapshot(action["atoms"])
        completed[action["id"]] = at
        for key in event.pop("_leases"):
            leases[key].remove(action["id"])
            if not leases[key]:
                leases.pop(key)
        for result_id in event["result_ids"]:
            record = pending[result_id]
            enqueue(record["ready_us"], 1, "publish", result_id)

    now = start_time
    while queue:
        at, phase, seq, kind, item = heapq.heappop(queue)
        now = at
        if kind == "publish":
            record = pending.pop(item)
            record["available_us"] = at
            results[item] = record
            continue
        if kind == "finish":
            finish(item[0], item[1], at)
            continue
        action = item
        unmet = [dep for dep in action["depends_on"] if dep not in completed]
        if unmet:
            # A zero-time dependency may be a later start in this timestamp.
            # Resolve only if another queued start can make progress; bounded
            # reordering avoids silently accepting same-time dependency cycles.
            peers = [entry for entry in queue if entry[0] == at and entry[3] == "start"]
            if peers and any(all(dep in completed for dep in entry[4]["depends_on"]) for entry in peers):
                enqueue(at, 2, "start", action)
                continue
            fail("DEPENDENCY_NOT_COMPLETE", f"Uncompleted dependencies {unmet}", action)
        condition_reads = []
        condition = action.get("condition")
        if condition:
            condition_reads.append(read(condition["bit"], at, action))
            if at + EPS < condition_reads[0]["ready_us"] + device["timings_us"]["feedback_latency"]:
                fail("FEEDBACK_TOO_EARLY", "Condition starts before device feedback latency", action,
                     result_id=condition["bit"])
        selected = not condition or condition_reads[0]["value"] == condition["equals"]
        event = {"action_id": action["id"], "kind": action["kind"],
                 "status": "completed" if selected else "skipped",
                 "t_start_us": at, "t_end_us": action["t_end_us"],
                 "atoms": deepcopy(action["atoms"]), "resources": deepcopy(action["resources"]),
                 "source_ids": deepcopy(action["source_ids"]), "depends_on": deepcopy(action["depends_on"]),
                 "payload": deepcopy(action["payload"]), "condition": deepcopy(condition),
                 "condition_reads": condition_reads, "reads": [], "result_ids": [],
                 "state_before": state.snapshot(action["atoms"]), "state_after": {}}
        events.append(event)
        if not selected:
            event["state_after"] = deepcopy(event["state_before"])
            completed[action["id"]] = at
            continue
        event["reads"] = [read(result_id, at, action) for result_id in action.get("reads", action["payload"].get("reads", []))]
        for record in event["reads"]:
            if at + EPS < record["ready_us"] + device["timings_us"]["feedback_latency"]:
                fail("FEEDBACK_TOO_EARLY", "Result read starts before device feedback latency", action,
                     result_id=record["result_id"])
        state.check(action)
        group = action["payload"].get("group_transport_id")
        group_key = (group, action["kind"], action["t_start_us"])
        if group is not None and action["kind"] in ("pickup", "drop") and group_key not in checked_groups:
            state.check_transfer_group(transfer_groups[group_key])
            checked_groups.add(group_key)
        keys = state.resource_keys(action)
        for key in keys:
            if key in leases:
                shared_axis = key.startswith("aod:") and (":row:" in key or ":column:" in key)
                joint = group is not None and action["kind"] in ("pickup", "drop") and shared_axis and all(
                    by_id[holder]["kind"] == action["kind"] and
                    by_id[holder]["payload"].get("group_transport_id") == group and
                    by_id[holder]["t_start_us"] == action["t_start_us"] and by_id[holder]["t_end_us"] == action["t_end_us"]
                    for holder in leases[key])
                if not joint:
                    fail("RESOURCE_CONFLICT", f"Resource held by {leases[key]}", action, resource_id=key)
        for key in keys:
            leases.setdefault(key, set()).add(action["id"])
        event["_leases"] = keys
        ids = output_ids(action)
        for result_id in ids:
            planned_ready = number(action["payload"].get("result_ready_us", action["t_end_us"]), "result_ready_us", action)
            lower_bound = state.result_lower_bound(action)
            if planned_ready + EPS < lower_bound:
                fail("RESULT_READY_TOO_EARLY", f"Ready time precedes device lower bound {lower_bound}", action, result_id=result_id)
            operation = action["payload"].get("operation")
            if action["kind"] == "measure" or operation == "fake":
                if result_id not in configured:
                    fail("MISSING_FAKE_RESULT", "Selected output has no configured fake value", action, result_id=result_id)
                configured_result = configured[result_id]
                ready = configured_result.get("ready_us", planned_ready)
                if ready + EPS < planned_ready:
                    fail("RESULT_READY_TOO_EARLY", "Scenario may delay, but cannot advance planned readiness", action, result_id=result_id)
                value = configured_result["value"]
                used.add(result_id)
            else:
                ready = planned_ready
                values = [r["value"] for r in event["reads"]]
                if operation == "xor" and values:
                    value = sum(values) % 2
                elif operation == "copy" and len(values) == 1:
                    value = values[0]
                elif operation == "all_zero" and values:
                    value = int(not any(values))
                elif operation == 'postprocess_phase':
                    from na_pipeline.frontend import postprocess_phase
                    params=action['payload'].get('params',{})
                    if len(values)!=8 or action['payload'].get('reads')!=params.get('bits_msb_first'):
                        fail('POSTPROCESS_BIT_ORDER','Eight phase bits must follow the declared MSB-first source order',action)
                    value=postprocess_phase(values,N=params['N'],a=params['a'],origin='fake')
                else:
                    fail("UNSUPPORTED_CLASSICAL", "Only fake, xor, all_zero or single-input copy is supported", action)
                if len(ids) != 1:
                    fail("UNSUPPORTED_CLASSICAL", "Deterministic operations have exactly one output", action)
            pending[result_id] = {"result_id": result_id, "action_id": action["id"], "value": value,
                                  "origin": "fake", "ready_us": ready,
                                  "derivation": "scenario" if action["kind"] == "measure" or operation == "fake" else operation}
        event["result_ids"] = ids
        event["result_ready_us"] = {rid: pending[rid]["ready_us"] for rid in ids}
        state.start(action)
        if action["t_end_us"] == at:
            finish(action, event, at)
        else:
            enqueue(action["t_end_us"], 0, "finish", (action, event))

    count = sum(event["status"] == "completed" for event in events)
    return {"schema_version": "EventTrace/0.2.0-draft",
            "artifact_id": "trace-" + digest(hashes)[:24],
            "producer_version": VERSION,
            "provenance": {"producer": "na_pipeline.runtime.run", "version": VERSION,
                           "fixture": bool(atom_program["provenance"].get("fixture", False)),
                           "scenario_provenance": deepcopy(scenario["provenance"])},
            "input_hashes": hashes, "device_ref": device["artifact_id"],
            "atom_program_ref": atom_program["artifact_id"], "scenario_ref": scenario["artifact_id"],
            "execution_kind": "fake_event_run", "quantum_state_simulated": False,
            "hardware_executed": False, "loss_enabled": False, "measurement_origin": "fake", "sampled": False,
            "events": events, "results": results, "final_state": state.export(now),
            "illumination_counts": deepcopy(state.illumination_counts),
            "stats": {"t_start_us": start_time, "t_end_us": now, "duration_us": now-start_time,
                      "atom_count": len(state.atoms), "action_count": len(actions),
                      "executed_action_count": count, "skipped_action_count": len(actions)-count,
                      "result_count": len(results), "unused_scenario_result_ids": sorted(set(configured)-used),
                      "wall_time_s": time.perf_counter()-started},
            "scope": "T501 fixed-plan fake event execution; independent acceptance is performed by R6",
            "unverified": [],
            "out_of_scope": ["quantum_state", "noise", "decoding", "hardware_execution",
                             "factory_token_lifecycle", "online_window_resume"]}
