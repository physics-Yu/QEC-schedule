"""Compile finite cost-noise preparation cases without inventing logical quality.

The requested goal is factory output followed by algorithm T consumption. If the
code-owned model cannot certify a consumption input, the actual canonicalized
resource remains offered and the real physical prefix is exported as incomplete.
There is no reference input-Z-error fallback and no synthetic rejection fixture.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import nadit_physical_compiler

from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.contracts.factory_recipe import ResourcePreparation
from modules.codes.rotated_surface_d3.protocols.factory import (
    factory_recipe,
    t_consumption_recipe,
)
from modules.codes.rotated_surface_d3.protocols.factory_backend import (
    SurfaceFactoryBackend,
)
from modules.codes.rotated_surface_d3.protocols.factory_world import (
    FactoryWorld,
    make_factory_world,
)
from modules.logical_compiler.examples.factory_to_t import _export, _ScenarioBackend
from modules.logical_compiler.src.protocols.cost import evaluate_physical_cost
from modules.logical_compiler.src.protocols.experiment_ledger import write_ledger
from modules.logical_compiler.src.protocols.factory import (
    FactoryCase,
    FactoryExecutor,
    FactoryLimits,
)
from modules.logical_compiler.src.protocols.physical import PhysicalContext

CASE_ID = "factory-cost-noise-v1"
DEFAULT_SEEDS = tuple(range(16))


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    ).encode("utf-8")


def _parameters(noise_params: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(noise_params, Mapping):
        raise TypeError("noise_params must be an explicit mapping")
    if any(not isinstance(key, str) for key in noise_params):
        raise ValueError("noise_params keys must be strings")
    result: dict[str, Any] = json.loads(_json_bytes(dict(noise_params)))
    return result


def _source_hashes() -> dict[str, str]:
    """Freeze local compilation, code and physical-cost implementation sources."""
    root = Path(__file__).resolve().parents[3]
    directories = (
        "modules/logical_compiler/src",
        "modules/codes/contracts",
        "modules/codes/_support",
        "modules/codes/rotated_surface_d3",
    )
    paths = {
        path
        for directory in directories
        for path in (root / directory).rglob("*.py")
        if "tests" not in path.relative_to(root).parts
        and "examples" not in path.relative_to(root).parts
    }
    paths.update(
        (
            Path(__file__).resolve(),
            Path(__file__).with_name("factory_to_t.py").resolve(),
        )
    )
    sources = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }
    physical_root = _physical_runtime_root()
    sources.update(
        {
            "runtime-physical:" + path.as_posix(): hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
            for path in sorted(physical_root.rglob("*.py"))
        }
    )
    return sources


def _physical_runtime_root() -> Path:
    """Locate the actually imported physical package, including editable installs."""
    location = nadit_physical_compiler.__file__
    if location is None:
        raise RuntimeError("Cannot freeze physical runtime without its source location")
    return Path(location).resolve().parent


class CostNoiseBackend(_ScenarioBackend):
    """Route raw preparation evidence to cost noise and preserve unsupported quality.

    The inherited scenario is fixed to cost-noise, which enables no scripted
    rejection or physical failure. These hooks require the new source-aware
    code-owned API; a missing hook fails explicitly instead of using an ideal port.
    """

    def __init__(self, backend: SurfaceFactoryBackend, output_carrier: str) -> None:
        super().__init__(backend, "cost-noise", output_carrier)
        for name in ("preparation_event", "preparation_quality_from_event"):
            if not callable(getattr(backend, name, None)):
                raise NotImplementedError(
                    f"COST_NOISE_BACKEND_UNAVAILABLE: missing {name}"
                )

    @staticmethod
    def _preparation_parameters(
        preparation: str, parameters: Mapping[str, Any] | None
    ) -> dict[str, Any]:
        if preparation != "raw_t_postselection":
            return {}
        values = dict(parameters or {})
        if (
            set(values) != {"noise_model", "noise_params"}
            or values["noise_model"] != "noise/v1"
        ):
            raise ValueError(
                "RAW_COST_PARAMETERS_REQUIRED: explicit noise/v1 and noise_params"
            )
        return {
            "noise_model": "noise/v1",
            "noise_params": _parameters(values["noise_params"]),
        }

    def preparation_event(
        self,
        preparation: str,
        source: Any,
        parameters: Mapping[str, Any] | None = None,
    ) -> ProbabilityPort:
        """Resolve a joint event from the actual source, with no ideal raw fallback."""
        hook = self.backend.preparation_event
        port: ProbabilityPort = hook(
            preparation, source, self._preparation_parameters(preparation, parameters)
        )
        return port

    def preparation_quality_from_event(
        self,
        preparation: str,
        source: Any,
        port: ProbabilityPort,
        values: Mapping[str, Any],
        parameters: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Retain the code's quality status, including unsupported/null consumption."""
        hook = self.backend.preparation_quality_from_event
        quality: dict[str, Any] = hook(
            preparation,
            source,
            port,
            values,
            self._preparation_parameters(preparation, parameters),
        )
        return quality


