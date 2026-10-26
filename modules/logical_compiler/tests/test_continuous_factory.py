"""Synthetic continuous-production lifecycles; no physical delivery claims."""

from dataclasses import replace
from itertools import pairwise

import pytest
from nadit_physical_compiler.device import Position
from test_factory_execution import CODE, consumption, preparation, toy_recipe
from test_scheduled_factory import BatchedPhysical, DeclaredBackend

from modules.codes.contracts.component import ComponentBinding
from modules.logical_compiler.src.protocols.cooperative import CooperativeFactoryRuntime
from modules.logical_compiler.src.protocols.factory import FactoryLimits
from modules.logical_compiler.src.protocols.factory_process import FactoryProcess
from modules.logical_compiler.src.protocols.production import (
    IdealExternalSink,
    OutputDelivery,
    OutputHandoff,
    ProductionPolicy,
    make_output_sink,
)
from modules.logical_compiler.src.protocols.protocol_intents import WaitIntent
from modules.logical_compiler.src.scheduling import ComponentScheduler


def synthetic_sink(process, token, *, delay=7, hold=3):
    """Explicit toy consumer; waiting is not evidence of a physical transfer."""
    owner = f"{process.factory_id}/cycle[{process.cycle_index}]/synthetic_sink"
    process.ledger.reserve(
        token.token_id,
        consumer=owner,
        at_us=process.execution.clock_us,
        expected_code=CODE,
        expected_distance=1,
        expected_kind="A",
        expected_canonicalization="canonical",
    )
    yield WaitIntent(process.execution.clock_us + delay, "synthetic_output_transfer")
    deliverable = process.execution.clock_us
    process.ledger.consume(
        token.token_id,
        consumer=owner,
        at_us=deliverable,
        safe_exit_at_us=deliverable + hold,
    )
    yield WaitIntent(deliverable + hold, "synthetic_output_consumer")
    released = process.execution.clock_us
    process.ledger.complete_use(token.carrier_id, owner=owner, at_us=released)
    return OutputDelivery(
        token.token_id,
        token.carrier_id,
        owner,
        deliverable,
        deliverable,
        released,
        {"kind": "test_fixture", "physical_delivery": False},
    )


def run_continuous(
    *,
    scripts=({},),
    policy=None,
    sink=synthetic_sink,
    limits=None,
    spares=0,
    continuation=None,
    cohort_ids=None,
):
    physical = BatchedPhysical()
    roles = ("W1", "W2", "R")
    physical.bindings = {
        f"line-{line}/{role}": ComponentBinding(
            f"line-{line}/{role}",
            Position(line * 10 + slot, 0),
            (line * len(roles) + slot,),
            "fixture_aod",
        )
        for line in range(len(scripts))
        for slot, role in enumerate(roles)
    }
    for line in range(len(scripts)):
        for index in range(spares):
            identity = f"line-{line}/spare-{index}"
            physical.bindings[identity] = ComponentBinding(
                identity,
                Position(line * 10 + len(roles) + index, 0),
                (len(scripts) * len(roles) + line * spares + index,),
                "fixture_aod",
            )
    processes = tuple(
        FactoryProcess(
            f"line-{line}",
            code=CODE,
            recipe=toy_recipe(),
            backend=DeclaredBackend(script),
            role_bindings={role: f"line-{line}/{role}" for role in roles},
            distance=1,
            production_policy=policy or ProductionPolicy(2),
            output_sink=sink,
            limits=limits,
            cohort_id="default" if cohort_ids is None else cohort_ids[line],
            **(
                {"production_continuation": continuation}
                if continuation is not None
                else {}
            ),
        )
        for line, script in enumerate(scripts)
    )
    runtime = CooperativeFactoryRuntime(
        physical,
        case_id="continuous-synthetic-fixture",
        seed=17,
        scheduler=ComponentScheduler(),
        processes=processes,
    )
    for identity, binding in physical.bindings.items():
        if "/spare-" in identity:
            runtime.ledger.register_carrier(
                identity, code_id=CODE, distance=1, atom_ids=binding.atom_ids
            )
    return runtime.run().to_dict(), runtime


