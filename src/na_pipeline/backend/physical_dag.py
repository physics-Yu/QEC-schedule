"""R3 PhysicalDAG/0.1.0 adapter preserving all typed dependencies and sources."""
from copy import deepcopy

from .enola_kernel import StrategyError, digest
from .physical_window import compile_operation_window
from .execution_context import validate_execution_context


def _shift_window(result, offset):
    atom = result["atom_program"]
    for action in atom["actions"]:
        action["t_start_us"] += offset
        action["t_end_us"] += offset
        for key in ("result_ready_us", "earliest_ready_us"):
            if key in action["payload"]: action["payload"][key] += offset
    def shift_group(value):
        if isinstance(value, list): return [shift_group(v) for v in value]
        if not isinstance(value, dict): return deepcopy(value)
        out = {}
        for key, val in value.items():
            if key in {"start_us", "end_us", "t_start_us", "t_end_us", "result_ready_us", "earliest_ready_us", "readout_start_us", "readout_end_us", "measurement_start_us", "measurement_end_us"} and type(val) in (int, float):
                out[key] = val + offset
            elif key == "earliest_readout_us": out[key] = {a: t+offset for a, t in val.items()}
            else: out[key] = shift_group(val)
        return out
    atom["groups"] = shift_group(atom["groups"])
    result["measurement_placements"] = shift_group(result.get("measurement_placements", []))
    atom["stats"]["t_end_us"] += offset
    atom["stats"]["duration_us"] += offset
    for decision in result["ready_decisions"]: decision["time_us"] += offset
    result["result_ready_offsets_us"] = {r: t+offset for r, t in result["result_ready_offsets_us"].items()}
    for interval in result["resource_intervals"]:
        interval["start_us"] += offset; interval["end_us"] += offset


def compile_physical_dag(physical_dag, device, initial_state, *, enola_root=None, budget=None, execution_context=None, defer_runtime_inputs=False):
    """Compile one or a list of fully bound, unguarded physical DAGs jointly.

    Lists must be a logical-ready batch selected by R5. Conditional nodes stay
    rejected until R5 passes a public resolved-guard contract; no fake value is guessed.
    """
    dags = physical_dag if isinstance(physical_dag, list) else [physical_dag]
    if not dags:
        raise StrategyError("EMPTY_PHYSICAL_DAG_BATCH", "Explicit nonempty ready batch required")
    if execution_context is not None:
        validate_execution_context(execution_context, dags, device, initial_state)
    operations, groups = [], []
    owner, used_qubits, requirements, external_reads = {}, set(), [], set()
    for dag in dags:
        from na_pipeline.qec.physical_dag import validate_physical_dag
        validate_physical_dag(dag)
        if dag.get("schema_version") != "PhysicalDAG/0.1.0" or dag.get("entry_mode") != "preinitialized":
            raise StrategyError("PHYSICAL_DAG_VERSION", "R3 PhysicalDAG/0.1.0 preinitialized required")
        if (dag.get("execution_guard") is not None or dag.get("external_reads")) and not defer_runtime_inputs and execution_context is None:
            raise StrategyError("PHYSICAL_DAG_GUARD_UNRESOLVED", "R5 must resolve execution guards and external reads before physical submission",
                                guard=dag.get("execution_guard"), external_reads=dag.get("external_reads"))
        requirements.append({"physical_dag_id": dag["artifact_id"], "execution_guard": deepcopy(dag.get("execution_guard")),
                             "external_reads": deepcopy(dag.get("external_reads", []))})
        external_reads.update(dag.get("external_reads", []))
        if dag.get("execution_guard"): external_reads.add(dag["execution_guard"]["bit"])
        nodes = {o["id"]: deepcopy(o) for o in dag["nodes"]}
        if any(dag.get(flag, False) is not False for flag in ("quantum_state_simulated", "hardware_executed", "loss_enabled")):
            raise StrategyError("PHYSICAL_DAG_EVIDENCE", "Only compile/schedule source evidence is supported")
        if len(nodes) != len(dag["nodes"]) or any(n in owner for n in nodes):
            raise StrategyError("PHYSICAL_ID_COLLISION", "Each instance must use its own physical operation namespace")
        declared = {q["id"] for q in dag["qubits"]}
        world_qubits = {a.get("site_id", a["qubit_id"]): a for a in initial_state["atoms"]}
        if any(q["id"] not in world_qubits or q.get("aod_group") != world_qubits[q["id"]]["aod_group"] for q in dag["qubits"]):
            raise StrategyError("PHYSICAL_AOD_BINDING", "Every declared physical qubit must retain its producer-assigned AOD group in the complete world")
        used = {q for o in nodes.values() for q in o["qubits"]}
        if used & used_qubits:
            raise StrategyError("JOINT_DAG_QUBIT_CONFLICT", "A logical-ready joint batch may not contain two nodes using the same qubit",
                                qubits=sorted(used & used_qubits))
        used_qubits.update(used)
        if any(q not in declared for o in nodes.values() for q in o["qubits"]):
            raise StrategyError("PHYSICAL_QUBIT_UNDECLARED", "DAG operation references an undeclared qubit")
        if any(dep not in nodes for o in nodes.values() for dep in o["after"]):
            raise StrategyError("PHYSICAL_DAG_EDGE", "Every operation after must be an internal DAG node")
        edges = set()
        for e in dag["edges"]:
            if e["kind"] not in {"quantum", "protocol", "classical_ready"} or e["source"] not in nodes or e["target"] not in nodes:
                raise StrategyError("PHYSICAL_DAG_EDGE", "Unknown edge kind or missing endpoint")
            edges.add((e["source"], e["target"]))
            if e["source"] not in nodes[e["target"]]["after"]:
                nodes[e["target"]]["after"].append(e["source"])
        if any((dep, o["id"]) not in edges for o in dag["nodes"] for dep in o["after"]):
            raise StrategyError("PHYSICAL_DAG_EDGE_COVERAGE", "Typed edges must cover every original after dependency")
        for n in nodes:
            owner[n] = dag["artifact_id"]
        operations.extend(nodes.values())
        for g in dag["groups"]:
            bound = deepcopy(g)
            for m in bound["members"]:
                if "mz_slot_role" not in m:
                    m["mz_slot_role"] = m["local_id"]
                if m.get("post_readout_reset_op_id") is None:
                    raise StrategyError("GROUP_SERVICE_RESET_UNDECLARED", "This compiler requires explicit service reset before return", group=g["group_id"])
            groups.append(bound)
    external_offsets = {r: execution_context["published_results"][r]["ready_us"] - execution_context["time_us"]
                        for r in external_reads} if execution_context is not None else external_reads
    result = compile_operation_window(operations, groups, device, initial_state, enola_root=enola_root, budget=budget, external_reads=external_offsets)
    return finalize_physical_plan(result, dags, device, initial_state, execution_context)