@dataclass(frozen=True)
class NoiseRun:
    """One independent static prefix, cost report and preserved experiment record."""

    case: FactoryCase
    executor: FactoryExecutor
    manifest: dict[str, Any]
    cost_report: dict[str, Any] | None
    ledger_record: dict[str, Any]
    output: Path


def _manifest(
    case: FactoryCase,
    params: dict[str, Any],
    source_start: dict[str, str],
    source_end: dict[str, str],
    cost_report: dict[str, Any] | None,
    cost_error: str | None,
    cost_payload: bytes | None,
) -> dict[str, Any]:
    document = case.to_dict()
    bundle = case.physical
    physical = document["physical"]
    calls = document["calls"]
    qualities = [token["quality"] for token in document["resources"]["tokens"]]
    return {
        "schema": "nadit.factory_noise_manifest/1",
        "scenario": "cost-noise",
        "experiment_id": CASE_ID,
        "run_id": f"seed-{document['seed']}",
        "case_id": document["case_id"],
        "seed": document["seed"],
        "status": document["status"],
        "failure": document["failure"],
        "goal": document["goal"],
        "code": document["code"],
        "protocol_id": document["recipe"]["protocol_id"],
        "protocol_version": document["recipe"]["version"],
        "duration_us": document["duration_us"],
        "execution_mode": "serial",
        "supply_mode": "on_demand",
        "inventory_maintenance": "not_implemented",
        "limits": document["limits"],
        "input_z_error": None,
        "input_quality_status": "unsupported"
        if any(q.get("status") == "unsupported" for q in qualities)
        else "not_established",
        "resource_quality_evidence": qualities,
        "logical_success": None,
        "algorithm_evaluation": None,
        "noise_parameters": params,
        "noise_parameters_file_sha256": hashlib.sha256(_json_bytes(params)).hexdigest(),
        "cost_profile": {
            "model": "noise/v1",
            "status": "evaluated" if cost_report is not None else "unavailable",
            "error": cost_error,
            "report_file": "physical-cost.json" if cost_report is not None else None,
            "report_sha256": None
            if cost_payload is None
            else hashlib.sha256(cost_payload).hexdigest(),
            "source_bundle_sha256": None
            if cost_report is None
            else cost_report.get("source_bundle_sha256"),
            "logical_success": None,
        },
        "scopes": {
            "actions": (
                "Actual code-owned preparation, reset/retry and canonicalization "
                "actions in the complete world"
            ),
            "timing": "Real component actions and explicit waits",
            "preparation_probabilities": (
                "Raw joint event from noise/v1 and the actual raw source; "
                "working-state initialization remains ideal"
            ),
            "input_quality": (
                "Only code-owned quality evidence; unsupported means "
                "no consumption and no p=0 fallback"
            ),
            "physical_noise": (
                "Explicit uncalibrated parameters; Pauli/readout acceptance "
                "and separately reported physical loss"
            ),
            "physical_execution": False,
            "physical_measurement_values": "unobserved",
            "full_quantum_simulation": False,
            "global_frame": "not_implemented",
            "event_fixture": False,
            "physical_failure_fixture": False,
        },
        "counts": {
            "protocol_calls": len(calls),
            "primitive_component_parts": None
            if physical is None
            else len(physical["parts"]),
            "atom_steps": None if bundle is None else len(bundle.program.steps),
            "atom_actions": None
            if bundle is None
            else sum(len(step.actions) for step in bundle.program.steps),
            "atoms": None if bundle is None else len(bundle.world.atoms),
            "pending_physical_results": None
            if bundle is None
            else len(bundle.pending_measurements),
            "raw_preparation_attempts": sum(
                call["component_id"] == "raw_t_postselection" for call in calls
            ),
        },
        "physical_validation": None if physical is None else physical["validation"],
        "output_token_id": document["output_token_id"],
        "algorithm_consumed_token_id": document["algorithm_consumed_token_id"],
        "source_files_sha256": source_start,
        "runtime_physical_package_root": str(_physical_runtime_root()),
        "source_files_sha256_at_end": source_end,
        "source_stable": source_start == source_end,
        "comparison_valid": source_start == source_end,
        "comparison_scope": "frozen_sources_and_noise_parameters_only",
        "probability_model_hashes": sorted(document["probability_models"]),
        "files_sha256": {},
    }


