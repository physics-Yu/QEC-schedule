"""Object supply contracts, independent of expensive production samples."""

import pytest

from modules.codes.rotated_surface.object_delivery import DeliveryObjectProfile
from modules.codes.rotated_surface.object_factory import FactoryObjectCatalog
from modules.logical_compiler.src.protocols.object_supply import ObjectFactorySupply
from modules.logical_compiler.src.protocols.resources import ResourceLedger


def supply_world(consumers=1):
    """Small ownership control, not a factory production result."""
    from modules.codes.rotated_surface.fast_factory import factory_recipe
    from modules.codes.rotated_surface.object_factory import FactoryObjectBackend
    from modules.codes.rotated_surface_d3.protocols.factory_experiment import (
        FactoryExperimentModel,
    )
    from modules.logical_compiler.src.estimation.kernel import ProfileExecutionKernel
    from modules.logical_compiler.src.protocols.cooperative import (
        CooperativeFactoryRuntime,
    )
    from modules.logical_compiler.src.protocols.factory_process import FactoryProcess
    from modules.logical_compiler.src.scheduling import ComponentScheduler

    catalog = FactoryObjectCatalog.load(distance=3)
    layout = catalog.layout(consumers + 1)
    profile = DeliveryObjectProfile(catalog, layout)
    execution = ProfileExecutionKernel(profile, layout)
    model = FactoryExperimentModel("theory", 0.01)
    consumer_model = FactoryExperimentModel(
        "theory",
        model.output_quality(model.final_theory_event())["consumption_parameters"][
            "input_z_error"
        ],
    )
    processes = tuple(
        FactoryProcess(
            f.factory_id,
            code=catalog.code_id,
            recipe=factory_recipe(3),
            backend=FactoryObjectBackend(
                profile, execution, model if i == 0 else consumer_model
            ),
            role_bindings={r: p.block_id for r, p in f.bindings.items()},
            distance=3,
            cohort_id=f.factory_id,
        )
        for i, f in enumerate(layout.factories)
    )
    runtime = CooperativeFactoryRuntime(
        execution=execution,
        case_id="supply-contract-control",
        seed=0,
        scheduler=ComponentScheduler(),
        processes=processes,
    )
    supply = ObjectFactorySupply(capacity=1, parking=(600.0, -60.0))
    supply.producers, supply.consumers = [processes[0]], list(processes[1:])
    for p in processes:
        p.status = "running"
        p.cycle_index = 0
    return supply, runtime, processes


def offer_output(producer, index, *, bad_quality=False):
    """Issue a declared token for a lifecycle unit control only."""
    now = producer.execution.clock_us
    carrier = producer.ledger.begin_preparation(
        producer.roles["W1"], owner="producer", at_us=now
    )
    port = producer.backend.model.final_theory_event()
    return producer.ledger.offer(
        f"output-{index}",
        carrier_id=carrier.carrier_id,
        epoch=carrier.epoch,
        owner="producer",
        resource_kind=producer.recipe.output_resource_kind,
        producer="producer",
        ready_at_us=now,
        exit_at_us=now,
        canonicalization="canonical",
        quality={} if bad_quality else producer.backend.model.output_quality(port),
        provenance={"port_sha256": port.content_sha256},
    )


def drive_delivery(flow, process, runtime, *, stop_after=None):
    """Execute only transport intents on the real shared kernel and scheduler."""
    from modules.logical_compiler.src.protocols.execution_kernel import ExecutionRequest
    from modules.logical_compiler.src.protocols.protocol_intents import CallIntent
    from modules.logical_compiler.src.scheduling import ComponentNode

    intent = next(flow)
    for leg in range(3):
        assert isinstance(intent, CallIntent)
        blocks = intent.participants(process.roles)
        scheduler, execution = runtime.scheduler, runtime.execution
        scheduler.add(
            ComponentNode(
                intent.invocation_id,
                execution.describe(process.backend, intent.call, blocks),
            )
        )
        admission = scheduler.admit(
            execution.clock_us, snapshot_id=execution.snapshot_id
        )
        receipts = execution.execute(
            admission,
            (
                ExecutionRequest(
                    intent.invocation_id, process.backend, intent.call, blocks
                ),
            ),
        )
        receipt = receipts[intent.invocation_id][0]
        carrier = runtime.ledger.carrier(blocks[0])
        runtime.ledger.extend_transport(
            blocks[0],
            owner=carrier.owner,
            at_us=receipt.start_us,
            safe_exit_at_us=receipt.action_end_us,
        )
        scheduler.commit_admission(admission)
        scheduler.mark_completed(intent.invocation_id, receipt.action_end_us)
        try:
            intent = flow.send((receipt,))
        except StopIteration as result:
            assert leg == 2
            return result.value
        if stop_after == leg + 1:
            return intent
    raise AssertionError("Three legs must complete delivery")


