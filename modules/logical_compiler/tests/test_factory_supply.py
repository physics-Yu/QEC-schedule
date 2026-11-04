"""Synthetic bounded L1 supply lifecycles; no physical or quality validation."""

from dataclasses import replace
from hashlib import sha256

from nadit_physical_compiler.device import Position
from scheduled_factory_fixtures import BatchedPhysical, DeclaredBackend
from test_factory_execution import CODE, consumption, preparation, toy_recipe

from modules.codes.contracts.component import ComponentBinding
from modules.logical_compiler.src.protocols.cooperative import CooperativeFactoryRuntime
from modules.logical_compiler.src.protocols.factory_process import FactoryProcess
from modules.logical_compiler.src.protocols.factory_supply import FactorySupply
from modules.logical_compiler.src.protocols.production import ProductionPolicy
from modules.logical_compiler.src.protocols.protocol_intents import (
    ParallelFlows,
    WaitIntent,
)
from modules.logical_compiler.src.scheduling import ComponentScheduler


class SyntheticBackend(DeclaredBackend):
    """Existing toy factory gates; declared quality is only a test control."""

    def __init__(self, quality=0.01):
        super().__init__()
        self.quality = quality

    def output_quality(self, port):
        return {
            "status": "synthetic_fixture",
            "consumption_parameters": {"input_z_error": self.quality},
        }

    def bind_call(self, component_id, participant_bindings, parameters=()):
        if component_id == "block_translation":
            bound = super().bind_call(component_id, participant_bindings)
            bound.destination = dict(parameters)["destination"]
            return bound
        return super().bind_call(component_id, participant_bindings, parameters)


class SyntheticPhysical(BatchedPhysical):
    """Clock-only endpoint bookkeeping; no native planning or physical checking."""

    def __init__(self, *, fail_delivery=False, fail_park=False):
        super().__init__()
        self.slots = {}
        self.transports = {}
        self.fail_delivery = fail_delivery
        self.fail_park = fail_park

    def invoke(self, bound, invocation_id, result_count=None, *, not_before_us=0):
        mechanical = bound.component_id == "block_translation"
        if mechanical and (
            (self.fail_delivery and invocation_id.endswith("/deliver"))
            or (self.fail_park and invocation_id.endswith("/park"))
        ):
            raise ValueError("SYNTHETIC_DELIVERY_FAILURE")
        entry = bound.bindings[0]
        result = super().invoke(
            bound, invocation_id, result_count, not_before_us=not_before_us
        )
        if mechanical:
            exit_binding = replace(entry, origin=self.slots[bound.destination])
            self.bindings[entry.block_id] = exit_binding
            self.transports[invocation_id] = (entry, exit_binding)
        return result


