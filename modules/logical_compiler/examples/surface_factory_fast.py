"""Generic surface factory execution through the existing fast logical kernel."""

import argparse
import json
from pathlib import Path
from time import perf_counter
from typing import Any

from modules.codes.contracts.factory_recipe import FactoryRecipe
from modules.codes.rotated_surface.fast_factory import (
    SurfaceFactoryBackend,
    SurfaceFactoryProfile,
    factory_recipe,
)
from modules.codes.rotated_surface_d3.protocols.factory_experiment import (
    FactoryExperimentModel,
)
from modules.logical_compiler.src.estimation.kernel import ProfileExecutionKernel
from modules.logical_compiler.src.placement import PlacementPlan
from modules.logical_compiler.src.protocols.array_ledger import build_array_ledger
from modules.logical_compiler.src.protocols.cooperative import CooperativeFactoryRuntime
from modules.logical_compiler.src.protocols.factory import FactoryLimits
from modules.logical_compiler.src.protocols.factory_process import FactoryProcess
from modules.logical_compiler.src.protocols.production import (
    OutputSink,
    ProductionPolicy,
)
from modules.logical_compiler.src.scheduling import ComponentScheduler


def run_surface_factory(
    profile: SurfaceFactoryProfile,
    *,
    seed: int,
    input_z_error: float,
    hardware: str = "shared_aod",
    raw_attempts: int = 8,
    batches: int = 1,
    placement_plan: PlacementPlan | None = None,
    production_policy: ProductionPolicy | None = None,
    output_sink: OutputSink | None = None,
    max_component_calls: int | None = None,
    recipe: FactoryRecipe | None = None,
) -> dict[str, Any]:
    """Run complete code-owned recipe with finite retries and one common scheduler.

    Supply rejection uses the position-specific calibrated port. Conditional S,
    final joint checks, token consumption and accepted-only growth are retained.
    An explicit plan must match the calibrated carriers; it cannot relocate costs.
    Continuous production requires an explicit sink; no output is freed implicitly.
    The result is a resource estimate, never a physical or quantum execution.
    """
    started = perf_counter()
    layout = profile.layout(hardware, placement_plan=placement_plan)
    execution = ProfileExecutionKernel(profile, layout)
    model = FactoryExperimentModel("theory", input_z_error)
    recipe = factory_recipe(profile.distance) if recipe is None else recipe
    if recipe.code_id != profile.code_id:
        raise ValueError("FACTORY_RECIPE_PROFILE_CODE_MISMATCH")
    call_budget = (
        10000
        * batches
        * (1 if production_policy is None else production_policy.max_cycles)
        if max_component_calls is None
        else max_component_calls
    )
    processes = tuple(
        FactoryProcess(
            f.factory_id,
            code=profile.code_id,
            recipe=recipe,
            backend=SurfaceFactoryBackend(profile, execution, model),
            role_bindings={r: p.block_id for r, p in f.bindings.items()},
            distance=profile.distance,
            limits=FactoryLimits(
                raw_attempts=raw_attempts,
                batches=batches,
                max_component_calls=call_budget,
            ),
            reference_parameters=model.parameters(profile.noise_params),
            production_policy=production_policy,
            output_sink=output_sink,
        )
        for f in layout.factories
    )
    case = (
        CooperativeFactoryRuntime(
            execution=execution,
            case_id="generic-surface-factory-theory-v1",
            seed=seed,
            scheduler=ComponentScheduler(),
            processes=processes,
        )
        .run()
        .to_dict()
    )
    ledger = build_array_ledger(case)
    counts = ledger["counts"]
    statuses = {row["status"] for row in ledger["lines"].values()}
    if production_policy is None and not statuses <= {
        "complete",
        "distillation_rejected",
        "input_supply_exhausted",
    }:
        raise ValueError(
            f"GENERIC_FACTORY_EXECUTION_FAILED: {case.get('errors', case)}"
        )
    summary = {
        "schema": "nadit.generic_surface_factory_run/1",
        "distance": profile.distance,
        "factory_count": profile.factory_count,
        "seed": seed,
        "status": case["status"],
        "hardware": layout.budget,
        "profile_sha256": profile.profile_sha256,
        "recipe_id": recipe.protocol_id,
        "recipe_version": recipe.version,
        "placement_fingerprint": (
            None
            if layout.placement_plan is None
            else layout.placement_plan.geometry_fingerprint
        ),
        "representation": "logical_estimate",
        "physical_validation_run": False,
        "physical_execution": False,
        "actual_output_error": None,
        "experiment_model": model.to_dict(),
        "raw_attempts": sum(row["raw_attempts"] for row in ledger["lines"].values()),
        "raw_rejections": sum(
            row["raw_rejections"] for row in ledger["lines"].values()
        ),
        "outputs": counts["accepted_outputs"],
        "delivered_outputs": counts["delivered_outputs"],
        "growth_calls": sum(
            c["component_id"] == "raw_t_postselection/canonicalize"
            for c in case["calls"]
        ),
        "makespan_us": case["duration_us"],
        "software_wall_seconds": perf_counter() - started,
        "accounting": case["execution"]["accounting"],
        "lines": {
            name: {k: v for k, v in row.items() if k != "state_intervals"}
            for name, row in ledger["lines"].items()
        },
        "limits": {
            "raw_attempts": raw_attempts,
            "batches": batches,
            "max_component_calls": call_budget,
        },
        "schedule_interpretation": getattr(
            profile,
            "schedule_interpretation",
            "historical conservative whole-component AOD reservations; not parallel-factory acceptance",
        ),
        "canonicalization": "calibrated worst-case one-Pauli-layer envelope; no frame samples or LER inference",
    }
    return {"case": case, "ledger": ledger, "summary": summary}


def main() -> None:
    """Load a frozen profile; run never invokes physical compilation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--input-z-error", type=float, required=True)
    parser.add_argument(
        "--hardware",
        choices=("shared_aod", "independent_aod_control"),
        default="shared_aod",
    )
    args = parser.parse_args()
    document = json.loads(args.profile.read_text(encoding="utf-8"))
    profile: SurfaceFactoryProfile
    if "joint_calibration" in document:
        from modules.codes.rotated_surface.joint_factory_profile import (
            JointSurfaceFactoryProfile,
        )

        profile = JointSurfaceFactoryProfile(document)
    else:
        profile = SurfaceFactoryProfile(document)
    result = run_surface_factory(
        profile,
        seed=args.seed,
        input_z_error=args.input_z_error,
        hardware=args.hardware,
    )
    args.output.mkdir(parents=True, exist_ok=False)
    for name, doc in result.items():
        (args.output / f"{name}.json").write_text(
            json.dumps(doc, indent=2, allow_nan=False), encoding="utf-8"
        )
    print(json.dumps(result["summary"], allow_nan=False))


if __name__ == "__main__":
    main()
