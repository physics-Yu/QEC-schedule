"""Physical adaptation preserves the legacy cases and their native sources."""

from dataclasses import replace
from types import SimpleNamespace

import pytest
from nadit_physical_compiler.device import Region
from nadit_physical_compiler.provenance import canonical_hash
from test_factory_process import _run
from test_protocol_physical import _part
from test_protocol_physical import setup_world as setup_world  # noqa: PLC0414

from modules.codes.contracts.factory_recipe import ComponentCall
from modules.codes.contracts.parallel import ComponentExecutionSpec, SpaceClaim
from modules.logical_compiler.src.protocols.execution_kernel import (
    ExecutionRequest,
    PhysicalExecutionKernel,
)
from modules.logical_compiler.src.protocols.factory import FactoryLimits
from modules.logical_compiler.src.protocols.physical import PhysicalContext
from modules.logical_compiler.src.scheduling import ComponentNode, ComponentScheduler


@pytest.mark.parametrize(
    "scenario,expected",
    [
        (
            "complete",
            "bf7ee28d6180107928655a11b58058df13a7d730dd689d56463575bca23fd8b3",
        ),
        ("retry_s", "c508ec7a5c5ceb75319aaf6628dff62fcaed1afb266dbddde8d0a1ba2b8b3af8"),
        ("failure", "d5592a9819fa7c14a288a0916f54d922633a7759347c64fb43744ab02d40fd52"),
        (
            "algorithm",
            "83eabf4df0e15fb3726f2a01e23aa9e0baf2c9950856ab749a553e777ec69104",
        ),
    ],
)
def test_complete_physical_wrapper_case_matches_pre_kernel_golden(scenario, expected):
    # Captured before introducing ExecutionKernel. The entire deterministic
    # fixture includes ledger, event models, schedule, lifecycle and timestamps.
    if scenario == "retry_s":
        case, _ = _run(
            ({"prep:W1": ("rejected", "accepted"), "t:rotation": ("m1",)}, {})
        )
    elif scenario == "failure":
        case, _ = _run(
            ({"prep:W1": ("rejected",)}, {}), limits=FactoryLimits(raw_attempts=1)
        )
    else:
        case, _ = _run(algorithm=scenario == "algorithm")
    assert canonical_hash(case) == expected


def test_native_source_without_optional_exit_binding_normalizes_after_commit(
    setup_world,
):
    device, world, bindings = setup_world
    context = PhysicalContext(device, world, bindings)
    kernel = PhysicalExecutionKernel(context)
    call = ComponentCall("rotate", "rotation", ("A",))

    class Backend:
        def describe_execution(self, component, participants, parameters):
            binding = participants[0]
            return ComponentExecutionSpec(
                "test",
                component,
                "local/fixture",
                (binding.block_id,),
                (
                    SpaceClaim(
                        Region(binding.origin.x - 1, -1, binding.origin.x + 1, 1),
                        "fixture",
                    ),
                ),
                (),
                "local_parallel",
                0,
            )

        def bind_call(self, component, participants, parameters):
            return SimpleNamespace(
                result_count=0,
                expand=lambda invocation: replace(
                    _part(invocation, participants[0], "rotation"), exit_binding=None
                ),
            )

    backend = Backend()
    scheduler = ComponentScheduler()
    scheduler.add(ComponentNode("native", kernel.describe(backend, call, ("A",))))
    admission = scheduler.admit(0, snapshot_id=kernel.snapshot_id)
    receipts = kernel.execute(
        admission, (ExecutionRequest("native", backend, call, ("A",)),)
    )["native"]
    assert receipts[0].participant_blocks == ("A",)
    assert receipts[0].representation == "physical"
    source = kernel.source("native")
    assert source is context.source("native") and source.exit_binding is None
    assert kernel.event_parts(receipts) == (source,)
    assert context.finalize().validation["ok"] is True
