"""Compile real factory actions with explicitly scoped physical no-fault proxies.

Raw events retain the code-owned detector model. A proxy can select another
factory batch or evaluate a completed algorithm, but it is never a logical
success claim, a measured bit, or a conditional output-state estimate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nadit_physical_compiler.provenance import canonical_hash

from modules.codes.contracts.component import ComponentExpansion
from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.contracts.factory_recipe import ResourcePreparation
from modules.codes.rotated_surface_d3.protocols import factory as surface_factory
from modules.codes.rotated_surface_d3.protocols.factory_world import (
    FactoryWorld,
    make_factory_world,
)
from modules.logical_compiler.examples import factory_noise as noise
from modules.logical_compiler.examples.factory_to_t import _export
from modules.logical_compiler.src.cases.backend import Occurrence, SeededEventBackend
from modules.logical_compiler.src.protocols import cost
from modules.logical_compiler.src.protocols.experiment_ledger import write_ledger
from modules.logical_compiler.src.protocols.factory import (
    FactoryCase,
    FactoryExecutor,
    FactoryLimits,
)
from modules.logical_compiler.src.protocols.physical import PhysicalContext
from modules.logical_compiler.src.scheduling import ComponentScheduler

CASE_ID = "factory-cost-proxy-v1"
DEFAULT_SEEDS = tuple(range(16))
_BATCH = re.compile(r"^(factory/batch\[\d+\])/")


def _source_hashes() -> dict[str, str]:
    """Include this entry point in the actual runtime/code source freeze."""
    result = noise._source_hashes()
    root = Path(__file__).resolve().parents[3]
    for path in Path(__file__).resolve().parent.glob("*.py"):
        result[path.relative_to(root).as_posix()] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    return result


def _batch_scope(invocation_id: str) -> str:
    match = _BATCH.match(invocation_id)
    if match is None:
        raise ValueError(f"INVALID_FACTORY_SCOPE: {invocation_id}")
    return match.group(1)


def _time(value: Any) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("INVALID_PROXY_INTERVAL: expected finite nonnegative time")
    return float(value)


def _raw_union(
    start_us: float,
    end_us: float,
    excluded: Iterable[tuple[float, float]],
) -> tuple[tuple[float, float], ...]:
    """Union full raw horizons, preserving exact boundaries without double cost."""
    start, end = _time(start_us), _time(end_us)
    if end <= start:
        raise ValueError("INVALID_PROXY_INTERVAL: batch must have positive duration")
    intervals: list[tuple[float, float]] = []
    for left, right in sorted((_time(a), _time(b)) for a, b in excluded):
        if left < start or right <= left or right > end:
            raise ValueError("INVALID_RAW_HORIZON: interval outside batch")
        if intervals and left <= intervals[-1][1]:
            intervals[-1] = (intervals[-1][0], max(right, intervals[-1][1]))
        else:
            intervals.append((left, right))
    return tuple(intervals)


def _included_intervals(
    start_us: float,
    end_us: float,
    excluded: Iterable[tuple[float, float]],
) -> tuple[tuple[float, float], ...]:
    """Take the complement of the raw union; physical action clipping is separate."""
    cursor, end = _time(start_us), _time(end_us)
    intervals = []
    for left, right in _raw_union(cursor, end, excluded):
        if cursor < left:
            intervals.append((cursor, left))
        cursor = right
    if cursor < end:
        intervals.append((cursor, end))
    if not intervals:
        raise ValueError("EMPTY_FACTORY_PROXY_SCOPE: no non-raw physical interval")
    return tuple(intervals)


def _scope_evidence(
    report: dict[str, Any],
    *,
    scope_id: str,
    stage: str,
    window: tuple[float, float],
    excluded: Iterable[tuple[float, float]] = (),
) -> dict[str, Any]:
    selection = report["interval_selection"]
    return {
        "scope_id": scope_id,
        "stage": stage,
        "window_us": list(window),
        "included_intervals_us": selection["include_intervals"],
        "excluded_raw_intervals_us": [list(pair) for pair in excluded],
        "source_result_hash": report["result_hash"],
        "scoped_activity_hash": selection["selected_activity_sha256"],
        "original_event_indices": selection["selected_event_indices"],
        "action_boundaries_checked": True,
        "noise_profile": selection["noise_profile"],
        "t2_granularity": selection["exposure_partition"],
        "full_trace_probability_equivalence_claimed": False,
    }


class CostProxyBackend(noise.CostNoiseBackend):
    """Bind code-owned proxy models to actual, ready physical intervals.

    This adapter only selects intervals. It neither invents probability ports nor
    derives logical input quality from physical no-fault probability.
    """

    def __init__(
        self, backend: Any, output_carrier: str, physical: PhysicalContext
    ) -> None:
        super().__init__(backend, output_carrier)
        for name in ("factory_proxy_event", "algorithm_proxy_event"):
            if not callable(getattr(backend, name, None)):
                raise NotImplementedError(f"COST_PROXY_BACKEND_UNAVAILABLE: {name}")
        self.proxy_backend = backend
        self.physical = physical
        self.raw_horizons: dict[str, dict[str, Any]] = {}
        self.factory_reports: dict[str, dict[str, Any]] = {}

    def describe_execution(
        self,
        component_id: str,
        participant_bindings: tuple[Any, ...],
        parameters: tuple[tuple[str, Any], ...] = (),
    ) -> Any:
        """Delegate declaration-only logical admission to the selected code."""
        return self.proxy_backend.describe_execution(
            component_id, participant_bindings, parameters
        )

    def preparation_event(
        self,
        preparation: str,
        source: Any,
        parameters: Mapping[str, Any] | None = None,
    ) -> ProbabilityPort:
        """Retain every real raw attempt's whole result-ready horizon."""
        lookup = getattr(self.physical, "batch_for", None)
        batch = (
            lookup(source.parts[0].invocation_id)
            if preparation == "raw_t_postselection" and callable(lookup)
            else None
        )
        if batch is not None:
            register = getattr(self.proxy_backend, "register_parallel_source", None)
            if not callable(register):
                raise ValueError("PARALLEL_PREPARATION_MODEL_REQUIRED")
            register(
                source,
                program=batch.program,
                entry_world=batch.entry_world,
                evidence=batch.to_dict(),
            )
        port = super().preparation_event(preparation, source, parameters)
        if preparation == "raw_t_postselection":
            first = source.parts[0]
            identity = first.invocation_id
            record = {
                "scope_id": _batch_scope(identity),
                "source_invocation": identity,
                "part_invocations": [part.invocation_id for part in source.parts],
                "start_us": first.start_us,
                "results_ready_us": source.results_ready_us,
                "port_sha256": port.content_sha256,
                "parallel_batch_id": None if batch is None else batch.batch_id,
            }
            previous = self.raw_horizons.get(identity)
            if previous is not None and previous != record:
                raise ValueError("RAW_HORIZON_BINDING_CHANGED")
            self.raw_horizons[identity] = record
        return port

    def resolve_event_from_sources(
        self,
        selector: str,
        parts: tuple[ComponentExpansion, ...],
        parameters: Mapping[str, Any],
        *,
        event_id: str,
    ) -> ProbabilityPort:
        """Evaluate the final-check proxy only after all real dependencies are ready."""
        if selector != "factory_cost_proxy":
            return self.resolve_event(selector, parameters)
        if not parts or any(
            part.results_ready_us > self.physical.clock_us for part in parts
        ):
            raise ValueError("FACTORY_PROXY_BEFORE_RESULTS_READY")
        scope = _batch_scope(event_id)
        invocations = tuple(
            item
            for item in self.physical.invocations
            if item.invocation_id.startswith(scope + "/")
        )
        if not invocations:
            raise ValueError("FACTORY_PROXY_WITHOUT_PHYSICAL_BATCH")
        start, end = min(item.start_us for item in invocations), self.physical.clock_us
        excluded = tuple(
            (item["start_us"], item["results_ready_us"])
            for item in self.raw_horizons.values()
            if item["scope_id"] == scope
        )
        raw_union = _raw_union(start, end, excluded)
        included = _included_intervals(start, end, raw_union)
        report = cost.evaluate_physical_cost_intervals(
            self.physical.finalize(),
            parameters["noise_params"],
            include_intervals=included,
        )
        evidence = _scope_evidence(
            report,
            scope_id=event_id,
            stage="factory",
            window=(start, end),
            excluded=raw_union,
        )
        evidence["raw_attempt_intervals_us"] = [list(pair) for pair in excluded]
        evidence["raw_exclusion_semantics"] = "union_of_complete_attempt_horizons"
        port: ProbabilityPort = self.proxy_backend.factory_proxy_event(report, evidence)
        self.factory_reports[event_id] = {
            "report": report,
            "report_content_sha256": canonical_hash(report),
            "scope_evidence": evidence,
            "port_sha256": port.content_sha256,
        }
        return port


