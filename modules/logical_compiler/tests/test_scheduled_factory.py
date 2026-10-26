"""Generic scheduling/lifecycle fixtures, not surface or physical evidence."""

from types import SimpleNamespace

from nadit_physical_compiler.device import Region
from test_factory_execution import CODE, FixtureBackend, FixturePhysical, toy_recipe

from modules.codes.contracts.parallel import ComponentExecutionSpec, SpaceClaim
from modules.logical_compiler.src.protocols.factory import FactoryExecutor
from modules.logical_compiler.src.scheduling import ComponentScheduler


class DeclaredBackend(FixtureBackend):
    def describe_execution(self, component_id, participants, parameters=()):
        count = int(component_id in ("toy.raw", "toy.plus", "toy.mz", "toy.mx"))
        single = len(participants) == 1 and component_id == "toy.raw"
        return ComponentExecutionSpec(
            CODE,
            component_id,
            component_id if single else None,
            tuple(p.block_id for p in participants),
            tuple(
                SpaceClaim(
                    Region(p.origin.x - 0.1, -0.1, p.origin.x + 0.1, 0.1), "fixture"
                )
                for p in participants
            ),
            (),
            "independent_aods_lockstep" if single else "exclusive",
            count,
        )


class BatchedPhysical(FixturePhysical):
    @property
    def snapshot_id(self):
        return f"fixture:{self.clock_us}:{len(self.committed)}"

    def invoke_batch(self, admission, requests, *, not_before_us=0):
        assert admission.snapshot_id == self.snapshot_id
        start, parts, ends = self.clock_us, [], []
        for request in requests:
            self.clock_us = start
            value = self.invoke(
                request.bound, request.invocation_id, request.result_count
            )
            parts.append((request.invocation_id, value))
            ends.append(self.clock_us)
        self.clock_us = max(ends)
        return SimpleNamespace(member_parts=tuple(parts), action_end_us=self.clock_us)


def scheduled(mode, *, scripts=None):
    backend = DeclaredBackend(
        {"prep:W1": ("rejected", "accepted")} if scripts is None else scripts
    )
    physical = BatchedPhysical()
    runner = FactoryExecutor(
        code=CODE,
        recipe=toy_recipe(),
        backend=backend,
        physical=physical,
        role_bindings={role: role for role in physical.bindings},
        distance=1,
        case_id="test-fixture-factory",
        seed=17,
        scheduler=ComponentScheduler(mode=mode),
    )
    return runner.run().to_dict(), physical


def test_initial_frontier_parallelizes_and_retries_only_failed_patch():
    case, physical = scheduled("parallel")
    assert case["status"] == "complete", case["failure"]
    bodies = [
        c
        for c in case["calls"]
        if c["component_id"] == "toy.raw" and "/prepare/W" in c["invocation_id"]
    ]
    first = [c for c in bodies if "/attempt[0]/" in c["invocation_id"]]
    assert len(first) == 2 and first[0]["start_us"] == first[1]["start_us"]
    assert len([c for c in bodies if "/prepare/W1/" in c["invocation_id"]]) == 2
    assert len([c for c in bodies if "/prepare/W2/" in c["invocation_id"]]) == 1
    w2 = next(t for t in case["resources"]["tokens"] if "/prepare/W2/" in t["token_id"])
    retry = next(c for c in bodies if "/attempt[1]/" in c["invocation_id"])
    assert w2["ready_at_us"] <= retry["start_us"]
    assert first[0]["after_calls"] == first[1]["after_calls"] == []
    assert case["component_schedule"]["policy"]["mode"] == "parallel"
    assert all(c["end_us"] >= c["start_us"] for c in case["calls"])
    assert physical.clock_us == case["duration_us"]


def test_serial_and_parallel_share_events_but_not_false_global_dependencies():
    # Separate the concurrency saving from retry latency hidden by serial work.
    serial, _ = scheduled("serial", scripts={})
    parallel, _ = scheduled("parallel", scripts={})
    assert serial["status"] == parallel["status"] == "complete"
    outcomes = lambda case: {
        (e["occurrence"]["invocation_id"], e["occurrence"]["attempt"]): e["outcome_key"]
        for e in case["events"]
    }
    assert outcomes(serial) == outcomes(parallel)
    assert parallel["duration_us"] < serial["duration_us"]
    initial = next(
        c
        for c in serial["calls"]
        if c["invocation_id"].endswith("prepare/W2/attempt[0]/body")
    )
    assert initial["after_calls"] == []


def test_empty_t_branch_still_gates_uncompute_on_declared_data_role():
    case, _ = scheduled("parallel", scripts={})
    uncompute = next(c for c in case["calls"] if c["component_id"] == "toy.uncompute")
    assert any(
        e["invocation_id"].endswith("rotation/event")
        for e in uncompute["event_dependencies"]
    )


def test_batch_retry_reset_waits_for_final_rejection_on_unmeasured_output_role():
    from modules.logical_compiler.src.protocols.factory import FactoryLimits

    backend, physical = (
        DeclaredBackend({"final": ("rejected", "accepted")}),
        BatchedPhysical(),
    )
    runner = FactoryExecutor(
        code=CODE,
        recipe=toy_recipe(),
        backend=backend,
        physical=physical,
        role_bindings={role: role for role in physical.bindings},
        distance=1,
        case_id="test-fixture-factory",
        seed=17,
        limits=FactoryLimits(batches=2),
        scheduler=ComponentScheduler(mode="parallel"),
    )
    case = runner.run().to_dict()
    assert case["status"] == "complete", case["failure"]
    reset = next(
        c
        for c in case["calls"]
        if c["invocation_id"] == "factory/batch[1]/prepare/W1/attempt[0]/body"
    )
    assert any(
        e["invocation_id"] == "factory/batch[0]/final/event"
        for e in reset["event_dependencies"]
    )
