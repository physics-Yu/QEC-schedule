"""The estimated execution boundary never binds physical components."""

from dataclasses import dataclass, replace
from types import SimpleNamespace

import pytest

from modules.codes.contracts.factory_recipe import ComponentCall
from modules.codes.contracts.parallel import ComponentExecutionSpec
from modules.logical_compiler.src.estimation.kernel import ProfileExecutionKernel
from modules.logical_compiler.src.protocols.execution_kernel import ExecutionRequest
from modules.logical_compiler.src.scheduling import ComponentNode, ComponentScheduler


class Profile:
    profile_sha256 = "f" * 64

    def describe(self, component_id, participants, parameters=(), **kwargs):
        return ComponentExecutionSpec(
            "toy",
            component_id,
            "local",
            tuple(p.block_id for p in participants),
            (),
            (),
            "independent_aods_lockstep",
            1,
        )

    def lookup(self, component_id, participants, selection=None, parameters=()):
        return SimpleNamespace(
            key=component_id,
            phase_durations_us=(2.0, 3.0),
            measurement_phases=((0, 10.0),),
            cost_segments=(
                {
                    "start_offset_us": 0.0,
                    "end_offset_us": 2.0,
                    "category": "measurement",
                    "resource": "camera",
                },
            ),
            primitive_counts={"Measure": 1},
        )


def kernel():
    return ProfileExecutionKernel(
        Profile(),
        SimpleNamespace(
            bindings={name: SimpleNamespace(block_id=name) for name in ("a", "b")},
            budget={},
        ),
    )


def test_receipts_keep_measurement_readiness_and_parallel_costs():
    execution = kernel()
    scheduler = ComponentScheduler()
    call = ComponentCall("read", "read", ("work",))
    scheduler.add(
        *(
            ComponentNode(name, execution.describe(None, call, (name,)))
            for name in ("a", "b")
        )
    )
    admission = scheduler.admit(0, snapshot_id=execution.snapshot_id)
    receipts = execution.execute(
        admission,
        tuple(ExecutionRequest(name, None, call, (name,)) for name in ("a", "b")),
    )
    assert execution.clock_us == 5
    assert [receipts[name][0].results_ready_us for name in ("a", "b")] == [12, 12]
    assert {receipts[name][0].result_availability[0][0] for name in ("a", "b")} == {
        0,
        1,
    }
    execution.wait_until(12, reason="feedback")
    snapshot = execution.snapshot()
    assert snapshot["accounting"]["work_by_category_us"]["measurement"] == 4
    assert snapshot["accounting"]["resource_busy_us"]["camera"] == 2
    assert execution.finalize() is None
    assert all(not carrier.atom_ids for carrier in execution.carriers.values())


def test_native_binding_and_stale_admission_fail_before_mutation():
    execution = kernel()
    scheduler = ComponentScheduler()
    call = ComponentCall("read", "read", ("work",))
    scheduler.add(ComponentNode("a", execution.describe(None, call, ("a",))))
    admission = scheduler.admit(0, snapshot_id=execution.snapshot_id)
    with pytest.raises(ValueError, match="NATIVE_BINDING"):
        execution.execute(
            admission,
            (ExecutionRequest("a", None, call, ("a",), lambda: pytest.fail("bound")),),
        )
    assert not execution.used
    execution.wait_until(1, reason="advance")
    with pytest.raises(ValueError, match="STALE"):
        execution.execute(admission, (ExecutionRequest("a", None, call, ("a",)),))


@dataclass(frozen=True)
class FixtureOrigin:
    x: float
    y: float


@dataclass(frozen=True)
class FixturePatch:
    block_id: str
    code_id: str
    distance: int
    origin: FixtureOrigin
    role: str = "stable-carrier-label"