@dataclass(frozen=True)
class ProxyRun:
    """A selected physical case and separate proxy evaluation, with static exports."""

    case: FactoryCase
    executor: FactoryExecutor
    manifest: dict[str, Any]
    evaluation: dict[str, Any]
    ledger_record: dict[str, Any]
    output: Path


def _algorithm_evaluation(
    case: FactoryCase,
    adapter: CostProxyBackend,
    params: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    document = case.to_dict()
    evaluation: dict[str, Any] = {
        "schema": "nadit.algorithm_proxy_evaluation/1",
        "case_id": document["case_id"],
        "seed": document["seed"],
        "status": "not_evaluated",
        "reason": "Algorithm T compilation did not complete",
        "probability_kind": "physical_no_fault_proxy",
        "proxy_success": None,
        "logical_success": None,
        "physical_execution": False,
        "physical_measurement_values": "unobserved",
        "feeds_back_into_compilation": False,
    }
    if document["status"] != "complete" or not any(
        mark["kind"] == "algorithm_t_complete" for mark in document["milestones"]
    ):
        return evaluation, None
    if case.physical is None:
        raise ValueError("ALGORITHM_PROXY_REQUIRES_VALIDATED_PHYSICAL_BUNDLE")
    decisions = [
        event
        for event in document["events"]
        if event["occurrence"]["invocation_id"] in adapter.factory_reports
        and event["values"]["accepted"] is True
    ]
    if len(decisions) != 1:
        raise ValueError("ALGORITHM_PROXY_REQUIRES_ONE_ACCEPTED_FACTORY_DECISION")
    tokens = [
        token
        for token in document["resources"]["tokens"]
        if token["token_id"] == document["output_token_id"]
    ]
    if len(tokens) != 1:
        raise ValueError("ALGORITHM_PROXY_REQUIRES_ONE_OUTPUT_TOKEN")
    delivery = tokens[0]["quality"]["delivery_assessment"]
    start = _time(delivery["start_us"])
    if start != decisions[0]["released_at_us"]:
        raise ValueError("ALGORITHM_PROXY_DELIVERY_BOUNDARY_MISMATCH")
    window = (start, document["duration_us"])
    report = cost.evaluate_physical_cost_intervals(
        case.physical, params, include_intervals=(window,)
    )
    evidence = _scope_evidence(
        report,
        scope_id="algorithm/terminal-proxy",
        stage="algorithm",
        window=window,
    )
    port: ProbabilityPort = adapter.proxy_backend.algorithm_proxy_event(
        report, evidence
    )
    sampler = SeededEventBackend(document["case_id"], document["seed"])
    occurrence = Occurrence(
        document["case_id"], "algorithm/terminal-proxy", 0, port.to_dict()["port_id"]
    )
    result = sampler.sample(port, occurrence, available_at_us=window[1])
    values = dict(port.outcome(result.outcome_key).values)
    success = values.get("proxy_success")
    if type(success) is not bool or values.get("no_fault") is not success:
        raise ValueError("INVALID_ALGORITHM_PROXY_OUTCOME")
    evaluation.update(
        status="evaluated",
        reason=None,
        event=result.to_dict(),
        values=values,
        proxy_success=success,
        delivery_assessment=delivery,
        probability_port=port.to_dict(),
        probability_port_sha256=port.content_sha256,
        scope_evidence=evidence,
        cost_report_content_sha256=canonical_hash(report),
    )
    return evaluation, report


def run_proxy_case(
    seed: int,
    noise_params: Mapping[str, Any],
    output: str | Path,
    *,
    world: FactoryWorld | None = None,
    backend: Any = None,
    source_snapshot: Mapping[str, str] | None = None,
    sampling_role: str = "individual_seed",
    scheduler: ComponentScheduler | None = None,
) -> ProxyRun:
    """Compile actual actions with finite retries, then sample a terminal proxy.

    Existing output paths are refused. Each invocation owns a new physical world
    context, event journal and resource ledger. Shared backend caches contain only
    code-owned templates/models. Witness seeds are explicitly labeled at export.
    """
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    if sampling_role not in ("individual_seed", "unbiased_cohort", "witness"):
        raise ValueError("INVALID_SAMPLING_ROLE")
    params = noise._parameters(noise_params)
    destination = Path(output).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"Output directory must be new: {destination}")
    frozen = _source_hashes() if source_snapshot is None else dict(source_snapshot)
    factory_world = world or make_factory_world()
    from modules.codes.rotated_surface_d3.protocols.cost_proxy import (
        SurfaceCostProxyBackend,
        factory_proxy_recipe,
    )

    real_backend = backend or SurfaceCostProxyBackend(factory_world.device)
    if real_backend.device != factory_world.device:
        raise ValueError("backend and world must use the same Device")
    bindings = factory_world.bindings
    physical = PhysicalContext(
        factory_world.device, factory_world.world_state, bindings.values()
    )
    adapter = CostProxyBackend(real_backend, bindings["W1"].block_id, physical)
    executor = FactoryExecutor(
        code="rotated_surface_d3",
        recipe=factory_proxy_recipe(),
        backend=adapter,
        physical=physical,
        role_bindings={role: binding.block_id for role, binding in bindings.items()},
        distance=3,
        case_id=CASE_ID,
        seed=seed,
        limits=FactoryLimits(raw_attempts=8, batches=2),
        reference_parameters={"noise_model": "noise/v1", "noise_params": params},
        scheduler=scheduler,
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
        algorithm_consumption=surface_factory.t_consumption_recipe(
            "W2", "W1", key="output-consumption"
        ),
    )
    evaluation, algorithm_report = _algorithm_evaluation(case, adapter, params)
    report = (
        None
        if case.physical is None
        else cost.evaluate_physical_cost(case.physical, params)
    )
    payload = None if report is None else noise._json_bytes(report)
    manifest = noise._manifest(
        case, params, frozen, _source_hashes(), report, None, payload
    )
    manifest.update(
        schema="nadit.factory_proxy_manifest/1",
        scenario="cost-proxy",
        experiment_id=CASE_ID,
        sampling_role=sampling_role,
        included_in_unbiased_statistics=sampling_role == "unbiased_cohort",
        input_quality_status="ideal_reference_for_proxy",
        algorithm_evaluation=evaluation,
        proxy_cost_scope_file="proxy-costs.json",
        physical_no_fault_is_logical_success=False,
        factory_final_acceptance_kind="physical_no_fault_proxy",
        whole_pipeline_no_fault_probability=None,
        execution_mode="serial" if scheduler is None else scheduler.mode,
        component_schedule=case.to_dict().get("component_schedule"),
    )
    manifest["scopes"].update(
        input_quality=(
            "Code-owned ideal_reference_for_proxy routing; actual accepted "
            "raw/output quality remains unsupported in resource evidence"
        ),
        factory_decision=(
            "Code-owned physical no-fault proxy on non-raw batch intervals"
        ),
        algorithm_evaluation="Separate terminal proxy; no feedback into compilation",
        t2_granularity=(
            "Selected exposure interval intersections, not whole-trace equivalence"
        ),
        full_trace_probability_equivalence_claimed=False,
        raw_loss=(
            "Separate source metadata; raw detector acceptance does not sample loss"
        ),
    )
    reports = {
        "schema": "nadit.factory_proxy_cost_scopes/1",
        "raw_horizons": list(adapter.raw_horizons.values()),
        "factory": adapter.factory_reports,
        "algorithm": algorithm_report,
        "logical_success": None,
    }
    extras = {
        "noise-params.json": noise._json_bytes(params),
        "evaluation.json": noise._json_bytes(evaluation),
        "proxy-costs.json": noise._json_bytes(reports),
    }
    if payload is not None:
        extras["physical-cost.json"] = payload
    if report is not None and isinstance(report.get("generated_qasm"), str):
        extras["selected-physical.qasm"] = report["generated_qasm"].encode("utf-8")
    manifest["additional_files_sha256"] = {
        name: hashlib.sha256(data).hexdigest() for name, data in extras.items()
    }
    _export(case, manifest, destination)
    for name, data in extras.items():
        with (destination / name).open("xb") as stream:
            stream.write(data)
        manifest["files_sha256"][name] = hashlib.sha256(data).hexdigest()
    (destination / "manifest.json").write_bytes(noise._json_bytes(manifest))
    record = json.loads((destination / "experiment.json").read_text("utf-8"))
    return ProxyRun(case, executor, manifest, evaluation, record, destination)