def build_supply(
    monkeypatch,
    *,
    producers=1,
    cycles=10,
    capacity=1,
    delay=0,
    quality=0.01,
    fail_delivery=False,
    fail_park=False,
    initial_inputs=4,
    rotation_inputs=1,
    consumers=1,
    slow_first_rotation=0,
    supply_mode="pipelined",
    separate_consumers=False,
    supplier_override=None,
):
    physical = SyntheticPhysical(fail_delivery=fail_delivery, fail_park=fail_park)
    producer_roles = ("W1", "W2", "R")
    consumer_roles = ("W1", "W2", "W3", "W4", "W5", "R")
    fixed_roles = [
        (f"producer{i}", role) for i in range(producers) for role in producer_roles
    ]
    consumer_ids = (
        ["consumer"] if consumers == 1 else [f"consumer{i}" for i in range(consumers)]
    )
    fixed_roles += [
        (identity, role) for identity in consumer_ids for role in consumer_roles
    ]
    physical.bindings = {
        f"{factory}/{role}": ComponentBinding(
            f"{factory}/{role}", Position(index * 10, 0), (index,), "synthetic_aod"
        )
        for index, (factory, role) in enumerate(fixed_roles)
    }
    slots = {key: key for key in fixed_roles}
    slot_names = {key: f"{key[0]}/{key[1]}" for key in slots}
    physical.slots = {
        name: binding.origin for name, binding in physical.bindings.items()
    }
    physical.slots["parking"] = Position(-50, 0)
    supply = FactorySupply(
        "inputs",
        capacity,
        "parking",
        slot_names,
        {"input_z_error": 0.01},
        current_bindings=lambda ids: tuple(physical.bindings[i] for i in ids),
        supply_mode=supply_mode,
    )
    received = []

    class Consumer(FactoryProcess):
        def flow(self):
            scope = f"{self.factory_id}/batch[0]"
            yield from self._prepare(preparation("W1", working=True), scope, scope)
            if delay:
                yield WaitIntent(
                    self.execution.clock_us + delay, "synthetic_consumer_delay"
                )
            adopted = yield ParallelFlows(
                tuple(
                    self._prepare(preparation(role), scope, scope)
                    for role in consumer_roles[1 : 1 + initial_inputs]
                )
            )
            received.extend(adopted)
            for index in range(rotation_inputs):
                key = f"rotation[{index}]"
                token = yield from self._prepare(
                    replace(preparation("R"), key=f"{key}/raw"),
                    scope,
                    scope + "/" + key,
                )
                received.append(token)
                assert token.status == "reserved"
                if (
                    slow_first_rotation
                    and self.factory_id == consumer_ids[-1]
                    and index == 0
                ):
                    yield WaitIntent(
                        self.execution.clock_us + slow_first_rotation,
                        "delayed_consumption",
                    )
                yield from self._consume(
                    consumption(key=key, selector=f"t:{key}"), scope, token
                )
                self._release(("R",))
            self._release(consumer_roles)

    producer_processes = tuple(
        FactoryProcess(
            f"producer{i}",
            code=CODE,
            recipe=toy_recipe(),
            backend=SyntheticBackend(quality),
            role_bindings={r: f"producer{i}/{r}" for r in producer_roles},
            distance=1,
            cohort_id=f"L1-{i}" if supply_mode == "synchronized_consumption" else "L1",
            production_policy=ProductionPolicy(cycles),
            output_sink=supply.producer_sink,
            production_continuation=supply.production_continuation,
        )
        for i in range(producers)
    )
    consumer_recipe = replace(
        toy_recipe(),
        work_roles=consumer_roles[:-1],
        retry_work_roles=consumer_roles[:-1],
        released_roles=consumer_roles[1:],
        initial_preparations=tuple(
            preparation(r, working=r == "W1") for r in consumer_roles[:-1]
        ),
    )
    consumer_processes = tuple(
        Consumer(
            identity,
            code=CODE,
            recipe=consumer_recipe,
            backend=SyntheticBackend(),
            role_bindings={r: f"{identity}/{r}" for r in consumer_roles},
            distance=1,
            cohort_id=identity if separate_consumers else "L2",
            external_inputs=True,
            preparation_supplier=supplier_override or supply.consumer_supplier,
        )
        for identity in consumer_ids
    )
    supply.bind_processes(producer_processes, consumer_processes)
    runtime = CooperativeFactoryRuntime(
        physical,
        case_id="synthetic-factory-supply",
        seed=0,
        scheduler=ComponentScheduler(),
        processes=(*producer_processes, *consumer_processes),
    )

    def transport_evidence(receipt):
        assert receipt.invocation_id in physical.transports
        return {
            key: sha256((receipt.invocation_id + "/" + key).encode()).hexdigest()
            for key in (
                "trace_sha256",
                "entry_world_sha256",
                "exit_world_sha256",
                "entry_binding_sha256",
                "exit_binding_sha256",
            )
        }

    def validate_handoff(receipts, *, expected_snapshot_id, expected_bindings):
        assert expected_snapshot_id == runtime.execution.snapshot_id
        assert len(receipts) == 3
        for receipt in receipts:
            assert receipt.invocation_id in physical.transports
        for binding in expected_bindings:
            assert physical.bindings[binding.block_id] == binding

    monkeypatch.setattr(
        runtime.execution, "transport_evidence", transport_evidence, raising=False
    )
    monkeypatch.setattr(
        runtime.execution, "validate_handoff_transport", validate_handoff, raising=False
    )
    return runtime, supply, received


def test_synchronized_supply_waits_for_last_consumer(monkeypatch):
    runtime, _, _ = build_supply(
        monkeypatch,
        producers=1,
        consumers=2,
        capacity=2,
        initial_inputs=1,
        rotation_inputs=2,
        slow_first_rotation=1000,
        supply_mode="synchronized_consumption",
    )
    case = runtime.run().to_dict()
    assert case["status"] == "complete", case["factories"]
    starts = [
        event["at_us"]
        for event in case["milestones"]
        if event["kind"] == "production_cycle_started"
    ]
    used = [
        event["at_us"]
        for event in case["milestones"]
        if event["kind"] == "resource_consumption_complete"
        and event["recipe"] == "rotation[0]"
    ]
    assert len(used) == 2 and min(used) < max(used)
    # The first four outputs supply two adoptions and both first-rotation states.
    assert len(starts) == 6
    assert starts[4] >= max(used)
