"""Run bounded native campaign acceptance through the existing experiment runner.

Six initial tasks cover continuous vertical production, horizontal/grid source
frontiers and real same-distance L1/L2 delivery. Missing calibration remains an
ordinary runner dependency. This is interface acceptance, not campaign scaling,
decoded logical-error evidence or human visual acceptance. No formal campaign
configuration, historical evidence or source file is modified.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import Path
from time import perf_counter
from typing import Any

from nadit_physical_compiler.cost.base import require_validated
from nadit_physical_compiler.experiments.journal import write_json
from nadit_physical_compiler.experiments.runner import run_task_plan
from nadit_physical_compiler.experiments.task_plan import validate_plan, validate_task
from nadit_physical_compiler.experiments.version import check_version, code_version
from nadit_physical_compiler.provenance import canonical_hash

from experiments.analysis.joint_factory_report import audit_native_activity
from experiments.analysis.msd_two_level_audit import audit_saved_two_level
from experiments.msd.campaign_report import _export_native_schedule, _native_template
from experiments.msd.joint_cache import (
    action_dependency_fingerprints,
    probability_dependency_fingerprints,
)
from experiments.msd.standard import (
    FACTORY_ROLES,
    ExperimentSpec,
    build_world,
    placement_request,
)
from modules.codes.rotated_surface.joint_factory_source import factory_component_source
from modules.logical_compiler.src.placement import GridFactoryPlacement, place

DEFAULT_CONFIG = Path("experiments/msd/campaign-single-aod-20261025.json")
WORKERS = 2
WORKER_BYTES = 8 * 1024**3
CALIBRATION_SECONDS = 300
PARENT_SECONDS = 1800
CAMPAIGN_SECONDS = 3600
STORAGE_BYTES = 8 * 1024**3
SAMPLING = {"shots": 64, "seed": 20261024}
SINK = {"kind": "ideal_external", "acknowledge_excluded_costs": True}
_AUDIT_SOURCES = {
    "experiments/analysis/msd_campaign_acceptance.py",
    "experiments/analysis/msd_two_level_audit.py",
    "experiments/analysis/joint_factory_report.py",
}


def _require(condition: Any, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _read(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text(encoding="utf-8")))


def _sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _inside(value: str | Path, root: Path) -> Path:
    path = Path(value)
    path = (path if path.is_absolute() else root / path).resolve()
    _require(path.is_relative_to(root), f"Acceptance artifact escapes run: {path}")
    return path


def _task(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = {
        "kind": kind,
        "payload": payload,
        "dependencies": [],
        "timeout_s": CALIBRATION_SECONDS if kind == "msd.calibrate" else PARENT_SECONDS,
        "max_attempts": 1,
        "memory_bytes": WORKER_BYTES,
    }
    return dict(validate_task({"task_id": canonical_hash(body), **body}))


def build_acceptance_plan(
    configuration: Mapping[str, Any], output: Path, source_paths: Sequence[str]
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Describe six bounded tasks; never compile, sample, write or dispatch them.

    The 64-shot diagnostic setting is explicit and leaves the supplied formal
    configuration unchanged. Native timing/noise/layout conventions come from
    the existing experiment standard. Returns the plan and named audit cases.
    """
    _require(
        configuration.get("standard") == "nadit.msd.standard/2"
        and configuration.get("aod_count") == 1,
        "Acceptance requires the current single-AOD standard",
    )
    _require(configuration.get("sink") == SINK, "Explicit ideal-external sink required")
    dependencies = {
        "actions": action_dependency_fingerprints(),
        "probabilities": probability_dependency_fingerprints(),
    }
    cases: dict[str, dict[str, Any]] = {}
    tasks = []
    for count, columns, name in (
        (2, 1, "vertical"),
        (2, 2, "horizontal"),
        (4, 2, "grid"),
    ):
        spec = ExperimentSpec(3, count)
        placement = place(
            placement_request(spec),
            GridFactoryPlacement(FACTORY_ROLES, columns=columns),
        )
        world = build_world(spec, placement_plan=placement)
        payload = {
            "spec": spec.to_dict(),
            "placement": placement.to_dict(),
            "noise_params": deepcopy(configuration["noise_params"]),
            "sampling": dict(SAMPLING),
            "cache_root": str(output / "cache"),
            "dependencies": dependencies,
        }
        if name == "vertical":
            payload.update(
                production_seed=0,
                input_z_error=configuration["input_z_error"],
                limits={"raw_attempts": 8, "batches": 4, "max_component_calls": 20000},
                calibration_budget={
                    "timeout_s": CALIBRATION_SECONDS,
                    "max_attempts": 1,
                    "memory_bytes": WORKER_BYTES,
                },
            )
            pilot = _task(
                "msd.pilot", {**payload, "pilot_cycles": 2, "output_sink": SINK}
            )
            tasks.append(pilot)
            cases["vertical-pilot"] = {
                "task_id": pilot["task_id"],
                "world": world.document(),
            }
            two_level = _task(
                "msd.two_level_witness",
                {
                    **payload,
                    "two_level": {
                        "level1_count": 1,
                        "level2_count": 1,
                        "buffer_capacity": 1,
                        "producer_max_cycles": 16,
                        "consumer_max_cycles": 1,
                        "level1_batches": 4,
                        "level2_batches": 1,
                        "parking_origin": {"x": -100, "y": -60},
                        "acknowledge_theory_transport_exclusions": True,
                        "output_sink": SINK,
                    },
                },
            )
            tasks.append(two_level)
            cases["two-level"] = {"task_id": two_level["task_id"]}
            continue
        for component, roles, suffix in (
            ("raw_t_postselection", ("R",), "raw"),
            ("logical_mx", ("W2", "W3", "W4", "W5"), "final-mx"),
        ):
            members = [
                f"{component}:factory{i}/{role}" for i in range(count) for role in roles
            ]
            task = _task("msd.calibrate", {**payload, "members": members})
            tasks.append(task)
            cases[f"{name}-{suffix}"] = {
                "task_id": task["task_id"],
                "factory_count": count,
                "members": members,
                "world": world.document(),
            }
    plan = validate_plan(
        {
            "schema": "nadit.task_plan/1",
            "tasks": tasks,
            "source_paths": list(source_paths),
            "budget": {
                "campaign_timeout_s": CAMPAIGN_SECONDS,
                "max_storage_bytes": STORAGE_BYTES,
                "max_artifact_refreshes": 1,
            },
        }
    )
    return dict(plan), cases