def test_two_successes_keep_one_clock_ledger_and_unique_epochs():
    case, runtime = run_continuous()
    assert case["status"] == "complete", case["factories"]
    outputs = case["factories"]["line-0"]["outputs"]
    assert len(outputs) == 2
    assert [row["cycle"] for row in outputs] == [0, 1]
    assert [row["epoch"] for row in outputs] == [1, 2]
    assert len({row["token_id"] for row in outputs}) == 2
    for row in outputs:
        assert (
            row["ready_at_us"]
            < row["deliverable_at_us"]
            <= row["consumed_at_us"]
            < row["released_at_us"]
        )
        assert row["quality"] == runtime.ledger.token(row["token_id"]).quality
        assert runtime.ledger.token(row["token_id"]).status == "consumed"
        assert row["delivery"]["evidence"]["physical_delivery"] is False
    second = [c for c in case["calls"] if "/cycle[1]/" in c["invocation_id"]]
    assert min(c["start_us"] for c in second) >= outputs[0]["released_at_us"]
    assert outputs[1]["ready_at_us"] > outputs[0]["released_at_us"]
    assert len({c["invocation_id"] for c in case["calls"]}) == len(case["calls"])
    assert all(c["owner"] is None for c in case["resources"]["carriers"])
    assert runtime.execution.clock_us == case["duration_us"]


def test_rejections_keep_cycle_and_retry_identities_distinct():
    case, _ = run_continuous(
        scripts=(
            {
                "prep:W1": ("rejected", "accepted"),
                "final": ("rejected", "accepted", "accepted"),
            },
        ),
        limits=FactoryLimits(raw_attempts=3, batches=2),
    )
    assert case["status"] == "complete", case["factories"]
    outputs = case["factories"]["line-0"]["outputs"]
    assert [row["batch"] for row in outputs] == [1, 0]
    assert len(outputs) == 2
    identities = [c["invocation_id"] for c in case["calls"]]
    assert any(
        "/cycle[0]/batch[0]/prepare/W1/attempt[1]/" in item for item in identities
    )
    assert any("/cycle[0]/batch[1]/" in item for item in identities)
    assert any("/cycle[1]/batch[0]/" in item for item in identities)


@pytest.mark.parametrize(
    ("script", "status"),
    [
        ({"prep:W1": ("rejected", "rejected")}, "input_supply_exhausted"),
        ({"final": ("rejected", "rejected")}, "distillation_rejected"),
    ],
)
def test_retry_exhaustion_is_an_explicit_failure(script, status):
    case, _ = run_continuous(
        scripts=(script,), limits=FactoryLimits(raw_attempts=2, batches=2)
    )
    line = case["factories"]["line-0"]
    assert line["status"] == status
    assert line["outputs"] == []
    assert case["status"] == "partial_failure"
    assert not any("/cycle[1]/" in c["invocation_id"] for c in case["calls"])


def test_sink_must_consume_and_release_before_next_cycle():
    def leaking_sink(process, token):
        now = process.execution.clock_us
        yield WaitIntent(now, "synthetic_invalid_sink")
        return OutputDelivery(
            token.token_id,
            token.carrier_id,
            "unused",
            now,
            now,
            now,
            {"kind": "test_fixture"},
        )

    case, _ = run_continuous(sink=leaking_sink)
    line = case["factories"]["line-0"]
    assert line["status"] == "protocol_failure"
    assert "OUTPUT_DELIVERY" in line["failure"]["detail"]
    assert len(line["outputs"]) == 1
    assert line["outputs"][0]["released_at_us"] is None
    assert not any("/cycle[1]/" in c["invocation_id"] for c in case["calls"])


def test_cycle_barrier_waits_for_peer_retry_and_delivery():
    def staggered_sink(process, token):
        return (
            yield from synthetic_sink(
                process, token, delay=50 if process.factory_id == "line-1" else 1
            )
        )

    case, _ = run_continuous(
        scripts=({}, {"final": ("rejected", "accepted", "accepted")}),
        sink=staggered_sink,
        limits=FactoryLimits(batches=2),
    )
    assert case["status"] == "complete", case["factories"]
    first_outputs = [line["outputs"][0] for line in case["factories"].values()]
    next_calls = [c for c in case["calls"] if "/cycle[1]/" in c["invocation_id"]]
    assert min(c["start_us"] for c in next_calls) >= max(
        row["released_at_us"] for row in first_outputs
    )
    barriers = [
        m
        for m in case["milestones"]
        if m["kind"] == "cohort_barrier_released"
        and m["stage_key"] == "cycle[0]/complete"
    ]
    assert len(barriers) == 2
    assert all(m["peers"] == ["line-0", "line-1"] for m in barriers)


