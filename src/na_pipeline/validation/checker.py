"""Independent artifact checks; no compiler/runtime validation helpers are used.

Intervals are half open. Inputs are JSON values. A missing/unsupported contract
never yields a full pass. Geometry is implemented separately from the producer.
"""
from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
import json
import math
import time

VERSION = "0.1.0"
EPS = 1e-8
KINDS = {"pickup", "move", "drop", "gate", "measure", "reset", "wait", "classical", "rebind"}
CHECKS = {
    "contract": "JSON artifact envelope, identities and required fields",
    "timing": "finite intervals, action dependencies and result causality",
    "resources": "declared and independently inferred resource conflicts",
    "geometry": "carrier lifecycle, piecewise linear trajectories and shared axes",
    "broadcast": "all geometrically eligible illuminated pairs and counts",
    "source": "physical operation coverage and supported native lowering semantics",
    "trace": "single fake path, trace correspondence and final state",
}


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


class Audit:
    def __init__(self):
        self.failures = []
        self.unverified = []
        self.metrics = {}

    def fail(self, check, code, message, **where):
        self.failures.append({"check": check, "code": code, "message": message, **where})

    def need(self, check, code, message):
        entry = {"check": check, "code": code, "message": message}
        if entry not in self.unverified:
            self.unverified.append(entry)

    def guard(self, check, fn, *args):
        try:
            return fn(self, *args)
        except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
            self.fail(check, "MALFORMED_INPUT", f"{type(exc).__name__}: {exc}")
            self.need(check, "CHECK_INCOMPLETE", "Malformed/unsupported input stopped this check")
            return None


def _envelope(audit, value, label, execution):
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be a JSON object")
    for key in ("schema_version", "artifact_id", "provenance"):
        if not value.get(key):
            audit.fail("contract", "MISSING_FIELD", f"{label}.{key} is required")
    for key in ("quantum_state_simulated", "hardware_executed", "loss_enabled"):
        if value.get(key) is not False:
            audit.fail("contract", "EVIDENCE_LABEL", f"{label}.{key} must be false in this profile")
    if execution and value.get("execution_kind") != execution:
        audit.fail("contract", "EVIDENCE_LABEL", f"{label}.execution_kind must be {execution}")


def _contract(audit, plan, device, trace, physical):
    _envelope(audit, plan, "atom_program", "compile_plan")
    for value, allowed in ((plan, {"AtomProgram/0.2.0-draft"}), (device, {"DeviceSpec/0.2.0-draft"}), (trace, {"EventTrace/0.2.0-draft"}), (physical, {"physical-program/0.2.0-draft"})):
        if value is not None and value.get("schema_version") not in allowed:
            audit.fail("contract", "SCHEMA_VERSION", f"Unsupported schema_version {value.get('schema_version')!r}")
    for key, value in device["timings_us"].items():
        if not _finite(value) or value <= 0:
            audit.fail("contract", "DEVICE_PARAMETER", f"timings_us.{key} must be finite and positive")
    for group, field in (("movement", "speed_um_per_us"), ("geometry", "gate_pair_distance_um"), ("geometry", "distance_tolerance_um")):
        if not _finite(device[group][field]) or device[group][field] <= 0:
            audit.fail("contract", "DEVICE_PARAMETER", f"{group}.{field} must be finite and positive")
    if device.get("units") != {"time": "us", "length": "um", "angle": "rad"}:
        audit.fail("contract", "DEVICE_UNITS", "Only us/um/rad units are supported")
    provenance = device.get("parameter_provenance", {})
    required_sources = [f"/timings_us/{key}" for key in device["timings_us"]] + ["/movement", "/geometry", "/zones", "/broadcast"]
    for pointer in required_sources:
        entry = provenance.get(pointer)
        if not isinstance(entry, dict) or not entry.get("source_refs") or not entry.get("kind") or not entry.get("scope"):
            audit.fail("contract", "PARAMETER_PROVENANCE", f"Device parameter source/assumption missing at {pointer}")
    for group in device["aod_groups"].values():
        if any(group.get(k) is not True for k in ("shared_rows", "shared_columns", "non_crossing")) or any(group.get(k) is not None for k in ("max_rows", "max_columns")):
            audit.need("geometry", "AOD_PROFILE", "Only uncapped shared, noncrossing axes are checked")
    if device["broadcast"].get("all_geometric_pairs") is not True or device["broadcast"].get("gate") != "CZ":
        audit.need("broadcast", "BROADCAST_PROFILE", "Only all-pair CZ broadcast model is checked")
    for label, value in (("device", device), ("trace", trace), ("physical_program", physical)):
        if value is not None:
            # Device describes capabilities; it is not itself an execution.
            if label == "device":
                for key in ("schema_version", "artifact_id", "provenance"):
                    if not value.get(key):
                        audit.fail("contract", "MISSING_FIELD", f"device.{key} is required")
            else:
                _envelope(audit, value, label, "fake_event_run" if label == "trace" else "compile_plan")
    seen = set()
    for action in plan["actions"]:
        aid = action["id"]
        if not isinstance(aid, str) or not aid or aid in seen:
            audit.fail("contract", "ACTION_ID", "Action IDs must be unique nonempty strings", action_id=aid)
        seen.add(aid)
        for key in ("kind", "atoms", "t_start_us", "t_end_us", "resources", "source_ids", "depends_on", "payload", "condition"):
            if key not in action:
                audit.fail("contract", "MISSING_FIELD", f"Action requires {key}", action_id=aid)
        if action.get("kind") not in KINDS:
            audit.fail("contract", "UNSUPPORTED_ACTION", f"Unknown action kind {action.get('kind')}", action_id=aid)
        if action.get("kind") == "gate":
            name = action["payload"].get("name")
            if name not in device["operations"]["native_1q_gates"] + ["CZ"]:
                audit.fail("contract", "UNSUPPORTED_GATE", f"Unknown native gate {name}", action_id=aid)
            if name != "CZ" and len(action["atoms"]) != 1:
                audit.fail("contract", "GATE_ARITY", "Native 1q gate must address exactly one atom", action_id=aid)
        if action.get("kind") == "measure" and len(action["atoms"]) != 1:
            audit.fail("contract", "MEASUREMENT_ARITY", "Readout must bind one atom to one result", action_id=aid)
        for key in ("atoms", "resources", "source_ids", "depends_on"):
            vals = action[key]
            if not isinstance(vals, list) or any(not isinstance(x, str) or not x for x in vals) or len(vals) != len(set(vals)):
                audit.fail("contract", "INVALID_LIST", f"{key} must contain unique nonempty strings", action_id=aid)
        if not action["source_ids"]:
            audit.fail("contract", "SOURCE_MISSING", "Every action needs source provenance", action_id=aid)
        cond = action.get("condition")
        if cond is not None and (not isinstance(cond, dict) or not isinstance(cond.get("bit"), str) or type(cond.get("equals")) is not int or cond["equals"] not in (0, 1)):
            audit.fail("contract", "CONDITION", "Invalid classical condition", action_id=aid)
        if cond is not None and not (action["kind"] == "gate" and action["payload"].get("name") != "CZ" and len(action["atoms"]) == 1):
            audit.need("contract", "CONDITIONAL_EFFECT", "Only conditional single-qubit gates are fully checked in this profile")
    audit.metrics["action_count"] = len(plan["actions"])