def _completed_result(
    output: Path, task_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    task = validate_task(_read(output / "task_definitions" / f"{task_id}.json"))
    completion = _read(output / "task_completions" / f"{task_id}.json")
    _require(task["task_id"] == task_id, "Saved task identity changed")
    _require(
        completion["status"] == "ok" and completion["kind"] == task["kind"],
        "Acceptance task did not succeed",
    )
    result = _read(_inside(completion["result_path"], output))
    _require(
        canonical_hash(result) == completion["result_sha256"],
        "Published result hash mismatch",
    )
    for artifact in completion.get("artifacts", []):
        path = _inside(artifact["path"], output)
        _require(
            artifact["hash_kind"] in ("bytes", "canonical_json"),
            "Unknown artifact hash kind",
        )
        digest = (
            _sha(path)
            if artifact["hash_kind"] == "bytes"
            else canonical_hash(_read(path))
        )
        _require(digest == artifact["sha256"], f"Artifact hash mismatch: {path}")
    return result, completion


def _trace_standard(trace: dict[str, Any]) -> None:
    require_validated(trace)
    device = trace["device"]
    _require(len(device["aods"]) == 1, "AOD count changed")
    _require(
        device["timing"]["load_us"] == device["timing"]["store_us"] == 10,
        "Transfer timing changed",
    )
    _require(
        device["readout"]["duration_us"] == 100
        and device["readout"]["latency_us"] == 0,
        "Readout timing changed",
    )
    _require(
        trace["entry_state"] == trace["exit_state"],
        "Ordinary fragment did not return home",
    )


def _audit_record(
    record: Mapping[str, Any], output: Path, expected_world: Mapping[str, Any]
) -> tuple[dict[str, Any], Path]:
    path = _inside(record["trace_path"], output)
    trace = _read(path)
    _require(canonical_hash(trace) == record["trace_sha256"], "Trace hash mismatch")
    action = _read(output / "cache/actions" / record["action_key"] / "action.json")[
        "record"
    ]
    _require(action["trace_sha256"] == record["trace_sha256"], "Action/trace mismatch")
    _trace_standard(trace)
    _require(
        trace["device"] == expected_world["device"],
        "Requested layout/device was rebuilt",
    )
    patches = {p["binding"]["block_id"]: p for p in expected_world["patches"]}
    wires = []
    for member in sorted(action["members"]):
        component, blocks = member.split(":", 1)
        selected = [patches[block] for block in blocks.split(",")]
        source = factory_component_source(
            component,
            selected[0].get("distance", expected_world["parameters"]["distance"]),
        )
        atoms = [atom for patch in selected for atom in patch["binding"]["atom_ids"]]
        active = [atoms[index] for index in source.wire_indices]
        _require(
            action["participant_atoms"][member] == active,
            "Source member atom binding changed",
        )
        _require(
            len(action["members"][member]["measurement_phases"]) == source.result_count,
            "Source result count changed",
        )
        wires.extend(active)
    expected_entry = {**expected_world["entry_state"], "qubit_to_atom": wires}
    _require(
        trace["entry_state"] == expected_entry,
        "Requested complete atom world/placement changed",
    )
    audit_native_activity(action, trace)
    return action, path


def _case_schedule(result: Mapping[str, Any], folder: Path) -> dict[str, Any]:
    folder.mkdir(parents=True, exist_ok=False)
    native, references = _export_native_schedule(result, folder)
    write_json(folder / "trace-references.json", references)
    with (folder / "schedule.csv").open("w", encoding="utf-8", newline="") as stream:
        fields = [
            "invocation_id",
            "component_id",
            "start_us",
            "action_end_us",
            "results_ready_us",
            "batch_id",
            "joint_trace_sha256",
        ]
        writer = csv.DictWriter(
            stream, fields, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(result["case"]["execution"]["calls"])
    return dict(native)


def _pilot_lifecycle(case: Mapping[str, Any], outputs: list[dict[str, Any]]) -> None:
    """Check the original token ledger independently of worker metric flags."""
    tokens = {t["token_id"]: t for t in case["resources"]["tokens"]}
    _require(len(tokens) == len(case["resources"]["tokens"]), "Duplicate ledger token")
    consumes: dict[str, list[dict[str, Any]]] = defaultdict(list)
    releases: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    preparations: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for event in case["resources"]["audit"]:
        if event["action"] == "consume":
            consumes[event["token_id"]].append(event)
        elif event["action"] == "complete_use":
            releases[event["carrier_id"], event["epoch"]].append(event)
        elif event["action"] == "begin_preparation":
            preparations[event["carrier_id"], event["epoch"]].append(event)
    for output in outputs:
        token, delivery = tokens[output["token_id"]], output["delivery"]
        carrier = (output["carrier_id"], output["epoch"])
        _require(
            token["status"] == "consumed"
            and (token["carrier_id"], token["epoch"]) == carrier,
            "Output token identity/use changed",
        )
        _require(
            token["quality"] == output["quality"]
            and token["ready_at_us"] == output["ready_at_us"],
            "Output provenance changed",
        )
        _require(
            delivery["token_id"] == token["token_id"]
            and delivery["carrier_id"] == token["carrier_id"]
            and delivery["consumer"] == token["consumer"],
            "Delivery identity changed",
        )
        _require(
            output["ready_at_us"]
            <= output["deliverable_at_us"]
            <= output["consumed_at_us"]
            <= output["released_at_us"]
            <= case["duration_us"],
            "Output lifecycle times reversed",
        )
        _require(
            all(
                output[key] == delivery[key]
                for key in ("deliverable_at_us", "consumed_at_us", "released_at_us")
            ),
            "Reported delivery times changed",
        )
        _require(
            token["consumed_at_us"] == output["consumed_at_us"]
            and len(consumes[token["token_id"]]) == len(releases[carrier]) == 1,
            "Output not used/released exactly once",
        )
        use, release = consumes[token["token_id"]][0], releases[carrier][0]
        _require(
            use["consumer"] == token["consumer"] == release["owner"]
            and use["at_us"] == output["consumed_at_us"]
            and release["at_us"] == output["released_at_us"]
            and use["sequence"] < release["sequence"],
            "Ledger does not support delivery/release",
        )
        _require(
            delivery["evidence"]["kind"] == "ideal_external"
            and delivery["evidence"]["physical_delivery"] is False,
            "Pilot terminal sink assumption changed",
        )
    for factory, line in case["factories"].items():
        before, after = line["outputs"]
        _require(
            after["epoch"] > before["epoch"]
            and after["ready_at_us"] > before["released_at_us"],
            "Next cycle reused state/clock",
        )
        prep = preparations[after["carrier_id"], after["epoch"]]
        _require(
            len(prep) == 1 and prep[0]["at_us"] >= before["released_at_us"],
            "Next preparation precedes carrier release",
        )
        prefix = f"{factory}/cycle[1]/batch[{after['batch']}]/"
        _require(
            any(
                c["invocation_id"].startswith(prefix)
                and c["component_id"] == "initialize_plus"
                and after["carrier_id"] in c["participant_blocks"]
                for c in case["execution"]["calls"]
            ),
            "Next-cycle preparation was not executed",
        )


def _pilot_audit(
    result: dict[str, Any], output: Path, expected_world: Mapping[str, Any]
) -> dict[str, Any]:
    case = result["case"]
    _require(
        case["status"] == "complete" and case.get("failure") is None, "Pilot incomplete"
    )
    _require(len(case["factories"]) == 2, "Pilot factory count changed")
    outputs = [item for line in case["factories"].values() for item in line["outputs"]]
    _require(
        len(outputs) == len({item["token_id"] for item in outputs}) == 4,
        "Pilot requires four distinct outputs",
    )
    _require(
        all(
            line["status"] == "complete"
            and [item["cycle"] for item in line["outputs"]] == [0, 1]
            for line in case["factories"].values()
        ),
        "Pilot cycles incomplete",
    )
    _require(
        len(result["metrics"]["outputs"]) == 4
        and all(
            item["delivery_lifecycle_verified"] for item in result["metrics"]["outputs"]
        ),
        "Pilot output lifecycle not validated",
    )
    _require(
        all(carrier["owner"] is None for carrier in case["resources"]["carriers"]),
        "Pilot carrier leaked",
    )
    _pilot_lifecycle(case, outputs)
    for cycle in (0, 1):
        prefixes = tuple(
            f"{factory}/cycle[{cycle}]/batch[{line['outputs'][cycle]['batch']}]/final/"
            for factory, line in case["factories"].items()
        )
        final = [
            call
            for call in case["execution"]["calls"]
            if call["component_id"] == "logical_mx"
            and call["invocation_id"].startswith(prefixes)
        ]
        _require(
            len(final) == 8 and len({call["batch_id"] for call in final}) == 1,
            "Pilot final-MX frontier split or missing",
        )
    concurrent = False
    for record in result["calibration_records"].values():
        group, _ = _audit_record(record, output, expected_world)
        concurrent |= group["factory_concurrency"][
            "peak_active_factories"
        ] >= 2 and any(
            member.startswith("raw_t_postselection:") for member in group["members"]
        )
    _require(concurrent, "Pilot lacks real shared-AOD raw concurrency")
    return {
        "passed": True,
        "outputs": 4,
        "duration_us": case["duration_us"],
        "ledger_lifecycle_verified": True,
        "requested_world_verified": True,
    }


def _fragment_audit(
    result: dict[str, Any],
    case: dict[str, Any],
    name: str,
    output: Path,
    *,
    export_folder: Path | None = None,
) -> dict[str, Any]:
    group, path = _audit_record(
        {**result, "trace_sha256": result["group"]["trace_sha256"]},
        output,
        case["world"],
    )
    _require(
        sorted(group["members"]) == sorted(case["members"]), "Fragment members changed"
    )
    _require(
        group["factory_concurrency"]["peak_active_factories"] == case["factory_count"],
        "Fragment lost factory concurrency",
    )
    duration, rows = _native_template(path, group["trace_sha256"])
    if name.endswith("final-mx"):
        _require(
            len(group["members"]) == 4 * case["factory_count"]
            and sum(row[4] == "Measure" for row in rows) == 1,
            "Final-MX is not one complete measurement frontier",
        )
    if export_folder is not None:
        _fragment_schedule(
            export_folder, case["world"], path, group["trace_sha256"], rows
        )
    return {
        "passed": True,
        "duration_us": duration,
        "members": len(group["members"]),
        "trace_sha256": group["trace_sha256"],
        "native_actions": len(rows),
        "requested_world_verified": True,
    }


def _fragment_schedule(
    folder: Path,
    world: Mapping[str, Any],
    trace_path: Path,
    trace_sha: str,
    rows: Sequence[tuple[int, int, float, float, str, str, str, str]],
) -> None:
    folder.mkdir(parents=True, exist_ok=False)
    with (folder / "native-action-schedule.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(
            [
                "step_index",
                "action_index",
                "start_us",
                "end_us",
                "duration_us",
                "kind",
                "resource",
                "atom_ids",
                "source_ids",
            ]
        )
        for step, action, start, span, kind, resource, atoms, sources in rows:
            writer.writerow(
                [
                    step,
                    action,
                    start,
                    start + span,
                    span,
                    kind,
                    resource,
                    atoms,
                    sources,
                ]
            )
    write_json(folder / "world.json", world)
    write_json(folder / "trace-references.json", {trace_sha: [str(trace_path)]})


def run_acceptance(
    output: Path,
    *,
    configuration: Path = DEFAULT_CONFIG,
    source_paths: Sequence[str] | None = None,
    allow_dirty: bool = False,
) -> dict[str, Any]:
    """Run and audit the fixed acceptance plan in a new directory.

    Every gate carries the same source scope used by the formal configuration.
    Dirty preacceptance runs emit passed diagnostics but never passed gates.
    Raises ValueError on reused output, missing audit-source pins, runner failure,
    changed source, failed evidence checks or non-idempotent resume.
    """
    started = perf_counter()
    output = output.resolve()
    _require(not output.exists(), "Use a new acceptance output directory")
    config = _read(configuration)
    paths = tuple(config["source_paths"] if source_paths is None else source_paths)
    _require(
        _AUDIT_SOURCES <= set(paths),
        "Declare all three analysis audit sources in config.source_paths",
    )
    version = code_version(allow_dirty=allow_dirty, scope="msd", source_paths=paths)
    plan, cases = build_acceptance_plan(config, output, paths)
    output.mkdir(parents=True)
    write_json(
        output / "acceptance-inputs.json",
        {
            "source_identity": version,
            "configuration_sha256": canonical_hash(config),
            "sampling": SAMPLING,
            "production_seed": 0,
            "workers": WORKERS,
            "scope": "64-shot diagnostic acceptance; formal campaign sampling unchanged",
            "cases": cases,
        },
    )
    write_json(output / "requested-plan.json", plan)
    status = run_task_plan(plan, output, workers=WORKERS, allow_dirty=allow_dirty)
    write_json(output / "final-status.json", status)
    _require(
        status["pending"] == 0 and set(status["statuses"]) == {"ok"},
        "Acceptance runner did not finish successfully; preserved status contains the reason",
    )
    _require(
        _read(output / "manifest.json")["code"] == version,
        "Acceptance manifest source changed",
    )
    audits: dict[str, Any] = {}
    for name, case in cases.items():
        result, completion = _completed_result(output, case["task_id"])
        if name == "vertical-pilot":
            audit = _pilot_audit(result, output, case["world"])
            folder = output / "audit/vertical-pilot"
            audit["native_schedule"] = _case_schedule(result, folder)
            write_json(folder / "world.json", case["world"])
            write_json(
                folder / "outputs.json",
                [
                    item
                    for line in result["case"]["factories"].values()
                    for item in line["outputs"]
                ],
            )
        elif name == "two-level":
            folder = output / "audit/two-level"
            _case_schedule(result, folder)
            audit = audit_saved_two_level(
                output, case["task_id"], folder / "native-action-schedule.csv"
            )
            audit["passed"] = audit["status"] == "passed"
        else:
            audit = _fragment_audit(
                result, case, name, output, export_folder=output / "audit" / name
            )
        audit.update(task_id=case["task_id"], result_sha256=completion["result_sha256"])
        write_json(output / "audit" / name / "audit.json", audit)
        audits[name] = audit
    dispatches = (output / "task_dispatches.jsonl").read_bytes()
    resumed = run_task_plan(plan, output, workers=WORKERS, allow_dirty=allow_dirty)
    _require(
        resumed["statuses"] == status["statuses"]
        and (output / "task_dispatches.jsonl").read_bytes() == dispatches,
        "Resume dispatched new work or changed task status",
    )
    check_version(version)
    observed_bytes = sum(
        path.stat().st_size for path in output.rglob("*") if path.is_file()
    )
    _require(
        perf_counter() - started <= CAMPAIGN_SECONDS
        and observed_bytes <= STORAGE_BYTES,
        "Acceptance audit/export exceeded the fixed total budget; no passed gates published",
    )
    clean = version["dirty"] is False
    for kind, names, filename in (
        (
            "physical_interface_acceptance",
            [name for name in cases if name != "two-level"],
            "interface-audit.json",
        ),
        ("physical_two_level_delivery", ["two-level"], "two-level-audit.json"),
    ):
        envelope = {
            "schema": "nadit.msd.campaign_acceptance/1",
            "passed": clean and all(audits[name]["passed"] for name in names),
            "diagnostic_checks_passed": True,
            "evidence_kind": kind,
            "source_identity": version,
            "configuration_sha256": canonical_hash(config),
            "checks": [
                {
                    "case": name,
                    "passed": True,
                    "audit_path": f"audit/{name}/audit.json",
                    "audit_sha256": canonical_hash(audits[name]),
                }
                for name in names
            ],
            "resume_dispatched_no_new_tasks": True,
            "sampling": SAMPLING,
            "actual_output_error": None,
            "human_visual_acceptance": False,
            "final_sink_physical_delivery": False,
            "scope": "native compiled schedules and saved-record audits; ideal external terminal sink; not decoded logical-error or hardware execution evidence",
            "gate_status": "ready" if clean else "preacceptance_only_dirty_source",
        }
        write_json(output / filename, envelope)
    report = {
        "passed": clean,
        "diagnostic_checks_passed": True,
        "source_identity": version,
        "output": str(output),
        "tasks": len(plan["tasks"]),
        "resume_dispatched_no_new_tasks": True,
    }
    write_json(output / "acceptance-summary.json", report)
    return report


def main() -> None:
    """Run fixed native acceptance only when explicitly invoked by the caller."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--source-paths", nargs="+")
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Preacceptance only; generated final gates remain passed=false",
    )
    args = parser.parse_args()
    result = run_acceptance(
        args.output,
        configuration=args.config,
        source_paths=args.source_paths,
        allow_dirty=args.allow_dirty,
    )
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