def test_progressive_four_adoptions_and_reserved_r_preserve_carriers_with_b1():
    supply, runtime, (producer, consumer) = supply_world()
    initial_ids = {c["carrier_id"] for c in runtime.ledger.snapshot()["carriers"]}
    preparations = [
        p for p in consumer.recipe.initial_preparations if p.resource_kind
    ] + [consumer.recipe.rotations[0].preparation]
    for i, prep in enumerate(preparations):
        flow = supply.prepare(consumer, prep, f"consumer/{i}", f"owner/{i}")
        wait = next(flow)
        assert not wait.ready()
        original = offer_output(producer, i)
        publication = supply(producer, original)
        assert next(publication).ready()
        pubwait = next(publication)
        assert wait.ready() and not pubwait.ready()
        received = drive_delivery(flow, consumer, runtime)
        assert received.token_id == original.token_id
        assert (received.carrier_id, received.epoch) == (
            original.carrier_id,
            original.epoch,
        )
        assert len(supply.queue) == 0
        assert runtime.ledger.carrier(received.carrier_id).owner == f"owner/{i}"
        assert runtime.ledger.carrier(producer.roles["W1"]).owner is None
        assert pubwait.ready()
        with pytest.raises(StopIteration) as done:
            next(publication)
        done.value.value.validate(original, runtime.ledger, runtime.execution.clock_us)
    assert received.status == "reserved"  # R delivery is not consumption.
    assert all(
        runtime.ledger.token(f"output-{i}").usage_kind == "adopt" for i in range(4)
    )
    assert {
        c["carrier_id"] for c in runtime.ledger.snapshot()["carriers"]
    } == initial_ids
    assert len(runtime.execution.profile.moves) == 15
    assert max(h["queue_size"] for h in supply.history) == 1


def test_b1_delivers_to_two_r_slots_before_either_consumes():
    supply, runtime, (producer, first, second) = supply_world(consumers=2)
    for i, consumer in enumerate((first, second)):
        flow = supply.prepare(
            consumer, consumer.recipe.rotations[0].preparation, f"c{i}", f"owner{i}"
        )
        wait = next(flow)
        publication = supply(producer, offer_output(producer, i))
        next(publication)
        next(publication)
        assert wait.ready()
        received = drive_delivery(flow, consumer, runtime)
        assert received.status == "reserved"
        assert not supply.queue
        with pytest.raises(StopIteration):
            next(publication)
    assert (
        runtime.ledger.token("output-0").status
        == runtime.ledger.token("output-1").status
        == "reserved"
    )


def test_wrong_quality_duplicate_publication_and_supply_exhaustion_are_explicit():
    supply, runtime, (producer, consumer) = supply_world()
    flow = supply.prepare(
        consumer, consumer.recipe.rotations[0].preparation, "c", "owner"
    )
    wait = next(flow)
    producer.status = "complete"
    with pytest.raises(Exception, match="producers="):
        wait.ready()
    producer.status = "running"
    token = offer_output(producer, 0, bad_quality=True)
    publication = supply(producer, token)
    next(publication)
    next(publication)
    with pytest.raises(ValueError, match="DUPLICATE"):
        next(supply(producer, token))
    assert wait.ready()
    with pytest.raises(ValueError, match="QUALITY"):
        next(flow)
    assert not runtime.execution.profile.moves
    assert runtime.ledger.token(token.token_id).status == "offered"