def _timing(audit, plan, device, external_actions=None, external_results=None):
    actions = plan["actions"]
    by_id = {a["id"]: a for a in actions}
    external_actions=external_actions or {}
    writers = {rid:(r['ready_us'],{'kind':'external','id':r['action_id']}) for rid,r in (external_results or {}).items()}
    for a in actions:
        start, end = a["t_start_us"], a["t_end_us"]
        if not _finite(start) or not _finite(end) or start < 0 or end < start or (a["kind"] != "classical" and end <= start):
            audit.fail("timing", "INTERVAL", "Invalid or zero duration physical interval", action_id=a["id"])
            continue
        for dep in a["depends_on"]:
            if dep == a["id"] or dep not in by_id and dep not in external_actions:
                audit.fail("timing", "DEPENDENCY", "Missing or self dependency", action_id=a["id"], resource=dep)
            elif (by_id[dep] if dep in by_id else external_actions[dep])["t_end_us"] > start + EPS:
                audit.fail("timing", "DEPENDENCY_TIME", "Action starts before dependency completes", action_id=a["id"], resource=dep)
        if a["kind"] in ("measure", "classical"):
            if a['kind']=='classical' and (a['payload'].get('operation') not in ('xor','copy','all_zero','postprocess_phase') or len(a['payload'].get('writes',[]))!=1):
                audit.need('timing','CLASSICAL_OPERATION_UNSUPPORTED','Unknown deterministic classical result producer')
                continue
            rid = a["payload"]["result_id"]
            ready = a["payload"]["result_ready_us"]
            if rid in writers:
                audit.fail("timing", "RESULT_REUSED", "Different measurement instances share a result ID", action_id=a["id"], resource=rid)
            writers[rid] = (ready, a)
            if not _finite(ready) or ready < end - EPS:
                audit.fail("timing", "RESULT_READY", "Result cannot be ready before readout completes", action_id=a["id"], resource=rid)
    # Explicit graph cycle check also handles zero-duration classical cycles.
    indegree = {aid: 0 for aid in by_id}
    children = defaultdict(list)
    for a in actions:
        for dep in a["depends_on"]:
            if dep in by_id:
                indegree[a["id"]] += 1
                children[dep].append(a["id"])
    pending = [aid for aid, degree in indegree.items() if degree == 0]
    visited = 0
    while pending:
        aid = pending.pop()
        visited += 1
        for child in children[aid]:
            indegree[child] -= 1
            if not indegree[child]:
                pending.append(child)
    if visited != len(by_id):
        audit.fail("timing", "DEPENDENCY_CYCLE", "Action dependency graph contains a cycle")
    for a in actions:
        reads = set(a["payload"].get("reads", []))
        if a.get("condition"):
            reads.add(a["condition"]["bit"])
        for rid in reads:
            if rid not in writers:
                audit.fail("timing", "RESULT_UNKNOWN", "Read has no measurement producer", action_id=a["id"], resource=rid)
            elif writers[rid][0] + device["timings_us"]["feedback_latency"] > a["t_start_us"] + EPS:
                audit.fail("timing", "EARLY_RESULT_READ", "Read precedes measurement result ready time", action_id=a["id"], resource=rid)
    audit.metrics["measurement_count"] = sum(a['kind']=='measure' for a in actions)
    audit.metrics['classical_result_count'] = sum(a['kind']=='classical' for _,a in writers.values())
    audit.metrics["makespan_us"] = max((a["t_end_us"] for a in actions), default=0) - min((a["t_start_us"] for a in actions), default=0)
    return writers