def _seeds(values: Sequence[int], *, allow_empty: bool = False) -> tuple[int, ...]:
    result = tuple(values)
    if (
        (not result and not allow_empty)
        or any(type(seed) is not int for seed in result)
        or len(set(result)) != len(result)
    ):
        raise ValueError("seeds must contain distinct integers")
    return result


def run_proxy_cohort(
    noise_params: Mapping[str, Any],
    output: str | Path,
    *,
    seeds: Sequence[int] = DEFAULT_SEEDS,
    witness_seeds: Sequence[int] = (),
    parameter_source: Mapping[str, Any] | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Freeze and export the seed cohort; keep selected witnesses in a separate ledger.

    The default unbiased cohort is seeds 0..15. Witness seeds must be explicit,
    disjoint from it, and are never included in its comparison or success counts.
    Source changes stop later runs and invalidate the frozen-model comparison.
    """
    selected = _seeds(seeds)
    witnesses = _seeds(witness_seeds, allow_empty=True)
    if set(selected) & set(witnesses):
        raise ValueError("witness seeds must be disjoint from the unbiased cohort")
    params = noise._parameters(noise_params)
    destination = Path(output).expanduser().resolve()
    if destination.exists():
        raise FileExistsError(f"Cohort output directory must be new: {destination}")
    from modules.codes.rotated_surface_d3.protocols.cost_proxy import (
        SurfaceCostProxyBackend,
    )

    frozen = _source_hashes()
    world = make_factory_world()
    backend = SurfaceCostProxyBackend(world.device)
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "noise-params.json").write_bytes(noise._json_bytes(params))
    summary: dict[str, Any] = {
        "schema": "nadit.factory_proxy_cohort/1",
        "experiment_id": CASE_ID,
        "case_id": CASE_ID,
        "seeds_requested": list(selected),
        "witness_seeds_requested": list(witnesses),
        "witnesses_included_in_unbiased_statistics": False,
        "noise_model": "noise/v1",
        "noise_parameters": params,
        "parameter_source": dict(parameter_source or {}),
        "noise_parameters_file_sha256": hashlib.sha256(
            noise._json_bytes(params)
        ).hexdigest(),
        "source_files_sha256_at_start": frozen,
        "runtime_physical_package_root": str(noise._physical_runtime_root()),
        "status": "running",
        "comparison_valid": False,
        "comparison_scope": "frozen_sources_and_noise_parameters_only",
        "logical_success": None,
        "probability_kind": "physical_no_fault_proxy",
        "limits": {"raw_attempts": 8, "batches": 2},
        "runs": [],
        "witness_runs": [],
    }
    (destination / "cohort.json").write_bytes(noise._json_bytes(summary))
    records: dict[str, list[dict[str, Any]]] = {"unbiased_cohort": [], "witness": []}
    schedule = tuple((seed, "unbiased_cohort") for seed in selected) + tuple(
        (seed, "witness") for seed in witnesses
    )
    for seed, role in schedule:
        if _source_hashes() != frozen:
            break
        if progress is not None:
            progress(f"Compiling {role} cost-proxy seed {seed}")
        run = run_proxy_case(
            seed,
            params,
            destination
            / (f"seed-{seed}" if role == "unbiased_cohort" else f"witness-seed-{seed}"),
            world=world,
            backend=backend,
            source_snapshot=frozen,
            sampling_role=role,
        )
        records[role].append(run.ledger_record)
        entry = {
            "seed": seed,
            "sampling_role": role,
            "case_status": run.case.status,
            "directory": run.output.name,
            "duration_us": run.manifest["duration_us"],
            "counts": run.manifest["counts"],
            "physical_validation_ok": None
            if run.manifest["physical_validation"] is None
            else run.manifest["physical_validation"]["ok"],
            "terminal_evaluation_status": run.evaluation["status"],
            "proxy_success": run.evaluation["proxy_success"],
            "logical_success": None,
            "manifest_sha256": hashlib.sha256(
                (run.output / "manifest.json").read_bytes()
            ).hexdigest(),
        }
        summary["runs" if role == "unbiased_cohort" else "witness_runs"].append(entry)
        if progress is not None:
            progress(
                f"Seed {seed}: {run.case.status}; terminal={run.evaluation['status']}"
            )
        (destination / "cohort.json").write_bytes(noise._json_bytes(summary))
        if not run.manifest["source_stable"]:
            break
    final_sources = _source_hashes()
    stable = frozen == final_sources
    complete = sum(len(items) for items in records.values()) == len(schedule)
    summary.update(
        source_files_sha256_at_end=final_sources,
        comparison_valid=stable and complete,
        status="compiled" if stable and complete else "source_changed",
        seeds_completed=[run["seed"] for run in summary["runs"]],
        witness_seeds_completed=[run["seed"] for run in summary["witness_runs"]],
        ledger_files=write_ledger(records["unbiased_cohort"], destination / "ledger"),
        witness_ledger_files=write_ledger(
            records["witness"], destination / "witness-ledger"
        ),
    )
    (destination / "cohort.json").write_bytes(noise._json_bytes(summary))
    return summary


def main(argv: list[str] | None = None) -> int:
    """Compile a frozen physical-proxy cohort from an explicit noise parameter file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--noise-params", required=True, type=Path)
    parser.add_argument("--seeds", nargs="+", type=int, default=list(DEFAULT_SEEDS))
    parser.add_argument("--witness-seeds", nargs="*", type=int, default=[])
    args = parser.parse_args(argv)
    payload = args.noise_params.read_bytes()
    summary = run_proxy_cohort(
        json.loads(payload),
        args.output,
        seeds=args.seeds,
        witness_seeds=args.witness_seeds,
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
                    "witness_seeds_completed",
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