def test_partial_exchange_preserves_position_token_and_parking_reservation():
    supply, runtime, (producer, consumer) = supply_world()
    prep = consumer.recipe.rotations[0].preparation
    receiver = consumer.roles[prep.role]
    flow = supply.prepare(consumer, prep, "c", "owner")
    wait = next(flow)
    publication = supply(producer, offer_output(producer, 0))
    next(publication)
    next(publication)
    assert wait.ready()
    drive_delivery(flow, consumer, runtime, stop_after=1)
    assert len(runtime.execution.profile.moves) == 1
    origin = runtime.execution.profile._patches[receiver].origin
    assert (origin.x, origin.y) == supply.parking
    assert consumer.roles[prep.role] == receiver  # No premature role handoff.
    assert supply.parking_owner is not None and len(supply.queue) == 1
    assert runtime.ledger.token("output-0").status == "reserved"


def test_busy_oldest_receiver_does_not_block_an_eligible_demand():
    supply, runtime, (producer, first, second) = supply_world(consumers=2)
    prep = first.recipe.rotations[0].preparation
    runtime.ledger.claim_transport(first.roles["R"], owner="occupied", at_us=0)
    blocked_flow = supply.prepare(first, prep, "blocked", "blocked-owner")
    blocked = next(blocked_flow)
    eligible_flow = supply.prepare(second, prep, "eligible", "eligible-owner")
    eligible = next(eligible_flow)
    publication = supply(producer, offer_output(producer, 0))
    next(publication)
    next(publication)
    assert not blocked.ready() and eligible.ready()
    supply.parking_owner = "another-exchange"
    assert not eligible.ready()
    supply.parking_owner = None
    assert eligible.ready()


def test_closure_retains_surplus_without_fake_release_or_unending_admission():
    supply, runtime, (producer, consumer) = supply_world()
    token = offer_output(producer, 0)
    publication = supply(producer, token)
    next(publication)
    wait = next(publication)
    supply.close(consumer)
    assert wait.ready()
    with pytest.raises(StopIteration) as done:
        next(publication)
    disposition = done.value.value
    disposition.validate(token, runtime.ledger, runtime.execution.clock_us)
    assert disposition.retained and not supply.queue
    assert runtime.ledger.token(token.token_id).status == "offered"
    assert runtime.ledger.carrier(token.carrier_id).owner == "producer"


def test_next_attempt_uses_new_token_and_preserves_used_lineage():
    supply, runtime, (producer, consumer) = supply_world()
    prep = next(p for p in consumer.recipe.initial_preparations if p.resource_kind)
    for cycle in range(2):
        consumer.cycle_index = cycle
        flow = supply.prepare(consumer, prep, f"round{cycle}", f"owner{cycle}")
        wait = next(flow)
        publication = supply(producer, offer_output(producer, cycle))
        next(publication)
        next(publication)
        assert wait.ready()
        received = drive_delivery(flow, consumer, runtime)
        with pytest.raises(StopIteration):
            next(publication)
        assert supply.lineage(consumer) == {"input_token_ids": [f"output-{cycle}"]}
        consumer._release((prep.role,))  # Same work-abandonment boundary as rejection.
        assert runtime.ledger.token(received.token_id).status == "consumed"
    assert runtime.ledger.token("output-0").status == "consumed"
    assert supply.deliveries[0]["token_id"] != supply.deliveries[1]["token_id"]


def test_versioned_move_commit_cannot_be_replayed():
    supply, runtime, (producer, consumer) = supply_world()
    flow = supply.prepare(
        consumer, consumer.recipe.rotations[0].preparation, "c", "owner"
    )
    wait = next(flow)
    publication = supply(producer, offer_output(producer, 0))
    next(publication)
    next(publication)
    assert wait.ready()
    drive_delivery(flow, consumer, runtime)
    with pytest.raises(ValueError, match="STALE"):
        runtime.execution.commit_transport(supply.deliveries[0]["receipt_ids"][-1])


