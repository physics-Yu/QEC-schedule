"""Strict display adapter for R4/R5 0.1.0-draft; no inferred movements."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

VERSION = "na-viewer/0.2.0"


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def position(value):
    return isinstance(value, list) and len(value) == 2 and all(finite(x) for x in value)


def transfer_bindings(action):
    payload = action["payload"]
    if "bindings" in payload:
        bindings = payload["bindings"]
        if not isinstance(bindings, list) or {b["atom_id"] for b in bindings} != set(action["atoms"]) or len(bindings) != len(action["atoms"]):
            raise ValueError("VIEW_TRANSFER_BINDING_COVERAGE: " + action["id"])
    else:
        if len(action["atoms"]) != 1:
            raise ValueError("VIEW_GROUP_TRANSFER_BINDINGS_REQUIRED: " + action["id"])
        bindings = [{"atom_id": action["atoms"][0], **payload}]
    for binding in bindings:
        if any(key not in binding for key in ("from_trap_id", "to_trap_id", "row_id", "column_id", "position_um")) or not position(binding["position_um"]):
            raise ValueError("VIEW_TRANSFER_BINDING_FIELDS: " + action["id"])
    return bindings


def group_projection(atom, trace=None):
    """Presentation metrics only, directly keyed by published action group_id."""
    events = {e["action_id"]: e for e in (trace or {}).get("events", [])}
    groups = {}
    for a in atom["actions"]:
        gid = a["payload"].get("group_id")
        if gid is None:
            continue
        group = groups.setdefault(gid, {"group_id": gid, "purpose": a["payload"].get("purpose", "未报告"), "members": set(), "action_ids": [], "measurements": [], "move_action_ids": [], "wait_actions": [], "split_reasons": []})
        group["members"].update(a["atoms"])
        group["action_ids"].append(a["id"])
        if trace is not None and events[a["id"]]["status"] == "skipped":
            continue
        if a["kind"] == "measure":
            rid = a["payload"]["result_id"]
            result = (trace or {}).get("results", {}).get(rid)
            ready = result["ready_us"] if result is not None else a["payload"]["result_ready_us"]
            group["measurements"].append({"action_id": a["id"], "atoms": a["atoms"], "result_id": rid, "t_start_us": a["t_start_us"], "t_end_us": a["t_end_us"], "ready_us": ready})
        if a["kind"] == "move":
            group["move_action_ids"].append(a["id"])
        if a["kind"] == "wait":
            group["wait_actions"].append({"action_id": a["id"], "atoms": a["atoms"], "duration_us": a["t_end_us"] - a["t_start_us"], "reason": a["payload"].get("reason", "未报告")})
        for reason in a["payload"].get("split_reasons", []):
            if reason not in group["split_reasons"]:
                group["split_reasons"].append(reason)
    for group in groups.values():
        group["members"] = sorted(group["members"])
        for label, field in (("readout_start_span_us", "t_start_us"), ("readout_end_span_us", "t_end_us"), ("result_ready_span_us", "ready_us")):
            times = [m[field] for m in group["measurements"]]
            group[label] = max(times) - min(times) if times else None
        group["metric_scope"] = "display_projection_from_declared_group_actions_not_independent_qualification"
        reported = atom.get("stats", {}).get("group_metrics", [])
        if isinstance(reported, list):
            group["reported_metrics"] = next((m for m in reported if m.get("group_id") == group["group_id"]), None)
    return list(groups.values())


def check_model(atom, trace=None, *, trace_schema="EventTrace/0.2.0-draft"):
    if atom.get("schema_version") != "AtomProgram/0.2.0-draft":
        raise ValueError("VIEW_UNSUPPORTED_SCHEMA: AtomProgram/0.2.0-draft required")
    if atom.get("complete") is not True:
        raise ValueError("VIEW_INCOMPLETE_PLAN: incomplete plans cannot be presented as a run")
    if atom.get("execution_kind") != "compile_plan":
        raise ValueError("VIEW_EVIDENCE_KIND")
    for obj in (atom, trace) if trace is not None else (atom,):
        for key in ("hardware_executed", "quantum_state_simulated", "loss_enabled"):
            if obj.get(key) is not False:
                raise ValueError(f"VIEW_EVIDENCE_LABEL: {key}")
    atoms = atom["initial_state"]["atoms"]
    ids = [a["atom_id"] for a in atoms]
    if len(ids) != len(set(ids)) or not all(position(a["position_um"]) for a in atoms):
        raise ValueError("VIEW_ATOM_ID_OR_POSITION")
    action_ids = set()
    known = {"pickup", "move", "drop", "gate", "measure", "reset", "wait", "classical", "rebind"}
    for action in atom["actions"]:
        aid = action["id"]
        if aid in action_ids:
            raise ValueError("VIEW_DUPLICATE_ACTION: " + aid)
        action_ids.add(aid)
        if action["kind"] not in known or not action.get("source_ids"):
            raise ValueError("VIEW_ACTION_OR_SOURCE_UNSUPPORTED: " + aid)
        if not all(a in ids for a in action["atoms"]):
            raise ValueError("VIEW_UNKNOWN_ATOM: " + aid)
        start, end = action["t_start_us"], action["t_end_us"]
        if not finite(start) or not finite(end) or end < start:
            raise ValueError("VIEW_INVALID_TIME: " + aid)
        if action["kind"] in {"pickup", "drop"}:
            transfer_bindings(action)
        payload = action["payload"]
        if "physical_op_ids" in payload:
            physical_ids = payload["physical_op_ids"]
            records = payload.get("source_op_records")
            if not isinstance(physical_ids, list) or len(physical_ids) != len(set(physical_ids)) or not physical_ids or not isinstance(records, dict) or set(records) != set(physical_ids) or not set(physical_ids) <= set(action["source_ids"]):
                raise ValueError("VIEW_MULTI_SOURCE_MAPPING: " + aid)
        if "pair_sources" in payload:
            if action["kind"] != "gate" or payload.get("name") != "CZ":
                raise ValueError("VIEW_PAIR_SOURCE_KIND: " + aid)
            pairs = payload.get("pairs", [])
            sources = payload["pair_sources"]
            if not isinstance(sources, list) or len(sources) != len(pairs) or {tuple(sorted(p)) for p in pairs} != {tuple(sorted(s["atoms"])) for s in sources}:
                raise ValueError("VIEW_PAIR_SOURCE_COVERAGE: " + aid)
            if any(s["physical_op_id"] not in payload["physical_op_ids"] or s["qubits"] != payload["source_op_records"][s["physical_op_id"]]["qubits"] for s in sources):
                raise ValueError("VIEW_PAIR_SOURCE_IDENTITY: " + aid)
        if action["kind"] == "move":
            payload = action["payload"]
            if payload.get("interpolation") != "linear":
                raise ValueError("VIEW_UNSUPPORTED_INTERPOLATION: " + aid)
            trajectories = payload.get("trajectories", [])
            moved = [t["atom_id"] for t in trajectories]
            if len(moved) != len(set(moved)) or set(moved) != set(action["atoms"]):
                raise ValueError("VIEW_TRAJECTORY_COVERAGE: " + aid)
            if any(not position(t["from_um"]) or not position(t["to_um"]) for t in trajectories):
                raise ValueError("VIEW_TRAJECTORY_COORDINATES: " + aid)
            if end == start and any(t["from_um"] != t["to_um"] for t in trajectories):
                raise ValueError("VIEW_ZERO_TIME_MOVE: " + aid)
    if trace is not None:
        if trace.get("schema_version") != trace_schema or trace.get("execution_kind") != "fake_event_run":
            raise ValueError("VIEW_TRACE_SCHEMA_OR_KIND")
        if trace.get("measurement_origin") != "fake" or trace.get("sampled") is not False:
            raise ValueError("VIEW_TRACE_FAKE_LABELS")
        ref = trace.get("atom_program_ref")
        if isinstance(ref, dict):
            ref = ref.get("artifact_id")
        if ref is not None and ref != atom["artifact_id"]:
            raise ValueError("VIEW_TRACE_PLAN_MISMATCH")
        events = trace["events"]
        if len(events) != len(action_ids) or {e["action_id"] for e in events} != action_ids:
            raise ValueError("VIEW_EVENT_COVERAGE")
        by_id = {a["id"]: a for a in atom["actions"]}
        for event in events:
            a = by_id[event["action_id"]]
            if event["status"] not in {"completed", "skipped"}:
                raise ValueError("VIEW_EVENT_STATUS")
            for key in ("kind", "t_start_us", "t_end_us", "atoms", "source_ids", "payload"):
                if key in event and event[key] != a[key]:
                    raise ValueError(f"VIEW_EVENT_PLAN_MISMATCH: {event['action_id']} {key}")
        for rid, result in trace.get("results", {}).items():
            if result.get("origin") != "fake" or not finite(result.get("ready_us")):
                raise ValueError("VIEW_RESULT_ORIGIN_OR_READY: " + rid)


def export_view(atom_path, out, *, trace_path=None, device_path=None, report_path=None, run_path=None, strategies_path=None):
    paths = {"atom_program": Path(atom_path)}
    for key, path in (("trace", trace_path), ("device", device_path), ("report", report_path), ("run", run_path), ("strategies", strategies_path)):
        if path is not None:
            paths[key] = Path(path)
    values, receipts = {}, {}
    for key, path in paths.items():
        data = path.read_bytes()
        values[key] = json.loads(data.decode("utf-8-sig"))
        receipts[key] = {"name": path.name, "byte_sha256": hashlib.sha256(data).hexdigest(), "canonical_sha256": canonical(values[key])}
    check_model(values["atom_program"], values.get("trace"))
    context = None
    if "run" in values:
        run = values["run"]
        if run.get("schema_version") != "logical-controller-run/0.1":
            raise ValueError("VIEW_STRATEGY_RUN_SCHEMA_UNSUPPORTED")
        if run.get("atom_program") != values["atom_program"] or run.get("event_trace") != values.get("trace"):
            raise ValueError("VIEW_RUN_ARTIFACT_MISMATCH")
        context = {"run_id": run.get("snapshot", {}).get("run_id"), "library_stats": run.get("snapshot", {}).get("library_stats"), "calls": [{k: instance.get(k) for k in ("call_id", "operation", "operands", "source_ids", "strategy_id", "strategy_hash", "backend_used", "start_us", "end_us", "status", "library_stats_before", "library_stats_after")} for instance in run["instances"]], "strategies": [{"strategy_id": s["strategy_id"], "strategy_hash": s["strategy_hash"], "backend_used": s["body"].get("backend_used"), "enola_provenance": s["body"].get("enola_provenance")} for s in values.get("strategies", {}).values()]}
        for strategy in values.get("strategies", {}).values():
            if canonical(strategy["body"]) != strategy["strategy_hash"]:
                raise ValueError("VIEW_STRATEGY_BODY_HASH_MISMATCH")
    for key in ("trace", "report"):
        for name, expected in values.get(key, {}).get("input_hashes", {}).items():
            canonical_name = {"atom": "atom_program", "event_trace": "trace", "device_spec": "device"}.get(name, name)
            if canonical_name in receipts and isinstance(expected, str) and expected != receipts[canonical_name]["canonical_sha256"]:
                raise ValueError(f"VIEW_INPUT_HASH_MISMATCH: {key}/{name}")
    payload = {"viewer_version": VERSION, **values, "receipts": receipts, "group_projection": group_projection(values["atom_program"], values.get("trace")), "user_visual_acceptance": "pending", "mode": "fake_event_run" if trace_path else "compile_plan", "fixture": any(v.get("provenance", {}).get("fixture", False) for v in values.values())}
    if context is not None:
        context["runtime_group_metrics"] = values["run"].get("group_metrics", [])
        payload["strategy_context"] = context
        metrics = [metric for instance in values["run"]["instances"] for metric in instance["atom_program"].get("stats", {}).get("group_metrics", [])]
        for group in payload["group_projection"]:
            group["reported_metrics"] = next((m for m in metrics if m.get("group_id") == group["group_id"]), None)
            runtime_metric = next((m for m in values["run"].get("group_metrics", []) if m.get("group_id") == group["group_id"]), None)
            if runtime_metric is not None:
                group["runtime_metrics"] = runtime_metric
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    folder = Path(__file__).parent
    html = (folder / "viewer.html").read_text(encoding="utf-8").replace("/*__STYLE__*/", (folder / "viewer.css").read_text(encoding="utf-8")).replace("/*__SCRIPT__*/", (folder / "viewer.js").read_text(encoding="utf-8")).replace("__PAYLOAD__", encoded)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(html.encode("utf-8"))
    return {"path": str(out.resolve()), "byte_sha256": hashlib.sha256(out.read_bytes()).hexdigest(), "fixture": payload["fixture"], "mode": payload["mode"], "user_visual_acceptance": "pending", "inputs": receipts}
