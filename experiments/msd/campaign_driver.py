"""Deterministic pilot-to-production dependency adapters for the existing runner."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from copy import deepcopy
from math import isfinite
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from time import perf_counter
from typing import Any

from nadit_physical_compiler.experiments.journal import (
    directory_lock,
    read_records,
    write_json,
)
from nadit_physical_compiler.experiments.task_plan import validate_plan, validate_task
from nadit_physical_compiler.provenance import canonical_hash

from modules.logical_compiler.src.protocols.production import make_output_sink

from .campaign_plan import expand_single_level, expand_two_level
from .campaign_policy import resolve_observation_policy
from .standard import ExperimentSpec

_RULE = {
    "pilot_cycles",
    "warmup_cycles",
    "target_observation_cycles",
    "minimum_observation_cycles",
    "max_total_simulated_us",
    "software_safety_factor",
}
_LIMITS = {"raw_attempts", "batches", "max_component_calls", "max_cycles"}


def _positive(
    value: Any, field: str, *, integer: bool = False, zero: bool = False
) -> float:
    if (
        type(value) not in (int, float)
        or not isfinite(value)
        or (integer and type(value) is not int)
        or value < 0
        or (value == 0 and not zero)
    ):
        raise ValueError(f"UNRESOLVED_CAMPAIGN_INPUT: {field}")
    return float(value)


def _validate_configuration(config: Mapping[str, Any]) -> None:
    required = {
        "schema",
        "standard",
        "aod_count",
        "distances",
        "factory_counts",
        "production_seeds",
        "budget",
        "sink",
        "noise_params",
        "sampling",
        "pilot_seed",
        "input_z_error",
        "limits",
        "observation_rule",
    }
    if not required <= config.keys() or config["schema"] != "nadit.msd.campaign/1":
        raise ValueError("INCOMPLETE_MSD_CAMPAIGN_CONFIGURATION")
    budget = config["budget"]
    if not isinstance(budget, Mapping):
        raise TypeError("UNRESOLVED_CAMPAIGN_BUDGET")
    for name in (
        "workers",
        "max_atoms",
        "memory_bytes",
        "software_max_attempts",
        "max_storage_bytes",
        "export_reserve_bytes",
        "max_artifact_refreshes",
    ):
        _positive(
            budget.get(name), name, integer=True, zero=name == "max_artifact_refreshes"
        )
    for name in (
        "calibration_timeout_s",
        "production_timeout_s",
        "pilot_timeout_s",
        "export_timeout_s",
        "export_reserve_s",
        "campaign_timeout_s",
    ):
        _positive(budget.get(name), name)
    if (
        budget["export_reserve_s"] >= budget["campaign_timeout_s"]
        or budget["export_reserve_bytes"] >= budget["max_storage_bytes"]
    ):
        raise ValueError("EXPORT_RESERVE_EXCEEDS_CAMPAIGN_CAP")
    make_output_sink(config["sink"])
    if not isinstance(config["noise_params"], Mapping):
        raise TypeError("EXPLICIT_NOISE_PARAMETERS_REQUIRED")
    sampling = config["sampling"]
    if not isinstance(sampling, Mapping) or set(sampling) != {"shots", "seed"}:
        raise ValueError("EXPLICIT_CALIBRATION_SAMPLING_REQUIRED")
    _positive(sampling["shots"], "shots", integer=True)
    _positive(sampling["seed"], "calibration_seed", integer=True, zero=True)
    _positive(config["pilot_seed"], "pilot_seed", integer=True, zero=True)
    if _positive(config["input_z_error"], "input_z_error", zero=True) > 1:
        raise ValueError("INVALID_CAMPAIGN_INPUT_Z_ERROR")
    if not isinstance(config["limits"], Mapping) or set(config["limits"]) != _LIMITS:
        raise ValueError("EXPLICIT_PRODUCTION_LIMITS_REQUIRED")
    for name in _LIMITS:
        _positive(config["limits"][name], name, integer=True)
    rule = config["observation_rule"]
    if not isinstance(rule, Mapping) or set(rule) != _RULE:
        raise ValueError("EXPLICIT_OBSERVATION_RULE_REQUIRED")
    for name in (
        "pilot_cycles",
        "warmup_cycles",
        "target_observation_cycles",
        "minimum_observation_cycles",
    ):
        _positive(rule[name], name, integer=True, zero=name == "warmup_cycles")
    if (
        rule["pilot_cycles"] < 2
        or rule["target_observation_cycles"] < rule["minimum_observation_cycles"]
    ):
        raise ValueError("INVALID_OBSERVATION_RULE")
    _positive(rule["max_total_simulated_us"], "max_total_simulated_us")
    if _positive(rule["software_safety_factor"], "software_safety_factor") < 1:
        raise ValueError("INVALID_SOFTWARE_SAFETY_FACTOR")
    _pilot_cost_model(config)
    canonical_hash(config)
    if "two_level" in config:
        _validate_two_level_configuration(config)


def _pilot_cost_model(config: Mapping[str, Any]) -> dict[str, Any] | None:
    if "pilot_cost_model" not in config:
        return None
    model = config["pilot_cost_model"]
    if (
        not isinstance(model, Mapping)
        or set(model) != {"mode", "future_miss_reserve_fraction"}
        or model["mode"] != "cached_replay"
    ):
        raise ValueError("INVALID_PILOT_COST_MODEL")
    fraction = _positive(
        model["future_miss_reserve_fraction"], "future_miss_reserve_fraction", zero=True
    )
    if fraction >= 1:
        raise ValueError("INVALID_PILOT_COST_RESERVE_FRACTION")
    return deepcopy(dict(model))


def _validate_two_level_configuration(config: Mapping[str, Any]) -> None:
    """Validate explicit Stage 3 controls without fabricating arrival evidence."""
    stage = config["two_level"]
    expected = {
        "candidate_rule",
        "worker_seconds_fraction",
        "pilot_seed",
        "limits",
        "observation_rule",
        "acknowledge_theory_transport_exclusions",
    }
    if not isinstance(stage, Mapping) or set(stage) != expected:
        raise ValueError("EXPLICIT_TWO_LEVEL_CAMPAIGN_CONFIGURATION_REQUIRED")
    fraction = _positive(stage["worker_seconds_fraction"], "worker_seconds_fraction")
    if fraction >= 1 or stage["acknowledge_theory_transport_exclusions"] is not True:
        raise ValueError("INVALID_TWO_LEVEL_CAMPAIGN_ALLOCATION_OR_QUALITY_ACK")
    limits = stage["limits"]
    if not isinstance(limits, Mapping) or set(limits) != {
        "raw_attempts",
        "max_component_calls",
        "producer_max_cycles",
        "consumer_max_cycles",
        "level1_batches",
        "level2_batches",
    }:
        raise ValueError("EXPLICIT_TWO_LEVEL_CAMPAIGN_LIMITS_REQUIRED")
    for name, value in limits.items():
        _positive(value, name, integer=True)
    probe = {key: value for key, value in config.items() if key != "two_level"}
    probe.update(
        pilot_seed=stage["pilot_seed"],
        observation_rule=stage["observation_rule"],
        limits={
            "raw_attempts": limits["raw_attempts"],
            "batches": limits["level2_batches"],
            "max_component_calls": limits["max_component_calls"],
            "max_cycles": limits["consumer_max_cycles"],
        },
    )
    _validate_configuration(probe)
    if stage["observation_rule"]["pilot_cycles"] > limits["consumer_max_cycles"]:
        raise ValueError("TWO_LEVEL_PILOT_EXCEEDS_CONSUMER_CYCLE_BUDGET")
    rule = stage["candidate_rule"]
    if not isinstance(rule, Mapping) or any(
        key in rule for key in ("arrival_evidence_sha256", "arrival_source_sha256")
    ):
        raise ValueError("ARRIVAL_PINS_ARE_RESOLVED_AFTER_SINGLE_LEVEL_EXECUTION")
    # Schema-only expansion with no trajectories constructs no physical worlds.
    # These inputs are never persisted or used as experimental arrival evidence.
    source = {"configuration_validation_only": True}
    empty = {
        "schema": "nadit.msd.arrival_evidence/1",
        "standard": config["standard"],
        "source_identity": source,
        "source_sha256": canonical_hash(source),
        "trajectories": [],
    }
    expand_two_level(
        {
            **rule,
            "arrival_evidence_sha256": canonical_hash(empty),
            "arrival_source_sha256": canonical_hash(source),
        },
        empty,
        source_identity=source,
    )
    if rule["budget"]["max_atoms"] > config["budget"]["max_atoms"] or (
        config["budget"].get("max_footprint_um2") is not None
        and rule["budget"]["max_footprint_um2"] > config["budget"]["max_footprint_um2"]
    ):
        raise ValueError("TWO_LEVEL_RESOURCE_BUDGET_EXCEEDS_CAMPAIGN")


def _target_path(directory: str | PurePath, *children: str) -> str:
    """Join an explicitly named host path without resolving it on the builder."""
    value = str(directory)
    path: PurePath = (
        PureWindowsPath(value) if PureWindowsPath(value).drive else PurePosixPath(value)
    )
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("ABSOLUTE_TARGET_CAMPAIGN_DIRECTORY_REQUIRED")
    return str(path.joinpath(*children))


def _task(
    kind: str,
    payload: dict[str, Any],
    budget: Mapping[str, Any],
    timeout: str,
    dependencies: list[str] | None = None,
    *,
    terminal: bool = False,
) -> dict[str, Any]:
    body = {
        "kind": kind,
        "payload": payload,
        "dependencies": dependencies or [],
        "timeout_s": budget[timeout],
        "max_attempts": budget["software_max_attempts"],
        "memory_bytes": budget["memory_bytes"],
    }
    if terminal:
        body["dependency_mode"] = "terminal"
    return validate_task({"task_id": canonical_hash(body), **body})


def _acceptance(
    descriptor: Mapping[str, Any] | None,
    source: Mapping[str, Any],
    *,
    evidence_kind: str = "physical_interface_acceptance",
) -> bool:
    if descriptor is None:
        return False
    if (
        set(descriptor) != {"path", "sha256", "hash_kind"}
        or descriptor["hash_kind"] != "canonical_json"
    ):
        raise ValueError("INVALID_CAMPAIGN_ACCEPTANCE_DESCRIPTOR")
    evidence = json.loads(Path(descriptor["path"]).read_text(encoding="utf-8"))
    if (
        canonical_hash(evidence) != descriptor["sha256"]
        or evidence.get("passed") is not True
        or evidence.get("evidence_kind") != evidence_kind
        or not isinstance(evidence.get("checks"), list)
        or not evidence["checks"]
        or not (
            evidence.get("source_identity") == source
            or (
                source.get("source_hash") is not None
                and evidence.get("source_hash") == source["source_hash"]
            )
        )
    ):
        raise ValueError("CAMPAIGN_ACCEPTANCE_EVIDENCE_MISMATCH")
    return True


def resolve_campaign(
    configuration: Mapping[str, Any],
    *,
    source_identity: Mapping[str, Any],
    action_dependencies: Mapping[str, Any],
    probability_dependencies: Mapping[str, Any],
    campaign_directory: str | PurePath,
    acceptance_evidence: Mapping[str, Any] | None = None,
    two_level_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve layout drivers and a terminal summary without touching target paths.

    Every numerical budget and sink is explicit. Each admitted layout receives an
    equal share of worker-seconds after the explicit finalization reserve; its
    measured unique pilot work is subtracted before dividing the remainder among
    seeds. Per-seed allocation is
    capped by production_timeout_s. This fixed heuristic does not guarantee full
    coverage; the existing runner enforces actual budgets. Absent audited acceptance
    leaves runnable=False. Optional Stage 3 reserves its worker share before L1
    pilots and requires separate source-matched physical delivery acceptance.
    """
    _validate_configuration(configuration)
    if not source_identity or not action_dependencies or not probability_dependencies:
        raise ValueError("EXPLICIT_CAMPAIGN_SOURCE_DEPENDENCIES_REQUIRED")
    directory = _target_path(campaign_directory)
    accepted = _acceptance(acceptance_evidence, source_identity)
    stage = configuration.get("two_level")
    two_level_accepted = bool(stage) and _acceptance(
        two_level_evidence, source_identity, evidence_kind="physical_two_level_delivery"
    )
    config = deepcopy(dict(configuration))
    layout_plan = expand_single_level(config, source_identity=source_identity)
    budget = config["budget"]
    admitted = [row for row in layout_plan["layouts"] if not row["budget_exclusions"]]
    available = (budget["campaign_timeout_s"] - budget["export_reserve_s"]) * budget[
        "workers"
    ]
    two_level_share = (
        0.0 if stage is None else available * stage["worker_seconds_fraction"]
    )
    available -= two_level_share
    allocation = {
        "schema": "nadit.msd.equal_layout_worker_allocation/1",
        "configured_worker_seconds": budget["campaign_timeout_s"] * budget["workers"],
        "reserved_worker_seconds": budget["export_reserve_s"] * budget["workers"],
        "available_worker_seconds": available,
        "admitted_layouts": len(admitted),
        "layout_worker_seconds": None if not admitted else available / len(admitted),
        "basis": "equal layout shares after finalization reserve; subtract unique pilot worker cost, then divide by production seeds",
    }
    drivers = []
    for layout in admitted:
        trajectories = [
            row
            for row in layout_plan["tasks"]
            if row["layout_id"] == layout["layout_id"]
        ]
        common = {
            "spec": ExperimentSpec(
                layout["distance"], layout["factory_count"]
            ).to_dict(),
            "placement": layout["placement"],
            "noise_params": config["noise_params"],
            "sampling": config["sampling"],
            "cache_root": _target_path(directory, "cache"),
            "dependencies": {
                "actions": dict(action_dependencies),
                "probabilities": dict(probability_dependencies),
            },
            "calibration_budget": {
                "timeout_s": budget["calibration_timeout_s"],
                "max_attempts": budget["software_max_attempts"],
                "memory_bytes": budget["memory_bytes"],
            },
            "output_sink": config["sink"],
            "input_z_error": config["input_z_error"],
        }
        payload = {
            "campaign_directory": directory,
            "layout_id": layout["layout_id"],
            "trajectories": trajectories,
            "common": common,
            "budget": budget,
            "limits": config["limits"],
            "pilot_seed": config["pilot_seed"],
            "observation_rule": config["observation_rule"],
            "allocation": allocation,
            "config_sha256": canonical_hash(config),
            "source_sha256": canonical_hash(source_identity),
        }
        if "pilot_cost_model" in config:
            payload["pilot_cost_model"] = deepcopy(config["pilot_cost_model"])
        drivers.append(
            _task(
                "msd.layout_driver", payload, budget, "export_timeout_s", terminal=True
            )
        )
    stage_driver = None
    if stage is not None:
        stage_driver = _task(
            "msd.two_level_driver",
            {
                "campaign_directory": directory,
                "single_level_plan": layout_plan,
                "configuration": config,
                "source_identity": deepcopy(dict(source_identity)),
                "dependencies": {
                    "actions": dict(action_dependencies),
                    "probabilities": dict(probability_dependencies),
                },
                "allocation": {
                    "stage_worker_seconds": two_level_share,
                    "basis": "preset share after the finalization reserve",
                },
                "acceptance_complete": two_level_accepted,
            },
            budget,
            "export_timeout_s",
            [task["task_id"] for task in drivers],
            terminal=True,
        )
    all_drivers = [*drivers, *([] if stage_driver is None else [stage_driver])]
    summary = _task(
        "msd.summarize",
        {
            "campaign_directory": directory,
            "task_plan_path": _target_path(directory, "task_plan.json"),
            "plots": True,
        },
        budget,
        "export_timeout_s",
        [task["task_id"] for task in all_drivers],
        terminal=True,
    )
    return validate_plan(
        {
            "schema": "nadit.task_plan/1",
            "tasks": [*all_drivers, summary],
            "finalization": {
                "task_ids": [summary["task_id"]],
                "reserve_seconds": budget["export_reserve_s"],
                "reserve_bytes": budget["export_reserve_bytes"],
            },
            "source_paths": deepcopy(config.get("source_paths", [])),
            "budget": {
                key: budget[key]
                for key in (
                    "campaign_timeout_s",
                    "max_storage_bytes",
                    "max_artifact_refreshes",
                )
            },
            "campaign": {
                "schema": "nadit.msd.campaign_context/1",
                "scope": "single_level" if stage is None else "single_and_two_level",
                "runnable": accepted and (stage is None or two_level_accepted),
                "acceptance_complete": accepted,
                "two_level_ready": two_level_accepted,
                "acceptance_evidence": deepcopy(acceptance_evidence),
                **(
                    {"two_level_evidence": deepcopy(two_level_evidence)}
                    if stage is not None
                    else {}
                ),
                "configuration": config,
                "configuration_sha256": canonical_hash(config),
                "source_identity": deepcopy(dict(source_identity)),
                "layout_plan": layout_plan,
                "campaign_directory": directory,
                "allocation_policy": allocation,
            },
        }
    )


