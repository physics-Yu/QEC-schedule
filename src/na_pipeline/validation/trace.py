"""Trace verification against independent plan reconstruction."""
from .checker import EPS, _finite, _hash


def check_trace(audit, plan, device, trace, geometry, external_results=None, boundary_time_us=None):
    if trace is None:
        audit.need("trace", "TRACE_MISSING", "Supply the actual fake EventTrace for execution checks")
        return
    if trace.get("sampled") is not False or trace.get("measurement_origin") != "fake":
        audit.fail("trace", "FAKE_LABEL", "Trace must explicitly mark fake, unsampled results")
    for key, source in (("atom_program", plan), ("device", device)):
        if key in trace.get("input_hashes", {}) and trace["input_hashes"][key] != _hash(source):
            audit.fail("trace", "TRACE_INPUT_HASH", f"Trace {key} input hash mismatch")
    if trace.get("atom_program_ref") != plan["artifact_id"] or trace.get("device_ref") != device["artifact_id"]:
        audit.fail("trace", "TRACE_REFERENCE", "Trace references a different plan/device artifact")
    actions = {a["id"]: a for a in plan["actions"]}
    events = {e["action_id"]: e for e in trace["events"]}
    if len(events) != len(trace["events"]) or set(events) != set(actions):
        audit.fail("trace", "EVENT_COVERAGE", "Each planned action must have exactly one completed/skipped event")
    own_results=trace['results']; external_results=external_results or {}
    if set(own_results)&set(external_results):audit.fail('trace','RESULT_REUSED','New window reuses an already certified result identity')
    results = {**external_results,**own_results}
    produced = set()
    for aid, event in events.items():
        if aid not in actions:
            continue
        action = actions[aid]
        for key in ("kind", "t_start_us", "t_end_us", "atoms", "resources", "source_ids", "depends_on", "condition", "payload"):
            if event.get(key) != action.get(key):
                audit.fail("trace", "EVENT_CHANGED", f"Event differs from its action in {key}", action_id=aid)
        should_run = True
        cond = action.get("condition")
        reads = set(action["payload"].get("reads", []))
        if cond:
            reads.add(cond["bit"])
            result = results.get(cond["bit"])
            if result is None:
                audit.fail("trace", "CONDITION_RESULT_MISSING", "Condition has no actual result", action_id=aid)
            else:
                should_run = result["value"] == cond["equals"]
        if event.get("status") != ("completed" if should_run else "skipped"):
            audit.fail("trace", "BRANCH_STATUS", "Event status disagrees with its actual condition", action_id=aid)
        condition_reads = event.get("condition_reads")
        expected_condition = [] if cond is None else [cond["bit"]]
        if not isinstance(condition_reads, list) or [r.get("result_id") for r in condition_reads] != expected_condition:
            audit.fail("trace", "CONDITION_READ_RECORD", "Condition read record is missing or belongs to another instance", action_id=aid)
        else:
            for record in condition_reads:
                actual = results.get(record["result_id"], {})
                if any(record.get(key) != actual.get(key) for key in ("value", "origin", "ready_us", "action_id")):
                    audit.fail("trace", "CONDITION_READ_RECORD", "Recorded condition input differs from actual published result", action_id=aid)
        for rid in reads:
            result = results.get(rid)
            if result is None or not _finite(result.get("ready_us")) or result["ready_us"] + device["timings_us"]["feedback_latency"] > action["t_start_us"] + EPS:
                audit.fail("trace", "EARLY_RESULT_READ", "Trace consumes absent/not-ready result", action_id=aid, resource=rid)
        if action["kind"] in ("measure", "classical") and should_run:
            rid = action["payload"]["result_id"]
            produced.add(rid)
            result = results.get(rid)
            if not result:
                audit.fail("trace", "RESULT_OMITTED", "Executed measurement has no result", action_id=aid, resource=rid)
                continue
            is_post=action['kind']=='classical' and action['payload'].get('operation')=='postprocess_phase'
            if result.get("origin") != "fake" or not is_post and (type(result.get("value")) is not int or result["value"] not in (0, 1)):
                audit.fail("trace", "RESULT_VALUE", "Result must be a labeled fake bit", action_id=aid, resource=rid)
            if result.get("action_id") != aid or result.get("result_id") != rid:
                audit.fail("trace", "RESULT_INSTANCE", "Result belongs to a different action/instance", action_id=aid, resource=rid)
            ready = result.get("ready_us")
            if not _finite(ready) or ready < action["payload"]["result_ready_us"] - EPS or result.get("available_us") != ready:
                audit.fail("trace", "RESULT_READY", "Trace result availability violates plan", action_id=aid, resource=rid)
            if event.get("result_ids") != [rid] or event.get("result_ready_us", {}).get(rid) != ready:
                audit.fail("trace", "EVENT_RESULT_BINDING", "Measurement event and published result do not agree", action_id=aid, resource=rid)
            if action['kind']=='classical':
                operation=action['payload'].get('operation'); inputs=action['payload'].get('reads',[])
                values=[results[r]['value'] for r in inputs]
                if operation=='xor' and values: expected_value=sum(values)%2
                elif operation=='copy' and len(values)==1: expected_value=values[0]
                elif operation=='all_zero' and values: expected_value=int(not any(values))
                elif operation=='postprocess_phase':
                    from .stream_postprocess import inspect_postprocess_value
                    inspect_postprocess_value(audit,action,values,result['value']);expected_value=result['value']
                else:
                    audit.need('trace','CLASSICAL_OPERATION_UNSUPPORTED','Unsupported deterministic classical computation'); continue
                if result['value']!=expected_value or result.get('derivation')!=operation:
                    audit.fail('trace','CLASSICAL_RESULT_VALUE','Actual classical result differs from its executed input bits and operation',action_id=aid,resource=rid)
                recorded=event.get('reads',[])
                if [r.get('result_id') for r in recorded]!=inputs or any(any(r.get(k)!=results[r['result_id']].get(k) for k in ('value','origin','ready_us','action_id')) for r in recorded):
                    audit.fail('trace','CLASSICAL_READ_RECORD','Classical event read evidence differs from its actual input producers',action_id=aid)
        elif event.get("result_ids") != []:
            audit.fail("trace", "UNEXPECTED_EVENT_RESULT", "A non-producing event declares results", action_id=aid)
        if geometry is not None:
            for phase in ("before", "after"):
                expected_state = geometry["snapshots"].get((aid, phase))
                actual_state = event.get(f"state_{phase}")
                if not isinstance(actual_state, dict) or set(actual_state) != set(action["atoms"]):
                    audit.fail("trace", "EVENT_STATE", f"state_{phase} must bind all action atoms", action_id=aid)
                    continue
                if expected_state is not None:
                    for atom_id, expected_atom in expected_state.items():
                        actual_atom = actual_state[atom_id]
                        for key in ("atom_id", "qubit_id", "site_id", "carrier", "trap_id", "aod_group", "row_id", "column_id", "position_um", "reset_epoch", "measurement_count"):
                            if actual_atom.get(key) != expected_atom.get(key):
                                audit.fail("trace", "EVENT_STATE", f"state_{phase}.{key} differs from independent reconstruction", action_id=aid, resource=atom_id)
    if set(own_results) != produced:
        audit.fail("trace", "EXTRA_RESULTS", "Trace carries unproduced or missing measurement instances")
    if geometry is None:
        audit.need("trace", "GEOMETRY_UNAVAILABLE", "Could not independently reconstruct final geometry")
    else:
        if trace["illumination_counts"] != geometry["illumination_counts"]:
            audit.fail("trace", "ILLUMINATION_COUNT", "Per-atom counts disagree with all illuminated atoms in actual broadcasts")
        final_atoms = trace["final_state"]["atoms"]
        final_atoms = {a["atom_id"]: a for a in final_atoms} if isinstance(final_atoms, list) else final_atoms
        if set(final_atoms) != set(geometry["atoms"]):
            audit.fail("trace", "FINAL_IDENTITY", "Atoms were added or removed during a no-loss run")
        for aid, expected in geometry["atoms"].items():
            actual = final_atoms.get(aid, {})
            for key in ("atom_id", "qubit_id", "site_id", "carrier", "trap_id", "aod_group", "row_id", "column_id", "reset_epoch", "measurement_count"):
                if actual.get(key) != expected.get(key):
                    audit.fail("trace", "FINAL_BINDING", f"Final {key} differs from reconstruction", resource=aid)
            point = actual.get("position_um")
            if not isinstance(point, list) or len(point) != 2 or any(not _finite(v) for v in point) or any(abs(x-y) > EPS for x,y in zip(point, expected["position_um"])):
                audit.fail("trace", "FINAL_POSITION", "Final position differs from integrated motion", resource=aid)
        final_traps = trace["final_state"]["slm_traps"]
        final_traps = {t["trap_id"]: t for t in final_traps} if isinstance(final_traps, list) else final_traps
        if final_traps != geometry["slm_traps"]:
            audit.fail("trace", "FINAL_TRAPS", "Final SLM trap inventory/occupancy differs from replay")
        for field, id_field, coord_key, coordinate in (("aod_rows", "row_id", "y_um", 1), ("aod_columns", "column_id", "x_um", 0)):
            expected_lines = {(a["aod_group"], a[id_field]): a["position_um"][coordinate] for a in geometry["atoms"].values() if a["carrier"] == "AOD"}
            line_list = trace["final_state"][field]
            actual_lines = {(line["aod_group"], line[id_field]): line[coord_key] for line in line_list}
            if len(actual_lines) != len(line_list) or actual_lines != expected_lines:
                audit.fail("trace", "FINAL_AXES", "Final AOD axis inventory differs from resident bindings", resource=field)
    stats = trace["stats"]
    start = min((a["t_start_us"] for a in actions.values()), default=0)
    end = max([a["t_end_us"] if events.get(a["id"], {}).get("status") == "completed" else a["t_start_us"] for a in actions.values()] + [r["ready_us"] for r in own_results.values()] + [start])
    if boundary_time_us is not None:
        if not _finite(boundary_time_us) or boundary_time_us<end-EPS:audit.fail('trace','BOUNDARY_BEFORE_READY','Committed boundary precedes an actual terminal/result')
        else:end=boundary_time_us
    expected_stats = {"t_start_us": start, "t_end_us": end, "duration_us": end-start, "atom_count": len(plan["initial_state"]["atoms"]), "action_count": len(actions), "result_count": len(own_results), "executed_action_count": sum(e.get("status") == "completed" for e in events.values()), "skipped_action_count": sum(e.get("status") == "skipped" for e in events.values())}
    if trace["final_state"].get("time_us") != end:
        audit.fail("trace", "FINAL_TIME", "Final state is not at the actual event/result end time")
    for key, expected in expected_stats.items():
        if not _finite(stats.get(key)) or abs(stats[key] - expected) > EPS:
            audit.fail("trace", "TRACE_STATS", f"{key} should be {expected}")