def run_noise_case(
    seed: int,
    noise_params: Mapping[str, Any],
    output: str | Path,
    *,
    world: FactoryWorld | None = None,
    backend: SurfaceFactoryBackend | None = None,
    source_snapshot: Mapping[str, str] | None = None,
) -> NoiseRun:
    """Compile a fresh requested factory-to-T case and export its honest prefix.

    Noise parameters must be explicit. No input-Z-error reference is supplied.
    Optional world/backend reuse shares immutable geometry and template caches,
    never a physical context, event journal, ledger or sampled case result.
    source_snapshot binds a cohort to its previously frozen source revision.
    Existing output paths are refused before work. Invalid inputs raise ValueError;
    missing source-aware backend hooks raise NotImplementedError.
    """
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    params = _parameters(noise_params)
    destination = Path(output).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"Output directory must be new: {destination}")
    frozen = _source_hashes() if source_snapshot is None else dict(source_snapshot)
    factory_world = world or make_factory_world()
    real_backend = backend or SurfaceFactoryBackend(factory_world.device)
    if real_backend.device != factory_world.device:
        raise ValueError("backend and world must use the same Device")
    bindings = factory_world.bindings
    adapter = CostNoiseBackend(real_backend, bindings["W1"].block_id)
    executor = FactoryExecutor(
        code="rotated_surface_d3",
        recipe=factory_recipe(),
        backend=adapter,
        physical=PhysicalContext(
            factory_world.device, factory_world.world_state, bindings.values()
        ),
        role_bindings={role: binding.block_id for role, binding in bindings.items()},
        distance=3,
        case_id=CASE_ID,
        seed=seed,
        limits=FactoryLimits(raw_attempts=8, batches=1),
        reference_parameters={"noise_model": "noise/v1", "noise_params": params},
    )
    case = executor.run(
        algorithm_preparation=ResourcePreparation(
            "data",
            "W2",
            "initialize_plus",
            "preparation:initialize_plus",
            "initialize_plus",
            None,
            "working",
        ),
        algorithm_consumption=t_consumption_recipe(
            "W2", "W1", key="output-consumption"
        ),
    )
    report, error = None, None
    if case.physical is None:
        error = "No validated physical bundle is available for cost evaluation"
    else:
        try:
            report = evaluate_physical_cost(case.physical, params)
        except (ValueError, TypeError, KeyError, NotImplementedError) as failure:
            error = str(failure)
    cost_payload = None if report is None else _json_bytes(report)
    manifest = _manifest(
        case, params, frozen, _source_hashes(), report, error, cost_payload
    )
    manifest["additional_files_sha256"] = {
        "noise-params.json": hashlib.sha256(_json_bytes(params)).hexdigest(),
        **(
            {"physical-cost.json": hashlib.sha256(cost_payload).hexdigest()}
            if cost_payload is not None
            else {}
        ),
    }
    _export(case, manifest, destination)
    extras = {"noise-params.json": _json_bytes(params)}
    if cost_payload is not None:
        extras["physical-cost.json"] = cost_payload
    if report is not None and isinstance(report.get("generated_qasm"), str):
        extras["selected-physical.qasm"] = report["generated_qasm"].encode("utf-8")
    for name, payload in extras.items():
        with (destination / name).open("xb") as stream:
            stream.write(payload)
        manifest["files_sha256"][name] = hashlib.sha256(payload).hexdigest()
    # This manifest was created in this run's new directory. Existing run paths
    # are never reused; cost payloads augment the shared export's file inventory.
    (destination / "manifest.json").write_bytes(_json_bytes(manifest))
    record = json.loads((destination / "experiment.json").read_text("utf-8"))
    return NoiseRun(case, executor, manifest, report, record, destination)


