"""Same-distance L1/L2 production on the existing shared runtime and cache.

The existing conditional theory model supplies quality parameters. Native
transport and waiting exposure are counted, but are not promoted to a decoded
logical-error model. This entry does not implement cross-distance conversion.
"""

from collections.abc import Mapping
from copy import deepcopy
from time import perf_counter
from typing import Any

from nadit_physical_compiler.device import Position
from nadit_physical_compiler.provenance import canonical_hash

from modules.codes.rotated_surface.fast_factory import (
    SurfaceFactoryBackend,
    factory_recipe,
)
from modules.codes.rotated_surface.joint_factory_profile import (
    JointSurfaceFactoryProfile,
    MissingJointCalibration,
)
from modules.codes.rotated_surface_d3.protocols.factory_experiment import (
    FactoryExperimentModel,
)
from modules.logical_compiler.src.estimation.kernel import ProfileExecutionKernel
from modules.logical_compiler.src.protocols.cooperative import CooperativeFactoryRuntime
from modules.logical_compiler.src.protocols.factory import FactoryLimits
from modules.logical_compiler.src.protocols.factory_process import FactoryProcess
from modules.logical_compiler.src.protocols.production import (
    ProductionPolicy,
    make_output_sink,
)
from modules.logical_compiler.src.scheduling import ComponentScheduler

from .joint_cache import JointCalibrationCache
from .production_metrics import summarize_production
from .standard import FACTORY_ROLES, add_buffer_sites