def test_cycle_budget_cannot_claim_completion_before_requested_horizon():
    case, _ = run_continuous(policy=ProductionPolicy(1, stop_at_us=1_000_000))
    assert case["factories"]["line-0"]["status"] == "production_cycle_budget_exhausted"
    assert len(case["factories"]["line-0"]["outputs"]) == 1
    assert case["status"] == "partial_failure"


@pytest.mark.parametrize(("horizon", "outputs"), [(0, 0), (1, 1)])
def test_horizon_stops_at_safe_cycle_boundary(horizon, outputs):
    case, _ = run_continuous(policy=ProductionPolicy(3, stop_at_us=horizon))
    assert case["status"] == "complete"
    assert len(case["factories"]["line-0"]["outputs"]) == outputs
    assert case["duration_us"] >= horizon


@pytest.mark.parametrize("count", (0, -1, True, 1.5))
def test_invalid_cycle_budgets_rejected(count):
    with pytest.raises(ValueError):
        ProductionPolicy(count)


@pytest.mark.parametrize("horizon", (-1, True, float("inf"), float("nan")))
def test_invalid_production_horizons_rejected(horizon):
    with pytest.raises(ValueError):
        ProductionPolicy(2, stop_at_us=horizon)


@pytest.mark.parametrize(
    "field", ("token_id", "consumer", "consumed_at_us", "released_at_us")
)
def test_sink_receipt_cannot_forge_identity_or_ledger_timestamps(field):
    def inconsistent_sink(process, token):
        delivery = yield from synthetic_sink(process, token)
        value = (
            "wrong"
            if field in ("token_id", "consumer")
            else getattr(delivery, field) + 1
        )
        return replace(delivery, **{field: value})

    case, _ = run_continuous(sink=inconsistent_sink)
    line = case["factories"]["line-0"]
    assert line["status"] == "protocol_failure"
    assert "OUTPUT_DELIVERY" in line["failure"]["detail"]
    assert len(line["outputs"]) == 1
    assert line["outputs"][0]["delivery"] is None


def test_failed_peer_does_not_block_remaining_production_cycles():
    case, _ = run_continuous(
        scripts=({}, {"prep:W1": ("rejected", "rejected")}),
        limits=FactoryLimits(raw_attempts=2),
    )
    assert case["status"] == "partial_failure"
    assert case["factories"]["line-1"]["status"] == "input_supply_exhausted"
    assert case["factories"]["line-0"]["status"] == "complete"
    assert len(case["factories"]["line-0"]["outputs"]) == 2


@pytest.mark.parametrize("missing", ("policy", "sink", "algorithm"))
def test_continuous_entry_requires_explicit_sink_and_supported_goal(missing):
    kwargs = {"production_policy": ProductionPolicy(2), "output_sink": synthetic_sink}
    if missing == "policy":
        kwargs["production_policy"] = None
    elif missing == "sink":
        kwargs["output_sink"] = None
    else:
        kwargs.update(
            algorithm_preparation=preparation("D", working=True),
            algorithm_consumption=consumption("D", "W1"),
        )
    with pytest.raises(ValueError, match="CONTINUOUS"):
        FactoryProcess(
            "line",
            code=CODE,
            recipe=toy_recipe(),
            backend=DeclaredBackend(),
            role_bindings={r: r for r in ("W1", "W2", "R", "D")},
            distance=1,
            **kwargs,
        )


@pytest.mark.parametrize(
    "configuration",
    [
        {},
        {"kind": "physical_delivery", "acknowledge_excluded_costs": True},
        {"kind": "ideal_external"},
        {"kind": "ideal_external", "acknowledge_excluded_costs": False},
        {"kind": "ideal_external", "acknowledge_excluded_costs": 1},
        {
            "kind": "ideal_external",
            "acknowledge_excluded_costs": True,
            "transfer_us": 10,
        },
        {
            "kind": "ideal_external",
            "acknowledge_excluded_costs": True,
            "consumer_id": "",
        },
    ],
)
def test_ideal_external_sink_requires_explicit_exact_configuration(configuration):
    with pytest.raises(ValueError):
        make_output_sink(configuration)