def test_real_single_pair_independent_sync_cohorts_reuse_objects(monkeypatch):
    """Two bounded real recipes, not the synthetic lifecycle controls above."""
    from modules.logical_compiler.examples.factory_level2 import run_level2
    from modules.logical_compiler.examples.object_cases import forbid_atom_work

    with forbid_atom_work() as guards:
        catalog = FactoryObjectCatalog.load(distance=3)
        ids = {key: id(value) for key, value in catalog.entries.items()}
        first = run_level2(catalog, seed=0)
        second = run_level2(catalog, seed=0, strategy="synchronous")
    assert first["case"]["events"] == second["case"]["events"]
    assert first["summary"]["makespan_us"] == second["summary"]["makespan_us"]
    assert second["summary"]["component_reuse"]["bound_cost_misses"] == 0
    assert ids == {key: id(value) for key, value in catalog.entries.items()}
    assert all(v == 0 for v in guards.values())
    assert (
        second["case"]["factories"]["L1-factory0"]["cohort_id"]
        != second["case"]["factories"]["L2-factory0"]["cohort_id"]
    )
    assert first["summary"]["inputs_delivered"] == 15
    assert first["summary"]["counts"]["block_delivery"] == 45
    assert first["summary"]["raw_rejections"] > 0
    output = next(
        t
        for t in first["case"]["resources"]["tokens"]
        if t["token_id"] == "L2-factory0/cycle[0]/batch[0]/output"
    )
    assert len(output["provenance"]["input_token_ids"]) == 15


def test_buffer_requires_positive_integer_capacity():
    for capacity in (0, -1, True, 1.5):
        with pytest.raises(ValueError, match="CAPACITY"):
            ObjectFactorySupply(capacity=capacity, parking=(600.0, -60.0))


@pytest.mark.parametrize("distance", [3, 5, 7, 9, 11])
@pytest.mark.parametrize(
    "placement,columns", [("vertical", None), ("horizontal", None), ("grid", 2)]
)
def test_two_level_layout_reuses_l1_placement_and_scales_geometry(
    distance, placement, columns
):
    from modules.codes.rotated_surface.object_delivery import factory_supply_layout
    from modules.logical_compiler.examples.object_cases import forbid_atom_work

    with forbid_atom_work() as guards:
        catalog = FactoryObjectCatalog.load(distance=distance)
        before = {k: id(v) for k, v in catalog.entries.items()}
        layout = factory_supply_layout(
            catalog, producers=4, placement=placement, columns=columns
        )
        original = catalog.layout(4, placement=placement, columns=columns)
    assert all(v == 0 for v in guards.values())
    assert before == {k: id(v) for k, v in catalog.entries.items()}
    assert len(layout.factories) == 5
    assert layout.factories[-1].factory_id == "L2-factory0"
    for actual, expected in zip(layout.factories[:4], original.factories, strict=True):
        assert [p.origin for p in actual.patches] == [
            p.origin for p in expected.patches
        ]
    assert max(p.origin.y + 20 * distance for p in layout.factories[-1].patches) < min(
        p.origin.y for f in layout.factories[:4] for p in f.patches
    )
    assert (
        layout.budget["atom_count_estimate"]
        == original.budget["atom_count_estimate"] * 5 // 4
    )
    assert layout.budget["parking"]["width_um"] == 20 * distance
    assert len(layout.bindings) == 30


def test_invalid_two_level_configuration_has_no_build_fallback():
    from modules.codes.rotated_surface.object_delivery import factory_supply_layout

    catalog = FactoryObjectCatalog.load()
    for count in (0, -1, True, 1.2):
        with pytest.raises(ValueError, match="COUNT"):
            factory_supply_layout(catalog, producers=count)
    with pytest.raises(ValueError, match="GRID_COLUMNS_REQUIRED"):
        factory_supply_layout(catalog, producers=2, placement="grid")


@pytest.mark.parametrize("position", ["below_center", "right_center", "above_center"])
def test_scan_consumer_position_uses_exact_frozen_coordinates(position):
    from modules.codes.rotated_surface.object_delivery import factory_supply_layout

    layout = factory_supply_layout(
        FactoryObjectCatalog.load(),
        producers=6,
        placement="grid",
        columns=3,
        level2_position=position,
    )
    origin = layout.factories[-1].patches[0].origin
    expected = {
        "below_center": (600, -260),
        "right_center": (1800, -110),
        "above_center": (600, -60),
    }
    assert (origin.x, origin.y) == expected[position]
    assert layout.factories[0].patches[0].origin.y == (
        -160 if position == "above_center" else -60
    )
    assert layout.budget["atom_count_estimate"] == 7 * 102


