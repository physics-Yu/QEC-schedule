"""Read-only production accounting with explicit physical or estimated evidence."""

from __future__ import annotations

import json
from collections import Counter
from copy import deepcopy
from math import isfinite
from typing import Any


def _state_intervals(line: dict[str, Any], duration: float) -> list[dict[str, Any]]:
    states = [
        mark for mark in line["milestones"] if mark["kind"] == "line_state_changed"
    ]
    finish = line.get("completed_at_us")
    end = duration if finish is None else finish
    return [
        {
            **state,
            "start_us": state["at_us"],
            "end_us": states[i + 1]["at_us"] if i + 1 < len(states) else end,
        }
        for i, state in enumerate(states)
    ]


def _line_summary(
    identity: str, line: dict[str, Any], case: dict[str, Any]
) -> dict[str, Any]:
    calls = line["calls"]
    raw = [call for call in calls if call["component_id"] == "raw_t_postselection"]
    raw_identities = {call["invocation_id"].split("/attempt[", 1)[0] for call in raw}
    raw_events = [
        event
        for event in case["events"]
        if event["occurrence"]["invocation_id"] in raw_identities
    ]
    decisions = [
        mark for mark in line["milestones"] if mark["kind"] == "batch_decision"
    ]
    states = _state_intervals(line, case["duration_us"])
    waits: Counter[str] = Counter()
    for state in states:
        if state["state"].startswith("waiting_"):
            waits[state["state"]] += state["end_us"] - state["start_us"]
    output = next(
        (
            token
            for token in case["resources"]["tokens"]
            if token["token_id"] == line.get("output_token_id")
        ),
        None,
    )
    return {
        "factory_id": identity,
        "status": line["status"],
        "failure": line.get("failure"),
        "production_success": output is not None,
        "factory_final_accepted": decisions[-1]["accepted"] if decisions else None,
        "batch_decisions": decisions,
        "raw_attempts": len(raw),
        "raw_accepted_events": sum(
            event["values"].get("accepted") is True for event in raw_events
        ),
        "raw_rejections": sum(
            event["values"].get("accepted") is False for event in raw_events
        ),
        "s_calls": sum(call["component_id"] == "logical_s" for call in calls),
        "se_calls": sum(call["component_id"] == "se_round" for call in calls),
        "component_calls": len(calls),
        "waiting_us": dict(waits),
        "state_intervals": states,
        "completed_at_us": line.get("completed_at_us"),
        "output_token_id": line.get("output_token_id"),
        "output_status": None if output is None else output["status"],
        "algorithm_consumed_token_id": line.get("algorithm_consumed_token_id"),
        "role_bindings": line["role_bindings"],
        "logical_success": None,
    }


def build_array_ledger(case: dict[str, Any]) -> dict[str, Any]:
    """Summarize line outcomes, waiting, ownership and the complete event history.

    A failed raw attempt is not a failed factory. Production success means an
    actual output token was issued, not a claim about decoded logical fidelity.
    The resource audit is retained for time-local replay without future leakage.
    """
    lines = {
        identity: _line_summary(identity, line, case)
        for identity, line in case["factories"].items()
    }
    physical = case.get("physical")
    aod_ids = (
        [] if physical is None else [aod["id"] for aod in physical["device"]["aods"]]
    )
    record: dict[str, Any] = json.loads(
        json.dumps(
            {
                "schema": "nadit.factory_array_ledger/1",
                "case_id": case["case_id"],
                "seed": case["seed"],
                "status": case["status"],
                "duration_us": case["duration_us"],
                "coordination_policy": case["coordination_policy"],
                "aod_ids": aod_ids,
                "counts": {
                    "lines": len(lines),
                    "successful_lines": sum(
                        line["production_success"] for line in lines.values()
                    ),
                    "failed_lines": sum(
                        line["failure"] is not None for line in lines.values()
                    ),
                    "raw_attempts": sum(
                        line["raw_attempts"] for line in lines.values()
                    ),
                    "raw_rejections": sum(
                        line["raw_rejections"] for line in lines.values()
                    ),
                    "s_calls": sum(line["s_calls"] for line in lines.values()),
                },
                "lines": lines,
                "calls": case["calls"],
                "events": case["events"],
                "milestones": case["milestones"],
                "resources": case["resources"],
                "component_schedule": case["component_schedule"],
                "physical_validation_ok": physical is not None
                and physical["validation"]["ok"],
                "factory_acceptance_kind": "physical_no_fault_proxy",
                "logical_success": None,
            },
            allow_nan=False,
        )
    )
    if case.get("execution_representation") == "logical_estimate":
        record.update(
            execution_representation="logical_estimate",
            resource_time_basis="logical_estimated_us",
            physical_validation="not_run",
            physical_validation_ok=None,
            factory_acceptance_kind="profile_estimate_no_fault_proxy",
        )
    if "experiment_model" in case:
        record["experiment_model"] = deepcopy(case["experiment_model"])
    selectors = {
        line.get("recipe", {}).get("final_event", {}).get("selector")
        for line in case["factories"].values()
    }
    if selectors == {"factory_mx"}:
        record["factory_acceptance_kind"] = "theoretical_iid_z"
        record["physical_no_fault_controls_factory_acceptance"] = False
        for identity, line in case["factories"].items():
            final_key = line["recipe"]["final_event"]["key"]
            checks = []
            for event in case["events"]:
                invocation = event["occurrence"]["invocation_id"]
                if not invocation.startswith(
                    identity + "/batch["
                ) or not invocation.endswith("/" + final_key):
                    continue
                port = case["probability_models"][event["port_sha256"]]
                checks.append(
                    {
                        "event_id": invocation,
                        "outcome_key": event["outcome_key"],
                        "values": deepcopy(event["values"]),
                        "released_at_us": event["released_at_us"],
                        "port_sha256": event["port_sha256"],
                        "acceptance_probability": sum(
                            outcome["probability"]
                            for outcome in port["outcomes"]
                            if outcome["values"].get("accepted") is True
                        ),
                        "conditional_output_z_error": port["model"]["evidence"].get(
                            "conditional_output_z_error"
                        ),
                    }
                )
            record["lines"][identity].update(
                factory_check_events=checks,
                factory_acceptance_probability=checks[-1]["acceptance_probability"]
                if checks
                else None,
                conditional_output_z_error=checks[-1]["conditional_output_z_error"]
                if checks
                else None,
            )
    return record


