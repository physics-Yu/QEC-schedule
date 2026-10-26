"""Bounded two-level real-recipe object estimates; no physical compilation."""

import argparse
import json
import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from typing import Any

from modules.codes.rotated_surface.fast_factory import factory_recipe
from modules.codes.rotated_surface.object_delivery import (
    DeliveryObjectProfile,
    factory_supply_layout,
)
from modules.codes.rotated_surface.object_factory import (
    FactoryObjectBackend,
    FactoryObjectCatalog,
)
from modules.codes.rotated_surface_d3.protocols.factory_experiment import (
    FactoryExperimentModel,
)
from modules.logical_compiler.src.estimation.kernel import ProfileExecutionKernel
from modules.logical_compiler.src.estimation.metrics import interval_union_us
from modules.logical_compiler.src.protocols.array_ledger import build_array_ledger
from modules.logical_compiler.src.protocols.cooperative import CooperativeFactoryRuntime
from modules.logical_compiler.src.protocols.factory import FactoryLimits
from modules.logical_compiler.src.protocols.factory_process import FactoryProcess
from modules.logical_compiler.src.protocols.factory_strategy import (
    resolve_factory_strategy,
)
from modules.logical_compiler.src.protocols.object_supply import ObjectFactorySupply
from modules.logical_compiler.src.protocols.production import (
    IdealExternalSink,
    ProductionPolicy,
)

from .object_cases import (
    _record_error,
    _sources,
    _write,
    execute_worker,
    forbid_atom_work,
)


class Level2RunError(RuntimeError):
    """A stopped estimate retaining the original cause and committed prefix."""

    def __init__(self, cause: Exception, diagnostics: dict[str, Any]) -> None:
        super().__init__(str(cause))
        self.cause_type = type(cause).__name__
        self.diagnostics = diagnostics