def finalize_physical_plan(result, dags, device, initial_state, execution_context=None):
    """Bind per-instance source/context summaries without rerunning placement or routing."""
    if execution_context is not None:
        validate_execution_context(execution_context, dags, device, initial_state)
    requirements = [{"physical_dag_id": d["artifact_id"], "execution_guard": deepcopy(d.get("execution_guard")), "external_reads": deepcopy(d.get("external_reads", []))} for d in dags]
    external_reads = {r for d in dags for r in d.get("external_reads", [])} | {d["execution_guard"]["bit"] for d in dags if d.get("execution_guard")}
    external_offsets = {r: execution_context["published_results"][r]["ready_us"]-execution_context["time_us"] for r in external_reads} if execution_context is not None else external_reads
    owner = {o["id"]: d["artifact_id"] for d in dags for o in d["nodes"]}
    result["atom_program"]["provenance"]["fixture"] = any(d.get("provenance", {}).get("fixture", False) for d in dags)
    result["schema_version"] = "physical-plan/0.1"
    result["physical_dags"] = deepcopy(dags)
    result["runtime_requirements"] = requirements
    result["atom_program"]["runtime_requirements"] = deepcopy(requirements)
    result["feedback_latency_us"] = device["timings_us"]["feedback_latency"]
    deferred = bool(external_reads and execution_context is None)
    result["atom_program"]["complete"] = not deferred
    result["atom_program"]["provenance"]["requires_runtime_binding"] = deferred
    if execution_context is not None:
        result["execution_context"] = deepcopy(execution_context)
        if external_reads:
            producers = [execution_context["published_results"][r]["action_id"] for r in sorted(external_reads)]
            roots = [a for a in result["atom_program"]["actions"] if not a["depends_on"]]
            offset = max(0., max(external_offsets.values()) + device["timings_us"]["feedback_latency"] - min(a["t_start_us"] for a in roots))
            if offset: _shift_window(result, offset)
            for action in roots:
                    action["depends_on"] += list(dict.fromkeys(producers))
                    action["payload"]["reads"] = list(dict.fromkeys(action["payload"].get("reads", []) + sorted(external_reads)))
                    action["payload"]["execution_context_ref"] = digest(execution_context)
    result["input_hashes"] = {"physical_dags": [digest(d) for d in dags], "device": digest(device), "world_state": digest(initial_state)}
    result["physical_node_owner"] = owner
    result["node_summaries"] = {}
    by_action = {a["id"]: a for a in result["atom_program"]["actions"]}
    for dag in dags:
        ids = list(dict.fromkeys(a for o in dag["nodes"] for a in result["atom_program"]["source_map"][o["id"]]))
        actions = [by_action[a] for a in ids]
        results = {b for o in dag["nodes"] for b in o["writes"]}
        start = min((a["t_start_us"] for a in actions), default=0.)
        end = max([start, *(a["t_end_us"] for a in actions), *(result["result_ready_offsets_us"][b] for b in results)])
        idset = set(ids)
        result["node_summaries"][dag["artifact_id"]] = {
            "node_id": dag.get("logical_node_id", dag.get("logical_binding", {}).get("logical_node_id", dag["artifact_id"])), "action_ids": ids,
            "start_us": start, "end_us": end, "duration_us": end-start,
            "result_ready_offsets_us": {b: result["result_ready_offsets_us"][b]-start for b in results},
            "terminal_source_ids": deepcopy(dag["terminals"]),
            "terminal_action_map": {n: deepcopy(result["atom_program"]["source_map"][n]) for n in dag["terminals"]},
            "reset_action_map": {o["id"]: [a for a in result["atom_program"]["source_map"][o["id"]] if by_action[a]["kind"] == "reset"]
                                 for o in dag["nodes"] if o["kind"] == "reset"},
            "lifecycle_completion": "requires_all_terminal_actions_results_and_actual_R5_cleanup_receipts",
            "intervals": [{**i, "start_us": i["start_us"]-start, "end_us": i["end_us"]-start}
                          for i in result["resource_intervals"] if i["action_id"] in idset]}
    return result