def test_explicit_ideal_sink_consumes_existing_tokens_without_external_cost_or_extra_offers():
    sink = make_output_sink(
        {"kind": "ideal_external", "acknowledge_excluded_costs": True}
    )
    assert isinstance(sink, IdealExternalSink)
    case, runtime = run_continuous(sink=sink)
    assert case["status"] == "complete", case["factories"]
    outputs = case["factories"]["line-0"]["outputs"]
    assert len(outputs) == 2
    for output in outputs:
        assert (
            output["ready_at_us"]
            == output["deliverable_at_us"]
            == output["consumed_at_us"]
            == output["released_at_us"]
        )
        evidence = output["delivery"]["evidence"]
        assert evidence["kind"] == "ideal_external"
        assert evidence["physical_delivery"] is False
        assert evidence["excluded_costs_us"] == {
            "external_transport": 0,
            "external_consumer": 0,
            "external_reset": 0,
        }
        assert (
            evidence["factory_reinitialization"]
            == "existing next-cycle preparation source remains counted"
        )
        identity = output["token_id"]
        token = runtime.ledger.token(identity)
        assert token.status == "consumed"
        audit = case["resources"]["audit"]
        assert (
            sum(
                event["action"] == "offer" and event["token"]["token_id"] == identity
                for event in audit
                if event["action"] == "offer"
            )
            == 1
        )
        assert (
            sum(
                event["action"] == "consume" and event["token_id"] == identity
                for event in audit
                if event["action"] == "consume"
            )
            == 1
        )
        assert any(
            event["action"] == "complete_use"
            and event["carrier_id"] == output["carrier_id"]
            and event["epoch"] == output["epoch"]
            and event["owner"] == token.consumer
            for event in audit
        )
    second_preparation = next(
        call
        for call in case["calls"]
        if "/cycle[1]/batch[0]/prepare/W1/attempt[0]/body" in call["invocation_id"]
    )
    assert second_preparation["start_us"] >= outputs[0]["released_at_us"]
    assert second_preparation["end_us"] > second_preparation["start_us"]
    assert not any(
        "ideal_external" in token["token_id"] for token in case["resources"]["tokens"]
    )


def test_ideal_external_sink_respects_existing_safe_exit_and_cannot_reconsume():
    from types import SimpleNamespace

    from modules.logical_compiler.src.protocols.resources import ResourceLedger

    ledger = ResourceLedger()
    ledger.register_logical_carrier("output", code_id=CODE, distance=1)
    ledger.begin_preparation("output", owner="producer", at_us=0)
    token = ledger.offer(
        "output-token",
        carrier_id="output",
        epoch=1,
        owner="producer",
        resource_kind="A",
        producer="fixture",
        ready_at_us=5,
        exit_at_us=9,
        canonicalization="canonical",
    )
    process = SimpleNamespace(
        factory_id="factory",
        cycle_index=0,
        code=CODE,
        distance=1,
        recipe=SimpleNamespace(output_resource_kind="A"),
        ledger=ledger,
        execution=SimpleNamespace(clock_us=0),
    )
    sink = IdealExternalSink(acknowledge_excluded_costs=True)
    flow = sink(process, token)
    wait = next(flow)
    assert wait.until_us == 9
    assert ledger.token(token.token_id).status == "offered"
    process.execution.clock_us = 9
    with pytest.raises(StopIteration) as finished:
        next(flow)
    delivery = finished.value.value
    delivery.validate(token, ledger, 9)
    assert delivery.released_at_us == 9
    assert ledger.carrier("output").owner is None
    replay = sink(process, token)
    next(replay)
    with pytest.raises(ValueError, match="TOKEN_NOT_AVAILABLE"):
        next(replay)


