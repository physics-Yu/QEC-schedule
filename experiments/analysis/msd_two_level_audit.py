"""Read-only independent JSON/native-action audit; never compile or sample.

This checks a completed same-d d3 N1=N2=1, one-successful-L2-run acceptance
artifact. It does not replace the saved native physical validator or certify
logical output error. stdout is the report; inputs are never modified.
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def require(condition: Any, message: str) -> None:
    """Reject an independently observed evidence mismatch."""
    if not condition:
        raise ValueError(message)


def canonical(value: Any) -> str:
    """Hash saved JSON independently of the production serializer."""
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def read(path: Path) -> dict[str, Any]:
    """Read a saved JSON object without changing it."""
    return dict(json.loads(Path(path).read_text(encoding="utf-8")))


def near(a: float, b: float) -> bool:
    """Compare independently reconstructed schedule times."""
    return math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-7)


def inside(path: str | Path, root: Path) -> Path:
    """Resolve an artifact path and reject references outside the run."""
    path = Path(path)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    require(path.is_relative_to(root), f"artifact outside campaign: {path}")
    return path


def layout_key(layout: dict[str, Any]) -> tuple[dict[str, Any], Any]:
    """Compare atom/world state without temporary source-wire ordering."""
    return {a["id"]: a for a in layout["atoms"]}, layout["aod_grids"]


def native_template(
    trace: dict[str, Any], expected_device: dict[str, Any], expected_atoms: set[str]
) -> dict[str, Any]:
    """Replay saved mechanical actions and verify declared goal endpoints."""
    require(
        trace.get("validation", {}).get("ok") is True,
        "native validation missing/failed",
    )
    require(trace["device"] == expected_device, "native Device changed")
    require(
        trace["entry_state"]["qubit_to_atom"] == trace["exit_state"]["qubit_to_atom"],
        "native wire map changed",
    )
    atoms = {a["id"]: copy.deepcopy(a) for a in trace["entry_state"]["atoms"]}
    require(set(atoms) == expected_atoms, "native world omitted/added atoms")
    sites = {s["id"]: s["position"] for s in trace["device"]["slm_sites"]}
    grids = {g["aod_id"]: g for g in trace["entry_state"]["aod_grids"]}
    kinds: Counter[str] = Counter()
    rows, time, tagged = [], 0.0, defaultdict(list)
    for step_index, step in enumerate(trace["program"]["steps"]):
        updates, touched = {}, set()
        for action_index, action in enumerate(step["actions"]):
            kind, span = action["kind"], action["duration_us"]
            require(math.isfinite(span) and span >= 0, "invalid native duration")
            kinds[kind] += 1
            rows.append(
                (
                    step_index,
                    action_index,
                    time,
                    span,
                    kind,
                    tuple(action.get("source_ids", ())),
                )
            )
            for source in action.get("source_ids", ()):
                tagged[source].append(kind)
            if kind in ("Load", "Store"):
                require(near(span, 10), "LOAD/STORE timing changed")
            if kind == "Measure":
                require(near(span, 100), "readout timing changed")
            if kind in ("Load", "Move", "Store"):
                grid = action["grid"]
                grids[grid["aod_id"]] = grid
                members = action["targets"] if kind == "Move" else action["bindings"]
                for member in members:
                    atom_id = member[0]
                    require(
                        atom_id in atoms and atom_id not in touched,
                        "unknown/double-driven atom in native step",
                    )
                    touched.add(atom_id)
                    atom = copy.deepcopy(atoms[atom_id])
                    if kind == "Load":
                        atom["holder"] = {
                            "kind": "aod",
                            "aod_id": grid["aod_id"],
                            "row": member[1],
                            "column": member[2],
                        }
                    elif kind == "Move":
                        atom["position"] = member[1]
                    else:
                        atom["position"] = sites[member[1]]
                        atom["holder"] = {"kind": "slm", "site_id": member[1]}
                    updates[atom_id] = atom
        atoms.update(updates)
        time += max((a["duration_us"] for a in step["actions"]), default=0)
    exit_atoms = {a["id"]: a for a in trace["exit_state"]["atoms"]}
    require(
        atoms == exit_atoms,
        "independent position/holder replay disagrees with native exit",
    )
    actual_grids = [
        grid for _, grid in sorted(grids.items()) if grid["rows"] or grid["columns"]
    ]
    require(
        actual_grids == trace["exit_state"]["aod_grids"],
        "independent AOD replay disagrees",
    )
    goals = []
    for goal in trace.get("transport_goals", []):
        node = trace["dag"]["nodes"][goal["operation_id"]]
        require(node["name"] == "relocate", "transport goal is not native relocation")
        kinds_for_goal = tagged[goal["operation_id"]]
        require(
            kinds_for_goal and set(kinds_for_goal) <= {"Load", "Move", "Store"},
            "transport attributed to fake quantum action",
        )
        require(
            "Move" in kinds_for_goal and "Store" in kinds_for_goal,
            "transport has no actual move/store",
        )
        goal_atoms = []
        for wire, site_id in goal["targets"]:
            atom_id = trace["entry_state"]["qubit_to_atom"][wire]
            require(
                atoms[atom_id]["holder"] == {"kind": "slm", "site_id": site_id},
                "goal final SLM differs",
            )
            require(
                atoms[atom_id]["position"] == sites[site_id],
                "goal final coordinate differs",
            )
            goal_atoms.append(atom_id)
        goals.append(frozenset(goal_atoms))
    return {
        "entry": trace["entry_state"],
        "exit": trace["exit_state"],
        "duration": time,
        "rows": rows,
        "kinds": kinds,
        "goals": goals,
    }


def audit_saved_two_level(
    campaign: Path, task_id: str, native_schedule: Path | None = None
) -> dict[str, Any]:
    """Audit one saved d3, 1+1-factory, one-output acceptance witness.

    This reads the original runner, ledger, native actions and optional exported
    schedule. It never compiles, samples, writes inputs or infers output quality.
    Raises ValueError for incomplete, inconsistent or out-of-scope evidence.
    """
    root = campaign.resolve()
    completion = read(root / "task_completions" / f"{task_id}.json")
    require(
        completion["status"] == "ok",
        f"runner not successful: {completion.get('reason')}",
    )
    require(completion["kind"] == "msd.two_level_witness", "wrong task kind")
    attempts = [
        json.loads(line)
        for line in (root / "task_attempts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    attempt_statuses = Counter(row["status"] for row in attempts)
    require(
        set(attempt_statuses) <= {"ok", "needs_dependencies"},
        "runner journal contains failure/deferred records",
    )
    parent_attempts = [row for row in attempts if row["task_id"] == task_id]
    require(
        sum(row["status"] == "ok" for row in parent_attempts) == 1,
        "duplicate successful parent publication",
    )
    require(
        completion.get("software_failures", 0) == 0, "parent software failures recorded"
    )
    result_path = inside(completion["result_path"], root)
    result = read(result_path)
    require(
        canonical(result) == completion["result_sha256"],
        "published result hash mismatch",
    )
    verified = set()
    for artifact in completion.get("artifacts", []):
        path = inside(artifact["path"], root)
        if path in verified:
            continue
        if artifact.get("hash_kind") == "canonical_json":
            digest = canonical(read(path))
        else:
            with path.open("rb") as stream:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
        require(digest == artifact["sha256"], f"artifact hash mismatch: {path}")
        verified.add(path)
    case, supply = result["case"], result["supply"]
    require(
        case["status"] == "complete" and case.get("failure") is None,
        "case incomplete/failed",
    )
    require(
        all(
            f["status"] == "complete" and f.get("failure") is None
            for f in case["factories"].values()
        ),
        "factory failure present",
    )
    require(
        supply["failure"] is None and supply["parking_lease"] is None,
        "supply failed or parking left leased",
    )
    require(
        not supply["waiting_producer_outputs"]
        and not supply["pending_consumer_requests"],
        "unresolved supply requests",
    )
    require(
        len(result["level1_factories"]) == len(result["level2_factories"]) == 1,
        "not target N1=N2=1 case",
    )
    l1, l2 = result["level1_factories"][0], result["level2_factories"][0]
    require(result["final_level_output_count"] == 1, "not one completed L2 output")
    deliveries = supply["deliveries"]
    require(
        len(deliveries) == len({d["token_id"] for d in deliveries}) == 15,
        "not 15 distinct delivered inputs",
    )
    require(
        Counter(d["ownership"] for d in deliveries) == {"adopt": 4, "reserve": 11},
        "wrong 4+11 ownership split",
    )
    require(
        Counter(d["role"] for d in deliveries if d["ownership"] == "adopt")
        == {f"W{i}": 1 for i in range(2, 6)},
        "wrong adopted work roles",
    )
    require(
        all(d["role"] == "R" for d in deliveries if d["ownership"] == "reserve"),
        "rotation input not R",
    )
    outputs = case["factories"][l1]["outputs"]
    by_output = {o["token_id"]: o for o in outputs}
    require(len(by_output) == len(outputs), "duplicate L1 output")
    tokens = {t["token_id"]: t for t in case["resources"]["tokens"]}
    require(len(tokens) == len(case["resources"]["tokens"]), "duplicate ledger token")
    audit_rows = case["resources"]["audit"]
    require(
        [r["sequence"] for r in audit_rows] == list(range(len(audit_rows))),
        "ledger audit discontinuity",
    )
    offered, consumed, reservations = (
        defaultdict(list),
        defaultdict(list),
        defaultdict(list),
    )
    for event in audit_rows:
        if event["action"] == "offer":
            offered[event["token"]["token_id"]].append(event)
        elif event["action"] == "consume":
            consumed[event["token_id"]].append(event)
        elif event["action"] == "reserve":
            reservations[event["token_id"]].append(event)
    arrivals = [
        m
        for m in case["milestones"]
        if m["kind"] == "external_input_received" and m["factory_id"] == l2
    ]
    require(
        len(arrivals) == len({m["token_id"] for m in arrivals}) == 15,
        "wrong actual L2 receipt count",
    )
    by_arrival = {m["token_id"]: m for m in arrivals}
    calls = {c["invocation_id"]: c for c in case["calls"]}
    require(len(calls) == len(case["calls"]), "duplicate protocol invocation")
    immutable = (
        "token_id",
        "carrier_id",
        "epoch",
        "resource_kind",
        "producer",
        "ready_at_us",
        "exit_at_us",
        "canonicalization",
        "quality",
        "provenance",
    )
    expected_quality = result["quality_assumptions"]["incoming_consumption_parameters"]
    handoffs: set[str] = set()
    for delivery in deliveries:
        identity = delivery["token_id"]
        require(
            identity in by_output and identity in by_arrival,
            "input lacks real L1 output or L2 receipt",
        )
        output, token, arrival = (
            by_output[identity],
            tokens[identity],
            by_arrival[identity],
        )
        require(
            len(offered[identity])
            == len(consumed[identity])
            == len(reservations[identity])
            == 1,
            "output not offered/reserved/consumed exactly once",
        )
        original = offered[identity][0]["token"]
        require(
            all(original[k] == token[k] for k in immutable),
            "input identity or quality changed",
        )
        require(
            token["producer"].startswith(l1 + "/")
            and token["producer"].endswith("/final/event"),
            "input is not an actual L1 final output",
        )
        require(
            token["quality"]["consumption_parameters"] == expected_quality,
            "input p differs from configured L2 model",
        )
        require(
            token["status"] == "consumed"
            and consumed[identity][0]["usage_kind"]
            == ("adopt" if delivery["ownership"] == "adopt" else "consume"),
            "wrong irreversible input use",
        )
        require(
            output["carrier_id"] == token["carrier_id"]
            and output["epoch"] == token["epoch"],
            "handoff relabeled state",
        )
        require(
            output["consumed_at_us"]
            is output["released_at_us"]
            is output["deliverable_at_us"]
            is None,
            "handoff counted as terminal sink",
        )
        require(
            output["ready_at_us"]
            <= delivery["handoff_at_us"]
            <= arrival["at_us"]
            <= consumed[identity][0]["at_us"],
            "ack/adopt/use order invalid",
        )
        require(
            near(output["handoff_at_us"], delivery["handoff_at_us"]),
            "handoff acknowledgement mismatch",
        )
        prefix = f"{l1}/cycle[{output['cycle']}]/batch[{output['batch']}]/"
        body = [c for name, c in calls.items() if name.startswith(prefix)]
        require(
            any(c["component_id"] == "raw_t_postselection" for c in body),
            "L1 output lacks executed raw supply",
        )
        require(
            sum(c["component_id"] == "logical_mx" for c in body) == 4,
            "L1 final four checks missing",
        )
        require(
            any(c["component_id"] == "logical_x" for c in body),
            "L1 accepted output canonicalization missing",
        )
        ids = delivery["transport_invocations"]
        require(
            len(ids) == 3
            and [i.rsplit("/", 1)[-1] for i in ids] == ["park", "deliver", "replace"],
            "wrong three-hop chain",
        )
        require(
            not handoffs.intersection(ids), "transport invocation reused across outputs"
        )
        handoffs.update(ids)
        park, delivered, replaced = (calls[i] for i in ids)
        require(
            park["factory_id"] == replaced["factory_id"] == l2
            and delivered["factory_id"] == l1,
            "three-hop actor mismatch",
        )
        require(
            park["end_us"] <= delivered["start_us"]
            and delivered["end_us"] <= replaced["start_us"],
            "three-hop causal order violated",
        )
        require(
            delivered["start_us"] >= max(token["ready_at_us"], token["exit_at_us"]),
            "source transport predates current token",
        )
    marked = {
        name for name, c in calls.items() if c["component_id"] == "block_translation"
    }
    require(handoffs == marked and len(marked) == 45, "not exactly 45 mechanical calls")
    require(
        all(
            calls[i].get("mechanical_transport") is True
            and calls[i]["consumed_token_id"] is None
            for i in marked
        ),
        "mechanical call consumed input",
    )
    magic_uses = [
        c["consumed_token_id"]
        for c in calls.values()
        if c["factory_id"] == l2 and c["consumed_token_id"] in by_arrival
    ]
    require(
        len(magic_uses) == len(set(magic_uses)) == 11,
        "not eleven unique rotation consumptions",
    )
    require(
        sum(e["action"] == "record_transport" for e in audit_rows) == 45,
        "ledger mechanical interval count differs",
    )
    retained = [o for o in outputs if o.get("retention") is not None]
    require(len(outputs) == len(deliveries) + len(retained), "unclassified L1 output")
    for output in retained:
        token = tokens[output["token_id"]]
        require(
            token["status"] == "offered" and not consumed[token["token_id"]],
            "surplus was consumed",
        )
        require(
            output["consumed_at_us"] is output["released_at_us"] is None,
            "retention freed physical state",
        )
    occupancy, peak = 0, 0
    for event in supply["buffer"]["audit"]:
        if event["action"] == "reserve_capacity":
            occupancy += 1
        elif event["action"] in ("remove", "abort_reservation"):
            occupancy -= 1
        require(
            0 <= occupancy <= supply["buffer"]["capacity"], "buffer capacity violated"
        )
        peak = max(peak, occupancy)
    require(
        occupancy == supply["buffer"]["occupied"], "buffer inventory accounting differs"
    )
    require(
        result["models"]["level2"]["input_z_error"]
        == result["models"]["level1"]["conditional_output_z_error"],
        "wrong L2 quality model input",
    )
    require(
        result["quality_assumptions"]["actual_output_error"] is None
        and result["quality_assumptions"][
            "transport_and_wait_noise_updates_logical_quality"
        ]
        is False,
        "physical quality overclaim",
    )
    world = copy.deepcopy(result["entry_world"])
    device = world["device"]
    require(
        len(device["aods"]) == 1
        and device["timing"]["load_us"] == device["timing"]["store_us"] == 10,
        "device AOD/transfer standard changed",
    )
    require(
        device["readout"]["duration_us"] == 100
        and device["readout"]["latency_us"] == 0,
        "readout standard changed",
    )
    atoms = {a["id"] for a in world["entry_state"]["atoms"]}
    require(
        len(atoms) == 204 and device == result["exit_world"]["device"],
        "world atoms/device changed",
    )
    footprints = {
        p["binding"]["block_id"]: frozenset(p["binding"]["atom_ids"])
        for p in world["patches"]
    }
    executions = {c["invocation_id"]: c for c in case["execution"]["calls"]}
    require(
        set(executions) == set(calls)
        and len(executions) == len(case["execution"]["calls"]),
        "execution/protocol call identities differ",
    )
    paths = {
        record["trace_sha256"]: inside(record["trace_path"], root)
        for record in result["calibration_records"].values()
    }
    seen: set[str] = set()
    templates, waves_seen, native_rows, goal_instances, previous = (
        {},
        set(),
        0,
        0,
        0,
    )
    mechanical_transitions = {}
    csv_stream = (
        native_schedule.open(encoding="utf-8", newline="") if native_schedule else None
    )
    csv_rows = iter(csv.DictReader(csv_stream)) if csv_stream else None
    for wave in sorted(case["execution"]["waves"], key=lambda w: w["start_us"]):
        ids, start, end = wave["invocations"], wave["start_us"], wave["end_us"]
        require(
            start >= previous - 1e-7
            and end >= start
            and end <= case["duration_us"] + 1e-7,
            "nonmonotone shared timeline",
        )
        require(
            wave["batch_id"] not in waves_seen
            and not seen.intersection(ids)
            and len(ids) == len(set(ids)),
            "duplicate wave/member",
        )
        waves_seen.add(wave["batch_id"])
        seen.update(ids)
        previous = end
        hashes = {executions[i]["joint_trace_sha256"] for i in ids}
        require(len(hashes) == 1, "members not compiled in same native world")
        key = hashes.pop()
        if key not in templates:
            trace = read(paths[key])
            require(canonical(trace) == key, "native trace canonical hash mismatch")
            templates[key] = native_template(trace, device, atoms)
        template = templates[key]
        require(
            near(template["duration"], end - start),
            "native wave duration differs from receipt",
        )
        require(
            layout_key(world["entry_state"]) == layout_key(template["entry"]),
            "world discontinuity between waves",
        )
        translated = [i for i in ids if i in marked]
        require(
            Counter(template["goals"])
            == Counter(
                footprints[executions[i]["participant_blocks"][0]] for i in translated
            ),
            "native goals differ from mechanical participants",
        )
        goal_instances += len(template["goals"])
        for step, action, offset, span, kind, sources in template["rows"]:
            native_rows += 1
            if csv_rows is not None:
                row = next(csv_rows, None)
                if row is None:
                    raise ValueError("native schedule wave/trace mismatch")
                require(
                    row["wave_id"] == wave["batch_id"] and row["trace_sha256"] == key,
                    "native schedule wave/trace mismatch",
                )
                require(
                    int(row["step_index"]) == step
                    and int(row["action_index"]) == action,
                    "duplicate/missing native CSV action",
                )
                require(
                    near(float(row["global_start_us"]), start + offset)
                    and near(float(row["global_end_us"]), start + offset + span),
                    "native schedule absolute time mismatch",
                )
                require(
                    row["kind"] == kind
                    and near(float(row["duration_us"]), span)
                    and json.loads(row["source_ids"]) == list(sources),
                    "native schedule kind/duration/source differs",
                )
        transition = wave.get("state_transition")
        if transition:
            require(
                canonical(world) == transition["entry_world_sha256"]
                and transition["trace_sha256"] == key,
                "transition entry world/hash mismatch",
            )
            for identity in translated:
                block = executions[identity]["participant_blocks"][0]
                mechanical_transitions[identity] = transition["bindings"][
                    f"block_translation:{block}"
                ]
            for update in transition["bindings"].values():
                patch = next(
                    p
                    for p in world["patches"]
                    if p["binding"]["block_id"] == update["entry"]["block_id"]
                )
                require(
                    patch["binding"] == update["entry"], "carrier binding discontinuity"
                )
                require(
                    update["entry"]["atom_ids"] == update["exit"]["atom_ids"],
                    "carrier atom identities changed",
                )
                patch["binding"], patch["home_sites"] = (
                    copy.deepcopy(update["exit"]),
                    list(update["home_sites"]),
                )
            old_map = world["entry_state"]["qubit_to_atom"]
            world["entry_state"] = copy.deepcopy(template["exit"])
            world["entry_state"]["qubit_to_atom"] = old_map
            require(
                canonical(world) == transition["exit_world_sha256"],
                "transition exit world/hash mismatch",
            )
        else:
            require(
                layout_key(template["entry"]) == layout_key(template["exit"]),
                "unregistered permanent world transition",
            )
    require(
        seen == set(executions) and goal_instances == 45,
        "incomplete native execution or wrong goal instance count",
    )
    require(world == result["exit_world"], "final reconstructed world mismatch")
    for delivery in deliveries:
        park, delivered, replaced = (
            mechanical_transitions[i] for i in delivery["transport_invocations"]
        )
        require(
            park["entry"]["block_id"]
            == replaced["exit"]["block_id"]
            != delivered["entry"]["block_id"],
            "replacement/source carrier mismatch",
        )
        require(
            delivered["entry"]["block_id"]
            == tokens[delivery["token_id"]]["carrier_id"],
            "transport did not move actual input carrier",
        )
        require(
            park["entry"]["origin"] == delivered["exit"]["origin"],
            "A did not reach original receiver slot",
        )
        require(
            park["exit"]["origin"] == replaced["entry"]["origin"],
            "replacement did not return from parking",
        )
        require(
            delivered["entry"]["origin"] == replaced["exit"]["origin"],
            "B did not restore original producer slot",
        )
    if csv_rows is not None:
        require(next(csv_rows, None) is None, "extra native schedule rows")
        if csv_stream is not None:
            csv_stream.close()
    return {
        "schema": "nadit.independent_two_level_audit/1",
        "status": "passed",
        "task_id": task_id,
        "result_sha256": completion["result_sha256"],
        "artifacts_verified": len(verified),
        "L1_inputs": 15,
        "adopted": 4,
        "rotation_consumed": 11,
        "native_relocations": goal_instances,
        "native_action_rows": native_rows,
        "waves": len(waves_seen),
        "unique_native_traces": len(templates),
        "atoms": len(atoms),
        "duration_us": case["duration_us"],
        "retained_surplus": len(retained),
        "buffer_peak": peak,
        "buffer_capacity": supply["buffer"]["capacity"],
        "buffer_wait_events": sum(
            m.get("state") == "waiting_buffer" for m in case["milestones"]
        ),
        "runner_attempt_statuses": dict(attempt_statuses),
        "parent_success_publications": 1,
        "parent_dependency_replays": sum(
            row["status"] == "needs_dependencies" for row in parent_attempts
        ),
        "three_hop_directions_and_current_token_readiness": "checked",
        "native_csv_checked": native_schedule is not None,
        "scope": "published identities/lifecycle plus independent saved-action position/holder replay; no compilation, sampling, logical quality inference or replacement of native physical validator",
    }


def main() -> None:
    """Print an independent audit of existing records; never execute a factory."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--native-schedule", type=Path)
    args = parser.parse_args()
    try:
        result = audit_saved_two_level(
            args.campaign, args.task_id, args.native_schedule
        )
    except (KeyError, ValueError, TypeError, OSError) as error:
        print(
            json.dumps(
                {
                    "schema": "nadit.independent_two_level_audit/1",
                    "status": "failed",
                    "reason": str(error),
                },
                indent=2,
            )
        )
        raise SystemExit(1) from error
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
