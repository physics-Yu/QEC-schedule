"""Factory estimates using recorded distance costs and precomputed probabilities."""

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict
from html import escape
from pathlib import Path
from time import perf_counter
from typing import Any

from modules.codes.rotated_surface.definition import definition
from modules.codes.rotated_surface.fast_factory import factory_recipe
from modules.codes.rotated_surface.object_factory import (
    FactoryObjectBackend,
    FactoryObjectCatalog,
    FactoryObjectProfile,
)
from modules.codes.rotated_surface_d3.protocols.factory_experiment import (
    FactoryExperimentModel,
)
from modules.logical_compiler.src.estimation.kernel import ProfileExecutionKernel
from modules.logical_compiler.src.protocols.array_ledger import build_array_ledger
from modules.logical_compiler.src.protocols.cooperative import CooperativeFactoryRuntime
from modules.logical_compiler.src.protocols.factory import FactoryLimits
from modules.logical_compiler.src.protocols.factory_process import FactoryProcess
from modules.logical_compiler.src.protocols.factory_strategy import (
    resolve_factory_strategy,
)
from modules.logical_compiler.src.protocols.production import (
    IdealExternalSink,
    ProductionPolicy,
)

from .object_cases import (
    _read_progress,
    _record_error,
    _sources,
    _write,
    execute_worker,
    forbid_atom_work,
)