def run_level2(
    catalog: FactoryObjectCatalog,
    *,
    seed: int,
    rounds: int = 1,
    producer_round_budget: int = 32,
    strategy: str = "asynchronous",
    level1_factories: int = 1,
    placement: str = "vertical",
    columns: int | None = None,
    level2_position: str = "below_left",
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    """Estimate N1 producers supplying one same-distance L2 with B=1.

    ``strategy`` controls L1 only; L2 has its own independent asynchronous cohort.
    Distance comes from the recorded catalog (3/5/7/9/11), not a physical build.
    ``placement``/``columns`` configure L1; L2 is below its array. Mixed distances
    require a different delivery capability and are not accepted here.
    The budget is fixed before sampling. Unsupported configuration or
    any incomplete recipe raises; failures preserve current receipts/ownership.
    """
    started = perf_counter()
    distance = catalog.distance
    if type(seed) is not int:
        raise ValueError("INTEGER_SEED_REQUIRED")
    policy = resolve_factory_strategy(strategy)
    policies = (
        ProductionPolicy(producer_round_budget, completion_basis="production_rounds"),
        ProductionPolicy(rounds, completion_basis="production_rounds"),
    )
    layout = factory_supply_layout(
        catalog,
        producers=level1_factories,
        placement=placement,
        columns=columns,
        level2_position=level2_position,
    )
    budget = layout.budget
    parking = (budget["parking"]["origin_um"][0], budget["parking"]["origin_um"][1])
    x0, y0, x1, y1 = budget["storage_bounds_um"]
    area = (x1 - x0) * (y1 - y0)
    block_area = budget["parking"]["width_um"] * budget["parking"]["height_um"]
    profile = DeliveryObjectProfile(catalog, layout)
    execution = ProfileExecutionKernel(profile, layout)
    l1_model = FactoryExperimentModel("theory", 0.01)
    l1_quality = l1_model.output_quality(l1_model.final_theory_event())
    l2_model = FactoryExperimentModel(
        "theory", l1_quality["consumption_parameters"]["input_z_error"]
    )
    models = (l1_model, l2_model)
    # Prepare the two declared theory ports once, before any production event.
    model_records = [model.to_dict() for model in models]
    supply = ObjectFactorySupply(capacity=1, parking=parking)
    processes = tuple(
        FactoryProcess(
            f.factory_id,
            code=catalog.code_id,
            recipe=factory_recipe(distance),
            backend=FactoryObjectBackend(
                profile, execution, models[int(i == level1_factories)]
            ),
            role_bindings={r: p.block_id for r, p in f.bindings.items()},
            distance=distance,
            limits=FactoryLimits(
                raw_attempts=32, batches=16, max_component_calls=10000
            ),
            reference_parameters=models[int(i == level1_factories)].parameters(
                catalog.noise_params
            ),
            cohort_id="L1/" + policy.cohort_id(f.factory_id)
            if i < level1_factories
            else "L2/independent",
            production_policy=policies[int(i == level1_factories)],
            output_sink=supply if i < level1_factories else IdealExternalSink(True),
            input_supplier=supply if i == level1_factories else None,
            production_gate=supply.gate if i < level1_factories else None,
            stage_synchronization=i < level1_factories and policy.name == "synchronous",
        )
        for i, f in enumerate(layout.factories)
    )
    supply.producers = list(processes[:level1_factories])
    supply.consumers = [processes[-1]]
    runtime = CooperativeFactoryRuntime(
        execution=execution,
        case_id="surface-object-level2-v1",
        seed=seed,
        scheduler=policy.make_scheduler(),
        processes=processes,
    )
    ids = {k: id(v) for k, v in catalog.entries.items()}
    counters_before = (
        catalog.lookups,
        catalog.bound_cost_hits,
        catalog.bound_cost_misses,
    )
    try:
        case = runtime.run(timeout_seconds=timeout_seconds).to_dict()
    except (RuntimeError, TimeoutError, ValueError, TypeError) as error:
        diagnostics = {
            "supply": supply.snapshot(),
            "positions": profile.moves,
            "resources": runtime.ledger.snapshot(),
            "last_model_time_us": execution.clock_us,
            "last_completed_call": execution.calls[-1] if execution.calls else None,
        }
        raise Level2RunError(error, diagnostics) from error
    if case["status"] != "complete":
        raise ValueError(f"INCOMPLETE_TWO_LEVEL_CASE: {case['status']}")
    if ids != {k: id(v) for k, v in catalog.entries.items()}:
        raise ValueError("COMPONENT_IDENTITY_CHANGED")
    counts = Counter(c["component_id"] for c in case["calls"])
    l2 = case["factories"]["L2-factory0"]
    l1 = [case["factories"][p.factory_id] for p in supply.producers]
    tokens = {t["token_id"]: t for t in case["resources"]["tokens"]}
    delivered = supply.deliveries
    if (
        len(delivered) != rounds * 15
        or len({d["token_id"] for d in delivered}) != len(delivered)
        or any(tokens[d["token_id"]]["status"] != "consumed" for d in delivered)
        or sum(d["ownership"] == "adopt" for d in delivered) != rounds * 4
        or counts["block_delivery"] != 3 * len(delivered)
        or any(c["component_id"].startswith("raw_t") for c in l2["calls"])
        or sum(c["component_id"] == "transversal_cnot" for c in l2["calls"])
        != 59 * rounds
    ):
        raise ValueError("LEVEL2_RECIPE_OR_IDENTITY_INVARIANT_FAILED")
    for row in l2["production_rounds"]:
        row["input_lineage"] = [
            d["token_id"] for d in delivered if d["round"] == row["round"]
        ]
    outputs = len(l2["production_cycles"])
    line_ledger = build_array_ledger(case)
    duration = case["duration_us"]
    raw_events = [
        e
        for e in case["events"]
        if e["occurrence"]["port_id"] == catalog.raw_port.port_id
    ]
    delivery_time = sum(m["end_us"] - m["start_us"] for m in profile.moves)
    busy: dict[str, list[tuple[float, float]]] = {
        block: [] for block in execution.carriers
    }
    for call in case["execution"]["calls"]:
        for block in call["participant_blocks"]:
            busy[block].append((call["start_us"], call["action_end_us"]))
    idle_block_us = sum(
        duration - interval_union_us(intervals) for intervals in busy.values()
    )
    summary = {
        "distance": distance,
        "level1_distance": distance,
        "level2_distance": distance,
        "factories": level1_factories + 1,
        "level1_factories": level1_factories,
        "level2_factories": 1,
        "buffer_capacity": 1,
        "seed": seed,
        "strategy": policy.to_dict(),
        "level1_strategy": policy.to_dict(),
        "level2_strategy": resolve_factory_strategy("asynchronous").to_dict(),
        "level1_placement": budget["level1_placement"],
        "level2_position": level2_position,
        "storage_width_um": x1 - x0,
        "storage_depth_um": y1 - y0,
        "placement_fingerprint": budget["placement_fingerprint"],
        "cycles_per_factory": rounds,
        "production_basis": "production_rounds",
        "accepted_outputs": outputs,
        "all_level_outputs": sum(
            len(p["production_cycles"]) for p in case["factories"].values()
        ),
        "level1_rounds": sum(len(p["production_rounds"]) for p in l1),
        "level1_rounds_by_factory": {
            p["factory_id"]: len(p["production_rounds"]) for p in l1
        },
        "level1_outputs": sum(len(p["production_cycles"]) for p in l1),
        "level1_handoffs": len(delivered),
        "retained_surplus": sum(d.retained for d in supply.dispositions.values()),
        "level2_rounds": len(l2["production_rounds"]),
        "inputs_delivered": len(delivered),
        "raw_attempts": len(raw_events),
        "raw_rejections": sum(not e["values"]["accepted"] for e in raw_events),
        "raw_acceptance_parameter": catalog.raw_probability,
        "schedule_changes_raw_parameter": False,
        "factory_rejections": sum(
            not r["accepted"]
            for p in case["factories"].values()
            for r in p["production_rounds"]
        ),
        "startup_latency_us": min(
            (c["delivery"]["deliverable_at_us"] for c in l2["production_cycles"]),
            default=None,
        ),
        "makespan_us": duration,
        "drain_completion_us": duration,
        "level2_completion_us": l2["completed_at_us"],
        "drain_tail_us": duration - l2["completed_at_us"],
        "level2_supply_wait_us": line_ledger["lines"]["L2-factory0"]["waiting_us"].get(
            "waiting_supply", 0.0
        ),
        "finite_batch_rate_per_second": outputs * 1e6 / duration,
        "steady_state_throughput": None,
        "allocated_atoms": budget["atom_count_estimate"],
        "storage_footprint_um2": area,
        "sum_block_footprint_um2": 6 * (level1_factories + 1) * block_area,
        "parking_footprint_um2": block_area,
        "readout_area_um2": None,
        "atom_us_per_accepted_output": budget["atom_count_estimate"]
        * duration
        / outputs
        if outputs
        else None,
        "storage_area_us_per_accepted_output": area * duration / outputs
        if outputs
        else None,
        "delivery_time_us": delivery_time,
        "delivery_transfer_us": len(delivered) * 60,
        "delivery_movement_us": delivery_time - len(delivered) * 60,
        "delivery_cost_model": "three Euclidean translations; each Load=10us, Move=distance*recorded_speed, Store=10us",
        "experiment_model": {
            "L1": model_records[0],
            "L2": model_records[1],
            "independent_inputs_assumed": True,
        },
        "actual_output_LER": None,
        "physical_validation": "not_run",
        "growth_rounds_per_accepted_input": catalog.protocol["growth_rounds"],
        "counts": dict(counts),
        "accounting": case["execution"]["accounting"],
        "exposure": {
            "idle_carrier_us": idle_block_us,
            "idle_allocated_atom_us": idle_block_us
            * budget["atom_count_estimate"]
            / len(busy),
            "basis": "allocated carriers outside component envelopes; not site-resolved active-state noise",
            "operation_counts": dict(
                case["execution"]["accounting"]["primitive_counts"]
            ),
            "noise_parameters": catalog.noise_params,
            "decoded_LER": None,
            "waiting_or_transport_changes_probabilities": False,
        },
        "factory_wait_us": {
            k: v["waiting_us"] for k, v in line_ledger["lines"].items()
        },
        "protocol": {
            "raw_attempt_budget": 32,
            "batch_budget": 16,
            "component_call_budget_per_factory": 10000,
            "wave_timeout_seconds": 5,
            "case_timeout_seconds": timeout_seconds,
            "producer_round_budget": producer_round_budget,
            "single_aod": True,
            "input_z_error": 0.01,
            "parking_origin_um": list(parking),
        },
        "software_wall_seconds": perf_counter() - started,
        "component_reuse": {
            "loaded_factory_objects": len(ids),
            "identities_unchanged": True,
            "lookups": catalog.lookups - counters_before[0],
            "bound_cost_hits": catalog.bound_cost_hits - counters_before[1],
            "bound_cost_misses": catalog.bound_cost_misses - counters_before[2],
            "delivery_numeric_variants": len(profile.move_costs),
            "delivery_lookups": profile.move_lookups,
            "catalog_sha256": catalog.fingerprint,
        },
    }
    return {
        "summary": summary,
        "case": case,
        "supply": supply.snapshot(),
        "moves": profile.moves,
        "layout": {
            "budget": budget,
            "patches": [asdict(p) for f in layout.factories for p in f.patches],
            "final_positions": [asdict(p) for p in profile._patches.values()],
        },
    }


def main() -> int:
    """Run one explicitly configured case, stopping with diagnostics on failure."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    if (
        config["schema"] != "nadit.msd.level2_local/1"
        or config.get("physical_compilation") is not False
        or type(config["level2_factories"]) is not int
        or config["level2_factories"] != 1
        or type(config["buffer_capacity"]) is not int
        or config["buffer_capacity"] != 1
        or config.get("level2_distance", config["distance"]) != config["distance"]
    ):
        raise ValueError("LEVEL2_REQUIRES_ONE_CONSUMER_B1_AND_MATCHING_DISTANCES")
    if not args.worker:
        args.output.mkdir(parents=True, exist_ok=False)
        code = execute_worker(
            [
                sys.executable,
                "-m",
                "modules.logical_compiler.examples.factory_level2",
                "--config",
                str(args.config.resolve()),
                "--output",
                str(args.output.resolve()),
                "--worker",
            ],
            args.output.resolve(),
            config["worker_timeout_seconds"],
        )
        print(
            json.dumps(
                {
                    "status": "complete" if code == 0 else "error",
                    "exit_code": code,
                    "report": str(
                        args.output
                        / ("complete-schedule.html" if code == 0 else "error.json")
                    ),
                }
            )
        )
        return code
    _write(args.output / "configuration.json", config)
    sources = _sources()
    started = perf_counter()
    try:
        with forbid_atom_work() as guards:
            catalog = FactoryObjectCatalog.load(distance=config["distance"])
            result = run_level2(
                catalog,
                seed=config["seed"],
                rounds=config["level2_rounds"],
                producer_round_budget=config["producer_round_budget"],
                strategy=config["strategy"],
                level1_factories=config["level1_factories"],
                placement=config.get("placement", "vertical"),
                columns=config.get("columns"),
                level2_position=config.get("level2_position", "below_left"),
                timeout_seconds=config["case_timeout_seconds"],
            )
        result["summary"]["forbidden_work"] = guards
        result["source_sha256"] = sources
        result["summary"]["worker_wall_seconds"] = perf_counter() - started
        _write(args.output / "case.json", result)
        from .factory_schedule import render_schedule

        audit = render_schedule(
            args.output / "case.json", args.output / "complete-schedule.html"
        )
        _write(args.output / "render-audit.json", audit)
        _write(
            args.output / "summary.json", {"status": "complete", **result["summary"]}
        )
        print(json.dumps(result["summary"], indent=2))
        return 0
    except (RuntimeError, TimeoutError, ValueError, TypeError) as error:
        _record_error(
            args.output,
            {
                "status": "error",
                "reason": str(error),
                "code": getattr(error, "cause_type", type(error).__name__),
                "wall_seconds": perf_counter() - started,
                "diagnostics": getattr(error, "diagnostics", {}),
            },
        )
        raise


if __name__ == "__main__":
    raise SystemExit(main())
