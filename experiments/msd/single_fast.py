"""Run reproducible single-level center-cost factories without atom execution.

Every trajectory uses the existing logical runtime, scheduler and resource
ledger. A separately seeded two-cycle pilot fixes each cell's observation
window. Completed artifacts are immutable and hash-checked on resume. Partial
attempts are retained and a later attempt receives a new directory.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
from collections import Counter, defaultdict
from collections.abc import Mapping
from hashlib import file_digest
from math import isfinite
from pathlib import Path
from time import perf_counter
from typing import Any

from nadit_physical_compiler.experiments.journal import directory_lock, write_json

from modules.codes.rotated_surface.assumed_s_profile import AssumedSProfile
from modules.codes.rotated_surface.center_costs import (
    load_center_references,
    reference_digest,
)
from modules.codes.rotated_surface.center_profile import CenterSurfaceFactoryProfile
from modules.codes.rotated_surface.factory_assumptions import (
    ECPolicy,
    TransversalSAssumption,
    assumed_factory_recipe,
)
from modules.logical_compiler.examples.surface_factory_fast import run_surface_factory
from modules.logical_compiler.src.protocols.production import (
    ProductionPolicy,
    make_output_sink,
)

from .center_metrics import summarize_center_case, summarize_center_samples
from .fast_guard import no_atom_execution

_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_DIRECTORIES = (
    "modules/codes/contracts",
    "modules/codes/_support",
    "modules/codes/rotated_surface",
    "modules/codes/rotated_surface_d3/protocols",
    "modules/codes/rotated_surface_d3/probabilities",
    "modules/logical_compiler/src",
)
_SOURCE_FILES = (
    "modules/logical_compiler/examples/surface_factory_fast.py",
    "experiments/msd/single_fast.py",
    "experiments/msd/center_metrics.py",
    "experiments/msd/production_metrics.py",
    "experiments/msd/fast_guard.py",
    "experiments/msd/campaign_report.py",
    "experiments/analysis/extract_center_references.py",
    "modules/physical_compiler/src/nadit_physical_compiler/experiments/journal.py",
    "modules/physical_compiler/src/nadit_physical_compiler/provenance.py",
    "modules/physical_compiler/src/nadit_physical_compiler/device.py",
)


def _read(path: Path) -> dict[str, Any]:
    value: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"EXPECTED_JSON_OBJECT: {path}")
    return value


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").hexdigest()


def source_manifest(root: Path = _ROOT) -> dict[str, Any]:
    """Hash production dependencies, excluding tests, reports and generated runs."""
    files = {root / relative for relative in _SOURCE_FILES}
    for relative in _SOURCE_DIRECTORIES:
        files.update(
            p for p in (root / relative).rglob("*.py") if "tests" not in p.parts
        )
    hashes = {path.relative_to(root).as_posix(): _sha(path) for path in sorted(files)}
    return {"files": hashes, "sha256": reference_digest(hashes)}


def load_configuration(path: Path) -> dict[str, Any]:
    """Require an explicit center-cost model and finite reproducible experiment axes."""
    config = _read(path)
    if (
        config.get("schema") != "nadit.single_level_fast_plan/1"
        or config.get("cost_basis") != "reference_intrinsic_plus_center_transport"
    ):
        raise ValueError("EXPLICIT_CENTER_COST_CONFIGURATION_REQUIRED")
    if config.get("physical_compilation_allowed_in_fast_run") is not False:
        raise ValueError("SINGLE_FAST_REQUIRES_NO_ATOM_EXECUTION")
    for key in ("distances", "factory_counts", "production_seeds"):
        values = config[key]
        if (
            not isinstance(values, list)
            or not values
            or any(type(v) is not int for v in values)
            or len(set(values)) != len(values)
        ):
            raise ValueError(f"INVALID_SINGLE_FAST_AXIS: {key}")
    if set(config["distances"]) - {3, 5, 7} or any(
        v < 1 for v in config["factory_counts"]
    ):
        raise ValueError("UNSUPPORTED_SINGLE_FAST_GRID")
    if (
        type(config["pilot_seed"]) is not int
        or config["pilot_seed"] in config["production_seeds"]
    ):
        raise ValueError("PILOT_SEED_MUST_BE_SEPARATE")
    hardware = config["hardware"]
    if (
        hardware["aod_count"] != 1
        or hardware["layout"] != "vertical"
        or hardware["patch_gap_um"] != hardware["factory_gap_um"]
    ):
        raise ValueError("SINGLE_FAST_REQUIRES_SHARED_AOD_VERTICAL_EQUAL_GAPS")
    _assumptions(config)
    for key in ("raw_attempts", "batches", "max_component_calls", "max_cycles"):
        if type(config["limits"][key]) is not int or config["limits"][key] < 1:
            raise ValueError(f"INVALID_SINGLE_FAST_LIMIT: {key}")
    observation = config["observation"]
    for key in ("pilot_cycles", "warmup_cycles", "target_cycles"):
        if type(observation[key]) is not int or observation[key] < (
            0 if key == "warmup_cycles" else 1
        ):
            raise ValueError(f"INVALID_SINGLE_FAST_OBSERVATION: {key}")
    if observation["pilot_cycles"] < 2:
        raise ValueError("SINGLE_FAST_PILOT_REQUIRES_TWO_CYCLES")
    make_output_sink(config["output_sink"])
    return config


def _assumptions(config: Mapping[str, Any]) -> tuple[TransversalSAssumption, ECPolicy]:
    s = TransversalSAssumption(
        tuple(config["s"]["pauli_error"]), config["s"]["duration_us"]
    )
    ec = ECPolicy(config["ec"]["mode"], config["ec"]["rounds"])
    return s, ec


def _write_new(path: Path, document: Any) -> None:
    if path.exists():
        raise FileExistsError(f"IMMUTABLE_EXPERIMENT_ARTIFACT: {path}")
    write_json(path, document)


def _initialize(config_path: Path, output: Path) -> dict[str, Any]:
    config = load_configuration(config_path)
    reference_path = (_ROOT / config["reference_file"]).resolve()
    reference_path.relative_to(_ROOT)
    references = load_center_references(reference_path)
    source = source_manifest()
    identity = {
        "config_sha256": reference_digest(config),
        "source_sha256": source["sha256"],
        "reference_payload_sha256": references["payload_sha256"],
    }
    manifest = {
        "schema": "nadit.single_fast_campaign/1",
        "identity": identity,
        "configuration": config,
        "source": source,
        "reference_file": config["reference_file"],
    }
    with directory_lock(output):
        path = output / "manifest.json"
        if path.exists():
            if _read(path) != manifest:
                raise ValueError("SINGLE_FAST_RESUME_IDENTITY_MISMATCH")
        else:
            _write_new(path, manifest)
    return {
        "config": config,
        "references": references,
        "identity": identity,
        "output": output,
    }


def _gzip_json(path: Path, document: Any) -> None:
    """Write deterministic gzip bytes; the filename and modification time are omitted."""
    with (
        path.open("xb") as raw,
        gzip.GzipFile(
            filename="", mode="wb", fileobj=raw, mtime=0, compresslevel=3
        ) as stream,
    ):
        encoder = json.JSONEncoder(
            sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        buffer: list[bytes] = []
        size = 0
        for chunk in encoder.iterencode(document):
            encoded = chunk.encode("utf-8")
            buffer.append(encoded)
            size += len(encoded)
            if size >= 65536:
                stream.write(b"".join(buffer))
                buffer.clear()
                size = 0
        if buffer:
            stream.write(b"".join(buffer))


def _verified_completion(
    directory: Path,
    identity: Mapping[str, str],
    expected_task: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    path = directory / "completion.json"
    if not path.exists():
        return None
    record = _read(path)
    if record["identity"] != dict(identity):
        raise ValueError("SINGLE_FAST_RESULT_IDENTITY_MISMATCH")
    if expected_task is not None and record.get("task") != dict(expected_task):
        raise ValueError("SINGLE_FAST_TASK_IDENTITY_MISMATCH")
    for relative, digest in record["artifacts"].items():
        artifact = (directory / relative).resolve()
        artifact.relative_to(directory.resolve())
        if _sha(artifact) != digest:
            raise ValueError(f"SINGLE_FAST_ARTIFACT_HASH_MISMATCH: {relative}")
    names = ("metrics", "summary", "guard", "ledger-counts")
    mirrored = {}
    for name in names:
        relative = f"{record['attempt']}/{name}.json"
        if relative not in record["artifacts"]:
            raise ValueError("SINGLE_FAST_COMPLETION_ARTIFACT_MISSING")
        mirrored[name] = _read(directory / relative)
    if (
        record["metrics"] != mirrored["metrics"]
        or record["guard"] != mirrored["guard"]
        or record["ledger_counts"] != mirrored["ledger-counts"]
        or any(
            record[key] != mirrored["summary"][key]
            for key in ("status", "lines", "profile_sha256")
        )
    ):
        raise ValueError("SINGLE_FAST_COMPLETION_CONTENT_MISMATCH")
    for key in ("distance", "factory_count", "seed"):
        if (
            not record[key]
            == record["task"][key]
            == mirrored["summary"][key]
            == mirrored["metrics"][key]
        ):
            raise ValueError("SINGLE_FAST_COMPLETION_POSITION_MISMATCH")
    return record


def _profile(
    context: Mapping[str, Any], distance: int, count: int
) -> tuple[CenterSurfaceFactoryProfile, AssumedSProfile, Any]:
    config = context["config"]
    hardware = config["hardware"]
    base = CenterSurfaceFactoryProfile(
        context["references"],
        distance,
        count,
        gap_um=hardware["patch_gap_um"],
        readout_gap_um=hardware["readout_gap_um"],
        movement_us_per_um=hardware["movement_us_per_um"],
        cnot_target_offset_um=tuple(hardware["cnot_target_offset_um"]),
    )
    s, ec = _assumptions(config)
    return base, AssumedSProfile(base, s), assumed_factory_recipe(distance, s=s, ec=ec)


def _execute(
    context: Mapping[str, Any],
    distance: int,
    count: int,
    seed: int,
    policy: ProductionPolicy,
    *,
    warmup_us: float = 0,
) -> dict[str, Any]:
    config = context["config"]
    with no_atom_execution() as guard:
        base, profile, recipe = _profile(context, distance, count)
        result = run_surface_factory(
            profile,
            seed=seed,
            input_z_error=config["input_z_error"],
            raw_attempts=config["limits"]["raw_attempts"],
            batches=config["limits"]["batches"],
            max_component_calls=config["limits"]["max_component_calls"],
            recipe=recipe,
            production_policy=policy,
            output_sink=make_output_sink(config["output_sink"]),
        )
        metrics = summarize_center_case(
            result["case"], base.plan, warmup_us=warmup_us, stop_us=policy.stop_at_us
        )
        bounds = base.plan.occupied_bounds
        shift = base.translation_y_um
        reserved_readout = [
            bounds.x_min,
            bounds.y_min + shift,
            bounds.x_max,
            bounds.y_max + shift,
        ]
        scene = [bounds.x_min, bounds.y_min, bounds.x_max, bounds.y_max + shift]
        area = (scene[2] - scene[0]) * (scene[3] - scene[1])
        area_time = area * metrics["actual_observation_us"]
        footprint = {
            "reserved_readout_bounds_um": reserved_readout,
            "allocated_scene_bounds_um": scene,
            "allocated_scene_bbox_area_um2": area,
            "allocated_scene_basis": "home code-block rectangle plus translated reserved readout rectangles and intervening corridor; model reservation, not actual occupied area",
        }
        metrics.update(**footprint, allocated_scene_bbox_area_time_um2_us=area_time)
        for key, denominator in (
            ("per_accepted_output", metrics["accepted_outputs"]),
            ("per_delivered_output", metrics["delivered_outputs"]),
        ):
            metrics[key]["allocated_scene_bbox_area_time_um2_us"] = (
                area_time / denominator if denominator else None
            )
        profile_info = {
            "profile_sha256": profile.profile_sha256,
            "base_profile_sha256": base.profile_sha256,
            "placement": base.plan.to_dict(),
            "assumptions": profile.calibration_evidence(),
            "reference_payload_sha256": context["references"]["payload_sha256"],
            **footprint,
        }
    return {
        **result,
        "metrics": metrics,
        "guard": guard.to_dict(),
        "profile": profile_info,
    }


def _run_once(
    context: Mapping[str, Any],
    directory: Path,
    distance: int,
    count: int,
    seed: int,
    policy: ProductionPolicy,
    *,
    warmup_us: float = 0,
) -> dict[str, Any]:
    task = {
        "distance": distance,
        "factory_count": count,
        "seed": seed,
        "max_cycles": policy.max_cycles,
        "stop_at_us": policy.stop_at_us,
        "warmup_us": warmup_us,
    }
    existing = _verified_completion(directory, context["identity"], task)
    if existing is not None:
        return existing
    directory.mkdir(parents=True, exist_ok=True)
    index = 1
    while (directory / f"attempt-{index:04d}").exists():
        index += 1
    attempt = directory / f"attempt-{index:04d}"
    attempt.mkdir()
    started = perf_counter()
    try:
        result = _execute(context, distance, count, seed, policy, warmup_us=warmup_us)
        if source_manifest()["sha256"] != context["identity"]["source_sha256"]:
            raise ValueError("SINGLE_FAST_SOURCE_CHANGED_DURING_EXECUTION")
        for name in ("case", "ledger"):
            _gzip_json(attempt / f"{name}.json.gz", result[name])
        for name in ("metrics", "summary", "guard", "profile"):
            _write_new(attempt / f"{name}.json", result[name])
        _write_new(attempt / "ledger-counts.json", result["ledger"]["counts"])
        record = {
            "schema": "nadit.single_fast_trajectory/1",
            "identity": dict(context["identity"]),
            "task": task,
            "distance": distance,
            "factory_count": count,
            "seed": seed,
            "status": result["summary"]["status"],
            "metrics": result["metrics"],
            "ledger_counts": result["ledger"]["counts"],
            "lines": result["summary"]["lines"],
            "profile_sha256": result["summary"]["profile_sha256"],
            "guard": result["guard"],
            "attempt": attempt.name,
            "worker_wall_seconds": perf_counter() - started,
        }
    except Exception as error:
        _write_new(
            attempt / "error.json",
            {"error_type": type(error).__name__, "message": str(error)},
        )
        raise
    record["artifacts"] = {
        p.relative_to(directory).as_posix(): _sha(p)
        for p in sorted(attempt.iterdir())
        if p.is_file()
    }
    _write_new(directory / "completion.json", record)
    print(
        json.dumps(
            {
                "distance": distance,
                "factory_count": count,
                "seed": seed,
                "status": record["status"],
                "accepted_outputs": record["metrics"]["accepted_outputs"],
                "window_complete": record["metrics"]["requested_window_complete"],
                "worker_wall_seconds": record["worker_wall_seconds"],
            }
        ),
        flush=True,
    )
    return record


def freeze_observation(
    pilot: Mapping[str, Any], config: Mapping[str, Any], count: int
) -> dict[str, Any]:
    """Freeze pilot-derived warmup and stop before inspecting production outcomes."""
    observation = config["observation"]
    cycles = observation["pilot_cycles"]
    metrics = pilot["metrics"]
    duration = metrics["case_duration_us"]
    if (
        pilot["status"] != "complete"
        or not metrics["requested_window_complete"]
        or metrics["delivered_outputs_total"] != cycles * count
        or not isinstance(duration, (float, int))
        or not isfinite(duration)
        or duration <= 0
    ):
        raise ValueError("PILOT_INCOMPLETE_CELL_EXCLUDED")
    cycle_us = duration / cycles
    return {
        "schema": "nadit.single_fast_observation/1",
        "pilot_seed": config["pilot_seed"],
        "pilot_completion_sha256": reference_digest(dict(pilot)),
        "cycle_us": cycle_us,
        "warmup_us": observation["warmup_cycles"] * cycle_us,
        "stop_us": (observation["warmup_cycles"] + observation["target_cycles"])
        * cycle_us,
        "basis": "separate pilot duration divided by completed cycles; window frozen before production",
        "boundary_convention": "[warmup_us, stop_us)",
    }


def smoke_invariants(
    case: Mapping[str, Any],
    ledger: Mapping[str, Any],
    config: Mapping[str, Any],
    distance: int,
) -> dict[str, Any]:
    """Check parallel initial supply, feedback/resource identity and explicit EC."""
    calls = case["execution"]["calls"]
    waves = {
        identity: wave["batch_id"]
        for wave in case["execution"]["waves"]
        for identity in wave["invocations"]
    }
    if (
        case["status"] != "complete"
        or case.get("physical") is not None
        or case["execution_representation"] != "logical_estimate"
    ):
        raise ValueError("SMOKE_REQUIRES_COMPLETE_LOGICAL_CASE")
    initial_sets = {}
    for factory in case["factories"]:
        selected = [
            row
            for row in calls
            if row["component_id"] == "raw_t_postselection"
            and row["invocation_id"].startswith(factory + "/cycle[0]/batch[0]/initial/")
            and row["invocation_id"].endswith("/attempt[0]/body")
        ]
        if (
            len(selected) != 4
            or len({waves[row["invocation_id"]] for row in selected}) != 1
        ):
            raise ValueError("SMOKE_INITIAL_RAW_NOT_PARALLEL")
        initial_sets[factory] = [row["invocation_id"] for row in selected]
    if ledger["counts"]["raw_rejections"] < 1:
        raise ValueError("SMOKE_HAS_NO_REJECTION_WITNESS")
    outputs = [
        row["token_id"]
        for line in case["factories"].values()
        for row in line["outputs"]
    ]
    if len(outputs) != len(set(outputs)):
        raise ValueError("SMOKE_OUTPUT_TOKEN_REUSED")
    consumed = Counter(
        row["token_id"]
        for row in case["resources"]["audit"]
        if row["action"] == "consume"
    )
    if any(value != 1 for value in consumed.values()) or any(
        consumed[token] != 1 for token in outputs
    ):
        raise ValueError("SMOKE_RESOURCE_CONSUMPTION_NOT_UNIQUE")
    ec_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for call in calls:
        if call["component_id"] == "se_round" and "/ec[" in call["invocation_id"]:
            ec_groups[call["invocation_id"].rsplit("/", 1)[0]].append(call)
        if (
            call["component_id"] == "assumed_transversal_s"
            and abs(
                call["action_end_us"] - call["start_us"] - config["s"]["duration_us"]
            )
            > 1e-7
        ):
            raise ValueError("SMOKE_S_DURATION_DIFFERS_FROM_ASSUMPTION")
    _, ec = _assumptions(config)
    expected = sum(
        mark["kind"] == "rotation_complete"
        for line in case["factories"].values()
        for mark in line["milestones"]
    ) * ec.resolved_rounds(distance)
    if len(ec_groups) != expected or any(
        {row["participant_blocks"][0].rsplit("/", 1)[1] for row in rows}
        != {"W1", "W2", "W3", "W4", "W5"}
        or len(rows) != 5
        or len({waves[row["invocation_id"]] for row in rows}) != 1
        for rows in ec_groups.values()
    ):
        raise ValueError("SMOKE_EC_WORK_PATCH_COVERAGE_OR_BATCHING")
    return {
        "passed": True,
        "initial_raw_same_wave": initial_sets,
        "raw_rejections": ledger["counts"]["raw_rejections"],
        "unique_outputs": len(outputs),
        "ec_groups": len(ec_groups),
        "ec_group_width": 5,
        "s_duration_verified": True,
        "physical_execution": False,
    }


def run_smoke(config_path: Path, output: Path) -> dict[str, Any]:
    """Run d3/N2/seed0 for two successful cycles and persist bounded acceptance."""
    context = _initialize(config_path, output)
    directory = output / "smoke"
    with directory_lock(directory):
        completion = _run_once(context, directory, 3, 2, 0, ProductionPolicy(2))
        attempt = directory / completion["attempt"]
        with gzip.open(attempt / "case.json.gz", "rt", encoding="utf-8") as stream:
            case = json.load(stream)
        with gzip.open(attempt / "ledger.json.gz", "rt", encoding="utf-8") as stream:
            ledger = json.load(stream)
        audit = {
            **smoke_invariants(case, ledger, context["config"], 3),
            "identity": context["identity"],
            "completion_sha256": reference_digest(completion),
            "no_atom_guard": completion["guard"],
        }
        path = directory / "acceptance.json"
        if path.exists():
            if _read(path) != audit:
                raise ValueError("SMOKE_ACCEPTANCE_IDENTITY_MISMATCH")
        else:
            _write_new(path, audit)
    return audit


def run_cell(
    config_path: Path, output: Path, distance: int, count: int
) -> dict[str, Any]:
    """Run one approved cell, resuming only complete source-matched trajectories."""
    context = _initialize(config_path, output)
    config = context["config"]
    if distance not in config["distances"] or count not in config["factory_counts"]:
        raise ValueError("CELL_OUTSIDE_FROZEN_GRID")
    acceptance_path = output / "smoke/acceptance.json"
    if (
        not acceptance_path.exists()
        or _read(acceptance_path).get("identity") != context["identity"]
        or _read(acceptance_path).get("passed") is not True
    ):
        raise ValueError("SOURCE_MATCHED_SMOKE_ACCEPTANCE_REQUIRED")
    directory = output / "cells" / f"d{distance}-n{count}"
    with directory_lock(directory):
        pilot = _run_once(
            context,
            directory / "pilot",
            distance,
            count,
            config["pilot_seed"],
            ProductionPolicy(config["observation"]["pilot_cycles"]),
        )
        try:
            policy = freeze_observation(pilot, config, count)
        except ValueError as error:
            excluded = {
                "status": "pilot_excluded",
                "reason": str(error),
                "distance": distance,
                "factory_count": count,
                "identity": context["identity"],
            }
            path = directory / "excluded.json"
            if not path.exists():
                _write_new(path, excluded)
            return excluded
        policy_path = directory / "observation.json"
        if policy_path.exists():
            if _read(policy_path) != policy:
                raise ValueError("OBSERVATION_WINDOW_ALREADY_FROZEN")
        else:
            _write_new(policy_path, policy)
        for seed in config["production_seeds"]:
            _run_once(
                context,
                directory / f"seed-{seed:04d}",
                distance,
                count,
                seed,
                ProductionPolicy(config["limits"]["max_cycles"], policy["stop_us"]),
                warmup_us=policy["warmup_us"],
            )
    return {
        "distance": distance,
        "factory_count": count,
        "status": "seed_runs_completed",
    }


def summarize_campaign(config_path: Path, output: Path) -> dict[str, Any]:
    """Export explicit complete, failed, excluded and not-run cell/seed coverage."""
    context = _initialize(config_path, output)
    config = context["config"]
    cells = []
    for distance in config["distances"]:
        for count in config["factory_counts"]:
            directory = output / "cells" / f"d{distance}-n{count}"
            rows = []
            missing = []
            for seed in config["production_seeds"]:
                completion = _verified_completion(
                    directory / f"seed-{seed:04d}", context["identity"]
                )
                if completion is None:
                    missing.append(seed)
                else:
                    if any(
                        completion[key] != expected
                        or completion["metrics"][key] != expected
                        for key, expected in (
                            ("distance", distance),
                            ("factory_count", count),
                            ("seed", seed),
                        )
                    ):
                        raise ValueError("SINGLE_FAST_SUMMARY_POSITION_MISMATCH")
                    rows.append(completion["metrics"])
            sample_statistics = summarize_center_samples(rows) if rows else None
            status = (
                "incomplete"
                if missing
                else "complete"
                if sample_statistics is not None
                and sample_statistics["complete_seed_count"] == len(rows)
                else "partial_failure"
            )
            cell = {
                "distance": distance,
                "factory_count": count,
                "completed_trajectories": len(rows),
                "not_run_seeds": missing,
                "status": status,
                "statistics": sample_statistics,
            }
            if (directory / "excluded.json").exists():
                cell.update(
                    status="pilot_excluded",
                    exclusion=_read(directory / "excluded.json"),
                )
            cells.append(cell)
    summary = {
        "schema": "nadit.single_fast_campaign_summary/1",
        "identity": context["identity"],
        "configuration": config,
        "cells": cells,
        "all_trajectories_recorded": all(not cell["not_run_seeds"] for cell in cells),
        "all_observation_windows_complete": all(
            cell["status"] == "complete" for cell in cells
        ),
        "physical_execution": False,
        "actual_output_error": None,
    }
    folder = output / "reports" / reference_digest(summary)[:16]
    with directory_lock(folder):
        if not (folder / "summary.json").exists():
            _write_new(folder / "summary.json", summary)
        elif _read(folder / "summary.json") != summary:
            raise ValueError("SINGLE_FAST_REPORT_CONTENT_MISMATCH")
        csv_bytes = _summary_csv(cells)
        csv_path = folder / "summary.csv"
        if csv_path.exists():
            if csv_path.read_bytes() != csv_bytes:
                raise ValueError("SINGLE_FAST_REPORT_CSV_MISMATCH")
        else:
            temporary = folder / "summary.csv.tmp"
            temporary.write_bytes(csv_bytes)
            temporary.replace(csv_path)
    return {"report_directory": str(folder), **summary}


def _summary_csv(cells: list[dict[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=(
            "distance",
            "factory_count",
            "status",
            "complete_seeds",
            "recorded_seeds",
            "accepted_per_second_mean",
            "accepted_per_second_pooled",
            "startup_latency_us_mean",
            "atom_time_per_accepted_output_pooled",
        ),
    )
    writer.writeheader()
    for cell in cells:
        statistics = cell["statistics"] or {}
        fields = statistics.get("statistics", {})
        pooled = statistics.get("pooled_cost_per_accepted_output", {})
        writer.writerow(
            {
                "distance": cell["distance"],
                "factory_count": cell["factory_count"],
                "status": cell["status"],
                "complete_seeds": statistics.get("complete_seed_count", 0),
                "recorded_seeds": cell["completed_trajectories"],
                "accepted_per_second_mean": fields.get(
                    "accepted_outputs_per_second", {}
                ).get("mean"),
                "accepted_per_second_pooled": statistics.get(
                    "pooled_accepted_outputs_per_second"
                ),
                "startup_latency_us_mean": fields.get(
                    "startup_deliverable_latency_us", {}
                ).get("mean"),
                "atom_time_per_accepted_output_pooled": pooled.get(
                    "configured_atom_time_us"
                ),
            }
        )
    return stream.getvalue().encode("utf-8")


def main() -> None:
    """Run smoke, approved cells or immutable summaries from one frozen config."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("smoke", "run", "summarize"))
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--distance", type=int)
    parser.add_argument("--count", type=int)
    args = parser.parse_args()
    if (args.distance is None) != (args.count is None):
        parser.error("--distance and --count must be supplied together")
    if args.command == "smoke":
        result = run_smoke(args.config, args.output)
    elif args.command == "summarize":
        result = summarize_campaign(args.config, args.output)
    elif args.distance is not None:
        result = run_cell(args.config, args.output, args.distance, args.count)
    else:
        config = load_configuration(args.config)
        for distance in config["distances"]:
            for count in config["factory_counts"]:
                run_cell(args.config, args.output, distance, count)
        result = summarize_campaign(args.config, args.output)
    print(json.dumps(result, allow_nan=False), flush=True)


if __name__ == "__main__":
    main()
