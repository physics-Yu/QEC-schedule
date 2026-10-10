"""One-way binding of an R4 relative physical window to a live session."""
from copy import deepcopy

from .engine import digest, number
from .errors import fail


def bind_physical_plan(plan, context):
    if plan.get("schema_version") != "physical-plan/0.1" or context.get("schema_version") != "execution-context/0.1":
        fail("WINDOW_BINDING_SCHEMA", "Expected physical-plan/0.1 and execution-context/0.1")
    atom = deepcopy(plan["atom_program"])
    if atom.get("complete") is not True or atom.get("provenance", {}).get("requires_runtime_binding") or atom.get("provenance", {}).get("requires_strategy_binding"):
        fail("WINDOW_RUNTIME_INPUTS_UNRESOLVED", "Static drafts with deferred runtime inputs are not executable")
    if "execution_context" in plan and plan["execution_context"] != context:
        fail("WINDOW_CONTEXT_CHANGED", "Runtime-bound plans cannot reuse another context's resolved values or decisions")
    if "session_binding" in atom or atom.get("time_basis") == "absolute_session":
        fail("WINDOW_ALREADY_BOUND", "Relative offsets may be translated exactly once")
    if plan["input_hashes"]["world_state"] != context["world_state_hash"] or plan["input_hashes"]["device"] != context["device_hash"]:
        fail("WINDOW_FRONTIER_MISMATCH", "Physical plan was compiled against another world or device")
    if plan["input_hashes"]["physical_dags"] != [d["physical_dag_sha256"] for d in context["graph_decisions"].values()]:
        fail("WINDOW_DAG_MISMATCH", "Physical plan must preserve the selected original DAGs")
    if any(d["decision"] != "execute" for d in context["graph_decisions"].values()):
        fail("WINDOW_SKIPPED_GRAPH", "Skipped logical graphs cannot be submitted as physical actions")
    t0 = number(context["time_us"], "window origin")
    ids = [a["id"] for a in atom["actions"]]
    if len(ids) != len(set(ids)):
        fail("WINDOW_ACTION_DUPLICATE", "Shared actions must have one physical record, not repeated copies")
    for action in atom["actions"]:
        action["t_start_us"] += t0
        action["t_end_us"] += t0
        for key in ("result_ready_us", "earliest_ready_us"):
            if key in action["payload"]: action["payload"][key] += t0
    # Only group timing records are traversed; source parameters stay untouched.
    def shift_group(value):
        if isinstance(value, list): return [shift_group(v) for v in value]
        if not isinstance(value, dict): return deepcopy(value)
        result = {}
        for key, val in value.items():
            if key in ("start_us", "end_us", "t_start_us", "t_end_us", "result_ready_us", "earliest_ready_us", "readout_start_us", "readout_end_us") and type(val) in (int, float):
                result[key] = val+t0
            elif key == "earliest_readout_us": result[key] = {a: v+t0 for a, v in val.items()}
            else: result[key] = shift_group(val)
        return result
    atom["groups"] = shift_group(atom.get("groups", []))
    atom["initial_state"]["time_us"] = t0
    for key in ("t_start_us", "t_end_us"):
        if key in atom.get("stats", {}): atom["stats"][key] += t0
    if "group_metrics" in atom.get("stats", {}): atom["stats"]["group_metrics"] = deepcopy(atom["groups"])
    atom["time_basis"] = "absolute_session"
    atom["session_binding"] = {"schema_version": "session-window-binding/0.1", "physical_plan_sha256": digest(plan),
        "time_origin_us": t0, "execution_context": deepcopy(context),
        "runtime_requirements": deepcopy(plan.get("runtime_requirements", [])),
        "physical_dag_hashes": deepcopy(plan["input_hashes"]["physical_dags"])}
    return atom
