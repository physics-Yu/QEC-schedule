"""Synthetic receipt kernel exercises the same protocol flows without atom state."""

from types import MappingProxyType

import pytest
from nadit_physical_compiler.device import Region
from test_factory_execution import CODE, FixtureBackend, toy_recipe
from test_factory_process import _run

from modules.codes.contracts.component import ComponentExpansion
from modules.codes.contracts.parallel import ComponentExecutionSpec, SpaceClaim
from modules.logical_compiler.src.protocols.cooperative import CooperativeFactoryRuntime
from modules.logical_compiler.src.protocols.execution_kernel import (
    CorrectionPlan,
    PhysicalExecutionKernel,
)
from modules.logical_compiler.src.protocols.factory import FactoryLimits
from modules.logical_compiler.src.protocols.factory_process import FactoryProcess
from modules.logical_compiler.src.protocols.receipts import (
    ComponentReceipt,
    ExecutionCarrier,
)
from modules.logical_compiler.src.scheduling import ComponentScheduler


class ProbabilityOnlyBackend:
    """Expose scripted test probabilities/quality, with no binding interface."""

    def __init__(self, script):
        self.events = FixtureBackend(script)

    def resolve_event(self, selector, parameters=None):
        return self.events.resolve_event(selector, parameters)

    def preparation_quality(self, preparation, parameters=None):
        return self.events.preparation_quality(preparation, parameters)

    def output_quality(self, port):
        return self.events.output_quality(port)


class ReceiptKernel:
    """Declared timing fixture only; neither a physical model nor calibration."""

    representation = "logical_estimate"

    def __init__(self):
        self.carriers = MappingProxyType(
            {
                f"line-{line}/{role}": ExecutionCarrier(
                    f"line-{line}/{role}", "logical_estimate"
                )
                for line in range(2)
                for role in ("W1", "W2", "R", "D")
            }
        )
        self.clock_us = 0.0
        self.records = {}
        self.next_result = 0
        self.selections = []

    @property
    def used(self):
        return bool(self.records)

    @property
    def snapshot_id(self):
        return f"logical-fixture:{self.clock_us}:{len(self.records)}:{self.next_result}"

    def describe(self, backend, call, participant_blocks):
        measured = call.component_id in ("toy.raw", "toy.plus", "toy.mz", "toy.mx")
        positions = {name: index * 2 for index, name in enumerate(self.carriers)}
        return ComponentExecutionSpec(
            CODE,
            call.component_id,
            "raw/fixture" if call.component_id == "toy.raw" else None,
            participant_blocks,
            tuple(
                SpaceClaim(
                    Region(positions[p], 0, positions[p] + 1, 1), "logical fixture"
                )
                for p in participant_blocks
            ),
            (),
            "independent_aods_lockstep"
            if call.component_id == "toy.raw"
            else "exclusive",
            int(measured),
        )

    def execute(self, admission, requests):
        assert admission.snapshot_id == self.snapshot_id
        outputs = {}
        for node, request in zip(admission.nodes, requests, strict=True):
            assert request.bound_factory is None
            duration = 5 if request.selection is None else 0
            end = admission.start_us + duration
            ready = end + (3 if node.spec.result_count else 0)
            results = tuple(
                (self.next_result + i, ready) for i in range(node.spec.result_count)
            )
            self.next_result += node.spec.result_count
            receipt = ComponentReceipt(
                request.invocation_id,
                request.call.component_id,
                request.participant_blocks,
                admission.start_us,
                end,
                ready,
                results,
            )
            self.records[receipt.invocation_id] = receipt
            outputs[request.invocation_id] = (receipt,)
            if request.selection is not None:
                self.selections.append(dict(request.selection))
        self.clock_us = max(receipts[0].action_end_us for receipts in outputs.values())
        return outputs

    def source(self, invocation_id):
        return self.records[invocation_id]

    def event_parts(self, receipts):
        return receipts

    def correction_plan(
        self, backend, preparation, source, port, observation, *, event_id
    ):
        assert isinstance(source, ComponentReceipt)
        assert self.clock_us >= source.results_ready_us
        return CorrectionPlan(selection=observation.values)

    def wait_until(self, time_us, *, reason):
        self.clock_us = max(self.clock_us, time_us)

    def finalize(self):
        return None

    def snapshot(self):
        return {
            "schema": "test_fixture.receipt_timing/1",
            "calibrated": False,
            "receipts": [record.to_dict() for record in self.records.values()],
        }


@pytest.mark.parametrize("failure", [False, True])
def test_same_factory_flows_execute_using_only_logical_receipts(monkeypatch, failure):
    from nadit_physical_compiler.state import AtomLayout

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "Logical receipt execution must not construct physical objects"
        )

    scripts = ({"prep:W1": ("rejected",) if failure else ("rejected", "accepted")}, {})
    limits = FactoryLimits(raw_attempts=1 if failure else 3)
    physical_case, _ = _run(scripts, limits=limits)
    monkeypatch.setattr(AtomLayout, "__init__", forbidden)
    monkeypatch.setattr(ComponentExpansion, "__init__", forbidden)
    monkeypatch.setattr(PhysicalExecutionKernel, "__init__", forbidden)
    kernel = ReceiptKernel()
    processes = tuple(
        FactoryProcess(
            f"line-{line}",
            code=CODE,
            recipe=toy_recipe(),
            backend=ProbabilityOnlyBackend(script),
            role_bindings={
                role: f"line-{line}/{role}" for role in ("W1", "W2", "R", "D")
            },
            distance=1,
            limits=limits,
        )
        for line, script in enumerate(scripts)
    )
    case = (
        CooperativeFactoryRuntime(
            execution=kernel,
            case_id="cooperative-fixture",
            seed=17,
            scheduler=ComponentScheduler(),
            processes=processes,
        )
        .run()
        .to_dict()
    )
    assert case["physical"] is None and case["physical_validation"] == "not_run"
    assert case["schema"] == "nadit.logical_factory_case/1"
    assert case["status"] == physical_case["status"]

    def selected(document):
        return {
            (e["occurrence"]["invocation_id"], e["occurrence"]["attempt"]): e[
                "outcome_key"
            ]
            for e in document["events"]
        }

    assert selected(case) == selected(physical_case)
    assert all(p._runtime.execution is kernel for p in processes)
    assert kernel.selections and all(
        selection == {"accepted": True, "byproduct_class": 0}
        for selection in kernel.selections
    )
    assert all("atom_ids" not in carrier for carrier in case["resources"]["carriers"])
    assert all(
        dependency["result_identity_kind"] == "logical_interface"
        for event in case["events"]
        for dependency in event["dependencies"]
    )
    if not failure:
        assert any(mark.get("state") == "waiting_peers" for mark in case["milestones"])
    for name, line in case["factories"].items():
        assert line["status"] == physical_case["factories"][name]["status"]

    def tokens(document):
        return {
            t["token_id"]: (t["epoch"], t["status"], t["usage_kind"])
            for t in document["resources"]["tokens"]
        }

    assert tokens(case) == tokens(physical_case)