def handoff_fixture(*, replacement_code=CODE, replacement_distance=1):
    """Ledger-only fixture; the trace reference is deliberately synthetic."""
    from modules.logical_compiler.src.protocols.resources import ResourceLedger

    ledger = ResourceLedger()
    ledger.register_logical_carrier("A", code_id=CODE, distance=1)
    ledger.register_logical_carrier(
        "B", code_id=replacement_code, distance=replacement_distance
    )
    ledger.begin_preparation("A", owner="producer", at_us=0)
    token = ledger.offer(
        "token-A",
        carrier_id="A",
        epoch=1,
        owner="producer",
        resource_kind="A",
        producer="L1",
        ready_at_us=5,
        exit_at_us=9,
        canonicalization="canonical",
        quality={"scope": "test_fixture"},
        provenance={"fixture": "original-source"},
    )
    ledger.reserve(
        token.token_id,
        consumer="L2",
        at_us=10,
        expected_code=CODE,
        expected_distance=1,
        expected_kind="A",
        expected_canonicalization="canonical",
    )
    receipt = OutputHandoff(
        token.token_id,
        token.carrier_id,
        "L2",
        12,
        "B",
        12,
        {
            "scope": "synthetic_test_fixture",
            "delivery_trace_ref": "synthetic://handoff",
            "snapshot": {"validated": False},
        },
    )
    return ledger, token, receipt


def validate_handoff(receipt, token, ledger, *, output_carrier_id="B", now_us=12):
    receipt.validate(
        token,
        ledger,
        now_us,
        output_carrier_id=output_carrier_id,
        code_id=CODE,
        distance=1,
    )


def test_handoff_preserves_reserved_resource_and_owns_no_physical_validation():
    ledger, token, receipt = handoff_fixture()
    before = ledger.snapshot()
    validate_handoff(receipt, token, ledger)
    assert ledger.snapshot() == before
    assert ledger.token(token.token_id) == replace(
        token, status="reserved", consumer="L2"
    )
    assert ledger.carrier("A").owner == "L2"
    assert ledger.carrier("B").phase == "free"
    document = receipt.to_dict()
    assert document["validation_scope"] == "ledger_lifecycle_only"
    document["evidence"]["snapshot"]["validated"] = True
    assert receipt.evidence["snapshot"]["validated"] is False


@pytest.mark.parametrize(
    "changes",
    [
        {"token_id": "different"},
        {"carrier_id": "B"},
        {"consumer": "wrong"},
        {"consumer": ""},
        {"handoff_at_us": 4},
        {"handoff_at_us": 9},
        {"handoff_at_us": 13},
        {"handoff_at_us": float("nan")},
        {"handoff_at_us": True},
        {"replacement_carrier_id": "A"},
        {"replacement_ready_at_us": 13},
        {"replacement_ready_at_us": True},
    ],
)
def test_handoff_rejects_invalid_identity_or_times(changes):
    ledger, token, receipt = handoff_fixture()
    with pytest.raises(ValueError, match="OUTPUT_HANDOFF"):
        validate_handoff(replace(receipt, **changes), token, ledger)


@pytest.mark.parametrize(
    "changes",
    [
        {"epoch": 0},
        {"quality_json": '{"changed":true}'},
        {"provenance_json": '{"changed":true}'},
        {"ready_at_us": 4},
        {"exit_at_us": 8},
        {"resource_kind": "A_dagger"},
        {"producer": "other"},
    ],
)
def test_handoff_requires_exact_original_token_metadata(changes):
    ledger, token, receipt = handoff_fixture()
    with pytest.raises(ValueError, match="OUTPUT_HANDOFF"):
        validate_handoff(receipt, replace(token, **changes), ledger)


@pytest.mark.parametrize(
    "kwargs", [{"replacement_code": "other"}, {"replacement_distance": 3}]
)
def test_handoff_replacement_must_match_source_code_and_distance(kwargs):
    ledger, token, receipt = handoff_fixture(**kwargs)
    with pytest.raises(ValueError, match="OUTPUT_HANDOFF"):
        validate_handoff(receipt, token, ledger)


@pytest.mark.parametrize(
    "fault",
    ["unbound_role", "busy_replacement", "future_replacement", "consumed_source"],
)
def test_handoff_rejects_unsafe_replacement_unbound_role_and_consumed_source(fault):
    ledger, token, receipt = handoff_fixture()
    output_carrier_id = "B"
    if fault == "unbound_role":
        output_carrier_id = "A"
    elif fault == "busy_replacement":
        ledger.begin_preparation("B", owner="busy", at_us=11)
    elif fault == "future_replacement":
        ledger.begin_preparation("B", owner="busy", at_us=11)
        ledger.complete_use("B", owner="busy", at_us=13)
    else:
        ledger.consume(token.token_id, consumer="L2", at_us=12, safe_exit_at_us=12)
    with pytest.raises(ValueError, match="OUTPUT_HANDOFF"):
        validate_handoff(receipt, token, ledger, output_carrier_id=output_carrier_id)