@pytest.mark.parametrize("strategy", ["asynchronous", "synchronous"])
def test_two_producers_progress_with_b1_and_preserve_all_output_dispositions(strategy):
    from modules.logical_compiler.examples.factory_level2 import run_level2
    from modules.logical_compiler.examples.object_cases import forbid_atom_work

    with forbid_atom_work() as guards:
        result = run_level2(
            FactoryObjectCatalog.load(), seed=0, level1_factories=2, strategy=strategy
        )
    case, supply, summary = result["case"], result["supply"], result["summary"]
    assert case["status"] == "complete" and summary["inputs_delivered"] == 15
    assert summary["allocated_atoms"] == 306
    assert len(case["resources"]["carriers"]) == 18
    assert max(h["queue_size"] for h in supply["history"]) == 1
    assert not supply["queue"] and not supply["pending"] and not supply["unmet_demands"]
    assert summary["level1_outputs"] == 15 + summary["retained_surplus"]
    assert all(n == 0 for n in guards.values())
    assert len({d["token_id"] for d in supply["deliveries"]}) == 15
    assert {d["producer"] for d in supply["deliveries"]} == {
        "L1-factory0",
        "L1-factory1",
    }
    assert summary["drain_completion_us"] >= summary["level2_completion_us"]
    tokens = {t["token_id"]: t for t in case["resources"]["tokens"]}
    for factory in (case["factories"]["L1-factory0"], case["factories"]["L1-factory1"]):
        for cycle in factory["production_cycles"]:
            delivery = cycle["delivery"]
            if delivery["evidence"]["kind"] == "retained":
                assert tokens[delivery["token_id"]]["status"] == "offered"
    if strategy == "synchronous":
        assert (
            case["factories"]["L1-factory0"]["cohort_id"]
            == case["factories"]["L1-factory1"]["cohort_id"]
        )
        assert (
            case["factories"]["L1-factory0"]["cohort_id"]
            != case["factories"]["L2-factory0"]["cohort_id"]
        )
        assert len(set(summary["level1_rounds_by_factory"].values())) == 1


def test_delivery_cost_is_three_moves_and_six_transfers():
    catalog = FactoryObjectCatalog.load(distance=3)
    layout = catalog.layout(2)
    profile = DeliveryObjectProfile(catalog, layout)
    patch = layout.factories[0].patches[0]
    entry = profile.lookup(
        "block_delivery",
        (patch,),
        parameters=(("x", 600.0), ("y", -60.0), ("version", 0)),
    )
    assert [s.category for s in entry.stages] == ["transfer", "movement", "transfer"]
    assert (
        sum(entry.phase_durations_us) == 20 + 600 * catalog.document["move_us_per_um"]
    )
    assert all(s.resources == ("aod:transport",) for s in entry.stages)
    assert not entry.measurement_phases


def test_stale_binding_and_invalid_destination_fail_before_motion():
    catalog = FactoryObjectCatalog.load(distance=3)
    layout = catalog.layout(2)
    profile = DeliveryObjectProfile(catalog, layout)
    patch = layout.factories[0].patches[0]
    with pytest.raises(ValueError, match="STALE"):
        profile.lookup(
            "block_delivery",
            (patch,),
            parameters=(("x", 600), ("y", -60), ("version", 1)),
        )
    with pytest.raises(ValueError, match="STORAGE"):
        profile.lookup(
            "block_delivery",
            (patch,),
            parameters=(("x", 600), ("y", 0), ("version", 0)),
        )


def test_transport_preserves_epoch_and_reserved_token():
    ledger = ResourceLedger()
    ledger.register_logical_carrier("c", code_id="surface", distance=3)
    carrier = ledger.begin_preparation("c", owner="producer", at_us=0)
    token = ledger.offer(
        "t",
        carrier_id="c",
        epoch=carrier.epoch,
        owner="producer",
        resource_kind="A",
        producer="p",
        ready_at_us=0,
        exit_at_us=0,
        canonicalization="canonical",
        quality={},
        provenance={},
    )
    ledger.reserve(
        "t",
        consumer="consumer",
        at_us=0,
        expected_code="surface",
        expected_kind="A",
        expected_canonicalization="canonical",
        expected_distance=3,
    )
    ledger.extend_transport("c", owner="consumer", at_us=0, safe_exit_at_us=20)
    assert ledger.token("t").status == "reserved"
    assert ledger.carrier("c").epoch == token.epoch
    with pytest.raises(ValueError, match="SAFE"):
        ledger.consume("t", consumer="consumer", at_us=10, safe_exit_at_us=10)
    with pytest.raises(ValueError, match="OWNER"):
        ledger.extend_transport("c", owner="other", at_us=20, safe_exit_at_us=30)
