"""Reconstruct diagnostics from actual per-atom events without editing times."""


def summarize_groups(atom_program, trace, calls=()):
    events = [e for e in trace["events"] if e["status"] == "completed"]
    owners = {aid: call["call_id"] for call in calls for aid in call["trace_action_ids"]}
    grouped = {}
    for event in events:
        gid = event["payload"].get("group_id")
        if gid is not None:
            grouped.setdefault((owners.get(event["action_id"]), gid), []).append(event)
    reports = []
    for (call_id, gid), group in grouped.items():
        measurements = [e for e in group if e["kind"] == "measure"]
        transports = [e for e in group if e["kind"] in ("pickup", "move", "drop")]
        if not measurements and not any(e["payload"].get("purpose") == "patch_initialization_transport" for e in group):
            continue
        report = {"group_id": f"{call_id}/{gid}" if call_id and not gid.startswith(call_id+"/") else gid, "formal_group_id": gid, "call_id": call_id,
                  "purpose": "maintenance_readout" if measurements else "patch_initialization_transport",
                  "cycle_start_us": min(e["t_start_us"] for e in group), "cycle_end_us": max(e["t_end_us"] for e in group),
                  "transport_batch_count": sum(e["kind"] == "move" for e in transports),
                  "split_reasons": [], "per_atom_wait_us": {}, "members": []}
        report["cycle_duration_us"] = report["cycle_end_us"]-report["cycle_start_us"]
        report["group_transport_interval_us"] = report["cycle_duration_us"]
        report["cycle_scope"] = "group_events_only"
        for call in calls:
            own = set(call["trace_action_ids"])
            if group[0]["action_id"] in own:
                report.update(call_id=call["call_id"], cycle_start_us=call["start_us"], cycle_end_us=call["end_us"],
                              cycle_duration_us=call["end_us"]-call["start_us"], cycle_scope="complete_logical_call")
                break
        if measurements:
            starts, ends, ready = [], [], []
            for event in measurements:
                aid, start = event["atoms"][0], event["t_start_us"]
                preceding = [e["t_end_us"] for e in events if aid in e["atoms"] and e["kind"] in ("gate", "pickup", "move", "drop", "reset") and e["t_end_us"] <= start]
                earliest = max([atom_program["initial_state"].get("time_us", 0), *preceding])
                rid = event["payload"]["result_id"]
                actual_ready = trace["results"][rid]["ready_us"]
                starts.append(start); ends.append(event["t_end_us"]); ready.append(actual_ready)
                report["per_atom_wait_us"][aid] = start-earliest
                report["members"].append({"atom_id": aid, "result_id": rid, "earliest_readout_us": earliest,
                                          "readout_start_us": start, "readout_end_us": event["t_end_us"], "result_ready_us": actual_ready})
            report.update(readout_start_span_us=max(starts)-min(starts), readout_end_span_us=max(ends)-min(ends),
                          result_ready_span_us=max(ready)-min(ready))
        else:
            members = sorted({aid for e in transports for aid in e["atoms"]})
            finishes = [max(e["t_end_us"] for e in transports if aid in e["atoms"]) for aid in members]
            report.update(members=members, initialization_completion_span_us=max(finishes)-min(finishes) if finishes else 0)
        # Absence of a reason is recorded; it is not invented from the spans.
        report["split_reasons"] = [reason for e in group for reason in e["payload"].get("split_reasons", [])]
        report["metric_scope"] = "actual runtime events; source eligibility and waiting reasons require independent validation"
        reports.append(report)
    return reports