def _configuration(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    config = payload["two_level"]
    if (
        not isinstance(config, Mapping)
        or config.get("acknowledge_theory_transport_exclusions") is not True
    ):
        raise ValueError("EXPLICIT_THEORY_TRANSPORT_EXCLUSIONS_REQUIRED")
    expected = {
        "level1_count",
        "level2_count",
        "buffer_capacity",
        "producer_max_cycles",
        "consumer_max_cycles",
        "level1_batches",
        "level2_batches",
        "parking_origin",
        "output_sink",
        "acknowledge_theory_transport_exclusions",
    }
    if set(config) != expected:
        raise ValueError("TWO_LEVEL_CONFIGURATION_FIELDS_MISMATCH")
    for key in (
        "level1_count",
        "level2_count",
        "buffer_capacity",
        "producer_max_cycles",
        "consumer_max_cycles",
        "level1_batches",
        "level2_batches",
    ):
        if type(config[key]) is not int or config[key] < 1:
            raise ValueError(f"INVALID_TWO_LEVEL_BUDGET: {key}")
    return config


def execute_two_level_task(task: dict[str, Any]) -> dict[str, Any]:
    """Execute finite real production, or request a current-world calibration.

    Both levels share one clock, ledger, Device and scheduler. L1 outputs enter a
    bounded producer-held queue; L2 inputs arrive through same-atom relocation.
    Missing calibration is delegated to the existing isolated experiment runner.
    Invalid configuration raises ValueError; execution failures retain evidence.
    """
    from .campaign_worker import (
        _CachedProfile,
        _context,
        _continuous_arguments,
        _policy_artifacts,
        calibration_dependency,
    )

    started = perf_counter()
    payload = task["payload"]
    config = _configuration(payload)
    n1, n2 = config["level1_count"], config["level2_count"]
    from modules.logical_compiler.src.protocols.factory_supply import FactorySupply

    continuous = task["kind"] in ("msd.two_level_pilot", "msd.two_level_produce")
    policy_artifacts: list[dict[str, str]] = []
    window = None
    consumer_policy = ProductionPolicy(config["consumer_max_cycles"])
    if continuous:
        if (
            payload["limits"].get("max_cycles", config["consumer_max_cycles"])
            != config["consumer_max_cycles"]
        ):
            raise ValueError("TWO_LEVEL_CONSUMER_CYCLE_BUDGET_MISMATCH")
        adapted = {
            **task,
            "kind": "msd.pilot"
            if task["kind"] == "msd.two_level_pilot"
            else "msd.produce",
            "payload": {
                **payload,
                "output_sink": config["output_sink"],
                "limits": {
                    **payload["limits"],
                    "max_cycles": config["consumer_max_cycles"],
                },
            },
        }
        policy_artifacts = _policy_artifacts(adapted)
        arguments = _continuous_arguments(adapted)
        consumer_policy, sink = arguments["production_policy"], arguments["output_sink"]
        if consumer_policy.max_cycles > config["consumer_max_cycles"]:
            raise ValueError("TWO_LEVEL_PILOT_EXCEEDS_CONSUMER_CYCLE_BUDGET")
        if adapted["kind"] == "msd.produce":
            window = payload["observation_policy"]
            if window.get("output_factory_ids") != sorted(
                f"factory{i}" for i in range(n1, n1 + n2)
            ):
                raise ValueError("TWO_LEVEL_OBSERVATION_FACTORY_SELECTION_MISMATCH")
    else:
        sink = make_output_sink(config["output_sink"])
    world, _, arguments = _context(payload)
    if world.spec.pipelines != n1 + n2 or len(world.device.aods) != 1:
        raise ValueError("TWO_LEVEL_SHARED_WORLD_COUNT_MISMATCH")
    world, parking = add_buffer_sites(
        world, {"exchange_parking": Position(**config["parking_origin"])}
    )
    family = canonical_hash(
        {"world": world.document(), "actions": payload["dependencies"]["actions"]}
    )
    arguments["family"] = family
    slots = {
        p.binding.block_id: (p.binding.origin, p.home_sites) for p in world.patches
    } | parking
    assert world.device.readout is not None
    document = JointSurfaceFactoryProfile.from_placement(
        world.placement_plan,
        family=family,
        noise_params=payload["noise_params"],
        limits={
            "max_rows": world.device.aods[0].max_rows,
            "max_columns": world.device.aods[0].max_columns,
            "max_readout_atoms": world.device.readout.max_atoms,
        },
    ).to_dict()
    profile = _CachedProfile(
        document,
        world,
        JointCalibrationCache(payload["cache_root"]),
        arguments,
        transport_slots=slots,
    )
    execution = ProfileExecutionKernel(profile, profile.layout())
    model1 = FactoryExperimentModel("theory", payload["input_z_error"])
    upstream_quality = model1.output_quality(model1.final_theory_event())
    model2 = FactoryExperimentModel(
        "theory", model1.to_dict()["conditional_output_z_error"]
    )
    models = (model1, model2)
    backends = tuple(
        SurfaceFactoryBackend(profile, execution, model) for model in models
    )
    supply = FactorySupply(
        buffer_id="L1-to-L2",
        capacity=config["buffer_capacity"],
        parking_slot="exchange_parking",
        role_slots={
            (f"factory{i}", role): f"factory{i}/{role}"
            for i in range(n1 + n2)
            for role in FACTORY_ROLES
        },
        expected_consumption_parameters=upstream_quality["consumption_parameters"],
        current_bindings=profile.current_bindings,
    )
    processes = []
    for index in range(n1 + n2):
        level = int(index >= n1)
        process = FactoryProcess(
            f"factory{index}",
            code=profile.code_id,
            recipe=factory_recipe(profile.distance),
            backend=backends[level],
            role_bindings={role: f"factory{index}/{role}" for role in FACTORY_ROLES},
            distance=profile.distance,
            cohort_id=f"level{level + 1}",
            reference_parameters=models[level].parameters(payload["noise_params"]),
            limits=FactoryLimits(
                raw_attempts=payload["limits"]["raw_attempts"],
                batches=config[f"level{level + 1}_batches"],
                max_component_calls=payload["limits"]["max_component_calls"],
            ),
            production_policy=ProductionPolicy(config["producer_max_cycles"])
            if level == 0
            else consumer_policy,
            output_sink=supply.producer_sink if level == 0 else sink,
            production_continuation=supply.production_continuation
            if level == 0
            else None,
            external_inputs=level == 1,
            preparation_supplier=supply.consumer_supplier if level == 1 else None,
        )
        processes.append(process)
    supply.bind_processes(tuple(processes[:n1]), tuple(processes[n1:]))
    runtime = CooperativeFactoryRuntime(
        execution=execution,
        case_id="same-distance-two-level-theory-v1",
        seed=payload["production_seed"],
        scheduler=ComponentScheduler(),
        processes=tuple(processes),
    )
    execution_started = perf_counter()
    try:
        case = runtime.run().to_dict()
    except MissingJointCalibration as missing:
        reason = missing.to_dict()
        reason["progress"] = {
            "scope": "deterministic_replay_prefix_not_a_completed_result",
            "logical_time_us": execution.clock_us,
            "level1_outputs_ready": sum(len(p.outputs) for p in processes[:n1]),
            "level1_outputs_handed_off": sum(
                output.get("handoff_at_us") is not None
                for p in processes[:n1]
                for output in p.outputs
            ),
            "level2_inputs_received": sum(
                milestone["kind"] == "external_input_received"
                for p in processes[n1:]
                for milestone in p.milestones
            ),
        }
        return {
            "status": "needs_dependencies",
            "reason": reason,
            "dependency_requests": [
                calibration_dependency(task, missing.members, request=missing.request)
            ],
            "software_seconds": {
                "setup": execution_started - started,
                "cache_load": profile.cache_load_seconds,
                "fast_prefix": max(
                    0, perf_counter() - execution_started - profile.cache_load_seconds
                ),
            },
        }
    fast_seconds = max(
        0, perf_counter() - execution_started - profile.cache_load_seconds
    )
    result: dict[str, Any] = {
        "scope": "same-distance two-level finite-cycle production; not steady-state scaling",
        "case": case,
        "entry_world": world.document(),
        "exit_world": profile.world.document(),
        "calibration_records": profile.cache_records,
        "level1_factories": [p.factory_id for p in processes[:n1]],
        "level2_factories": [p.factory_id for p in processes[n1:]],
        "models": {"level1": model1.to_dict(), "level2": model2.to_dict()},
        "quality_assumptions": {
            "acknowledged_theory_transport_exclusions": True,
            "incoming_consumption_parameters": upstream_quality[
                "consumption_parameters"
            ],
            "physical_transport_and_wait_exposure_counted": None,
            "transport_and_wait_noise_updates_logical_quality": False,
            "actual_output_error": None,
        },
        "software_seconds": {
            "setup": execution_started - started,
            "cache_load": profile.cache_load_seconds,
            "fast_execution": fast_seconds,
        },
    }
    if continuous:
        result.update(
            {
                key: payload[key]
                for key in (
                    "trajectory_id",
                    "layout_id",
                    "seed",
                    "config_sha256",
                    "source_sha256",
                    "geometry_layout_id",
                    "buffer_capacity",
                    "arrival_evidence_sha256",
                )
                if key in payload
            }
        )
        result.update(
            scope="same-distance two-level continuous production from validated joint traces; explicit theory quality and delivery assumptions",
            case_sha256=canonical_hash(case),
            two_level=deepcopy(dict(config)),
            output_sink=deepcopy(config["output_sink"]),
            final_level_output_count_scope="complete case including surplus drain; window counts are in metrics",
        )
        if window is not None:
            result["observation_policy"] = deepcopy(window)
            result["observation_policy_sha256"] = canonical_hash(window)
    try:
        result["supply"] = supply.snapshot(
            ledger=runtime.ledger, at_us=execution.clock_us
        )
        metric_started = perf_counter()
        result["metrics"] = summarize_production(
            case,
            world,
            profile.load_trace,
            warmup_us=0.0 if window is None else window["warmup_us"],
            stop_us=case["duration_us"] if window is None else window["stop_us"],
            output_factory_ids={p.factory_id for p in processes[n1:]},
        )
        result["software_seconds"][
            "validation" if continuous else "validation_metrics"
        ] = perf_counter() - metric_started
        result["quality_assumptions"][
            "physical_transport_and_wait_exposure_counted"
        ] = True
    except (ValueError, TypeError, KeyError) as error:
        if continuous:
            result["software_times_seconds"] = dict(result["software_seconds"])
        return {
            "status": "software_error",
            "reason": f"TWO_LEVEL_AUDIT_FAILED: {error}",
            "result": result,
            "artifacts": [*profile.artifacts.values(), *policy_artifacts],
            "software_seconds": result["software_seconds"],
        }
    states = {p.status for p in processes}
    if states & {"expansion_budget_exhausted", "production_cycle_budget_exhausted"}:
        status = "budget_exceeded"
    elif states - {
        "complete",
        "distillation_rejected",
        "input_supply_exhausted",
        "external_supply_exhausted",
    } or case.get("failure"):
        status = "software_error"
    else:
        status = "ok"
    result["final_level_output_count"] = sum(
        output.get("deliverable_at_us") is not None
        for process in processes[n1:]
        for output in process.outputs
    )
    if continuous:
        result["software_times_seconds"] = dict(result["software_seconds"])
    return {
        "status": status,
        "reason": None if status == "ok" else sorted(states),
        "result": result,
        "artifacts": [*profile.artifacts.values(), *policy_artifacts],
        "software_seconds": result["software_seconds"],
    }
