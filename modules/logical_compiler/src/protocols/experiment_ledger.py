"""Read-only accounting of exported factory cases, without sampling or compilation.

Counts describe committed selected component calls and issued resource tokens.
Protocol acceptance, output readiness, physical validation and whole-case status
remain separate evidence. No logical-success conclusion is inferred.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

_SCHEMA = "nadit.factory_experiment_ledger/2"
_BATCH = re.compile(r"^factory/batch\[(\d+)\]/")
_COUNT_FIELDS = (
    "factory_s_calls",
    "algorithm_s_calls",
    "factory_s_requested",
    "algorithm_s_requested",
    "raw_preparation_attempts",
    "raw_accepted_resources",
    "batches_started",
    "batches_checked",
    "batches_accepted",
    "batches_rejected",
)
_CSV_FIELDS = (
    "schema",
    "experiment_id",
    "run_id",
    "case_id",
    "seed",
    "code",
    "protocol_id",
    "protocol_version",
    "goal",
    "case_status",
    "duration_us",
    *_COUNT_FIELDS,
    "factory_final_accepted",
    "factory_output_ready",
    "algorithm_consumed",
    "algorithm_complete",
    "physical_validation_ok",
    "event_fixture",
    "physical_failure_fixture",
    "logical_success",
    "batches_json",
    "cost_profile_json",
    "algorithm_evaluation_json",
    "probability_model_hashes_json",
    "source_provenance_json",
    "metadata_json",
)


def _copy_object(value: dict[str, Any], name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"INVALID_LEDGER_INPUT: {name} must be a JSON object")
    try:
        copied: dict[str, Any] = json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"INVALID_LEDGER_INPUT: {name} must contain finite JSON"
        ) from error
    return copied


def _boolean(value: Any) -> bool | None:
    return value if type(value) is bool else None


def _acceptance_probability(port: dict[str, Any] | None) -> float | None:
    """Sum the original joint table only when every outcome declares acceptance."""
    outcomes = [] if port is None else port.get("outcomes", [])
    if not outcomes or any(
        type(outcome.get("values", {}).get("accepted")) is not bool
        for outcome in outcomes
    ):
        return None
    probabilities = []
    for outcome in outcomes:
        probability = outcome.get("probability")
        if type(probability) not in (int, float) or not 0 <= probability <= 1:
            raise ValueError("INVALID_LEDGER_INPUT: invalid final outcome probability")
        if outcome["values"]["accepted"]:
            probabilities.append(probability)
    return math.fsum(probabilities)


def _batches(case: dict[str, Any]) -> list[dict[str, Any]]:
    starts = {
        mark["batch"]: mark.get("at_us")
        for mark in case.get("milestones", [])
        if mark.get("kind") == "batch_started"
    }
    final_key = case.get("recipe", {}).get("final_event", {}).get("key")
    final_events: dict[int, dict[str, Any]] = {}
    for event in case.get("events", []):
        identity = event.get("occurrence", {}).get("invocation_id", "")
        match = _BATCH.match(identity)
        if match is None or identity[match.end() :] != final_key:
            continue
        index = int(match.group(1))
        if index in final_events:
            raise ValueError("INVALID_LEDGER_INPUT: duplicate final event for a batch")
        final_events[index] = event
    rows = []
    for index in sorted(starts.keys() | final_events.keys()):
        event = final_events.get(index)
        digest = None if event is None else event.get("port_sha256")
        port = case.get("probability_models", {}).get(digest)
        rows.append(
            {
                "batch": index,
                "started_at_us": starts.get(index),
                "accepted": None
                if event is None
                else _boolean(event.get("values", {}).get("accepted")),
                "acceptance_probability": _acceptance_probability(port),
                "final_event": event,
                "port_sha256": digest,
                "probability_port": port,
            }
        )
    return rows


def build_ledger_record(
    case: dict[str, Any], metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Summarize one exported ``nadit.factory_case/1`` without changing its evidence.

    Args:
        case: The already exported selected case, including partial failures.
        metadata: Optional experiment/run IDs, source revision and file hashes,
            cost_profile, algorithm_evaluation and fixture declarations. The full
            object is retained. Unknown optional evidence is represented by null.

    Returns:
        A fresh JSON-compatible ``nadit.factory_experiment_ledger/2`` record.
        Actual S counts use committed logical_s calls; requested S counts use
        selected m1/logical_m=1 events. Raw resources require an issued canonical
        token from a committed raw_t_postselection/canonicalize call. The last
        started batch has null acceptance if its final joint event is absent.
        logical_success stays null; supplied evaluations remain separate evidence.

    Raises:
        ValueError: The schema, JSON values or final-event evidence is invalid.
    """
    document = _copy_object(case, "case")
    meta = _copy_object({} if metadata is None else metadata, "metadata")
    if document.get("schema") != "nadit.factory_case/1":
        raise ValueError("INVALID_LEDGER_INPUT: expected nadit.factory_case/1")
    calls = document.get("calls", [])
    events = document.get("events", [])
    marks = document.get("milestones", [])
    models = document.get("probability_models", {})
    recipe = document.get("recipe", {})
    batches = _batches(document)

    def s_calls(prefix: str) -> int:
        return sum(
            call.get("component_id") == "logical_s"
            and call.get("invocation_id", "").startswith(prefix)
            for call in calls
        )

    def s_requested(prefix: str) -> int:
        return sum(
            event.get("occurrence", {}).get("invocation_id", "").startswith(prefix)
            and event.get("outcome_key") == "m1"
            and type(event.get("values", {}).get("logical_m")) is int
            and event["values"]["logical_m"] == 1
            for event in events
        )

    canonicalizers = {
        call["invocation_id"]
        for call in calls
        if call.get("component_id") == "raw_t_postselection/canonicalize"
    }
    counts = {
        "factory_s_calls": s_calls("factory/"),
        "algorithm_s_calls": s_calls("algorithm/"),
        "factory_s_requested": s_requested("factory/"),
        "algorithm_s_requested": s_requested("algorithm/"),
        "raw_preparation_attempts": sum(
            call.get("component_id") == "raw_t_postselection" for call in calls
        ),
        "raw_accepted_resources": sum(
            token.get("producer") in canonicalizers
            and token.get("canonicalization") == "canonical"
            and token.get("token_id") != document.get("output_token_id")
            for token in document.get("resources", {}).get("tokens", [])
        ),
        "batches_started": sum(mark.get("kind") == "batch_started" for mark in marks),
        "batches_checked": sum(batch["accepted"] is not None for batch in batches),
        "batches_accepted": sum(batch["accepted"] is True for batch in batches),
        "batches_rejected": sum(batch["accepted"] is False for batch in batches),
    }
    validation = (document.get("physical") or {}).get("validation")
    source_provenance = {
        "source_revision": meta.get("source_revision"),
        "source_files_sha256": meta.get("source_files_sha256"),
        "artifact_files_sha256": meta.get("files_sha256"),
    }
    return {
        "schema": _SCHEMA,
        "experiment_id": meta.get("experiment_id"),
        "run_id": meta.get("run_id"),
        "case_id": document.get("case_id"),
        "seed": document.get("seed"),
        "code": document.get("code"),
        "protocol_id": recipe.get("protocol_id"),
        "protocol_version": recipe.get("version"),
        "goal": document.get("goal"),
        "case_status": document.get("status"),
        "failure": document.get("failure"),
        "duration_us": document.get("duration_us"),
        "counts": counts,
        "batches": batches,
        "factory_final_accepted": batches[-1]["accepted"] if batches else None,
        "factory_output_ready": any(
            mark.get("kind") == "factory_output_ready" for mark in marks
        ),
        "output_token_id": document.get("output_token_id"),
        "algorithm_consumed": document.get("algorithm_consumed_token_id") is not None,
        "algorithm_consumed_token_id": document.get("algorithm_consumed_token_id"),
        "algorithm_complete": any(
            mark.get("kind") == "algorithm_t_complete" for mark in marks
        ),
        "physical_validation": validation,
        "physical_validation_ok": None
        if validation is None
        else _boolean(validation.get("ok")),
        "event_fixture": any(
            model.get("model", {}).get("kind") == "test_fixture"
            for model in models.values()
        ),
        "physical_failure_fixture": _boolean(
            meta.get(
                "physical_failure_fixture",
                (meta.get("scopes") or {}).get("physical_failure_fixture"),
            )
        ),
        "probability_model_hashes": sorted(models),
        "probability_models": models,
        "reference_parameters": document.get("reference_parameters"),
        "source_provenance": source_provenance,
        "cost_profile": meta.get("cost_profile"),
        "algorithm_evaluation": meta.get("algorithm_evaluation"),
        "logical_success": None,
        "metadata": meta,
    }