@pytest.mark.parametrize("code,distance", [("other", 1), (CODE, 3)])
def test_handoff_source_must_match_producer_declaration(code, distance):
    ledger, token, receipt = handoff_fixture()
    with pytest.raises(ValueError, match="OUTPUT_HANDOFF"):
        receipt.validate(
            token, ledger, 12, output_carrier_id="B", code_id=code, distance=distance
        )


@pytest.mark.parametrize(
    "evidence",
    [
        {},
        {"scope": "synthetic_test_fixture"},
        {"delivery_trace_ref": "synthetic://handoff"},
        {"scope": "synthetic_test_fixture", "delivery_trace_ref": ""},
    ],
)
def test_handoff_requires_scoped_delivery_trace_reference(evidence):
    ledger, token, receipt = handoff_fixture()
    with pytest.raises(ValueError, match="OUTPUT_HANDOFF"):
        validate_handoff(replace(receipt, evidence=evidence), token, ledger)


def test_one_producer_can_handoff_four_reserved_outputs_without_fake_consumption():
    def synthetic_handoff(process, token):
        owner = f"synthetic-L2/input-{process.cycle_index}"
        process.ledger.reserve(
            token.token_id,
            consumer=owner,
            at_us=process.execution.clock_us,
            expected_code=CODE,
            expected_distance=1,
            expected_kind="A",
            expected_canonicalization="canonical",
        )
        yield WaitIntent(process.execution.clock_us + 3, "synthetic_handoff_delay")
        replacement = f"{process.factory_id}/spare-{process.cycle_index}"
        # Test-only role assignment, deliberately not a physical transfer adapter.
        process.roles[process.recipe.output_role] = replacement
        return OutputHandoff(
            token.token_id,
            token.carrier_id,
            owner,
            process.execution.clock_us,
            replacement,
            process.execution.clock_us,
            {
                "scope": "synthetic_test_fixture",
                "delivery_trace_ref": f"synthetic://handoff/{process.cycle_index}",
            },
        )

    case, runtime = run_continuous(
        policy=ProductionPolicy(4), sink=synthetic_handoff, spares=4
    )
    assert case["status"] == "complete", case["factories"]
    outputs = case["factories"]["line-0"]["outputs"]
    assert len(outputs) == 4
    assert len({row["carrier_id"] for row in outputs}) == 4
    assert len({row["token_id"] for row in outputs}) == 4
    for row in outputs:
        current = runtime.ledger.token(row["token_id"])
        assert current.status == "reserved"
        assert runtime.ledger.carrier(row["carrier_id"]).owner == current.consumer
        assert (
            row["consumed_at_us"]
            is row["released_at_us"]
            is row["deliverable_at_us"]
            is None
        )
        assert row["delivery"] is None
        assert row["handoff_at_us"] >= row["ready_at_us"]
        assert row["handoff"]["validation_scope"] == "ledger_lifecycle_only"
    handoffs = [
        m for m in case["milestones"] if m["kind"] == "factory_output_handed_off"
    ]
    assert len(handoffs) == 4
    assert not any(
        m["kind"]
        in (
            "factory_output_consumed",
            "factory_output_released",
            "factory_output_deliverable",
        )
        for m in case["milestones"]
    )
    for previous, next_output in pairwise(outputs):
        assert next_output["carrier_id"] == previous["replacement_carrier_id"]
        assert next_output["ready_at_us"] > previous["handoff_at_us"]


def test_failed_handoff_cannot_start_next_cycle_or_erase_reserved_output():
    def missing_role_binding(process, token):
        now = process.execution.clock_us
        process.ledger.reserve(
            token.token_id,
            consumer="synthetic-L2",
            at_us=now,
            expected_code=CODE,
            expected_kind="A",
            expected_distance=1,
            expected_canonicalization="canonical",
        )
        yield WaitIntent(now, "synthetic_invalid_handoff")
        return OutputHandoff(
            token.token_id,
            token.carrier_id,
            "synthetic-L2",
            now,
            "line-0/spare-0",
            now,
            {
                "scope": "synthetic_test_fixture",
                "delivery_trace_ref": "synthetic://invalid",
            },
        )

    case, runtime = run_continuous(sink=missing_role_binding, spares=1)
    line = case["factories"]["line-0"]
    assert line["status"] == "protocol_failure"
    assert "OUTPUT_HANDOFF" in line["failure"]["detail"]
    assert len(line["outputs"]) == 1
    output = line["outputs"][0]
    assert output["consumed_at_us"] is output["released_at_us"] is None
    assert runtime.ledger.token(output["token_id"]).status == "reserved"
    assert not any("/cycle[1]/" in call["invocation_id"] for call in case["calls"])


