"""Bounded shared-runtime mechanical handoff with an explicit prepared-token fixture.

The token is not produced by distillation. This task verifies native transport,
stateful cache misses and atomic role handoff; it cannot satisfy an L1/L2
production or quality gate. The ordinary MSD runner owns isolation and recovery.
"""

from dataclasses import asdict
from time import perf_counter
from typing import Any

from nadit_physical_compiler.device import Position
from nadit_physical_compiler.provenance import canonical_hash

from modules.codes.contracts.factory_recipe import ComponentCall
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
from modules.logical_compiler.src.protocols.factory_process import FactoryProcess
from modules.logical_compiler.src.protocols.production import OutputHandoff
from modules.logical_compiler.src.protocols.protocol_intents import (
    CallIntent,
    ProtocolFlow,
    ResourceWaitIntent,
    RoleHandoffIntent,
)
from modules.logical_compiler.src.scheduling import ComponentScheduler

from .joint_cache import JointCalibrationCache
from .standard import FACTORY_ROLES, add_buffer_sites


def execute_transport_witness(task: dict[str, Any]) -> dict[str, Any]:
    """Run one exact three-hop exchange, requesting missing offline calibrations.

    Configuration must select d3/N2 and explicit parking coordinates. The fixture
    supplies one offered token and one working patch; their state preparation is
    explicitly outside this transport-only acceptance. No factory output count is
    returned and no output-error model is asserted.
    """
    from .campaign_worker import _CachedProfile, _context, calibration_dependency

    started = perf_counter()
    payload = task["payload"]
    if payload.get("acknowledge_prepared_token_fixture") is not True:
        raise ValueError("PREPARED_TOKEN_FIXTURE_ACKNOWLEDGEMENT_REQUIRED")
    world, _, arguments = _context(payload)
    if world.spec.distance != 3 or world.spec.pipelines != 2:
        raise ValueError("TRANSPORT_WITNESS_REQUIRES_D3_N2")
    world, parking = add_buffer_sites(
        world, {"exchange_parking": Position(**payload["parking_origin"])}
    )
    family = canonical_hash(
        {"world": world.document(), "actions": payload["dependencies"]["actions"]}
    )
    arguments["family"] = family
    slots = {
        p.binding.block_id: (p.binding.origin, p.home_sites) for p in world.patches
    } | parking
    document = JointSurfaceFactoryProfile.from_placement(
        world.placement_plan,
        family=family,
        noise_params=payload["noise_params"],
        additional_calls=(("se_round", ("factory0/W2",)),),
    ).to_dict()
    profile = _CachedProfile(
        document,
        world,
        JointCalibrationCache(payload["cache_root"]),
        arguments,
        transport_slots=slots,
    )
    execution = ProfileExecutionKernel(profile, profile.layout())
    backend = SurfaceFactoryBackend(
        profile, execution, FactoryExperimentModel("theory", 0)
    )
    signals: dict[str, Any] = {}
    consumer_owner = "factory1/fixture_input"
    source_id, replacement_id = "factory0/W1", "factory1/W2"

    class Producer(FactoryProcess):
        def flow(self) -> ProtocolFlow:
            yield CallIntent(
                ComponentCall("se", "se_round", ("W2",)), "factory0/witness"
            )
            self.ledger.complete_use(
                "factory0/W2",
                owner="factory0/fixture_se",
                at_us=self.execution.clock_us,
            )
            yield ResourceWaitIntent(
                "exchange", "wait_for_empty_receiver", lambda: "parked" in signals
            )
            token = self.ledger.token("prepared-token-fixture")
            parts = yield CallIntent(
                ComponentCall(
                    "deliver",
                    "block_translation",
                    ("W1",),
                    (("destination", replacement_id),),
                ),
                "factory0/witness",
                token=token,
                transport_owner=consumer_owner,
            )
            signals["delivered"] = parts[0]
            yield ResourceWaitIntent(
                "exchange", "wait_for_replacement", lambda: "handed_off" in signals
            )
            receipt = OutputHandoff(
                token.token_id,
                source_id,
                consumer_owner,
                self.execution.clock_us,
                replacement_id,
                self.execution.clock_us,
                {
                    "scope": "prepared_token_transport_fixture",
                    "delivery_trace_ref": parts[0].provenance["joint_trace_sha256"],
                },
            )
            receipt.validate(
                signals["offered"],
                self.ledger,
                self.execution.clock_us,
                output_carrier_id=self.roles["W1"],
                code_id=self.code,
                distance=3,
            )
            signals["handoff_receipt"] = receipt.to_dict()

    class Consumer(FactoryProcess):
        def flow(self) -> ProtocolFlow:
            self.ledger.reserve(
                "prepared-token-fixture",
                consumer=consumer_owner,
                at_us=self.execution.clock_us,
                expected_code=self.code,
                expected_kind=self.recipe.output_resource_kind,
                expected_distance=3,
                expected_canonicalization="canonical",
            )
            parked = yield CallIntent(
                ComponentCall(
                    "park",
                    "block_translation",
                    ("W2",),
                    (("destination", "exchange_parking"),),
                ),
                "factory1/witness",
                transport_owner=consumer_owner,
            )
            signals["parked"] = parked[0]
            yield ResourceWaitIntent(
                "exchange", "wait_for_source_delivery", lambda: "delivered" in signals
            )
            returned = yield CallIntent(
                ComponentCall(
                    "replace",
                    "block_translation",
                    ("W2",),
                    (("destination", source_id),),
                ),
                "factory1/witness",
                transport_owner=consumer_owner,
            )
            self.ledger.complete_use(
                replacement_id, owner=consumer_owner, at_us=self.execution.clock_us
            )
            bindings = {p.binding.block_id: p.binding for p in profile.world.patches}
            token = yield RoleHandoffIntent(
                "factory0",
                "factory1",
                "W1",
                "W2",
                "prepared-token-fixture",
                consumer_owner,
                source_id,
                replacement_id,
                (parked[0], signals["delivered"], returned[0]),
                self.execution.snapshot_id,
                (bindings[source_id], bindings[replacement_id]),
            )
            signals["handed_off"] = token.token_id

    processes = tuple(
        cls(
            f"factory{i}",
            code="rotated_surface_d3",
            recipe=factory_recipe(3),
            backend=backend,
            role_bindings={role: f"factory{i}/{role}" for role in FACTORY_ROLES},
            distance=3,
            cohort_id=f"level{i}",
        )
        for i, cls in enumerate((Producer, Consumer))
    )
    runtime = CooperativeFactoryRuntime(
        execution=execution,
        case_id="transport-only-prepared-token-fixture",
        seed=payload["production_seed"],
        scheduler=ComponentScheduler(),
        processes=processes,
    )
    carrier = runtime.ledger.begin_preparation(
        source_id, owner="factory0/fixture", at_us=0
    )
    signals["offered"] = runtime.ledger.offer(
        "prepared-token-fixture",
        carrier_id=source_id,
        epoch=carrier.epoch,
        owner="factory0/fixture",
        resource_kind=processes[0].recipe.output_resource_kind,
        producer="factory0/synthetic_fixture",
        ready_at_us=0,
        exit_at_us=0,
        canonicalization="canonical",
        quality={"status": "synthetic_fixture"},
        provenance={"state_preparation_executed": False},
    )
    runtime.ledger.begin_preparation(
        "factory0/W2", owner="factory0/fixture_se", at_us=0
    )
    runtime.ledger.finish_preparation(
        "factory0/W2", owner="factory0/fixture_se", at_us=0
    )
    try:
        case = runtime.run().to_dict()
    except MissingJointCalibration as missing:
        return {
            "status": "needs_dependencies",
            "reason": missing.to_dict(),
            "dependency_requests": [
                calibration_dependency(task, missing.members, request=missing.request)
            ],
            "software_seconds": {
                "cache_load": profile.cache_load_seconds,
                "fast_prefix": max(
                    0, perf_counter() - started - profile.cache_load_seconds
                ),
            },
        }
    if case["status"] != "complete" or "handoff_receipt" not in signals:
        return {
            "status": "software_error",
            "reason": "TRANSPORT_HANDOFF_WITNESS_FAILED",
            "result": {"case": case},
        }
    token = runtime.ledger.token("prepared-token-fixture")
    assert token.status == "reserved" and token.carrier_id == source_id
    assert tuple(a.id for a in profile.world.state.atoms) == tuple(
        a.id for a in world.state.atoms
    )
    assert len(world.state.atoms) == 204
    assert (
        processes[0].roles["W1"] == replacement_id
        and processes[1].roles["W2"] == source_id
    )
    assert runtime.ledger.carrier(replacement_id).epoch == 0
    assert runtime.ledger.carrier(replacement_id).phase == "free"
    result = {
        "scope": "prepared-token fixture; no L1 production, L2 consumption or output-quality claim",
        "case": case,
        "entry_world": world.document(),
        "exit_world": profile.world.document(),
        "handoff": signals["handoff_receipt"],
        "calibration_records": profile.cache_records,
        "prepared_token": asdict(signals["offered"]),
        "current_token": token.to_dict(),
        "two_level_runtime_complete": False,
        "logical_quality": None,
        "software_seconds": {
            "cache_load": profile.cache_load_seconds,
            "fast_execution": max(
                0, perf_counter() - started - profile.cache_load_seconds
            ),
        },
    }
    return {
        "status": "ok",
        "result": result,
        "artifacts": list(profile.artifacts.values()),
        "software_seconds": result["software_seconds"],
    }