def _csv_cell(value: Any) -> Any:
    if value is None:
        return ""
    if type(value) is bool:
        return "true" if value else "false"
    if isinstance(value, dict | list):
        return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)
    return value


def write_ledger(
    records: Iterable[dict[str, Any]], new_output_directory: str | Path
) -> dict[str, str]:
    """Write fixed-schema ledger.jsonl and ledger.csv into a new directory.

    Args:
        records: Already built ledger records; all are validated before writing.
        new_output_directory: A directory that must not already exist.

    Returns:
        Absolute output paths under the keys jsonl and csv. CSV nulls are empty;
        nested evidence columns contain JSON. JSONL retains the complete records.

    Raises:
        ValueError: A record has another schema or non-JSON/nonfinite values.
        FileExistsError: The output directory already exists; nothing is replaced.
        OSError: The destination cannot be created or written.
    """
    documents = [_copy_object(record, "record") for record in records]
    if any(document.get("schema") != _SCHEMA for document in documents):
        raise ValueError(f"INVALID_LEDGER_INPUT: expected {_SCHEMA}")
    required = {"case_id", "seed", "code", "case_status", "batches", "counts"}
    if any(
        not required <= document.keys()
        or not isinstance(document["counts"], dict)
        or not set(_COUNT_FIELDS) <= document["counts"].keys()
        for document in documents
    ):
        raise ValueError("INVALID_LEDGER_INPUT: incomplete ledger record")
    output = Path(new_output_directory).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=False)
    jsonl, csv_path = output / "ledger.jsonl", output / "ledger.csv"
    with jsonl.open("x", encoding="utf-8", newline="\n") as stream:
        for document in documents:
            stream.write(json.dumps(document, sort_keys=True, ensure_ascii=False))
            stream.write("\n")
    with csv_path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=_CSV_FIELDS)
        writer.writeheader()
        for document in documents:
            flat = document | document.get("counts", {})
            row = {
                field: _csv_cell(
                    document.get(field.removesuffix("_json"))
                    if field.endswith("_json")
                    else flat.get(field)
                )
                for field in _CSV_FIELDS
            }
            writer.writerow(row)
    return {"jsonl": str(jsonl), "csv": str(csv_path)}
