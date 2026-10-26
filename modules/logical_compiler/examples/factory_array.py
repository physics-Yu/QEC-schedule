"""Compile synchronized factory lines into one shared-AOD resource ledger."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nadit_physical_compiler.device import Position
from nadit_physical_compiler.visualization.export import write_html

from modules.codes.rotated_surface_d3.protocols.factory_array import (
    FactoryArrayConfig,
    make_factory_array,
)
from modules.codes.rotated_surface_d3.protocols.factory_experiment import (
    ExperimentMode,
    FactoryExperimentModel,
)
from modules.codes.rotated_surface_d3.protocols.parallel_backend import (
    SurfaceParallelCostBackend,
)
from modules.logical_compiler.examples.array_backend import ArrayCostBackend
from modules.logical_compiler.examples.factory_noise import _json_bytes, _parameters
from modules.logical_compiler.examples.factory_proxy import _source_hashes
from modules.logical_compiler.src.protocols.array_ledger import build_array_ledger
from modules.logical_compiler.src.protocols.cooperative import (
    CooperativeFactoryCase,
    CooperativeFactoryRuntime,
)
from modules.logical_compiler.src.protocols.factory import FactoryLimits
from modules.logical_compiler.src.protocols.factory_process import FactoryProcess
from modules.logical_compiler.src.protocols.physical import PhysicalContext
from modules.logical_compiler.src.scheduling import ComponentScheduler

CASE_ID = "factory-array-theory-v1"
DEFAULT_CONFIG = (
    Path(__file__).resolve().parents[1] / "configs/factory_array_reference.json"
)
EXPECTED_TERMINALS = {"complete", "distillation_rejected", "input_supply_exhausted"}


def load_configuration(
    document: Mapping[str, Any],
) -> tuple[FactoryArrayConfig, FactoryLimits, int | None]:
    """Require an explicit code entry, finite limits and cohort synchronization."""
    if (
        set(document)
        != {"schema", "code", "world", "limits", "max_parallel", "coordination_policy"}
        or document["schema"] != "nadit.factory_array_configuration/1"
        or document["code"] != "rotated_surface_d3"
        or document["coordination_policy"] != "cohort_stage_barriers"
        or not isinstance(document["world"], dict)
        or not isinstance(document["limits"], dict)
    ):
        raise ValueError("INVALID_FACTORY_ARRAY_CONFIGURATION")
    world = dict(document["world"])
    if "origin" in world:
        world["origin"] = Position(**world["origin"])
    maximum = document["max_parallel"]
    ComponentScheduler(max_parallel=maximum)
    return FactoryArrayConfig(**world), FactoryLimits(**document["limits"]), maximum


@dataclass(frozen=True)
class ArrayRun:
    """One seeded production experiment; rejected production remains valid evidence."""

    case: CooperativeFactoryCase
    ledger: dict[str, Any]
    manifest: dict[str, Any]
    output: Path


def _export(
    case: CooperativeFactoryCase,
    ledger: dict[str, Any],
    output: Path,
    budget: dict[str, Any],
    reports: dict[str, Any],
) -> None:
    from modules.logical_compiler.examples.array_report import write_array_report

    (output / "case.json").write_text(case.to_json(), encoding="utf-8")
    (output / "array-ledger.json").write_bytes(_json_bytes(ledger))
    cost_file = (
        "physical-costs.json"
        if ledger["experiment_model"]["mode"] == "theory"
        else "proxy-costs.json"
    )
    (output / cost_file).write_bytes(_json_bytes(reports))
    (output / "resource-events.jsonl").write_bytes(
        b"".join(_json_bytes(item) for item in ledger["resources"]["audit"])
    )
    fields = (
        "factory_id",
        "status",
        "production_success",
        "factory_final_accepted",
        "raw_attempts",
        "raw_accepted_events",
        "raw_rejections",
        "s_calls",
        "output_token_id",
        "output_status",
        "completed_at_us",
    )
    with (output / "lines.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(ledger["lines"].values())
    if case.physical is not None:
        bundle = case.physical
        (output / "atom-program.json").write_bytes(
            _json_bytes(bundle.to_dict()["program"])
        )
        (output / "atom-program.txt").write_text(
            bundle.program.to_text(), encoding="utf-8"
        )
        trace = bundle.build_trace(
            title=f"Synchronized factories / 1 AOD / seed {ledger['seed']}",
            description=(
                "One physical world and scheduler. Ready resources wait for cohort peers. "
                f"Acceptance model: {ledger['experiment_model']['mode']}. "
                "Seeded events are separate from unobserved physical measurements."
            ),
        )
        trace["component_schedule"] = ledger["component_schedule"]
        (output / "trace.json").write_bytes(_json_bytes(trace))
        write_html(
            (trace,),
            output / "atom-replay.html",
            title="NADiT synchronized factory array",
        )
    write_array_report(ledger, output, budget=budget)


def run_array(
    seed: int,
    noise_params: Mapping[str, Any],
    output: str | Path,
    *,
    configuration: Mapping[str, Any],
    sampling_role: str = "individual_seed",
    acceptance_model: ExperimentMode = "theory",
    input_z_error: float | None = None,
) -> ArrayRun:
    """Run real components and independent line events through one coordinator.

    All successful output resources remain offered. No consumer, inventory
    prefetch, periodic waiting SE or replacement after physical loss is inferred.
    Sampling role labels a selected branch witness separately from statistics.
    """
    if type(seed) is not int or sampling_role not in ("individual_seed", "witness"):
        raise ValueError("INVALID_ARRAY_EXPERIMENT_SEED_OR_ROLE")
    model = FactoryExperimentModel(mode=acceptance_model, input_z_error=input_z_error)
    config, limits, maximum = load_configuration(configuration)
    params = _parameters(noise_params)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    source_start = _source_hashes()
    world = make_factory_array(config)
    physical = PhysicalContext(world.device, world.world_state, world.bindings.values())
    code_backend = SurfaceParallelCostBackend(world.device)
    adapters = {
        placement.factory_id: ArrayCostBackend(
            code_backend,
            placement.bindings["W1"].block_id,
            physical,
            factory_id=placement.factory_id,
            atom_ids=placement.atom_ids,
            experiment_model=model,
        )
        for placement in world.factories
    }
    runtime = CooperativeFactoryRuntime(
        physical,
        case_id=model.case_id(),
        seed=seed,
        scheduler=ComponentScheduler(max_parallel=maximum),
        processes=tuple(
            FactoryProcess(
                placement.factory_id,
                code="rotated_surface_d3",
                recipe=model.recipe(),
                backend=adapters[placement.factory_id],
                role_bindings={
                    role: binding.block_id
                    for role, binding in placement.bindings.items()
                },
                distance=3,
                limits=limits,
                reference_parameters=model.parameters(params),
            )
            for placement in world.factories
        ),
    )
    case = runtime.run()
    document = case.to_dict()
    ledger = build_array_ledger(document)
    ledger["device_budget"] = world.budget
    ledger["experiment_model"] = model.to_dict()
    reports = {
        identity: {
            "raw_horizons": list(adapter.raw_horizons.values()),
            "factory": adapter.factory_reports,
        }
        for identity, adapter in adapters.items()
    }
    _export(case, ledger, output, world.budget, reports)
    source_end = _source_hashes()
    manifest = {
        "schema": "nadit.factory_array_manifest/1",
        "case_id": model.case_id(),
        "seed": seed,
        "sampling_role": sampling_role,
        "included_in_unbiased_statistics": False,
        "configuration": dict(configuration),
        "noise_parameters": params,
        "experiment_model": model.to_dict(),
        "device_budget": world.budget,
        "status": case.status,
        "execution_completed": all(
            line["status"] in EXPECTED_TERMINALS for line in ledger["lines"].values()
        )
        and ledger["physical_validation_ok"],
        "lines": {
            identity: {
                key: value for key, value in line.items() if key != "state_intervals"
            }
            for identity, line in ledger["lines"].items()
        },
        "source_start": source_start,
        "source_end": source_end,
        "source_stable": source_start == source_end,
        "files_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(output.iterdir())
            if path.is_file()
        },
        "logical_success": None,
        "physical_execution": False,
        "scope": (
            "actual shared timeline; seeded theoretical joint MX checks; "
            "independent full-line physical no-fault diagnostics; outputs held"
            if model.mode == "theory"
            else "actual shared timeline; legacy per-line non-raw cost proxy; outputs held"
        ),
    }
    (output / "manifest.json").write_bytes(_json_bytes(manifest))
    return ArrayRun(case, ledger, manifest, output)


def main(argv: list[str] | None = None) -> int:
    """Compile one finite synchronized production experiment and export its ledger."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--noise-params", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--acceptance-model",
        choices=("theory", "physical_no_fault_proxy"),
        default="theory",
    )
    parser.add_argument(
        "--input-z-error",
        type=float,
        help="Required in theory mode: iid Z error of accepted canonical raw A inputs.",
    )
    parser.add_argument(
        "--sampling-role",
        choices=("individual_seed", "witness"),
        default="individual_seed",
    )
    args = parser.parse_args(argv)
    try:
        FactoryExperimentModel(
            mode=args.acceptance_model, input_z_error=args.input_z_error
        )
    except ValueError as error:
        parser.error(str(error))
    result = run_array(
        args.seed,
        json.loads(args.noise_params.read_text("utf-8")),
        args.output,
        configuration=json.loads(args.config.read_text("utf-8")),
        sampling_role=args.sampling_role,
        acceptance_model=args.acceptance_model,
        input_z_error=args.input_z_error,
    )
    print(
        json.dumps(
            {
                "status": result.case.status,
                "counts": result.ledger["counts"],
                "execution_completed": result.manifest["execution_completed"],
            }
        ),
        flush=True,
    )
    return 0 if result.manifest["execution_completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
