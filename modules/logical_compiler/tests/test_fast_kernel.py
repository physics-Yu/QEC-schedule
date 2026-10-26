"""The estimated execution boundary never binds physical components."""

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
