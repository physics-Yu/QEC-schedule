"""Streaming checks against public PhysicalProgram instances."""
from .checker import EPS, _hash


def check_source(audit, plan, physical):
    if physical is None:
        audit.need("source", "PHYSICAL_INPUT_MISSING", "Supply the original PhysicalProgram for omission and semantic checks")
        return
    from na_pipeline.qec import iter_physical_ops
    actions = {a["id"]: a for a in plan["actions"]}
    source_map = plan["source_map"]
    qubits = {a["atom_id"]: a["qubit_id"] for a in plan["initial_state"]["atoms"]}
    expected_qubits = {q["id"] for q in physical["qubits"]}
    if set(qubits.values()) != expected_qubits:
        audit.fail("source", "QUBIT_COVERAGE", "Physical qubit inventory differs from atom bindings")
    for key in ("physical_program", "physical"):
        if key in plan.get("input_hashes", {}) and plan["input_hashes"][key] != _hash(physical):
            audit.fail("source", "PHYSICAL_HASH", "Physical program differs from the compiler input")
    seen, used, endpoints = set(), set(), {}
    count = 0
    for op in iter_physical_ops(physical):
        count += 1
        sid = op["id"]
        if sid in seen:
            audit.fail("source", "SOURCE_INSTANCE_ID", "Expanded instance operation ID is reused", source_id=sid)
        seen.add(sid)
        listed = source_map.get(sid, [])
        if not listed:
            audit.fail("source", "SOURCE_OMITTED", "Physical operation has no atomic implementation", source_id=sid)
            continue
        if len(listed) != len(set(listed)) or any(aid not in actions for aid in listed):
            audit.fail("source", "SOURCE_MAP", "Source map repeats or references missing actions", source_id=sid)
            continue
        mapped = [actions[aid] for aid in listed]
        for a in mapped:
            used.add(a["id"])
            if sid not in a["source_ids"] or a["payload"].get("physical_op_id") != sid:
                audit.fail("source", "SOURCE_BINDING", "Action and source map disagree on operation instance", source_id=sid, action_id=a["id"])
            if not set(op["source_ids"]).issubset(a["source_ids"]):
                audit.fail("source", "SOURCE_PROVENANCE", "Original operation provenance was dropped", source_id=sid, action_id=a["id"])
            if a["payload"].get("source_metadata", {}) != op.get("metadata", {}):
                audit.fail("source", "SOURCE_METADATA", "Operation metadata was dropped or changed", source_id=sid, action_id=a["id"])
            expected_writes = op["writes"] if a["kind"] in ("measure", "classical") else []
            if a["payload"].get("writes") != expected_writes:
                audit.fail("source", "WRITES_CHANGED", "Source result write namespace changed", source_id=sid, action_id=a["id"])
        semantic = sorted([a for a in mapped if a["kind"] in ("gate", "measure", "reset", "wait", "classical")], key=lambda a: (a["t_start_us"], a["t_end_us"], a["id"]))
        # Backend waiting actions may be explicit scheduling overhead; only
        # source kind wait uses wait as the implementing semantic operation.
        if op["kind"] != "wait":
            semantic = [a for a in semantic if a["kind"] != "wait"]
        if not semantic:
            audit.fail("source", "SOURCE_NO_EFFECT", "Source covered only by transport, no semantic operation", source_id=sid)
            continue
        expected = []
        if op["kind"] == "gate":
            name = op["params"]["name"]
            if name == "CX":
                c, t = op["qubits"]
                expected = [("gate", "H", [t]), ("gate", "CZ", sorted([c,t])), ("gate", "H", [t])]
            else:
                expected = [("gate", name, sorted(op["qubits"]) if name == "CZ" else op["qubits"])]
        else:
            expected = [(op["kind"], None, op["qubits"])]
        actual = []
        for a in semantic:
            p = a["payload"]
            if a["kind"] == "gate" and p.get("name") == "CZ":
                if len(p.get("pairs", [])) == 1:
                    bound = sorted(qubits[key] for key in p["pairs"][0])
                else:
                    bound = [sorted(qubits[key] for key in pair) for pair in p.get("pairs", [])]
            else:
                bound = [qubits[key] for key in a["atoms"]]
            actual.append((a["kind"], p.get("name") if a["kind"] == "gate" else None, bound))
            if a.get("condition") != op.get("condition"):
                audit.fail("source", "CONDITION_CHANGED", "Lowering changed or dropped a source condition", source_id=sid, action_id=a["id"])
            if not set(op["reads"]).issubset(p.get("reads", [])):
                audit.fail("source", "READS_DROPPED", "Source classical reads disappeared", source_id=sid, action_id=a["id"])
            if op["kind"] == "measure" and (p.get("result_id") not in op["writes"] or len(op["writes"]) != 1 or p.get("basis") != op["params"].get("basis", "Z")):
                audit.fail("source", "MEASUREMENT_CHANGED", "Readout basis or result namespace changed", source_id=sid, action_id=a["id"])
            if op["kind"] == "reset" and p.get("state") != 0:
                audit.fail("source", "RESET_CHANGED", "Reset target changed", source_id=sid, action_id=a["id"])
            if op["kind"] == "gate" and op["params"]["name"] != "CX":
                for key, value in op["params"].items():
                    if key != "name" and p.get("params", {}).get(key) != value:
                        audit.fail("source", "GATE_PARAMETER", f"Gate parameter {key} changed", source_id=sid, action_id=a["id"])
        if actual != expected:
            audit.fail("source", "LOWERING_SEMANTICS", f"Expected {expected}; got {actual}", source_id=sid)
        if op["kind"] == "classical":
            audit.need("source", "CLASSICAL_SEMANTICS", "General classical computation equivalence is not implemented")
        start = min(a["t_start_us"] for a in semantic)
        end = max(a["t_end_us"] for a in semantic)
        for earlier, later in zip(semantic, semantic[1:]):
            if earlier["t_end_us"] > later["t_start_us"] + EPS:
                audit.fail("source", "LOWERING_ORDER", "Sequential decomposition gates overlap", source_id=sid)
        for dep in op["after"]:
            if dep not in endpoints or endpoints[dep] > start + EPS:
                audit.fail("source", "PHYSICAL_DEPENDENCY", "Lowering violates a physical operation dependency", source_id=sid, resource=dep)
        endpoints[sid] = end
    for sid in set(source_map) - seen:
        audit.fail("source", "SOURCE_EXTRA", "Source map refers to a nonexistent physical operation", source_id=sid)
    for aid in set(actions) - used:
        audit.fail("source", "ACTION_UNMAPPED", "Action has no source implementation binding", action_id=aid)
    audit.metrics["physical_operation_count"] = count
    if "physical_op_count" in plan.get("stats", {}) and plan["stats"]["physical_op_count"] != count:
        audit.fail("source", "PHYSICAL_COUNT", "Plan physical operation count is not the expanded instance count")

