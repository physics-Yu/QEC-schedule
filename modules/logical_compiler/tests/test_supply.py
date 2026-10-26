"""Synthetic inventory and cooperative-supply constraints, not physical delivery."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from nadit_physical_compiler.device import Position
from test_factory_execution import CODE, preparation, toy_recipe
from test_scheduled_factory import BatchedPhysical, DeclaredBackend

from modules.codes.contracts.component import ComponentBinding
from modules.codes.contracts.factory_recipe import ComponentCall
from modules.logical_compiler.src.protocols.cooperative import CooperativeFactoryRuntime
from modules.logical_compiler.src.protocols.events import EventDependency
from modules.logical_compiler.src.protocols.factory_process import FactoryProcess
from modules.logical_compiler.src.protocols.protocol_intents import (
    CallIntent,
    FeedbackIntent,
    ResourceWaitIntent,
    RoleHandoffIntent,
    WaitIntent,
)
from modules.logical_compiler.src.protocols.receipts import ComponentReceipt
from modules.logical_compiler.src.protocols.resources import ResourceLedger
from modules.logical_compiler.src.protocols.supply import TokenBuffer
from modules.logical_compiler.src.scheduling import ComponentNode, ComponentScheduler


def offer(ledger, name="R", *, owner="producer", distance=1):
    ledger.register_logical_carrier(name, code_id=CODE, distance=distance)
    carrier = ledger.begin_preparation(name, owner=owner, at_us=0)
    return ledger.offer(
        name + "/token",
        carrier_id=name,
        epoch=carrier.epoch,
        owner=owner,
        resource_kind="A",
        producer="fixture",
        ready_at_us=1,
        exit_at_us=2,
        canonicalization="canonical",
        quality={"status": "test_fixture", "consumption_parameters": {}},
    )


def test_capacity_is_reserved_until_explicit_safe_removal():
    ledger = ResourceLedger()
    token = offer(ledger)
    buffer = TokenBuffer("inputs", 1)
    assert buffer.reserve_capacity("slot0", owner="producer")
    assert not buffer.reserve_capacity("slot1", owner="other")
    buffer.publish("slot0", token.token_id, ledger=ledger, at_us=2)
    assert buffer.available(ledger=ledger, at_us=2) == (token.token_id,)
    received = buffer.claim(
        token.token_id,
        ledger=ledger,
        consumer="consumer",
        at_us=2,
        expected_code=CODE,
        expected_distance=1,
        expected_kind="A",
    )
    assert received is ledger.token(token.token_id)
    assert received.status == "reserved"
    assert buffer.available(ledger=ledger, at_us=2) == ()
    assert not buffer.reserve_capacity("slot1", owner="other")
    buffer.consume(
        token.token_id, ledger=ledger, consumer="consumer", at_us=2, safe_exit_at_us=5
    )
    with pytest.raises(ValueError, match="NOT_SAFE"):
        buffer.remove(token.token_id, ledger=ledger, at_us=4)
    buffer.remove(token.token_id, ledger=ledger, at_us=5)
    assert buffer.reserve_capacity("slot1", owner="other")
    assert ledger.token(token.token_id).status == "consumed"
    assert ledger.carrier("R").owner == "consumer"


def test_invalid_tokens_and_duplicate_publication_do_not_release_capacity():
    ledger = ResourceLedger()
    token = offer(ledger)
    buffer = TokenBuffer("inputs", 2)
    assert buffer.reserve_capacity("slot0", owner="producer")
    with pytest.raises(ValueError, match="NOT_READY"):
        buffer.publish("slot0", token.token_id, ledger=ledger, at_us=1)
    buffer.publish("slot0", token.token_id, ledger=ledger, at_us=2)
    assert buffer.reserve_capacity("slot1", owner="producer")
    with pytest.raises(ValueError, match="DUPLICATE"):
        buffer.publish("slot1", token.token_id, ledger=ledger, at_us=2)
    with pytest.raises(ValueError, match="INCOMPATIBLE_RESOURCE"):
        buffer.claim(
            token.token_id,
            ledger=ledger,
            consumer="consumer",
            at_us=2,
            expected_code=CODE,
            expected_distance=3,
            expected_kind="A",
        )
    assert buffer.occupied == 2
    assert ledger.token(token.token_id).status == "offered"
    buffer.abort_reservation("slot1", owner="producer")
    buffer.abort_token(
        token.token_id, ledger=ledger, owner="producer", at_us=2, safe_exit_at_us=3
    )
    assert buffer.occupied == 1
    buffer.remove(token.token_id, ledger=ledger, at_us=3)
    assert buffer.occupied == 0


def test_buffer_uses_current_ledger_and_rejects_stale_epoch():
    ledger = ResourceLedger()
    token = offer(ledger)
    buffer = TokenBuffer("inputs", 1)
    buffer.reserve_capacity("slot", owner="producer")
    buffer.publish("slot", token.token_id, ledger=ledger, at_us=2)
    current = ledger.fork()
    current.discard(token.token_id, owner="producer", at_us=2)
    current.complete_use("R", owner="producer", at_us=2)
    current.begin_preparation("R", owner="producer", at_us=2)
    with pytest.raises(ValueError, match="STALE"):
        buffer.available(ledger=current, at_us=2)
    assert buffer.available(ledger=ledger, at_us=2) == (token.token_id,)


def test_close_and_abort_distinguish_backpressure_from_exhaustion():
    buffer = TokenBuffer("inputs", 1)
    assert buffer.reserve_capacity("pending", owner="producer")
    buffer.close()
    assert buffer.closed and buffer.available_capacity == 0
    assert not buffer.exhausted
    assert not buffer.reserve_capacity("later", owner="producer")
    with pytest.raises(ValueError, match="OWNER"):
        buffer.abort_reservation("pending", owner="other")
    buffer.abort_reservation("pending", owner="producer")
    assert buffer.exhausted


def test_buffer_rejects_abort_before_publication_time():
    ledger = ResourceLedger()
    token = offer(ledger)
    buffer = TokenBuffer("inputs", 1)
    buffer.reserve_capacity("slot", owner="producer")
    buffer.publish("slot", token.token_id, ledger=ledger, at_us=5)
    with pytest.raises(ValueError, match="NOT_READY"):
        buffer.abort_token(token.token_id, ledger=ledger, owner="producer", at_us=4)
    assert ledger.token(token.token_id).status == "offered" and buffer.occupied == 1


def runtime_for(
    process_types=(FactoryProcess, FactoryProcess),
    *,
    cohorts=("default", "default"),
    recipes=None,
    factory_ids=None,
    **kwargs,
):
    physical = BatchedPhysical()
    roles = ("W1", "W2", "R")
    names = factory_ids or tuple(f"line{line}" for line in range(len(process_types)))
    physical.bindings = {
        f"{names[line]}/{role}": ComponentBinding(
            f"{names[line]}/{role}",
            Position(line * 10 + slot, 0),
            (line * 3 + slot,),
            "fixture_aod",
        )
        for line in range(len(process_types))
        for slot, role in enumerate(roles)
    }
    processes = tuple(
        cls(
            names[line],
            code=CODE,
            recipe=(recipes or [toy_recipe()] * len(process_types))[line],
            backend=DeclaredBackend(),
            role_bindings={r: f"{names[line]}/{r}" for r in roles},
            distance=1,
            cohort_id=cohorts[line],
            **kwargs,
        )
        for line, cls in enumerate(process_types)
    )
    return CooperativeFactoryRuntime(
        physical,
        case_id="supply-fixture",
        seed=0,
        scheduler=ComponentScheduler(),
        processes=processes,
    )


def test_separate_cohorts_share_global_admission_but_not_recipe_barriers():
    recipes = [toy_recipe(), replace(toy_recipe(), protocol_id="other-fixture")]
    with pytest.raises(ValueError, match="INCOMPATIBLE_COHORT_RECIPES"):
        runtime_for(recipes=recipes)
    case = runtime_for(cohorts=("level1", "level2"), recipes=recipes).run().to_dict()
    assert case["status"] == "complete", case["factories"]
    initial = [
        c
        for c in case["calls"]
        if c["component_id"] == "toy.raw" and "/prepare/W" in c["invocation_id"]
    ]
    assert len(initial) == 4
    assert len({c["batch_id"] for c in initial}) == 1
    releases = [m for m in case["milestones"] if m["kind"] == "cohort_barrier_released"]
    assert all(m["peers"] == [m["factory_id"]] for m in releases)


@pytest.mark.parametrize("exhaust", (False, True))
def test_resource_wait_allows_producer_progress_and_reports_exhaustion(exhaust):
    state = {"ready": False, "closed": False}

    class Producer(FactoryProcess):
        def flow(self):
            yield WaitIntent(5, "fixture producer")
            state.update(ready=not exhaust, closed=True)

    class Consumer(FactoryProcess):
        def flow(self):
            yield ResourceWaitIntent(
                "inputs",
                "await accepted input",
                lambda: state["ready"],
                lambda: state["closed"],
            )

    case = (
        runtime_for((Producer, Consumer), cohorts=("producer", "consumer"))
        .run()
        .to_dict()
    )
    assert case["duration_us"] == 5
    assert case["factories"]["line1"]["status"] == (
        "external_supply_exhausted" if exhaust else "complete"
    )
    waits = [m for m in case["milestones"] if m.get("state") == "waiting_supply"]
    assert waits and waits[0]["resource_id"] == "inputs"


def test_resource_wait_without_progress_is_explicit_deadlock():
    class Waiting(FactoryProcess):
        def flow(self):
            yield ResourceWaitIntent("inputs", "await accepted input", lambda: False)

    case = runtime_for((Waiting,), cohorts=("consumer",)).run().to_dict()
    assert case["factories"]["line0"]["status"] == "protocol_deadlock"


@pytest.mark.parametrize("wait_kind", ("supply", "buffer"))
def test_resource_wait_does_not_block_an_admitted_producer_component(wait_kind):
    state = {"ready": False}

    class Producer(FactoryProcess):
        def flow(self):
            owner = self.factory_id + "/fixture"
            yield from self._call(
                ComponentCall("produce", "toy.plus", ("W1",)),
                owner,
                begin_preparation_owner=owner,
            )
            self.ledger.finish_preparation(
                self.roles["W1"], owner=owner, at_us=self.execution.clock_us
            )
            self.ledger.complete_use(
                self.roles["W1"], owner=owner, at_us=self.execution.clock_us
            )
            state["ready"] = True

    class Consumer(FactoryProcess):
        def flow(self):
            yield ResourceWaitIntent(
                "inputs",
                "await producer component",
                lambda: state["ready"],
                wait_kind=wait_kind,
            )

    case = (
        runtime_for((Producer, Consumer), cohorts=("producer", "consumer"))
        .run()
        .to_dict()
    )
    assert case["status"] == "complete", case["factories"]
    assert len(case["calls"]) == 1 and case["calls"][0]["component_id"] == "toy.plus"
    assert case["factories"]["line1"]["completed_at_us"] >= case["calls"][0]["end_us"]
    waits = [m for m in case["milestones"] if m.get("state") == "waiting_" + wait_kind]
    assert waits and waits[0]["resource_id"] == "inputs"
    assert case["wait_instrumentation"] == {
        "schema": "nadit.resource_wait_instrumentation/1",
        "resource_wait_kinds": ["supply", "buffer"],
    }


def test_consecutive_buffer_wait_reasons_are_not_deduplicated():
    state = {"phase": 0}

    class Producer(FactoryProcess):
        def flow(self):
            yield WaitIntent(3, "fixture first arrival")
            state["phase"] = 1
            yield WaitIntent(6, "fixture second arrival")
            state["phase"] = 2

    class Consumer(FactoryProcess):
        def flow(self):
            yield ResourceWaitIntent(
                "buffer0",
                "await capacity",
                lambda: state["phase"] >= 1,
                wait_kind="buffer",
            )
            yield ResourceWaitIntent(
                "buffer0",
                "await safe release",
                lambda: state["phase"] >= 2,
                wait_kind="buffer",
            )

    case = (
        runtime_for((Producer, Consumer), cohorts=("producer", "consumer"))
        .run()
        .to_dict()
    )
    waits = [m for m in case["milestones"] if m.get("state") == "waiting_buffer"]
    assert [(m["at_us"], m["reason"]) for m in waits] == [
        (0, "await capacity"),
        (3, "await safe release"),
    ]
    assert case["status"] == "complete" and case["duration_us"] == 6


def test_legacy_state_reason_changes_keep_existing_deduplication():
    runtime = runtime_for((FactoryProcess,), cohorts=("default",))
    process = runtime.processes[0]
    runtime._state(process, "waiting_resources", "first frontier")
    runtime._state(process, "waiting_resources", "updated frontier")
    states = [m for m in process.milestones if m["kind"] == "line_state_changed"]
    assert len(states) == 1 and states[0]["reason"] == "first frontier"


@pytest.mark.parametrize("wait_kind", ("capacity", "", None, 1))
def test_resource_wait_kind_is_explicit_and_validated(wait_kind):
    with pytest.raises(ValueError, match="INVALID_RESOURCE_WAIT_KIND"):
        ResourceWaitIntent("inputs", "fixture", lambda: False, wait_kind=wait_kind)


@pytest.mark.parametrize("predicate", ("ready", "exhausted"))
def test_resource_wait_predicates_cannot_return_truthy_nonbooleans(predicate):
    class Waiting(FactoryProcess):
        def flow(self):
            yield ResourceWaitIntent(
                "inputs",
                "await accepted input",
                lambda: 1 if predicate == "ready" else False,
                lambda: 1,
            )

    case = runtime_for((Waiting,), cohorts=("consumer",)).run().to_dict()
    line = case["factories"]["line0"]
    assert line["status"] == "protocol_failure"
    assert "INVALID_RESOURCE_WAIT_RESULT" in line["failure"]["detail"]


@pytest.mark.parametrize("role", ("W1", "R"))
def test_external_supplier_returns_real_current_token_and_preserves_ownership_mode(
    role,
):
    ledger = ResourceLedger()
    token = offer(ledger, role)

    def supplied(process, request, identity, owner):
        yield WaitIntent(2, "fixture delivery only")
        return process.ledger.reserve(
            token.token_id,
            consumer=owner,
            at_us=2,
            expected_code=CODE,
            expected_distance=1,
            expected_kind="A",
            expected_canonicalization="canonical",
        )

    process = FactoryProcess(
        "consumer",
        code=CODE,
        recipe=toy_recipe(),
        backend=DeclaredBackend(),
        role_bindings={r: r for r in ("W1", "W2", "R")},
        distance=1,
        external_inputs=True,
        preparation_supplier=supplied,
    )
    process._runtime = SimpleNamespace(
        ledger=ledger, execution=SimpleNamespace(clock_us=2), milestones=[]
    )
    flow = process._prepare(preparation(role), "scope", "consumer-owner")
    assert isinstance(next(flow), WaitIntent)
    with pytest.raises(StopIteration) as done:
        flow.send(None)
    assert done.value.value.token_id == token.token_id
    assert ledger.token(token.token_id).status == (
        "consumed" if role == "W1" else "reserved"
    )
    assert ledger.carrier(role).owner == "consumer-owner"
    assert process.calls == []


def role_handoff_fixture(
    monkeypatch,
    *,
    producer_id="line0",
    token_producer=None,
    transport_intervals=((5, 10), (5, 10)),
):
    """Synthetic committed-state capability, never a physical routing result."""
    runtime = runtime_for(
        cohorts=("producer", "consumer"), factory_ids=(producer_id, "line1")
    )
    producer, consumer = runtime.processes
    producer.status = consumer.status = "running"
    source = producer.roles["W1"]
    replacement = consumer.roles["W1"]
    ledger = runtime.ledger
    owner = producer_id + "/output"
    carrier = ledger.begin_preparation(source, owner=owner, at_us=0)
    token = ledger.offer(
        "handoff-input",
        carrier_id=source,
        epoch=carrier.epoch,
        owner=owner,
        producer=producer_id if token_producer is None else token_producer,
        resource_kind="A",
        ready_at_us=5,
        exit_at_us=5,
        canonicalization="canonical",
        quality={"scope": "synthetic_test_fixture", "consumption_parameters": {}},
    )
    ledger.reserve(
        token.token_id,
        consumer="line1/input",
        at_us=10,
        expected_code=CODE,
        expected_distance=1,
        expected_kind="A",
        expected_canonicalization="canonical",
    )
    physical = runtime.physical
    physical.clock_us = 10
    old_source, old_replacement = (
        physical.bindings[source],
        physical.bindings[replacement],
    )
    physical.bindings[source] = replace(old_source, origin=old_replacement.origin)
    physical.bindings[replacement] = replace(old_replacement, origin=old_source.origin)
    receipts = tuple(
        ComponentReceipt(
            f"synthetic-transport/{index}",
            "fixture.relocate",
            (identity,),
            transport_intervals[index][0],
            transport_intervals[index][1],
            transport_intervals[index][1],
            representation="physical",
            provenance_json='{"scope":"synthetic_test_fixture","physical_validation":false}',
        )
        for index, identity in enumerate((source, replacement))
    )
    bindings = (physical.bindings[source], physical.bindings[replacement])
    checks = []

    def validate(received, *, expected_snapshot_id, expected_bindings):
        checks.append((received, expected_snapshot_id, expected_bindings))
        if (
            received != receipts
            or expected_snapshot_id != runtime.execution.snapshot_id
            or expected_bindings != bindings
        ):
            raise ValueError("SYNTHETIC_UNCOMMITTED_TRANSPORT")

    monkeypatch.setattr(
        runtime.execution, "validate_handoff_transport", validate, raising=False
    )
    request = RoleHandoffIntent(
        producer_id,
        "line1",
        "W1",
        "W1",
        token.token_id,
        "line1/input",
        source,
        replacement,
        receipts,
        runtime.execution.snapshot_id,
        bindings,
    )
    return runtime, request, checks


def test_role_handoff_accepts_actual_factory_event_scope_producer(monkeypatch):
    runtime, request, checks = role_handoff_fixture(
        monkeypatch,
        producer_id="factory1",
        token_producer="factory1/cycle[0]/batch[0]/final/event",
    )
    original = runtime.ledger.token(request.token_id)
    returned = runtime.commit_role_handoff(request)
    assert returned == original
    assert returned.producer == "factory1/cycle[0]/batch[0]/final/event"
    assert runtime.processes[0].roles["W1"] == request.replacement_carrier_id
    assert len(checks) == 1


@pytest.mark.parametrize(
    "token_producer",
    [
        "factory10",
        "factory10/cycle[0]/batch[0]/final/event",
        "factory1-extra/cycle[0]/batch[0]/final/event",
        "other/factory1/final/event",
    ],
)
def test_role_handoff_rejects_lookalike_factory_producer_namespace(
    monkeypatch, token_producer
):
    runtime, request, checks = role_handoff_fixture(
        monkeypatch,
        producer_id="factory1",
        token_producer=token_producer,
    )
    before = handoff_state(runtime)
    with pytest.raises(ValueError, match="INVALID_ROLE_HANDOFF_RESOURCES"):
        runtime.commit_role_handoff(request)
    assert handoff_state(runtime) == before
    assert checks == []


def test_role_handoff_rejects_previous_epoch_transport_before_kernel_hook(monkeypatch):
    runtime, request, checks = role_handoff_fixture(monkeypatch)
    ledger = runtime.ledger
    ledger.consume(
        request.token_id, consumer=request.consumer_owner, at_us=10, safe_exit_at_us=10
    )
    ledger.complete_use(
        request.source_carrier_id, owner=request.consumer_owner, at_us=10
    )
    prepared = ledger.begin_preparation(
        request.source_carrier_id, owner="line0/new-epoch", at_us=10
    )
    current = ledger.offer(
        "new-epoch-output",
        carrier_id=request.source_carrier_id,
        epoch=prepared.epoch,
        owner="line0/new-epoch",
        resource_kind="A",
        producer="line0/cycle[1]/batch[0]/final/event",
        ready_at_us=11,
        exit_at_us=11,
        canonicalization="canonical",
        quality={"scope": "synthetic_test_fixture"},
    )
    ledger.reserve(
        current.token_id,
        consumer=request.consumer_owner,
        at_us=12,
        expected_code=CODE,
        expected_kind="A",
        expected_distance=1,
        expected_canonicalization="canonical",
    )
    runtime.physical.clock_us = 12
    request = replace(
        request,
        token_id=current.token_id,
        expected_snapshot_id=runtime.execution.snapshot_id,
    )
    before = handoff_state(runtime)
    with pytest.raises(ValueError, match="ROLE_HANDOFF_SOURCE_TRANSPORT"):
        runtime.commit_role_handoff(request)
    assert handoff_state(runtime) == before
    assert checks == []


def test_role_handoff_allows_replacement_parking_before_source_ready(monkeypatch):
    runtime, request, checks = role_handoff_fixture(
        monkeypatch, transport_intervals=((5, 10), (0, 4))
    )
    token = runtime.ledger.token(request.token_id)
    assert request.transport_receipts[1].action_end_us < token.ready_at_us
    assert runtime.commit_role_handoff(request) == token
    assert len(checks) == 1


@pytest.mark.parametrize("source_chain", ["absent", "contains_early_receipt"])
def test_role_handoff_requires_every_source_transport_to_follow_current_token(
    monkeypatch, source_chain
):
    runtime, request, checks = role_handoff_fixture(monkeypatch)
    receipts = request.transport_receipts
    if source_chain == "absent":
        receipts = receipts[1:]
    else:
        receipts += (
            replace(
                receipts[0],
                invocation_id="synthetic-transport/old-source",
                start_us=4,
                action_end_us=5,
                results_ready_us=5,
            ),
        )
    request = replace(request, transport_receipts=receipts)
    before = handoff_state(runtime)
    with pytest.raises(ValueError, match="ROLE_HANDOFF_SOURCE_TRANSPORT"):
        runtime.commit_role_handoff(request)
    assert handoff_state(runtime) == before
    assert checks == []


def handoff_state(runtime):
    return (
        tuple(
            (dict(p.roles), dict(p._role_calls), dict(p._role_events), dict(p._sources))
            for p in runtime.processes
        ),
        runtime.ledger.snapshot(),
        runtime.scheduler.snapshot(),
        list(runtime.milestones),
    )


def test_role_handoff_exchanges_only_two_bindings_after_kernel_validation(monkeypatch):
    runtime, request, checks = role_handoff_fixture(monkeypatch)
    producer, consumer = runtime.processes
    ledger_before = runtime.ledger.snapshot()
    histories = tuple(dict(p._sources) for p in runtime.processes)
    returned = runtime.commit_role_handoff(request)
    assert len(checks) == 1
    assert producer.roles["W1"] == request.replacement_carrier_id
    assert consumer.roles["W1"] == request.source_carrier_id
    assert producer.roles["W2"] == "line0/W2"
    assert consumer.roles["R"] == "line1/R"
    assert returned is runtime.ledger.token(request.token_id)
    assert returned.status == "reserved" and returned.consumer == "line1/input"
    assert runtime.ledger.snapshot() == ledger_before
    assert tuple(p._sources for p in runtime.processes) == histories
    assert (
        len([m for m in runtime.milestones if m["kind"] == "role_handoff_committed"])
        == 2
    )


@pytest.mark.parametrize(
    "fault", ["missing_hook", "rejected_hook", "stale_snapshot", "wrong_binding"]
)
def test_role_handoff_needs_committed_kernel_evidence_and_is_atomic(monkeypatch, fault):
    runtime, request, _ = role_handoff_fixture(monkeypatch)
    if fault == "missing_hook":
        monkeypatch.setattr(runtime.execution, "validate_handoff_transport", None)
    elif fault == "rejected_hook":

        def reject(*args, **kwargs):
            raise ValueError("SYNTHETIC_TRANSPORT_NOT_COMMITTED")

        monkeypatch.setattr(runtime.execution, "validate_handoff_transport", reject)
    elif fault == "stale_snapshot":
        request = replace(request, expected_snapshot_id="stale")
    else:
        request = replace(
            request,
            expected_bindings=(
                replace(request.expected_bindings[0], origin=Position(999, 0)),
                request.expected_bindings[1],
            ),
        )
    before = handoff_state(runtime)
    with pytest.raises((ValueError, NotImplementedError)):
        runtime.commit_role_handoff(request)
    assert handoff_state(runtime) == before


@pytest.mark.parametrize(
    "fault",
    [
        "unreserved",
        "wrong_owner",
        "wrong_code",
        "wrong_distance",
        "busy_replacement",
        "unsafe_replacement",
    ],
)
def test_role_handoff_rejects_incompatible_current_ownership(monkeypatch, fault):
    runtime, request, _ = role_handoff_fixture(monkeypatch)
    if fault == "unreserved":
        current = runtime.ledger.token(request.token_id)
        runtime.ledger._tokens[current.token_id] = replace(
            current, status="offered", consumer=None
        )
    elif fault == "wrong_owner":
        request = replace(request, consumer_owner="third-party")
    elif fault == "wrong_code":
        runtime.processes[1].code = "different"
    elif fault == "wrong_distance":
        runtime.processes[1].distance = 3
    else:
        runtime.ledger.begin_preparation(
            request.replacement_carrier_id, owner="line1/work", at_us=10
        )
        if fault == "unsafe_replacement":
            runtime.ledger.complete_use(
                request.replacement_carrier_id, owner="line1/work", at_us=11
            )
    before = handoff_state(runtime)
    with pytest.raises(ValueError, match="ROLE_HANDOFF"):
        runtime.commit_role_handoff(request)
    assert handoff_state(runtime) == before


@pytest.mark.parametrize(
    "kind",
    [
        "unqueued_call",
        "queued_call",
        "running_call",
        "feedback_source",
        "feedback_role",
        "pending_role_call",
        "pending_role_event",
    ],
)
def test_role_handoff_rejects_any_dependency_on_old_bindings(monkeypatch, kind):
    runtime, request, _ = role_handoff_fixture(monkeypatch)
    producer = runtime.processes[0]
    call = ComponentCall("old-binding", "toy.x", ("W1",))
    if kind == "unqueued_call":
        runtime._fibers[0].intent = CallIntent(call, "line0")
    elif kind in ("queued_call", "running_call"):
        spec = runtime.execution.describe(
            producer.backend, call, (request.source_carrier_id,)
        )
        runtime.scheduler.add(ComponentNode("line0/old-binding", spec))
        if kind == "running_call":
            admission = runtime.scheduler.admit(
                10, snapshot_id=runtime.execution.snapshot_id
            )
            runtime.scheduler.commit_admission(admission)
    elif kind.startswith("feedback"):
        parts = (
            request.transport_receipts
            if kind == "feedback_source"
            else (
                replace(request.transport_receipts[0], participant_blocks=("line0/R",)),
            )
        )
        runtime._fibers[0].intent = FeedbackIntent(
            "pending",
            0,
            parts,
            lambda: None,
            participant_roles=("W1",) if kind == "feedback_role" else (),
        )
    elif kind == "pending_role_call":
        producer._role_calls["W1"] = "missing-completion"
    else:
        producer._role_events["W1"] = SimpleNamespace(released_at_us=11)
    before = handoff_state(runtime)
    with pytest.raises(ValueError, match="ROLE_HANDOFF"):
        runtime.commit_role_handoff(request)
    assert handoff_state(runtime) == before


def test_role_handoff_does_not_treat_supply_wait_as_a_stale_carrier_dependency(
    monkeypatch,
):
    runtime, request, _ = role_handoff_fixture(monkeypatch)
    runtime._fibers[1].intent = ResourceWaitIntent(
        "inputs", "waiting for delivered role", lambda: False
    )
    runtime.commit_role_handoff(request)
    assert runtime.processes[1].roles["W1"] == request.source_carrier_id


def test_role_handoff_clears_only_settled_role_shortcuts_and_keeps_history(monkeypatch):
    runtime, request, _ = role_handoff_fixture(monkeypatch)
    producer = runtime.processes[0]
    call = ComponentCall("history", "toy.x", ("W1",))
    identity = "line0/history"
    spec = runtime.execution.describe(
        producer.backend, call, (request.source_carrier_id,)
    )
    runtime.scheduler.add(ComponentNode(identity, spec))
    admission = runtime.scheduler.admit(5, snapshot_id=runtime.execution.snapshot_id)
    runtime.scheduler.commit_admission(admission)
    runtime.scheduler.mark_completed(identity, 9)
    receipt = ComponentReceipt(
        identity,
        call.component_id,
        (request.source_carrier_id,),
        5,
        9,
        9,
        ((0, 9),),
        "physical",
    )
    producer._sources[identity] = (receipt,)
    producer._role_calls.update(W1=identity, R="unrelated-shortcut")
    event = runtime.journal.sample(
        producer.backend.resolve_event("final"),
        invocation_id="line0/history-event",
        attempt=0,
        dependencies=(EventDependency.from_receipt(receipt),),
        context=runtime.execution,
    )
    runtime.scheduler.release_event(producer.event_key(event), event.released_at_us)
    producer._role_events.update(W1=event, R=event)
    scheduler_before, journal_before = (
        runtime.scheduler.snapshot(),
        runtime.journal.snapshot(),
    )
    runtime.commit_role_handoff(request)
    assert producer._role_calls == {"R": "unrelated-shortcut"}
    assert producer._role_events == {"R": event}
    assert producer._sources == {identity: (receipt,)}
    assert runtime.scheduler.snapshot() == scheduler_before
    assert runtime.journal.snapshot() == journal_before


def test_role_handoff_pump_unblocks_supply_and_producer_uses_replacement(monkeypatch):
    runtime, request, checks = role_handoff_fixture(monkeypatch)
    producer, consumer = runtime.processes
    observed = {}

    def produce():
        observed["returned"] = yield request
        owner = producer.factory_id + "/next"
        yield from producer._call(
            ComponentCall("prepare-next", "toy.plus", ("W1",)),
            owner,
            begin_preparation_owner=owner,
        )
        producer.ledger.finish_preparation(
            producer.roles["W1"], owner=owner, at_us=producer.execution.clock_us
        )
        producer.ledger.complete_use(
            producer.roles["W1"], owner=owner, at_us=producer.execution.clock_us
        )

    def receive():
        yield ResourceWaitIntent(
            "input",
            "waiting for role handoff",
            lambda: consumer.roles["W1"] == request.source_carrier_id,
        )
        observed["received"] = consumer.ledger.token(request.token_id)

    runtime._fibers[0].flow = produce()
    runtime._fibers[1].flow = receive()
    case = runtime.run().to_dict()
    assert case["status"] == "complete", case["factories"]
    assert len(checks) == 1
    assert (
        observed["returned"]
        == observed["received"]
        == runtime.ledger.token(request.token_id)
    )
    assert observed["received"].status == "reserved"
    assert (
        runtime.ledger.carrier(request.source_carrier_id).owner
        == request.consumer_owner
    )
    assert runtime.physical.committed[-1][1] == (request.replacement_carrier_id,)
    assert len(case["calls"]) == 1


def test_role_handoff_rejects_completed_action_with_pending_result_metadata(
    monkeypatch,
):
    runtime, request, _ = role_handoff_fixture(monkeypatch)
    producer = runtime.processes[0]
    call = ComponentCall("history", "toy.x", ("W1",))
    identity = "line0/history"
    runtime.scheduler.add(
        ComponentNode(
            identity,
            runtime.execution.describe(
                producer.backend, call, (request.source_carrier_id,)
            ),
        )
    )
    admission = runtime.scheduler.admit(5, snapshot_id=runtime.execution.snapshot_id)
    runtime.scheduler.commit_admission(admission)
    runtime.scheduler.mark_completed(identity, 9)
    producer._role_calls["W1"] = identity
    producer._sources[identity] = (
        ComponentReceipt(
            identity,
            call.component_id,
            (request.source_carrier_id,),
            5,
            9,
            11,
            ((0, 11),),
            "physical",
        ),
    )
    before = handoff_state(runtime)
    with pytest.raises(ValueError, match="ROLE_HANDOFF_PENDING_CALL_METADATA"):
        runtime.commit_role_handoff(request)
    assert handoff_state(runtime) == before


def test_role_handoff_cannot_be_replayed_after_roles_changed(monkeypatch):
    runtime, request, checks = role_handoff_fixture(monkeypatch)
    runtime.commit_role_handoff(request)
    before = handoff_state(runtime)
    with pytest.raises(ValueError, match="ROLE_HANDOFF"):
        runtime.commit_role_handoff(request)
    assert handoff_state(runtime) == before
    assert len(checks) == 1


def mechanical_call_fixture(
    monkeypatch,
    *,
    token_status=None,
    hook=True,
    release=False,
    token_exit_at_us=0,
    working=False,
):
    """A clock-only mechanical source with explicitly synthetic proof references."""
    seen = {}

    class Mover(FactoryProcess):
        def flow(self):
            seen["parts"] = yield CallIntent(
                ComponentCall("move", "block_translation", ("W1",)),
                "line0/transport",
                token=seen.get("token"),
                transport_owner=seen["owner"],
            )
            seen["after"] = self.ledger.carrier(self.roles["W1"])
            if release:
                self.ledger.complete_use(
                    self.roles["W1"], owner=seen["owner"], at_us=self.execution.clock_us
                )

    runtime = runtime_for((Mover,), cohorts=("transport",))
    carrier_id = runtime.processes[0].roles["W1"]
    seen["owner"] = "line0/transport"
    if working:
        runtime.ledger.begin_preparation(carrier_id, owner=seen["owner"], at_us=0)
        runtime.ledger.finish_preparation(carrier_id, owner=seen["owner"], at_us=0)
    if token_status is not None:
        carrier = runtime.ledger.begin_preparation(
            carrier_id, owner="line0/transport", at_us=0
        )
        token = runtime.ledger.offer(
            "mechanical-input",
            carrier_id=carrier_id,
            epoch=carrier.epoch,
            owner="line0/transport",
            producer="line0",
            resource_kind="A",
            ready_at_us=0,
            exit_at_us=token_exit_at_us,
            canonicalization="canonical",
            quality={"scope": "synthetic_test_fixture"},
        )
        if token_status == "reserved":
            token = runtime.ledger.reserve(
                token.token_id,
                consumer="receiver/input",
                at_us=0,
                expected_code=CODE,
                expected_kind="A",
                expected_distance=1,
                expected_canonicalization="canonical",
            )
            seen["owner"] = "receiver/input"
        seen["token"] = token
    seen["proof_calls"] = []

    def proof(receipt):
        assert receipt in seen["kernel_receipts"]
        seen["proof_calls"].append(receipt)
        return {
            name: str(index) * 64
            for index, name in enumerate(
                (
                    "trace_sha256",
                    "entry_world_sha256",
                    "exit_world_sha256",
                    "entry_binding_sha256",
                    "exit_binding_sha256",
                ),
                start=1,
            )
        }

    original_execute = runtime.execution.execute

    def execute(admission, requests):
        outputs = original_execute(admission, requests)
        seen["kernel_receipts"] = tuple(p for parts in outputs.values() for p in parts)
        return outputs

    monkeypatch.setattr(runtime.execution, "execute", execute)
    monkeypatch.setattr(
        runtime.execution, "transport_evidence", proof if hook else None, raising=False
    )
    return runtime, seen


@pytest.mark.parametrize("release", [False, True])
def test_mechanical_call_leases_free_carrier_without_preparation_or_epoch_change(
    monkeypatch, release
):
    runtime, seen = mechanical_call_fixture(monkeypatch, release=release)
    case = runtime.run().to_dict()
    assert case["status"] == "complete", case["factories"]
    carrier = runtime.ledger.carrier("line0/W1")
    assert seen["after"].phase == "transport" and seen["after"].epoch == 0
    assert carrier.phase == ("free" if release else "transport")
    assert carrier.epoch == 0 and carrier.atom_ids == (0,)
    assert len(seen["proof_calls"]) == 1
    actions = [event["action"] for event in runtime.ledger.snapshot()["audit"]]
    assert actions.count("acquire_transport") == actions.count("record_transport") == 1
    assert not {"begin_preparation", "extend_use", "consume", "offer"}.intersection(
        actions
    )
    assert case["calls"][0]["consumed_token_id"] is None


@pytest.mark.parametrize("status", ["offered", "reserved"])
def test_mechanical_call_preserves_every_active_token_field(monkeypatch, status):
    runtime, seen = mechanical_call_fixture(monkeypatch, token_status=status)
    original = seen["token"]
    case = runtime.run().to_dict()
    assert case["status"] == "complete", case["factories"]
    assert runtime.ledger.token(original.token_id) == original
    carrier = runtime.ledger.carrier(original.carrier_id)
    assert carrier.phase == "resource" and carrier.owner == seen["owner"]
    assert carrier.epoch == original.epoch
    assert carrier.safe_exit_at_us == seen["parts"][0].action_end_us
    events = runtime.ledger.snapshot()["audit"]
    assert len([e for e in events if e["action"] == "record_transport"]) == 1
    assert not any(
        e["action"] in ("consume", "extend_use", "acquire_transport") for e in events
    )


@pytest.mark.parametrize(
    "fault",
    ["missing_hook", "owner_mismatch", "unsafe", "missing_active_token", "stale_token"],
)
def test_mechanical_call_prevalidation_emits_no_physical_work(monkeypatch, fault):
    active = (
        "reserved"
        if fault in ("owner_mismatch", "unsafe", "missing_active_token", "stale_token")
        else None
    )
    runtime, seen = mechanical_call_fixture(
        monkeypatch,
        token_status=active,
        hook=fault != "missing_hook",
        token_exit_at_us=1 if fault == "unsafe" else 0,
    )
    if fault == "owner_mismatch":
        seen["owner"] = "wrong"
    elif fault == "missing_active_token":
        del seen["token"]
    elif fault == "stale_token":
        seen["token"] = replace(seen["token"], quality_json='{"stale":true}')
    before = runtime.ledger.snapshot()
    case = runtime.run().to_dict()
    assert case["factories"]["line0"]["status"] in (
        "physical_failure",
        "protocol_failure",
    )
    assert runtime.physical.committed == []
    assert seen["proof_calls"] == []
    assert runtime.ledger.snapshot() == before


def test_mechanical_call_rejects_post_execution_proof_without_fabricating_ledger_interval(
    monkeypatch,
):
    runtime, _ = mechanical_call_fixture(monkeypatch)

    def reject(receipt):
        raise ValueError("SYNTHETIC_NATIVE_PROOF_REJECTED")

    monkeypatch.setattr(runtime.execution, "transport_evidence", reject)
    case = runtime.run().to_dict()
    assert case["factories"]["line0"]["status"] == "physical_failure"
    assert (
        "SYNTHETIC_NATIVE_PROOF_REJECTED"
        in case["factories"]["line0"]["failure"]["detail"]
    )
    assert len(runtime.physical.committed) == 1
    assert not any(
        e["action"] in ("acquire_transport", "record_transport")
        for e in runtime.ledger.snapshot()["audit"]
    )


def test_ordinary_call_never_requests_transport_proof(monkeypatch):
    class Ordinary(FactoryProcess):
        def flow(self):
            yield from self._call(
                ComponentCall("prepare", "toy.plus", ("W1",)),
                "line0/ordinary",
                begin_preparation_owner="line0/ordinary",
            )

    runtime = runtime_for((Ordinary,), cohorts=("ordinary",))

    def forbidden(receipt):
        raise AssertionError("ordinary call requested mechanical proof")

    monkeypatch.setattr(
        runtime.execution, "transport_evidence", forbidden, raising=False
    )
    assert runtime.run().to_dict()["status"] == "complete"
    assert not any(
        e["action"] == "record_transport" for e in runtime.ledger.snapshot()["audit"]
    )


def test_mechanical_call_preserves_owned_work_phase_without_repreparation(monkeypatch):
    runtime, seen = mechanical_call_fixture(monkeypatch, working=True)
    original = runtime.ledger.carrier("line0/W1")
    before_events = len(runtime.ledger.snapshot()["audit"])
    assert runtime.run().to_dict()["status"] == "complete"
    carrier = runtime.ledger.carrier("line0/W1")
    assert (carrier.phase, carrier.epoch, carrier.atom_ids, carrier.owner) == (
        original.phase,
        original.epoch,
        original.atom_ids,
        original.owner,
    )
    assert carrier.safe_exit_at_us == seen["parts"][0].action_end_us
    assert [
        event["action"] for event in runtime.ledger.snapshot()["audit"][before_events:]
    ] == ["record_transport"]


def test_mechanical_wave_proof_failure_commits_no_partial_ledger(monkeypatch):
    from test_factory_execution import FixtureBackend

    class Mover(FactoryProcess):
        def flow(self):
            owner = self.factory_id + "/transport"
            yield CallIntent(
                ComponentCall("move", "block_translation", ("W1",)),
                owner,
                transport_owner=owner,
            )

    runtime = runtime_for((Mover, Mover), cohorts=("left", "right"))
    for process in runtime.processes:
        process.backend = (
            FixtureBackend()
        )  # Synthetic compatible batch declaration only.
    proofs = []

    def proof(receipt):
        proofs.append(receipt)
        if len(proofs) == 2:
            raise ValueError("SYNTHETIC_SECOND_PROOF_REJECTED")
        return {
            name: str(index) * 64
            for index, name in enumerate(
                (
                    "trace_sha256",
                    "entry_world_sha256",
                    "exit_world_sha256",
                    "entry_binding_sha256",
                    "exit_binding_sha256",
                ),
                start=1,
            )
        }

    monkeypatch.setattr(runtime.execution, "transport_evidence", proof, raising=False)
    before = runtime.ledger.snapshot()
    case = runtime.run().to_dict()
    assert len(proofs) == len(runtime.physical.committed) == 2
    assert (
        case["duration_us"] == 5
    )  # One synthetic batch, not physical timing evidence.
    assert all(
        line["status"] == "physical_failure" for line in case["factories"].values()
    )
    assert runtime.ledger.snapshot() == before
    assert case["calls"] == []
    assert not runtime.scheduler.snapshot()["admissions"]


def test_unmarked_block_translation_cannot_enter_ordinary_use_path():
    with pytest.raises(ValueError, match="TRANSPORT_CALL_OWNER_REQUIRED"):
        CallIntent(ComponentCall("move", "block_translation", ("W1",)), "line0")


@pytest.mark.parametrize(
    "change",
    ["two_roles", "wrong_component", "prepare", "consume", "selection", "empty_owner"],
)
def test_mechanical_intent_rejects_quantum_or_ambiguous_lifecycle(change):
    call = ComponentCall("move", "block_translation", ("W1",))
    kwargs = {"transport_owner": "line0/transport"}
    if change == "two_roles":
        call = replace(call, participant_roles=("W1", "W2"))
    elif change == "wrong_component":
        call = replace(call, component_id="toy.x")
    elif change == "prepare":
        kwargs["begin_preparation_owner"] = "line0/transport"
    elif change == "consume":
        call = replace(call, consumes_resource_role="W1")
    elif change == "selection":
        kwargs["selection"] = {}
    else:
        kwargs["transport_owner"] = ""
    with pytest.raises(ValueError, match="TRANSPORT_CALL"):
        CallIntent(call, "line0", **kwargs)


def test_external_mode_requires_supplier_instead_of_local_raw_fallback():
    with pytest.raises(ValueError, match="EXTERNAL_PREPARATION_SUPPLIER_REQUIRED"):
        FactoryProcess(
            "consumer",
            code=CODE,
            recipe=toy_recipe(),
            backend=DeclaredBackend(),
            role_bindings={r: r for r in ("W1", "W2", "R")},
            distance=1,
            external_inputs=True,
        )


@pytest.mark.parametrize("change", ("carrier", "distance", "status", "owner", "future"))
def test_external_supplier_cannot_relabel_or_use_incompatible_resource(change):
    ledger = ResourceLedger()
    token = offer(
        ledger,
        "other" if change == "carrier" else "R",
        distance=3 if change == "distance" else 1,
    )

    def supplied(process, request, identity, owner):
        yield WaitIntent(2, "fixture only")
        if change == "status":
            return token
        return ledger.reserve(
            token.token_id,
            consumer="wrong" if change == "owner" else owner,
            at_us=10 if change == "future" else 2,
            expected_code=CODE,
            expected_distance=ledger.carrier(token.carrier_id).distance,
            expected_kind="A",
            expected_canonicalization="canonical",
        )

    process = FactoryProcess(
        "consumer",
        code=CODE,
        recipe=toy_recipe(),
        backend=DeclaredBackend(),
        role_bindings={r: r for r in ("W1", "W2", "R")},
        distance=1,
        external_inputs=True,
        preparation_supplier=supplied,
    )
    process._runtime = SimpleNamespace(
        ledger=ledger, execution=SimpleNamespace(clock_us=2), milestones=[]
    )
    flow = process._prepare(preparation("R"), "scope", "consumer-owner")
    next(flow)
    with pytest.raises(ValueError, match="INCOMPATIBLE_EXTERNAL_RESOURCE"):
        flow.send(None)
    assert process.calls == []