def _local(directory: Path, value: str) -> Path:
    path = (directory / value).resolve()
    if not path.is_relative_to(directory):
        raise ValueError("CAMPAIGN_ARTIFACT_OUTSIDE_DIRECTORY")
    return path


def _read(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _completion(directory: Path, identity: str) -> dict[str, Any] | None:
    path = directory / "task_completions" / f"{identity}.json"
    if not path.exists():
        return None
    record = _read(path)
    if record.get("task_id") != identity:
        raise ValueError("CAMPAIGN_COMPLETION_IDENTITY_MISMATCH")
    return record


def _result(directory: Path, descriptor: Mapping[str, Any]) -> dict[str, Any]:
    path = _local(directory, descriptor["result_path"])
    if path.is_file():
        document = _read(path)
        if canonical_hash(document) == descriptor["result_sha256"]:
            return document
    # A refreshed dependency may replace its canonical result path. Its original
    # pilot proof remains immutable in the runner's invalidation history.
    for event in read_records(directory / "task_invalidations.jsonl"):
        previous = event["previous_completion"]
        if (
            event["task_id"] == descriptor["task_id"]
            and previous.get("result_sha256") == descriptor["result_sha256"]
        ):
            document = _read(_local(directory, previous["result_path"]))
            if canonical_hash(document) == descriptor["result_sha256"]:
                return document
    raise ValueError("FROZEN_PILOT_RESULT_MISSING_OR_CHANGED")


def _pilot_ledger(
    directory: Path, pilot_id: str, *, measured: bool = False
) -> list[dict[str, Any]]:
    extra: dict[str, set[str]] = {}
    for row in read_records(directory / "task_edges.jsonl"):
        extra.setdefault(row["task_id"], set()).update(row.get("add", ()))
    selected, pending = set(), [pilot_id]
    while pending:
        identity = pending.pop()
        if identity in selected:
            continue
        selected.add(identity)
        task = validate_task(_read(directory / "task_definitions" / f"{identity}.json"))
        pending.extend(set(task["dependencies"]) | extra.get(identity, set()))
    return _ledger_records(directory, selected_tasks=selected, measured=measured)


def _ledger_records(
    directory: Path,
    *,
    selected_tasks: set[str] | None = None,
    selected_runs: set[str] | None = None,
    measured: bool = False,
) -> list[dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for row in read_records(directory / "task_attempts.jsonl"):
        if not (
            (selected_tasks is not None and row["task_id"] in selected_tasks)
            or (selected_runs is not None and row["run_id"] in selected_runs)
        ):
            continue
        if row.get("attempt", 0) < 1:
            continue
        basis = (
            "process_wall_s"
            if row.get("process_wall_s") is not None
            else "legacy_worker_wall_s"
        )
        elapsed = _positive(
            row.get("process_wall_s")
            if measured
            else row.get("process_wall_s")
            if basis == "process_wall_s"
            else row.get("worker_wall_s"),
            "WARM_PROCESS_WALL_UNMEASURED" if measured else "pilot_process_wall_s",
            zero=True,
        )
        item = {
            "run_id": row["run_id"],
            "task_id": row["task_id"],
            "kind": row["kind"],
            "worker_wall_s": elapsed,
            "timing_basis": basis,
        }
        if measured:
            status = row.get("status")
            if status not in {
                "ok",
                "needs_dependencies",
                "deferred",
                "software_error",
                "budget_exceeded",
            }:
                raise ValueError("WARM_COST_ATTEMPT_STATUS_MISSING")
            validation = (row.get("runner_software_seconds") or {}).get(
                "artifact_validation"
            )
            if status == "ok" or validation is not None:
                validation = _positive(
                    validation, "WARM_ARTIFACT_VALIDATION_UNMEASURED", zero=True
                )
            item.update(
                status=status,
                process_wall_s=elapsed,
                artifact_validation_s=validation,
                worker_wall_s=elapsed + (0.0 if validation is None else validation),
                timing_basis="process_wall_s_plus_reported_runner_artifact_validation",
            )
        if item["run_id"] in records and records[item["run_id"]] != item:
            raise ValueError("CONFLICTING_PILOT_COST_RECORD")
        records[item["run_id"]] = item
    if selected_runs is not None and records.keys() != selected_runs:
        raise ValueError("FROZEN_PILOT_COST_RECORD_MISSING")
    return [records[key] for key in sorted(records)]


def _warm_case_hash(result: Mapping[str, Any], seed: int) -> str:
    case = result.get("case")
    if (
        not isinstance(case, Mapping)
        or case.get("status") != "complete"
        or case.get("failure") is not None
        or type(case.get("seed")) is not int
        or case["seed"] != seed
        or result.get("case_sha256") != canonical_hash(case)
    ):
        raise ValueError("WARM_PILOT_CASE_HASH_OR_SEED_MISMATCH")
    return canonical_hash(case)


def _warm_cost(
    payload: Mapping[str, Any],
    model: Mapping[str, Any],
    ledger: list[dict[str, Any]],
    cold_runs: list[str],
    warm_proof: Mapping[str, Any],
    case_hash: str,
) -> dict[str, Any]:
    records = {row["run_id"]: row for row in ledger}
    if not set(cold_runs) <= records.keys() or len(set(cold_runs)) != len(cold_runs):
        raise ValueError("WARM_COLD_COST_LEDGER_MISMATCH")
    final = records.get(warm_proof.get("run_id"))
    if (
        final is None
        or final["task_id"] != warm_proof["task_id"]
        or final["status"] != "ok"
    ):
        raise ValueError("WARM_SUCCESSFUL_PROBE_ATTEMPT_MISSING")
    process = _positive(final["process_wall_s"], "WARM_PROCESS_WALL_UNMEASURED")
    validation = _positive(
        final["artifact_validation_s"], "WARM_ARTIFACT_VALIDATION_UNMEASURED", zero=True
    )
    work = sum(row["worker_wall_s"] for row in ledger)
    cold = sum(records[run]["worker_wall_s"] for run in cold_runs)
    share = payload["allocation"]["layout_worker_seconds"]
    remaining = share - work
    if remaining <= 0:
        raise ValueError("PILOT_BUDGET_CANNOT_SUPPORT_MINIMUM_OBSERVATION_WINDOW")
    reserved = model["future_miss_reserve_fraction"] * remaining
    available = min(
        payload["budget"]["production_timeout_s"],
        (remaining - reserved) / len(payload["trajectories"]),
    )
    return {
        **dict(model),
        "cold_run_ids": cold_runs,
        "cold_worker_seconds": cold,
        "warm_incremental_worker_seconds": work - cold,
        "preparation_worker_seconds": work,
        "layout_worker_seconds": share,
        "warm_final_run_id": final["run_id"],
        "warm_process_wall_s": process,
        "warm_artifact_validation_s": validation,
        "warm_replay_worker_seconds": process + validation,
        "warm_case_sha256": case_hash,
        "remaining_after_preparation_worker_seconds": remaining,
        "future_miss_reserved_worker_seconds": reserved,
        "production_seed_count": len(payload["trajectories"]),
        "production_timeout_s": payload["budget"]["production_timeout_s"],
        "available_worker_seconds_per_seed": available,
        "reserve_is_hard_quota": False,
        "future_cache_misses": "normal bounded calibration dependencies; no zero-miss assumption",
        "formula": "Cprep=unique preparation run costs; reserve=r*(B-Cprep); A=min(timeout,(B-Cprep-reserve)/seeds); slope=(warm process wall+artifact validation)/pilot cycles",
        "validation_cost_scope": "successful attempts require reported artifact validation; non-success unreported validation stays null in the ledger",
    }


def _policy(
    directory: Path,
    payload: dict[str, Any],
    pilot: dict[str, Any],
    completion: dict[str, Any],
    *,
    warm_pilot: dict[str, Any] | None = None,
    warm_completion: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    model = _pilot_cost_model(payload)
    if model is not None:
        if warm_pilot is None or warm_completion is None:
            raise ValueError("WARM_PILOT_MEASUREMENT_REQUIRED")
        if (
            warm_pilot["kind"] != pilot["kind"]
            or warm_pilot["dependencies"] != [pilot["task_id"]]
            or warm_pilot["payload"]
            != {
                **pilot["payload"],
                "pilot_role": "warm_replay",
                "replay_of": pilot["task_id"],
            }
        ):
            raise ValueError("WARM_PILOT_SCIENTIFIC_INPUT_MISMATCH")
    elif warm_pilot is not None or warm_completion is not None:
        raise ValueError("WARM_PILOT_REQUIRES_EXPLICIT_COST_MODEL")
    folder = directory / "policies" / payload["layout_id"]
    path, marker = folder / "policy.json", folder / "frozen.json"
    identity = {
        key: payload[key]
        for key in (
            "layout_id",
            "config_sha256",
            "source_sha256",
            "observation_rule",
            "allocation",
        )
    }
    identity.update(
        pilot_task_id=pilot["task_id"],
        trajectories=[row["task_id"] for row in payload["trajectories"]],
    )
    if payload.get("phase") == "two_level":
        identity["two_level"] = payload["common"]["two_level"]
    if model is not None:
        assert warm_pilot is not None
        identity.update(
            pilot_cost_model=model, warm_pilot_task_id=warm_pilot["task_id"]
        )
    warm_proof: dict[str, Any] = {}
    cold_runs: list[str] = []
    with directory_lock(folder):
        if marker.exists() and not path.exists():
            raise ValueError("FROZEN_OBSERVATION_POLICY_MISSING")
        if path.exists():
            envelope = _read(path)
            if (
                envelope.get("schema") != "nadit.msd.frozen_observation_policy/1"
                or envelope.get("identity") != identity
                or envelope.get("policy_sha256") != canonical_hash(envelope["policy"])
            ):
                raise ValueError("FROZEN_OBSERVATION_POLICY_CHANGED")
            ledger = _ledger_records(
                directory,
                selected_runs={row["run_id"] for row in envelope["cost_ledger"]},
                measured=model is not None,
            )
            if ledger != envelope["cost_ledger"]:
                raise ValueError("FROZEN_PILOT_COST_RECORD_CHANGED")
            proof = envelope["pilot_evidence"]
            if model is not None:
                warm_proof = envelope["warm_pilot_evidence"]
                cold_runs = envelope["pilot_cost_model"]["cold_run_ids"]
        else:
            ledger = _pilot_ledger(
                directory, pilot["task_id"], measured=model is not None
            )
            proof = {
                key: completion[key]
                for key in ("task_id", "result_path", "result_sha256")
            }
            if model is not None:
                assert warm_pilot is not None and warm_completion is not None
                cold_runs = [row["run_id"] for row in ledger]
                by_run = {row["run_id"]: row for row in ledger}
                for row in _pilot_ledger(
                    directory, warm_pilot["task_id"], measured=True
                ):
                    if row["run_id"] in by_run and by_run[row["run_id"]] != row:
                        raise ValueError("CONFLICTING_PILOT_COST_RECORD")
                    by_run[row["run_id"]] = row
                ledger = [by_run[run] for run in sorted(by_run)]
                if not isinstance(warm_completion.get("run_id"), str):
                    raise ValueError("WARM_SUCCESSFUL_PROBE_ATTEMPT_MISSING")
                warm_proof = {
                    key: warm_completion[key]
                    for key in ("task_id", "result_path", "result_sha256", "run_id")
                }
        work = sum(row["worker_wall_s"] for row in ledger)
        available = min(
            payload["budget"]["production_timeout_s"],
            (payload["allocation"]["layout_worker_seconds"] - work)
            / len(payload["trajectories"]),
        )
        if available <= 0:
            raise ValueError("PILOT_BUDGET_CANNOT_SUPPORT_MINIMUM_OBSERVATION_WINDOW")
        pilot_result = _result(directory, proof)
        selectors: dict[str, Any] = {}
        warm_cost = None
        if model is not None:
            warm_result = _result(directory, warm_proof)
            case_hash = _warm_case_hash(pilot_result, payload["pilot_seed"])
            if _warm_case_hash(warm_result, payload["pilot_seed"]) != case_hash:
                raise ValueError("WARM_REPLAY_PROTOCOL_RESULT_MISMATCH")
            warm_cost = _warm_cost(
                payload, model, ledger, cold_runs, warm_proof, case_hash
            )
            available = warm_cost["available_worker_seconds_per_seed"]
            selectors["warm_replay_worker_seconds"] = warm_cost[
                "warm_replay_worker_seconds"
            ]
        if payload.get("phase") == "two_level":
            config = payload["common"]["two_level"]
            expected_factories = [
                f"factory{i}"
                for i in range(
                    config["level1_count"],
                    config["level1_count"] + config["level2_count"],
                )
            ]
            if pilot_result.get("level2_factories") != expected_factories:
                raise ValueError("TWO_LEVEL_PILOT_OUTPUT_FACTORIES_MISMATCH")
            selectors["output_factory_ids"] = set(expected_factories)
        policy = resolve_observation_policy(
            pilot_result,
            payload["observation_rule"],
            available_worker_seconds=available,
            pilot_worker_seconds=work,
            **selectors,
        )
        expected = {
            "schema": "nadit.msd.frozen_observation_policy/1",
            "identity": identity,
            "policy": policy,
            "policy_sha256": canonical_hash(policy),
            "pilot_evidence": proof,
            "cost_ledger": ledger,
            "cost_basis": "unique pilot and dependency attempt wall times; parent orchestration is separate",
        }
        if warm_cost is not None:
            expected.update(
                warm_pilot_evidence=warm_proof,
                pilot_cost_model=warm_cost,
                cost_basis="union of cold and warm preparation run IDs; process wall plus reported artifact validation; complete successful warm replay supplies slope",
            )
        if path.exists():
            if envelope != expected:
                raise ValueError("FROZEN_OBSERVATION_POLICY_CHANGED")
        else:
            write_json(path, expected)
        digest = canonical_hash(expected)
        if marker.exists() and _read(marker) != {"policy_artifact_sha256": digest}:
            raise ValueError("FROZEN_OBSERVATION_POLICY_COMMITMENT_CHANGED")
        if not marker.exists():
            write_json(marker, {"policy_artifact_sha256": digest})
    return expected, {
        "path": str(path),
        "sha256": digest,
        "hash_kind": "canonical_json",
    }


def _drive(task: dict[str, Any], directory: Path) -> dict[str, Any]:
    payload, budget = task["payload"], task["payload"]["budget"]
    model = _pilot_cost_model(payload)
    two_level = task["kind"] == "msd.two_level_layout_driver"
    if two_level != (payload.get("phase") == "two_level"):
        raise ValueError("CAMPAIGN_LAYOUT_DRIVER_PHASE_MISMATCH")
    pilot = _task(
        "msd.two_level_pilot" if two_level else "msd.pilot",
        {
            **deepcopy(payload["common"]),
            "layout_id": payload["layout_id"],
            "production_seed": payload["pilot_seed"],
            "pilot_cycles": payload["observation_rule"]["pilot_cycles"],
            "limits": dict(payload["limits"])
            if two_level
            else {key: payload["limits"][key] for key in _LIMITS - {"max_cycles"}},
        },
        budget,
        "pilot_timeout_s",
    )
    completion = _completion(directory, pilot["task_id"])
    if completion is None or completion["status"] == "invalidated":
        return {
            "status": "needs_dependencies",
            "dependency_requests": [pilot],
            "reason": {"stage": "pilot", "layout_id": payload["layout_id"]},
        }
    if completion["status"] != "ok":
        return {
            "status": "budget_exceeded"
            if completion["status"] == "budget_exceeded"
            else "software_error",
            "reason": {"stage": "pilot", "completion": completion},
        }
    warm_pilot = warm_completion = None
    if model is not None:
        warm_pilot = _task(
            pilot["kind"],
            {
                **deepcopy(pilot["payload"]),
                "pilot_role": "warm_replay",
                "replay_of": pilot["task_id"],
            },
            budget,
            "pilot_timeout_s",
            [pilot["task_id"]],
        )
        warm_completion = _completion(directory, warm_pilot["task_id"])
        if warm_completion is None or warm_completion["status"] == "invalidated":
            return {
                "status": "needs_dependencies",
                "dependency_requests": [warm_pilot],
                "reason": {"stage": "warm_pilot", "layout_id": payload["layout_id"]},
            }
        if warm_completion["status"] != "ok":
            return {
                "status": "budget_exceeded"
                if warm_completion["status"] == "budget_exceeded"
                else "software_error",
                "reason": {"stage": "warm_pilot", "completion": warm_completion},
            }
    try:
        frozen, artifact = _policy(
            directory,
            payload,
            pilot,
            completion,
            warm_pilot=warm_pilot,
            warm_completion=warm_completion,
        )
    except ValueError as error:
        if str(error).startswith("Experiment already has a writer:"):
            return {"status": "deferred", "reason": str(error)}
        if (
            str(error).startswith("PILOT_BUDGET_CANNOT_SUPPORT")
            or str(error) == "PILOT_INCOMPLETE"
        ):
            return {
                "status": "budget_exceeded",
                "reason": str(error),
                "result": {
                    "layout_id": payload["layout_id"],
                    "pilot_task_id": pilot["task_id"],
                },
            }
        raise
    producers = []
    for trajectory in payload["trajectories"]:
        producers.append(
            _task(
                "msd.two_level_produce" if two_level else "msd.produce",
                {
                    **deepcopy(payload["common"]),
                    "limits": payload["limits"],
                    **{
                        key: trajectory[key]
                        for key in (
                            "layout_id",
                            "seed",
                            "config_sha256",
                            "source_sha256",
                        )
                    },
                    "production_seed": trajectory["seed"],
                    "trajectory_id": trajectory["task_id"],
                    "observation_policy": frozen["policy"],
                    "observation_policy_artifact": artifact,
                },
                budget,
                "production_timeout_s",
                [pilot["task_id"]]
                + ([] if warm_pilot is None else [warm_pilot["task_id"]]),
            )
        )
    outcomes = {
        producer["task_id"]: _completion(directory, producer["task_id"])
        for producer in producers
    }
    missing = [
        producer
        for producer in producers
        if (outcomes[producer["task_id"]] or {}).get("status") in (None, "invalidated")
    ]
    if missing:
        return {
            "status": "needs_dependencies",
            "dependency_requests": missing,
            "reason": {"stage": "production", "layout_id": payload["layout_id"]},
            "artifacts": [artifact],
        }
    failed = {
        identity: row["status"]
        for identity, row in outcomes.items()
        if row is not None and row["status"] != "ok"
    }
    if failed:
        return {
            "status": "software_error",
            "reason": {"stage": "production", "failed_tasks": failed},
            "result": {
                "layout_id": payload["layout_id"],
                "pilot_cost_ledger": frozen["cost_ledger"],
            },
            "artifacts": [artifact],
        }
    return {
        "status": "ok",
        "result": {
            "layout_id": payload["layout_id"],
            "pilot_task_id": pilot["task_id"],
            "production_task_ids": [producer["task_id"] for producer in producers],
            "observation_policy": frozen["policy"],
            "pilot_cost_ledger": frozen["cost_ledger"],
            "pilot_cost_global_aggregation": "union run_id across layout ledgers before summing shared work",
            **(
                {}
                if warm_pilot is None
                else {
                    "warm_pilot_task_id": warm_pilot["task_id"],
                    "pilot_cost_model": frozen["pilot_cost_model"],
                }
            ),
        },
        "artifacts": [artifact],
    }


def software_accounting(
    directory: Path, *, current_task_id: str | None = None
) -> dict[str, Any]:
    """Sum unique executed attempts once, retaining explicit missing stage counts.

    Worker sums are not campaign elapsed time. Stage timers overlap; cold
    calibration includes action validation. The current summary's export timer
    enters its runner record after this snapshot, never as an invented zero.
    """
    unique: dict[str, dict[str, Any]] = {}
    duplicate_rows = 0
    for row in read_records(directory / "task_attempts.jsonl"):
        if row.get("attempt", 0) < 1:
            continue
        if row["run_id"] in unique:
            if unique[row["run_id"]] != row:
                raise ValueError("CONFLICTING_SOFTWARE_ATTEMPT_RECORD")
            duplicate_rows += 1
        unique[row["run_id"]] = row
    rows = list(unique.values())

    def measured(values: list[Any]) -> dict[str, Any]:
        known = [
            _positive(value, "software_seconds", zero=True)
            for value in values
            if value is not None
        ]
        return {
            "sum_seconds": sum(known) if known else None,
            "n_reported": len(known),
            "n_missing": len(values) - len(known),
        }

    phases = (
        "setup",
        "cold_calibration",
        "action_calibration",
        "probability_calibration",
        "cache_load",
        "fast_prefix",
        "fast_execution",
        "validation",
        "export",
        "total",
    )
    return {
        "schema": "nadit.msd.software_accounting/1",
        "unique_attempts": len(rows),
        "duplicate_rows_ignored": duplicate_rows,
        "process_wall_by_kind": {
            kind: measured(
                [row.get("process_wall_s") for row in rows if row["kind"] == kind]
            )
            for kind in sorted({row["kind"] for row in rows})
        },
        "worker_wall_by_kind": {
            kind: measured(
                [row.get("worker_wall_s") for row in rows if row["kind"] == kind]
            )
            for kind in sorted({row["kind"] for row in rows})
        },
        "stages": {
            phase: measured(
                [(row.get("software_seconds") or {}).get(phase) for row in rows]
            )
            for phase in phases
        },
        "runner_artifact_validation": measured(
            [
                (row.get("runner_software_seconds") or {}).get("artifact_validation")
                for row in rows
            ]
        ),
        "stage_timers_not_additive_to_worker_wall": True,
        "cold_calibration_includes_action_validation": True,
        "worker_wall_sum_is_not_elapsed_campaign_time": True,
        "timer_scope": "process_wall_s includes startup and parent observation; worker_wall_s is child-reported work for current records; legacy records can conflate these scopes",
        "current_summary_task_not_yet_journaled": current_task_id,
    }


def execute_task(task: dict[str, Any]) -> dict[str, Any]:
    """Advance one dependency driver or export terminal outcomes; never run physics."""
    validate_task(task)
    started = perf_counter()
    payload = task["payload"]
    directory = Path(payload["campaign_directory"])
    if not directory.is_absolute():
        raise ValueError("CAMPAIGN_DIRECTORY_PLATFORM_MISMATCH")
    directory = directory.resolve()
    if task["kind"] in ("msd.layout_driver", "msd.two_level_layout_driver"):
        result = _drive(task, directory)
        result["software_seconds"] = {"orchestration": perf_counter() - started}
        return result
    if task["kind"] == "msd.two_level_driver":
        from .two_level_campaign import advance_two_level

        if payload.get("acceptance_complete") is not True:
            return {
                "status": "software_error",
                "reason": "TWO_LEVEL_ACCEPTANCE_REQUIRED",
            }
        result = advance_two_level(task, directory)
        result["software_seconds"] = {"orchestration": perf_counter() - started}
        return result
    if task["kind"] == "msd.summarize":
        from .campaign import summarize_saved

        result = summarize_saved(
            _read(_local(directory, payload["task_plan_path"])),
            directory,
            plots=payload["plots"],
        )
        result["campaign_software_accounting"] = software_accounting(
            directory, current_task_id=task["task_id"]
        )
        write_json(directory / "report/summary.json", result)
        artifacts = [
            {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "hash_kind": "bytes",
            }
            for path in sorted((directory / "report").rglob("*"))
            if path.is_file()
        ]
        return {
            "status": "ok",
            "result": result,
            "artifacts": artifacts,
            "software_seconds": {"export": perf_counter() - started},
        }
    raise ValueError(f"UNSUPPORTED_MSD_DRIVER_TASK: {task['kind']}")