def retained_fixture_sink(process, token):
    """Keep an unused accepted output; the wait represents no physical delivery."""
    from modules.logical_compiler.src.protocols.production import OutputRetention

    yield WaitIntent(process.execution.clock_us + 2, "synthetic_downstream_closed")
    return OutputRetention(
        token.token_id,
        token.carrier_id,
        process.ledger.carrier(token.carrier_id).owner,
        process.execution.clock_us,
        "downstream_completed",
        {"kind": "synthetic_retained_inventory", "physical_delivery": False},
    )


def test_retained_surplus_stops_normally_without_consuming_or_freeing_output():
    case, runtime = run_continuous(
        policy=ProductionPolicy(3, stop_at_us=1e9), sink=retained_fixture_sink
    )
    line = case["factories"]["line-0"]
    assert case["status"] == line["status"] == "complete", line["failure"]
    assert len(line["outputs"]) == 1
    output = line["outputs"][0]
    token = runtime.ledger.token(output["token_id"])
    carrier = runtime.ledger.carrier(output["carrier_id"])
    assert token.status == "offered" and token.consumer is None
    assert token.consumed_at_us is token.discarded_at_us is None
    assert carrier.owner == "line-0/cycle[0]/batch[0]"
    assert carrier.phase == "resource" and carrier.epoch == token.epoch == 1
    assert output["retained_at_us"] >= max(token.ready_at_us, carrier.safe_exit_at_us)
    assert output["retention_reason"] == "downstream_completed"
    assert output["retention"]["producer_owner"] == carrier.owner
    assert (
        output["deliverable_at_us"]
        is output["consumed_at_us"]
        is output["released_at_us"]
        is None
    )
    assert output["delivery"] is None
    assert not any("/cycle[1]/" in call["invocation_id"] for call in case["calls"])
    assert not any(
        event.get("token_id") == token.token_id
        and event["action"] in ("reserve", "consume", "discard")
        for event in runtime.ledger.snapshot()["audit"]
    )
    assert not any(
        event.get("token_id") == token.token_id
        and event["kind"]
        in (
            "factory_output_deliverable",
            "factory_output_consumed",
            "factory_output_released",
            "factory_output_handed_off",
        )
        for event in case["milestones"]
    )


@pytest.mark.parametrize("cohorts", (None, ("L1-a", "L1-b")))
def test_retained_line_leaves_live_peer_barriers_without_deadlock(cohorts):
    def sink(process, token):
        if process.factory_id == "line-0":
            return (yield from retained_fixture_sink(process, token))
        return (yield from synthetic_sink(process, token, delay=9))

    case, runtime = run_continuous(scripts=({}, {}), sink=sink, cohort_ids=cohorts)
    assert case["status"] == "complete", case["factories"]
    assert len(case["factories"]["line-0"]["outputs"]) == 1
    assert len(case["factories"]["line-1"]["outputs"]) == 2
    retained = case["factories"]["line-0"]["outputs"][0]
    assert runtime.ledger.token(retained["token_id"]).status == "offered"


def test_caller_demand_stops_before_next_cycle_and_is_explicit_in_snapshot():
    observed = []

    def demand(process):
        observed.append((process.factory_id, len(process.outputs)))
        return not process.outputs

    case, _ = run_continuous(
        policy=ProductionPolicy(3, stop_at_us=1e9), continuation=demand
    )
    line = case["factories"]["line-0"]
    assert line["status"] == "complete", line["failure"]
    assert len(line["outputs"]) == 1
    assert line["production_continuation"] == "caller_controlled"
    assert line["production_stop_reason"] == "caller_no_demand"
    assert observed == [("line-0", 0), ("line-0", 1)]
    assert not any("/cycle[1]/" in call["invocation_id"] for call in case["calls"])