def _resources(audit, plan):
    intervals = defaultdict(list)
    for a in plan["actions"]:
        resources = set(a["resources"]) | {f"atom:{atom}" for atom in a["atoms"]}
        for r in resources:
            intervals[r].append(a)
    for resource, actions in intervals.items():
        actions.sort(key=lambda a: (a["t_start_us"], a["t_end_us"], a["id"]))
        active = None
        for a in actions:
            if a["t_end_us"] <= a["t_start_us"]:
                continue
            if active is not None and a["t_start_us"] < active["t_end_us"] - EPS:
                audit.fail("resources", "RESOURCE_OVERLAP", f"Overlaps action {active['id']}", action_id=a["id"], resource=resource)
            if active is None or a["t_end_us"] > active["t_end_us"]:
                active = a


def validate(atom_program: dict, device: dict, trace: dict | None = None, physical_program: dict | None = None) -> dict:
    """Return an auditable report, never a compiler-provided acceptance flag."""
    started = time.perf_counter()
    audit = Audit()
    inputs = {"atom_program": atom_program, "device": device, "trace": trace, "physical_program": physical_program}
    hashes, versions = {}, {}
    for label, value in inputs.items():
        if value is None:
            continue
        try:
            hashes[label] = _hash(value)
            versions[label] = value.get("schema_version")
        except (TypeError, ValueError, AttributeError) as exc:
            audit.fail("contract", "NON_JSON_INPUT", f"{label}: {exc}")
    audit.guard("contract", _contract, atom_program, device, trace, physical_program)
    audit.guard("timing", _timing, atom_program, device)
    audit.guard("resources", _resources, atom_program)
    from .geometry import check_geometry
    geometry = audit.guard("geometry", check_geometry, atom_program, device)
    if geometry is None:
        audit.need("broadcast", "GEOMETRY_UNAVAILABLE", "Broadcast reconstruction was not completed")
    from .source import check_source
    audit.guard("source", check_source, atom_program, physical_program)
    from .trace import check_trace
    audit.guard("trace", check_trace, atom_program, device, trace, geometry)
    failed = {x["check"] for x in audit.failures}
    unknown = {x["check"] for x in audit.unverified}
    checks = [{"id": check, "scope": scope, "status": "failed" if check in failed else "unverified" if check in unknown else "passed"} for check, scope in CHECKS.items()]
    audit.metrics["validation_wall_seconds"] = time.perf_counter() - started
    return {
        "schema_version": "ValidationReport/0.2.0-draft", "artifact_id": "validation/" + _hash(hashes)[:16],
        "provenance": {"producer": "na_pipeline.validation", "version": VERSION, "kb_revision": "kb-0004", "contract": "IF-MVP-001/0.2.1-draft", "input_fixture": any(isinstance(value, dict) and isinstance(value.get("provenance"), dict) and value["provenance"].get("fixture") is True for value in inputs.values() if value is not None)},
        "passed": not audit.failures and not audit.unverified, "scoped_pass": not audit.failures,
        "scope": "T601 supported compile/schedule profile; one fake path",
        "checks": checks, "failures": audit.failures, "unverified": audit.unverified,
        "out_of_scope": ["quantum_state", "hardware_execution", "noise_or_fidelity", "fault_tolerance_proof", "logical_to_physical_protocol_proof", "user_visual_acceptance", "full_Shor_acceptance", "factory_lifecycle_until_T302", "cache_performance_or_online_window_resume"],
        "input_hashes": hashes, "input_versions": versions, "metrics": audit.metrics,
        "quantum_state_simulated": False, "hardware_executed": False, "loss_enabled": False,
    }