def run_factory_objects(
    catalog: FactoryObjectCatalog,
    *,
    factories: int,
    seed: int,
    distance: int | None = None,
    strategy: str = "asynchronous",
    cycles: int = 2,
    production_basis: str | None = None,
    placement: str = "vertical",
    columns: int | None = None,
    input_z_error: float = 0.01,
    raw_attempts: int = 32,
    batches: int = 16,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    """Run the real recipe with explicit accepted-output or attempted-round limits.

    ``cycles`` counts ``production_basis`` units. By default synchronous/v2 uses
    production rounds, while asynchronous retains its accepted-output default.
    Use production_rounds explicitly for paired policies. A rejected round has
    no delivery; zero accepted outputs produce null per-output/startup metrics.
    Invalid coverage/policies and exhausted budgets raise rather than fall back.
    ``placement`` selects vertical/horizontal/grid whole-factory translation;
    only grid accepts explicit ``columns``. Component internals remain cached.
    """
    started = perf_counter()
    distance = catalog.distance if distance is None else distance
    definition(distance)
    policy = resolve_factory_strategy(strategy)
    if production_basis is None:
        production_basis = (
            "production_rounds" if policy.name == "synchronous" else "accepted_outputs"
        )
    production = ProductionPolicy(cycles, completion_basis=production_basis)
    layout = catalog.layout(
        factories, distance=distance, placement=placement, columns=columns
    )
    profile = FactoryObjectProfile(catalog, layout)
    execution = ProfileExecutionKernel(profile, layout)
    model = FactoryExperimentModel("theory", input_z_error)
    processes = tuple(
        FactoryProcess(
            f.factory_id,
            code=f"rotated_surface_d{distance}",
            recipe=factory_recipe(distance),
            backend=FactoryObjectBackend(profile, execution, model),
            role_bindings={role: patch.block_id for role, patch in f.bindings.items()},
            distance=distance,
            limits=FactoryLimits(
                raw_attempts=raw_attempts, batches=batches, max_component_calls=10000
            ),
            reference_parameters=model.parameters(catalog.noise_params),
            cohort_id=policy.cohort_id(f.factory_id),
            production_policy=production,
            output_sink=IdealExternalSink(True),
            stage_synchronization=policy.name == "synchronous",
        )
        for f in layout.factories
    )
    case = (
        CooperativeFactoryRuntime(
            execution=execution,
            case_id="surface-object-factory-v1",
            seed=seed,
            scheduler=policy.make_scheduler(),
            processes=processes,
        )
        .run(timeout_seconds=timeout_seconds)
        .to_dict()
    )
    if case["status"] != "complete":
        failures = {
            k: p["failure"] for k, p in case["factories"].items() if p["failure"]
        }
        raise RuntimeError(f"FACTORY_OBJECT_RUN_FAILED: {failures}")
    counts = Counter(call["component_id"] for call in case["calls"])
    batch_count = sum(
        m["kind"] == "batch_started"
        for p in case["factories"].values()
        for m in p["milestones"]
    )
    raw_events = [
        e
        for e in case["events"]
        if e["occurrence"]["port_id"] == catalog.raw_port.port_id
    ]
    raw_rejected = sum(e["values"]["accepted"] is False for e in raw_events)
    outputs = [
        cycle["delivery"]
        for p in case["factories"].values()
        for cycle in p["production_cycles"]
    ]
    duration = case["duration_us"]
    if (
        batch_count != factories * cycles
        if production_basis == "production_rounds"
        else len(outputs) != factories * cycles
    ) or counts["transversal_cnot"] != 59 * batch_count:
        raise ValueError("INCOMPLETE_FACTORY_RECIPE_OR_PRODUCTION_COUNT")
    area = layout.budget["storage_bounds_um"]
    storage_area = (area[2] - area[0]) * (area[3] - area[1])
    bounds = layout.budget["code_geometry"]["relative_bounds"]
    block_area = (bounds["x_max"] - bounds["x_min"]) * (
        bounds["y_max"] - bounds["y_min"]
    )
    growth_rounds = catalog.protocol["growth_rounds"]
    accepted_raw = counts["raw_t_postselection/canonicalize"]
    syndrome_rounds = sum(
        count
        * catalog.entries[component].claim.get(
            "syndrome_rounds",
            3
            if component == "raw_t_postselection"
            else int(component in ("initialize_plus", "logical_s", "se_round")),
        )
        for component, count in counts.items()
    )
    summary = {
        "distance": distance,
        "strategy": policy.to_dict(),
        "factories": factories,
        "seed": seed,
        "placement": dict(layout.budget["factory_placement"]),
        "placement_fingerprint": layout.budget["placement_fingerprint"],
        "cycles_per_factory": cycles,
        "production_basis": production_basis,
        "rounds_per_factory": cycles
        if production_basis == "production_rounds"
        else None,
        "accepted_outputs_by_factory": {
            k: len(p["production_cycles"]) for k, p in case["factories"].items()
        },
        "accepted_outputs": len(outputs),
        "batches": batch_count,
        "factory_rejections": batch_count - len(outputs),
        "raw_attempts": len(raw_events),
        "raw_rejections": raw_rejected,
        "raw_acceptance_observed": (len(raw_events) - raw_rejected) / len(raw_events),
        "raw_acceptance_parameter": catalog.raw_probability,
        "raw_probability_policy": "precomputed_component_reference",
        "raw_probability_reestimated": False,
        "schedule_changes_raw_parameter": False,
        "counts": dict(counts),
        "syndrome_rounds_in_components": syndrome_rounds,
        "injection_syndrome_rounds": 3 * counts["raw_t_postselection"],
        "growth_syndrome_rounds": growth_rounds * accepted_raw,
        "growth_rounds_per_accepted_input": growth_rounds,
        "preparation_protocol": dict(catalog.protocol),
        "startup_latency_us": min(
            (o["deliverable_at_us"] for o in outputs), default=None
        ),
        "makespan_us": duration,
        "finite_batch_rate_per_second": 1e6 * len(outputs) / duration,
        "steady_state_throughput": None,
        "actual_output_LER": None,
        "allocated_atoms": layout.budget["atom_count_estimate"],
        "storage_footprint_um2": storage_area,
        "storage_width_um": area[2] - area[0],
        "storage_depth_um": area[3] - area[1],
        "sum_block_footprint_um2": 6 * factories * block_area,
        "atom_us_per_accepted_output": layout.budget["atom_count_estimate"]
        * duration
        / len(outputs)
        if outputs
        else None,
        "storage_area_us_per_accepted_output": storage_area * duration / len(outputs)
        if outputs
        else None,
        "readout_area_um2": None,
        "footprint_scope": "resident storage blocks; no assigned readout footprint "
        "in source cost records",
        "physical_validation": "not_run",
        "experiment_model": model.to_dict(),
        "logical_probability_reference": "existing ideal-Clifford and iid accepted-"
        "input Z-error model; original port names retained; not decoded LER",
        "correction_cost": "existing one-Pauli-layer bound; no sampled decoder frame",
        "accepted_raw_cost_scope": "ordinary growth/SE plus correction after acceptance"
        if growth_rounds
        else "correction after acceptance; no growth at d3",
        "accounting": case["execution"]["accounting"],
        "timing_breakdown": _timing_breakdown(case, catalog),
        "software_wall_seconds": perf_counter() - started,
    }
    return {
        "summary": summary,
        "case": case,
        "layout": {
            "budget": layout.budget,
            "patches": [asdict(p) for f in layout.factories for p in f.patches],
        },
    }


def _timing_breakdown(
    case: dict[str, Any], catalog: FactoryObjectCatalog
) -> dict[str, Any]:
    """Separate member work and waits; their sum is not the global makespan."""
    calls = {c["invocation_id"]: c for c in case["execution"]["calls"]}
    motions = {
        (name, phase.name): row[4]
        for name, entry in catalog.entries.items()
        for phase, row in zip(
            entry.stages, catalog.document["entries"][name]["phases"], strict=True
        )
    }
    totals: Counter[str] = Counter()
    commands: Counter[str] = Counter()
    wave_counts: Counter[str] = Counter()
    command_counts: Counter[str] = Counter()
    shared_counts: Counter[str] = Counter()
    for wave in case["execution"]["waves"]:
        component = calls[wave["invocations"][0]]["component_id"]
        wave_counts[component] += 1
        for stage in wave["stage_schedule"]:
            duration = stage["end_us"] - stage["start_us"]
            command_counts[component] += 1
            shared_counts[component] += int(len(stage["members"]) > 1)
            commands["operation/" + stage["category"]] += duration
            totals["operation/" + stage["category"]] += (
                stage["end_us"] - stage["start_us"]
            ) * len(stage["members"])
            if stage["category"] == "movement":
                component = calls[stage["members"][0]]["component_id"]
                key = (
                    "readout_transport"
                    if motions[component, stage["phase"]] == "readout"
                    else "gate_transport"
                )
                totals[key] += (stage["end_us"] - stage["start_us"]) * len(
                    stage["members"]
                )
                commands[key] += duration
        for wait in wave["stage_waits"]:
            key = (
                "shared_aod_wait"
                if "aod:transport" in wait["resources"]
                else "shared_control_wait"
            )
            totals[key] += wait["end_us"] - wait["start_us"]
        totals["wave_tail_synchronization"] += sum(
            wave["end_us"] - calls[i]["action_end_us"] for i in wave["invocations"]
        )
    ledger = build_array_ledger(case)
    return {
        "member_microseconds": dict(totals),
        "command_microseconds": dict(commands),
        "command_counts_by_component": {
            component: {
                "waves": wave_counts[component],
                "stages": command_counts[component],
                "shared_stages": shared_counts[component],
                "shared_stage_fraction": shared_counts[component]
                / command_counts[component],
            }
            for component in command_counts
        },
        "factory_frontier_wait_us": {
            k: v["waiting_us"] for k, v in ledger["lines"].items()
        },
        "protocol_barrier_wait_us_by_factory": {
            k: v["waiting_us"].get("waiting_peers", 0.0)
            for k, v in ledger["lines"].items()
        },
        "member_work_and_wait_sum_is_global_elapsed": False,
    }


def _report(
    path: Path, rows: list[dict[str, Any]], representative: dict[str, Any]
) -> None:
    distance = representative["summary"]["distance"]
    headings = (
        "N",
        "seed",
        "outputs",
        "raw attempts",
        "raw rejects",
        "factory rejects",
        "startup us",
        "makespan us",
    )
    table = "<tr>" + "".join(f"<th>{h}</th>" for h in headings) + "</tr>"
    for row in rows:
        values = [
            row[k]
            for k in (
                "factories",
                "seed",
                "accepted_outputs",
                "raw_attempts",
                "raw_rejections",
                "factory_rejections",
                "startup_latency_us",
                "makespan_us",
            )
        ]
        table += (
            "<tr>" + "".join(f"<td>{escape(str(v))}</td>" for v in values) + "</tr>"
        )
    schedule = (
        "<tr><th>Component</th><th>Invocation</th><th>Start us</th><th>End us</th></tr>"
    )
    for call in representative["case"]["calls"]:
        schedule += (
            "<tr>"
            + "".join(
                f"<td>{escape(str(call[k]))}</td>"
                for k in ("component_id", "invocation_id", "start_us", "end_us")
            )
            + "</tr>"
        )
    phases = ""
    layout_rows = "<tr><th>Block</th><th>x (um)</th><th>y (um)</th></tr>"
    for patch in representative["layout"]["patches"]:
        layout_rows += (
            "<tr>"
            + "".join(
                f"<td>{escape(str(value))}</td>"
                for value in (
                    patch["block_id"],
                    patch["origin"]["x"],
                    patch["origin"]["y"],
                )
            )
            + "</tr>"
        )
    selected = set()
    component_by_id = {
        c["invocation_id"]: c["component_id"] for c in representative["case"]["calls"]
    }
    for wave in representative["case"]["execution"]["waves"]:
        component = component_by_id[wave["invocations"][0]]
        if component in selected:
            continue
        selected.add(component)
        phases += (
            f"<details><summary>{escape(component)}: first wave stages</summary><table>"
        )
        for stage in wave["stage_schedule"]:
            phase_values = (
                stage["phase"],
                wave["start_us"] + stage["start_us"],
                wave["start_us"] + stage["end_us"],
                ", ".join(stage["resources"]),
                ", ".join(stage["members"]),
            )
            phases += (
                "<tr>"
                + "".join(f"<td>{escape(str(v))}</td>" for v in phase_values)
                + "</tr>"
            )
        phases += "</table></details>"
    path.write_text(
        "<!doctype html><meta charset='utf-8'>"
        f"<title>d{distance} factory objects</title>"
        "<style>body{font:14px system-ui;margin:30px}table{border-collapse:collapse}"
        "td,th{border:1px solid #aaa;padding:5px}details{margin:12px 0}</style>"
        f"<h1>Full d{distance} factory resource estimates</h1>"
        "<p>Existing component costs "
        "and precomputed probability backend. No compilation or atom expansion. "
        "Rates are finite-batch observations, not steady state. "
        "Theoretical output quality is not decoded logical error rate.</p><table>"
        + table
        + "</table><h2>Representative whole-factory layout</h2>"
        "<p>Storage/gates below y=0; readout above y=50 um. "
        "Object origins; physical trajectories are not validated.</p><table>"
        + layout_rows
        + "</table><h2>Representative component schedule</h2><table>"
        + schedule
        + "</table><h2>Representative phase schedules</h2>"
        + phases,
        encoding="utf-8",
    )


def run_acceptance(config: dict[str, Any], output: Path) -> dict[str, Any]:
    """Run only the requested small local cases; stop immediately on error/timeout."""
    if config.get("schema") != "nadit.factory_objects_local/1":
        raise ValueError("UNSUPPORTED_LOCAL_FACTORY_CONFIG")
    distance = config["distance"]
    definition(distance)
    policy = resolve_factory_strategy(config.get("strategy", "asynchronous"))
    placement = config.get("placement", {})
    if not isinstance(placement, dict) or set(placement) - {"kind", "columns"}:
        raise ValueError("INVALID_FACTORY_PLACEMENT_CONFIG")
    if config.get("raw_probability_policy") != "precomputed_component_reference":
        raise ValueError("RAW_PROBABILITY_POLICY_MUST_USE_PRECOMPUTED_INPUT")
    for key in ("factory_counts", "seeds"):
        if not config[key] or len(set(config[key])) != len(config[key]):
            raise ValueError(f"DUPLICATE_OR_EMPTY_LOCAL_CASES: {key}")
    if any(type(n) is not int or n < 1 for n in config["factory_counts"]):
        raise ValueError("INVALID_FACTORY_COUNT")
    started = perf_counter()
    source_hashes = _sources()
    with forbid_atom_work() as counters:
        catalog = FactoryObjectCatalog.load(distance=distance)
        # Coverage is a cost-provider property, never a scheduling-policy limit.
        catalog.layout(1, distance=distance)
        identities = {k: id(v) for k, v in catalog.entries.items()}
        rows = []
        representative = None
        for count in config["factory_counts"]:
            for seed in config["seeds"]:
                name = f"d{distance}-n{count}-seed{seed}"
                _write(output / "progress.json", {"stage": name, "state": "running"})
                result = run_factory_objects(
                    catalog,
                    factories=count,
                    seed=seed,
                    distance=distance,
                    strategy=policy.name,
                    cycles=config["cycles_per_factory"],
                    production_basis=config.get("production_basis"),
                    placement=placement.get("kind", "vertical"),
                    columns=placement.get("columns"),
                    input_z_error=config["input_z_error"],
                    raw_attempts=config["raw_attempt_limit"],
                    batches=config["batch_attempt_limit"],
                    timeout_seconds=config["case_timeout_seconds"],
                )
                (output / (name + ".json")).write_text(
                    json.dumps(result, separators=(",", ":"), allow_nan=False) + "\n",
                    encoding="utf-8",
                )
                rows.append(result["summary"])
                if representative is None or (
                    count == 2 and representative["summary"]["factories"] != 2
                ):
                    representative = result
        if identities != {k: id(v) for k, v in catalog.entries.items()}:
            raise ValueError("OBJECT_CATALOG_WAS_REBUILT")
        if any(counters.values()):
            raise ValueError("FORBIDDEN_COMPILATION_OR_ATOM_WORK")
    if _sources() != source_hashes:
        raise ValueError("SOURCES_CHANGED_DURING_ACCEPTANCE")
    if representative is None:
        raise ValueError("EMPTY_FACTORY_ACCEPTANCE")
    summary = {
        "schema": "nadit.factory_objects_result/1",
        "status": "complete",
        "configuration": config,
        "scope": f"complete_first_level_d{distance}_finite_production",
        "strategy": policy.to_dict(),
        "software_work_seconds": perf_counter() - started,
        "cases": rows,
        "model_input_sha256": catalog.fingerprint,
        "input_provenance": catalog.document["source"],
        "raw_model": catalog.raw_port.to_dict()["model"],
        "reuse": {
            "component_templates_loaded": len(catalog.entries),
            "lookups": catalog.lookups,
            "bound_cost_cache_hits": catalog.bound_cost_hits,
            "bound_cost_cache_misses": catalog.bound_cost_misses,
            "template_identities_preserved": True,
            **counters,
        },
        "physical_validation": "not_run",
        "steady_state_throughput": None,
        "actual_output_LER": None,
    }
    _write(output / "source-hashes.json", source_hashes)
    _report(output / "schedule.html", rows, representative)
    summary["total_worker_work_seconds"] = perf_counter() - started
    _write(output / "summary.json", summary)
    _write(output / "progress.json", {"stage": "complete", "state": "complete"})
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    output = args.output.resolve()
    if args.worker:
        try:
            summary = run_acceptance(config, output)
            print(json.dumps({"status": summary["status"], "reuse": summary["reuse"]}))
            return 0
        except Exception as error:
            _record_error(
                output,
                {
                    "status": "error",
                    "code": type(error).__name__,
                    "reason": str(error),
                    "last_progress": _read_progress(output),
                    "partial_output_is_success": False,
                },
            )
            raise
    output.mkdir(parents=True, exist_ok=False)
    code = execute_worker(
        [
            sys.executable,
            "-m",
            "modules.logical_compiler.examples.factory_objects",
            "--config",
            str(args.config.resolve()),
            "--output",
            str(output),
            "--worker",
        ],
        output,
        config["wall_timeout_seconds"],
    )
    print(
        json.dumps(
            {
                "status": "complete" if code == 0 else "error",
                "exit_code": code,
                "report": str(output / ("summary.json" if code == 0 else "error.json")),
            }
        )
    )
    return code


if __name__ == "__main__":
    raise SystemExit(main())