def test_no_initial_demand_emits_no_preparation_or_sink_actions():
    case, runtime = run_continuous(continuation=lambda _: False)
    line = case["factories"]["line-0"]
    assert line["status"] == "complete" and line["outputs"] == []
    assert line["cycle_index"] is None and case["calls"] == []
    assert runtime.execution.clock_us == 0
    assert all(carrier["epoch"] == 0 for carrier in case["resources"]["carriers"])


@pytest.mark.parametrize("result", (1, 0, None, "closed"))
def test_continuation_requires_boolean_decision_before_starting_cycle(result):
    case, _ = run_continuous(continuation=lambda _: result)
    line = case["factories"]["line-0"]
    assert line["status"] == "protocol_failure"
    assert "PRODUCTION_CONTINUATION" in line["failure"]["detail"]
    assert line["outputs"] == [] and case["calls"] == []


def retention_fixture():
    from modules.logical_compiler.src.protocols.production import OutputRetention
    from modules.logical_compiler.src.protocols.resources import ResourceLedger

    ledger = ResourceLedger()
    ledger.register_logical_carrier("A", code_id=CODE, distance=1)
    ledger.begin_preparation("A", owner="producer", at_us=0)
    token = ledger.offer(
        "token-A",
        carrier_id="A",
        epoch=1,
        owner="producer",
        resource_kind="A",
        producer="L1",
        ready_at_us=5,
        exit_at_us=9,
        canonicalization="canonical",
        quality={"scope": "fixture"},
        provenance={"source": "unchanged"},
    )
    return (
        ledger,
        token,
        OutputRetention(
            token.token_id,
            token.carrier_id,
            "producer",
            10,
            "downstream_completed",
            {"kind": "fixture", "physical_delivery": False},
        ),
    )


def validate_retention(receipt, token, ledger, **changes):
    parameters = {
        "output_carrier_id": "A",
        "producer_owner": "producer",
        "code_id": CODE,
        "distance": 1,
    }
    parameters.update(changes)
    receipt.validate(token, ledger, 10, **parameters)


@pytest.mark.parametrize(
    "change",
    (
        {"token_id": "wrong"},
        {"carrier_id": "wrong"},
        {"producer_owner": "other"},
        {"retained_at_us": 8},
        {"retained_at_us": 11},
        {"retained_at_us": True},
        {"reason": ""},
        {"evidence": {}},
        {"evidence": {"cost": float("nan")}},
    ),
)
def test_retention_rejects_forged_identity_ownership_or_times_without_mutation(change):
    ledger, token, receipt = retention_fixture()
    before = ledger.snapshot()
    with pytest.raises(ValueError, match="OUTPUT_RETENTION"):
        validate_retention(replace(receipt, **change), token, ledger)
    assert ledger.snapshot() == before


def test_retention_validates_unchanged_offered_token_and_keeps_evidence_independent():
    ledger, token, receipt = retention_fixture()
    before = ledger.snapshot()
    validate_retention(receipt, token, ledger)
    assert ledger.snapshot() == before and ledger.token(token.token_id) is token
    document = receipt.to_dict()
    document["evidence"]["kind"] = "mutated"
    assert receipt.evidence["kind"] == "fixture"
    ledger.reserve(
        token.token_id,
        consumer="L2",
        at_us=10,
        expected_code=CODE,
        expected_distance=1,
        expected_kind="A",
        expected_canonicalization="canonical",
    )
    with pytest.raises(ValueError, match="OUTPUT_RETENTION"):
        validate_retention(receipt, token, ledger)


@pytest.mark.parametrize("invalid", ("missing_policy", "noncallable"))
def test_continuation_configuration_requires_explicit_continuous_policy(invalid):
    kwargs = (
        {"production_continuation": lambda _: False}
        if invalid == "missing_policy"
        else {
            "production_policy": ProductionPolicy(2),
            "output_sink": synthetic_sink,
            "production_continuation": True,
        }
    )
    with pytest.raises((ValueError, TypeError), match="PRODUCTION_CONTINUATION"):
        FactoryProcess(
            "line",
            code=CODE,
            recipe=toy_recipe(),
            backend=DeclaredBackend(),
            role_bindings={role: role for role in ("W1", "W2", "R")},
            distance=1,
            **kwargs,
        )