class StatefulProfile(Profile):
    """Synthetic stateful profile; lookup never changes its committed bindings."""

    def __init__(self, damage=None):
        self.bindings = {
            name: FixturePatch(name, "toy", 3, FixtureOrigin(10 * index, 0))
            for index, name in enumerate(("a", "b"))
        }
        self.damage = damage
        self.prepared = self.committed = self.lookup_count = 0
        self.revision = 0
        self.described = []
        self.evidence = {"trace_sha256": "a" * 64, "transition": {"kind": "fixture"}}

    def describe(self, component_id, participants, parameters=(), **kwargs):
        self.described.append(tuple(participants))
        return super().describe(component_id, participants, parameters, **kwargs)

    def lookup(self, component_id, participants, selection=None, parameters=()):
        self.lookup_count += 1
        entry = super().lookup(component_id, participants, selection, parameters)
        if self.damage == "phase" and participants[0].block_id == "b":
            entry.phase_durations_us = (2.0, 4.0)
        return entry

    def prepare_wave_update(self, requests, entries):
        from modules.logical_compiler.src.estimation.kernel import PreparedProfileUpdate

        self.prepared += 1
        assert len(entries) == len(requests)
        assert all(
            entry.key == request.call.component_id
            for request, entry in zip(requests, entries, strict=True)
        )
        previous = dict(self.bindings)
        following = dict(previous)
        for request in requests:
            for name in request.participant_blocks:
                patch = following[name]
                following[name] = replace(
                    patch, origin=replace(patch.origin, y=patch.origin.y - 10)
                )
        if self.damage == "stale":
            previous["a"] = replace(previous["a"], origin=FixtureOrigin(0, 99))
        elif self.damage == "missing":
            del following["b"]
        elif self.damage in ("block_id", "code_id", "role", "distance"):
            following["a"] = replace(
                following["a"],
                **{self.damage: 5 if self.damage == "distance" else "bad"},
            )
        elif self.damage == "origin":
            following["a"] = replace(
                following["a"], origin=FixtureOrigin(float("nan"), 0)
            )
        elif self.damage == "mutable":
            following["a"] = SimpleNamespace(**vars(following["a"]))
        evidence = self.evidence
        if self.damage == "evidence":
            evidence = {"value": float("nan")}

        def commit():
            if self.damage == "commit":
                raise ValueError("FIXTURE_COMMIT_FAILED")
            assert self.bindings == previous
            self.bindings = following
            self.revision += 1
            self.committed += 1

        return PreparedProfileUpdate(
            following, commit, evidence, previous_bindings=previous
        )


def stateful_kernel(damage=None):
    profile = StatefulProfile(damage)
    execution = ProfileExecutionKernel(
        profile, SimpleNamespace(bindings=profile.bindings, budget={})
    )
    return profile, execution


def proposed_wave(execution, *, suffix="", participants=("a", "b"), component="read"):
    scheduler = ComponentScheduler()
    call = ComponentCall(component, component, ("work",))
    scheduler.add(
        *(
            ComponentNode(name + suffix, execution.describe(None, call, (name,)))
            for name in participants
        )
    )
    return (
        scheduler.admit(execution.clock_us, snapshot_id=execution.snapshot_id),
        tuple(
            ExecutionRequest(name + suffix, None, call, (name,))
            for name in participants
        ),
    )


def test_stateful_profile_commits_once_and_next_wave_uses_updated_binding():
    profile, execution = stateful_kernel()
    before = dict(profile.bindings)
    profile.lookup("read", (before["a"],))
    assert profile.bindings == before and profile.prepared == profile.committed == 0
    admission, requests = proposed_wave(execution)
    snapshot_id = execution.snapshot_id
    receipts = execution.execute(admission, requests)
    assert profile.prepared == profile.committed == profile.revision == 1
    assert execution.clock_us == 5 and execution.snapshot_id != snapshot_id
    assert receipts["a"][0].result_availability == ((0, 12.0),)
    assert profile.bindings["a"].origin.y == -10
    assert execution.carriers["a"].atom_ids == ()
    wave = execution.snapshot()["waves"][0]
    assert wave["state_transition"] == profile.evidence
    profile.evidence["transition"]["kind"] = "mutated-after-commit"
    assert wave["state_transition"]["transition"]["kind"] == "fixture"
    admission, requests = proposed_wave(execution, suffix="-next", participants=("a",))
    assert profile.described[-1][0] == profile.bindings["a"]
    execution.execute(admission, requests)
    assert profile.prepared == profile.committed == 2
    assert execution.clock_us == 10
    assert profile.bindings["a"].origin.y == -20
    assert profile.bindings["b"].origin.y == -10