def resource_state_at(ledger: dict[str, Any], at_us: float) -> dict[str, Any]:
    """Replay resources through a chosen time in the ledger's declared time basis.

    Historical offer records use the carrier's last activity time. Expose the
    offered token only once both its physical exit and ready time have arrived;
    neither a scheduled correction nor a future delivery becomes ready early.
    """
    if (
        type(at_us) not in (int, float)
        or not isfinite(at_us)
        or not 0 <= at_us <= ledger["duration_us"]
    ):
        raise ValueError("INVALID_LEDGER_TIME")
    carriers: dict[str, dict[str, Any]] = {}
    tokens: dict[str, dict[str, Any]] = {}
    for event in ledger["resources"]["audit"]:
        effective = event["at_us"]
        if event["action"] == "offer":
            effective = max(
                effective, event["token"]["ready_at_us"], event["token"]["exit_at_us"]
            )
        if effective > at_us:
            continue
        action = event["action"]
        if action == "register_carrier":
            carrier = deepcopy(event["carrier"])
            carriers[carrier["carrier_id"]] = carrier
            continue
        if action == "offer":
            token = deepcopy(event["token"])
            tokens[token["token_id"]] = token
            carriers[token["carrier_id"]].update(
                phase="resource", safe_exit_at_us=token["exit_at_us"]
            )
            continue
        if "token_id" in event:
            token = tokens[event["token_id"]]
            carrier = carriers[token["carrier_id"]]
            if action == "reserve":
                token.update(status="reserved", consumer=event["consumer"])
                carrier["owner"] = event["consumer"]
            elif action == "consume":
                token.update(
                    status="consumed",
                    consumed_at_us=event["at_us"],
                    usage_kind=event["usage_kind"],
                )
                carrier.update(phase="work", safe_exit_at_us=event["safe_exit_at_us"])
            elif action == "discard":
                token.update(status="discarded", discarded_at_us=event["at_us"])
                carrier.update(phase="work", safe_exit_at_us=event["safe_exit_at_us"])
            else:
                raise ValueError(f"UNKNOWN_RESOURCE_ACTION: {action}")
        else:
            carrier = carriers[event["carrier_id"]]
            if action == "begin_preparation":
                carrier.update(
                    phase="preparing",
                    epoch=event["epoch"],
                    owner=event["owner"],
                    safe_exit_at_us=event["at_us"],
                )
            elif action == "finish_preparation":
                carrier["phase"] = "work"
            elif action == "extend_use":
                carrier["safe_exit_at_us"] = event["safe_exit_at_us"]
            elif action == "complete_use":
                carrier.update(phase="free", owner=None)
            else:
                raise ValueError(f"UNKNOWN_RESOURCE_ACTION: {action}")
        carrier["last_at_us"] = event["at_us"]
    return {
        "at_us": at_us,
        "carriers": [carriers[key] for key in sorted(carriers)],
        "tokens": [tokens[key] for key in sorted(tokens)],
    }
