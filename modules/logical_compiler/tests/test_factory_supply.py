"""Synthetic bounded L1 supply lifecycles; no physical or quality validation."""

from dataclasses import replace
from hashlib import sha256

import pytest
from nadit_physical_compiler.device import Position
from test_factory_execution import CODE, consumption, preparation, toy_recipe
from test_scheduled_factory import BatchedPhysical, DeclaredBackend

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
):
    physical = SyntheticPhysical(fail_delivery=fail_delivery, fail_park=fail_park)
    producer_roles = ("W1", "W2", "R")
    consumer_roles = ("W1", "W2", "W3", "W4", "W5", "R")
    fixed_roles = [
        (f"producer{i}", role) for i in range(producers) for role in producer_roles
    ]
    fixed_roles += [("consumer", role) for role in consumer_roles]
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
    )
    received = []

    class Consumer(FactoryProcess):
        def flow(self):
            scope = "consumer/batch[0]"
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
            cohort_id="L1",
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
    consumer = Consumer(
        "consumer",
        code=CODE,
        recipe=consumer_recipe,
        backend=SyntheticBackend(),
        role_bindings={r: f"consumer/{r}" for r in consumer_roles},
        distance=1,
        cohort_id="L2",
        external_inputs=True,
        preparation_supplier=supply.consumer_supplier,
    )
    supply.bind_processes(producer_processes, (consumer,))
    runtime = CooperativeFactoryRuntime(
        physical,
        case_id="synthetic-factory-supply",
        seed=0,
        scheduler=ComponentScheduler(),
        processes=(*producer_processes, consumer),
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


def test_supply_requires_finite_capacity_and_explicit_quality():
    with pytest.raises(ValueError):
        FactorySupply(
            "inputs",
            0,
            "parking",
            {},
            {"input_z_error": 0},
            current_bindings=lambda ids: (),
        )


def test_one_real_process_supplies_four_adopted_and_one_reserved_input(monkeypatch):
    runtime, supply, received = build_supply(monkeypatch)
    case = runtime.run().to_dict()
    assert case["status"] == "complete", case["factories"]
    assert len(received) == 5
    assert [t.usage_kind for t in received[:4]] == ["adopt"] * 4
    assert received[4].status == "reserved"
    assert len({t.token_id for t in received}) == 5
    source_outputs = case["factories"]["producer0"]["outputs"]
    by_id = {row["token_id"]: row for row in source_outputs}
    for token in received:
        assert token.carrier_id == by_id[token.token_id]["carrier_id"]
        assert token.epoch == by_id[token.token_id]["epoch"]
        assert token.quality == by_id[token.token_id]["quality"]
        assert by_id[token.token_id]["handoff_at_us"] is not None
        assert by_id[token.token_id]["consumed_at_us"] is None
    report = supply.snapshot(ledger=runtime.ledger, at_us=runtime.execution.clock_us)
    assert report["counts"]["supplied"] == 5
    assert report["counts"]["reclaimed"] >= 4
    assert report["parking_lease"] is None and report["failure"] is None
    assert len(runtime.physical.transports) == 15
    assert not any(
        c["component_id"] == "toy.raw" and c["factory_id"] == "consumer"
        for c in case["calls"]
    )
    assert all(runtime.ledger.token(t.token_id).status == "consumed" for t in received)
    retained = [row for row in source_outputs if row.get("retained_at_us") is not None]
    assert retained
    for row in retained:
        assert runtime.ledger.token(row["token_id"]).status == "offered"
        assert row["consumed_at_us"] is row["released_at_us"] is None


def test_capacity_one_backpressures_producers_and_preserves_fifo(monkeypatch):
    runtime, supply, _ = build_supply(monkeypatch, producers=2, delay=200)
    case = runtime.run().to_dict()
    assert case["status"] == "complete", case["factories"]
    waits = [m for m in case["milestones"] if m.get("state") == "waiting_buffer"]
    assert waits
    report = supply.snapshot(ledger=runtime.ledger, at_us=runtime.execution.clock_us)
    assert [d["producer_id"] for d in report["deliveries"][:2]] == [
        "producer0",
        "producer1",
    ]
    occupancy = 0
    for event in report["buffer"]["audit"]:
        if event["action"] == "reserve_capacity":
            occupancy += 1
        elif event["action"] in ("remove", "abort_reservation"):
            occupancy -= 1
        assert 0 <= occupancy <= 1
    assert "producer-carrier-held" in report["storage"]


def test_all_fifteen_real_toy_outputs_reuse_receiving_role_without_stale_inventory(
    monkeypatch,
):
    runtime, supply, received = build_supply(monkeypatch, cycles=20, rotation_inputs=11)
    case = runtime.run().to_dict()
    assert case["status"] == "complete", case["factories"]
    assert len(received) == len({token.token_id for token in received}) == 15
    assert [token.usage_kind for token in received[:4]] == ["adopt"] * 4
    assert all(token.status == "reserved" for token in received[4:])
    report = supply.snapshot(ledger=runtime.ledger, at_us=runtime.execution.clock_us)
    assert report["counts"]["supplied"] == 15
    assert report["counts"]["reclaimed"] >= 14
    assert len(runtime.physical.transports) == 45
    assert [
        identity.rsplit("/", 1)[-1] for identity in runtime.physical.transports
    ] == ["park", "deliver", "replace"] * 15
    assert all(
        runtime.ledger.token(token.token_id).status == "consumed" for token in received
    )


def test_source_exhaustion_is_explicit_without_inventing_inputs(monkeypatch):
    runtime, supply, received = build_supply(monkeypatch, cycles=2)
    case = runtime.run().to_dict()
    assert case["factories"]["consumer"]["status"] == "external_supply_exhausted"
    assert len(case["factories"]["producer0"]["outputs"]) == 2
    assert len(received) <= 2
    assert (
        supply.snapshot(ledger=runtime.ledger, at_us=runtime.execution.clock_us)[
            "counts"
        ]["supplied"]
        == 2
    )


def test_delivery_failure_wakes_receiver_and_preserves_failure_evidence(monkeypatch):
    runtime, supply, _ = build_supply(monkeypatch, fail_delivery=True)
    case = runtime.run().to_dict()
    assert case["status"] == "partial_failure"
    assert case["factories"]["producer0"]["status"] == "physical_failure"
    assert case["factories"]["consumer"]["status"] == "supply_delivery_failed"
    report = supply.snapshot(ledger=runtime.ledger, at_us=runtime.execution.clock_us)
    assert report["failure"] and report["counts"]["supplied"] == 0
    assert len(runtime.physical.transports) == 1


def test_receiver_failure_wakes_producer_without_reusing_parking(monkeypatch):
    runtime, supply, _ = build_supply(monkeypatch, fail_park=True)
    case = runtime.run().to_dict()
    assert case["factories"]["consumer"]["status"] == "physical_failure"
    assert case["factories"]["producer0"]["status"] == "supply_delivery_failed"
    report = supply.snapshot(ledger=runtime.ledger, at_us=runtime.execution.clock_us)
    assert report["failure"] and report["counts"]["claimed"] == 1
    assert report["counts"]["handed_off"] == 0


def test_invalid_input_quality_rejected_before_claim_or_transport(monkeypatch):
    runtime, supply, _ = build_supply(monkeypatch, quality=0.02)
    case = runtime.run().to_dict()
    assert case["factories"]["producer0"]["status"] == "unsupported_resource_quality"
    assert case["factories"]["consumer"]["status"] == "external_supply_exhausted"
    assert not runtime.physical.transports
    assert (
        supply.snapshot(ledger=runtime.ledger, at_us=runtime.execution.clock_us)[
            "counts"
        ]["claimed"]
        == 0
    )