def test_phase_rejection_does_not_prepare_or_commit_profile_update():
    profile, execution = stateful_kernel("phase")
    admission, requests = proposed_wave(execution)
    before, bindings = execution.snapshot(), dict(profile.bindings)
    snapshot_id = execution.snapshot_id
    with pytest.raises(ValueError, match="LOCKSTEP_PHASE_MISMATCH"):
        execution.execute(admission, requests)
    assert execution.snapshot() == before and execution.snapshot_id == snapshot_id
    assert execution.clock_us == 0 and not execution.used
    assert profile.bindings == bindings and profile.prepared == profile.committed == 0


@pytest.mark.parametrize(
    "damage",
    (
        "stale",
        "missing",
        "block_id",
        "code_id",
        "distance",
        "role",
        "origin",
        "mutable",
        "evidence",
    ),
)
def test_invalid_prepared_update_leaves_kernel_and_profile_uncommitted(damage):
    profile, execution = stateful_kernel(damage)
    admission, requests = proposed_wave(execution)
    before, bindings = execution.snapshot(), dict(profile.bindings)
    snapshot_id = execution.snapshot_id
    with pytest.raises((ValueError, TypeError), match="PROFILE_UPDATE"):
        execution.execute(admission, requests)
    assert execution.snapshot() == before and execution.snapshot_id == snapshot_id
    assert execution.clock_us == 0 and not execution.used
    assert profile.bindings == bindings and profile.prepared == 1
    assert profile.committed == profile.revision == 0


def test_profile_commit_failure_preserves_kernel_and_can_retry_same_admission():
    profile, execution = stateful_kernel("commit")
    admission, requests = proposed_wave(execution)
    before, bindings = execution.snapshot(), dict(profile.bindings)
    snapshot_id = execution.snapshot_id
    with pytest.raises(ValueError, match="FIXTURE_COMMIT_FAILED"):
        execution.execute(admission, requests)
    assert execution.snapshot() == before and execution.snapshot_id == snapshot_id
    assert profile.bindings == bindings and profile.committed == 0
    assert execution.clock_us == 0 and not execution.used
    profile.damage = None
    execution.execute(admission, requests)
    assert profile.prepared == 2 and profile.committed == 1
    assert execution.snapshot()["logical_result_count"] == 2


def test_optional_empty_profile_update_preserves_legacy_wave_and_bindings():
    execution = kernel()
    observed = []

    def prepare(requests, entries):
        observed.append((requests, entries))

    execution.profile.prepare_wave_update = prepare
    admission, requests = proposed_wave(execution)
    execution.execute(admission, requests)
    assert len(observed) == 1 and observed[0][0] == requests
    assert execution.clock_us == 5
    assert "state_transition" not in execution.snapshot()["waves"][0]


def test_handoff_receipts_require_profile_native_proof_even_with_provenance():
    execution = kernel()
    admission, requests = proposed_wave(execution, component="block_translation")
    result = execution.execute(admission, requests)
    receipts = tuple(result[name][0] for name in ("a", "b"))
    before = execution.snapshot()
    with pytest.raises(ValueError, match="PROFILE_PROOF_REQUIRED"):
        execution.validate_handoff_transport(
            receipts, expected_snapshot_id=execution.snapshot_id, expected_bindings=()
        )
    assert execution.snapshot() == before


@pytest.mark.parametrize("damage", ("stale", "foreign", "duplicate", "empty", "gate"))
def test_handoff_rejects_stale_or_uncommitted_receipts_before_profile_hook(damage):
    execution = kernel()
    component = "read" if damage == "gate" else "block_translation"
    admission, requests = proposed_wave(execution, component=component)
    result = execution.execute(admission, requests)
    receipts = tuple(result[name][0] for name in ("a", "b"))
    snapshot_id = execution.snapshot_id
    if damage == "stale":
        snapshot_id = admission.snapshot_id
    elif damage == "foreign":
        receipts = (replace(receipts[0], provenance_json='{"forged":true}'),)
    elif damage == "duplicate":
        receipts = (receipts[0], receipts[0])
    elif damage == "empty":
        receipts = ()
    execution.profile.validate_handoff_transport = lambda *a, **k: pytest.fail(
        "invalid receipts reached profile proof hook"
    )
    with pytest.raises(ValueError, match="HANDOFF_TRANSPORT"):
        execution.validate_handoff_transport(
            receipts, expected_snapshot_id=snapshot_id, expected_bindings=()
        )