def run_noise_cohort(
    noise_params: Mapping[str, Any],
    output: str | Path,
    *,
    seeds: Sequence[int] = DEFAULT_SEEDS,
    parameter_source: Mapping[str, Any] | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run frozen-source seeds serially, preserving every static prefix and ledger.

    The default is exactly seeds 0..15. A source change stops further seeds and
    marks comparison_valid false; saved partial evidence is retained. No cohort
    field substitutes factory acceptance or a physical proxy for logical success.
    The output directory and ledger subdirectory must be new.
    """
    selected = tuple(seeds)
    if (
        not selected
        or any(type(seed) is not int for seed in selected)
        or len(set(selected)) != len(selected)
    ):
        raise ValueError("seeds must be a nonempty sequence of distinct integers")
    params = _parameters(noise_params)
    destination = Path(output).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"Cohort output directory must be new: {destination}")
    frozen = _source_hashes()
    world = make_factory_world()
    backend = SurfaceFactoryBackend(world.device)
    # Fail before creating a study directory if the source-aware API is absent.
    CostNoiseBackend(backend, world.bindings["W1"].block_id)
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "noise-params.json").write_bytes(_json_bytes(params))
    summary: dict[str, Any] = {
        "schema": "nadit.factory_noise_cohort/1",
        "experiment_id": CASE_ID,
        "case_id": CASE_ID,
        "seeds_requested": list(selected),
        "noise_model": "noise/v1",
        "noise_parameters": params,
        "parameter_source": dict(parameter_source or {}),
        "noise_parameters_file_sha256": hashlib.sha256(_json_bytes(params)).hexdigest(),
        "source_files_sha256_at_start": frozen,
        "runtime_physical_package_root": str(_physical_runtime_root()),
        "status": "running",
        "comparison_valid": False,
        "comparison_scope": "frozen_sources_and_noise_parameters_only",
        "logical_success": None,
        "limits": {"raw_attempts": 8, "batches": 1},
        "runs": [],
    }
    (destination / "cohort.json").write_bytes(_json_bytes(summary))
    records = []
    for seed in selected:
        if _source_hashes() != frozen:
            break
        if progress is not None:
            progress(f"Compiling cost-noise seed {seed}")
        run = run_noise_case(
            seed,
            params,
            destination / f"seed-{seed}",
            world=world,
            backend=backend,
            source_snapshot=frozen,
        )
        records.append(run.ledger_record)
        summary["runs"].append(
            {
                "seed": seed,
                "status": run.case.status,
                "directory": run.output.name,
                "duration_us": run.manifest["duration_us"],
                "counts": run.manifest["counts"],
                "physical_validation_ok": None
                if run.manifest["physical_validation"] is None
                else run.manifest["physical_validation"]["ok"],
                "cost_status": run.manifest["cost_profile"]["status"],
                "manifest_sha256": hashlib.sha256(
                    (run.output / "manifest.json").read_bytes()
                ).hexdigest(),
                "logical_success": None,
            }
        )
        if progress is not None:
            progress(
                f"Seed {seed}: {run.case.status}; "
                f"raw attempts={run.manifest['counts']['raw_preparation_attempts']}"
            )
        (destination / "cohort.json").write_bytes(_json_bytes(summary))
        if not run.manifest["source_stable"]:
            break
    final_sources = _source_hashes()
    stable = frozen == final_sources
    summary.update(
        source_files_sha256_at_end=final_sources,
        comparison_valid=stable and len(records) == len(selected),
        status="compiled"
        if stable and len(records) == len(selected)
        else "source_changed",
        seeds_completed=[run["seed"] for run in summary["runs"]],
        ledger_files=write_ledger(records, destination / "ledger"),
    )
    (destination / "cohort.json").write_bytes(_json_bytes(summary))
    return summary


def main(argv: list[str] | None = None) -> int:
    """Compile the explicitly parameterized default sixteen-seed cohort."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--noise-params", required=True, type=Path)
    parser.add_argument("--seeds", nargs="+", type=int, default=list(DEFAULT_SEEDS))
    args = parser.parse_args(argv)
    payload = args.noise_params.read_bytes()
    summary = run_noise_cohort(
        json.loads(payload),
        args.output,
        seeds=args.seeds,
        parameter_source={
            "file": str(args.noise_params.resolve()),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
        progress=lambda message: print(message, flush=True),
    )
    print(
        json.dumps(
            {
                key: summary[key]
                for key in (
                    "status",
                    "seeds_completed",
                    "comparison_valid",
                    "logical_success",
                )
            },
            indent=2,
        )
    )
    return 0 if summary["comparison_valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