def test_handoff_forwards_committed_receipts_and_expected_bindings_read_only():
    from nadit_physical_compiler.device import Position

    from modules.codes.contracts.component import ComponentBinding

    execution = kernel()
    admission, requests = proposed_wave(execution, component="block_translation")
    result = execution.execute(admission, requests)
    receipts = tuple(result[name][0] for name in ("a", "b"))
    bindings = (ComponentBinding("a", Position(0, 0), (1, 2), "transport"),)
    observed = []

    def verify(actual, *, expected_bindings):
        observed.append((actual, expected_bindings))

    execution.profile.validate_handoff_transport = verify
    before = execution.snapshot()
    execution.validate_handoff_transport(
        receipts, expected_snapshot_id=execution.snapshot_id, expected_bindings=bindings
    )
    assert observed == [(receipts, bindings)]
    assert execution.snapshot() == before


def committed_translation():
    execution = kernel()
    admission, requests = proposed_wave(
        execution, component="block_translation", participants=("a",)
    )
    receipt = execution.execute(admission, requests)["a"][0]
    return execution, receipt


def native_reference_fixture():
    """Synthetic reference identifiers, not a physical delivery claim."""
    return {
        "trace_sha256": "1" * 64,
        "entry_world_sha256": "2" * 64,
        "exit_world_sha256": "3" * 64,
        "entry_binding_sha256": "4" * 64,
        "exit_binding_sha256": "5" * 64,
    }


def test_transport_evidence_requires_profile_proof_and_preserves_its_exact_hashes():
    execution, receipt = committed_translation()
    before = execution.snapshot()
    with pytest.raises(ValueError, match="TRANSPORT_EVIDENCE_PROFILE_PROOF_REQUIRED"):
        execution.transport_evidence(receipt)
    evidence = native_reference_fixture()
    seen = []

    def proof(source):
        seen.append(source)
        return evidence

    execution.profile.transport_evidence = proof
    result = execution.transport_evidence(receipt)
    assert seen == [receipt]
    assert result == evidence
    result["trace_sha256"] = "6" * 64
    assert evidence == native_reference_fixture()
    assert execution.snapshot() == before


@pytest.mark.parametrize("damage", ("foreign", "gate"))
def test_transport_evidence_rejects_invalid_source_before_proof_hook(damage):
    execution, receipt = committed_translation()
    if damage == "foreign":
        receipt = replace(receipt, provenance_json='{"trace_sha256":"forged"}')
    else:
        admission, requests = proposed_wave(
            execution, suffix="-gate", participants=("a",)
        )
        receipt = execution.execute(admission, requests)["a-gate"][0]
    execution.profile.transport_evidence = lambda *a: pytest.fail("invalid source")
    with pytest.raises(ValueError, match="INVALID_TRANSPORT_EVIDENCE_RECEIPT"):
        execution.transport_evidence(receipt)


@pytest.mark.parametrize("damage", ("missing", "extra", "digest", "world", "binding"))
def test_transport_evidence_rejects_incomplete_or_nonmechanical_reference(damage):
    execution, receipt = committed_translation()
    evidence = native_reference_fixture()
    if damage == "missing":
        del evidence["entry_world_sha256"]
    elif damage == "extra":
        evidence["physical_delivery"] = True
    elif damage == "digest":
        evidence["trace_sha256"] = "unvalidated-label"
    elif damage == "world":
        evidence["exit_world_sha256"] = evidence["entry_world_sha256"]
    else:
        evidence["exit_binding_sha256"] = evidence["entry_binding_sha256"]
    execution.profile.transport_evidence = lambda _: evidence
    before = execution.snapshot()
    with pytest.raises(ValueError, match="INVALID_TRANSPORT_EVIDENCE_REFERENCES"):
        execution.transport_evidence(receipt)
    assert execution.snapshot() == before
