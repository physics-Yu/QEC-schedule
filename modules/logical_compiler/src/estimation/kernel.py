"""Execute admitted component waves from explicit calibrated summaries only.

This adapter creates logical receipts, never atom programs or physical bindings.
Its profile and placement are code-owned objects with lookup/describe interfaces.
The protocol state machine, scheduler and resource ledger remain shared.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from math import isfinite
from typing import Any

from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.contracts.factory_recipe import ComponentCall
from modules.codes.contracts.parallel import ComponentExecutionSpec

from ..protocols.events import EventDependency, EventObservation
from ..protocols.execution_kernel import (
    CorrectionPlan,
    ExecutionBindingError,
    ExecutionRequest,
)
from ..protocols.receipts import ComponentReceipt, ExecutionCarrier, Representation
from ..scheduling import Admission
from ..scheduling.compatibility import compatible_specs
from .metrics import summarize_costs


class ProfileExecutionKernel:
    """One monotone logical timeline with explicit calibration provenance.

    Coverage and admission checks complete before committing a wave. Profile
    phase boundaries preserve measurement availability before return transport;
    result identifiers belong only to logical interfaces, not physical bits.
    """

    representation: Representation = "logical_estimate"

    def __init__(self, profile: Any, layout: Any) -> None:
        self.profile, self.layout = profile, layout
        self._patches = dict(layout.bindings)
        self._carriers = {
            name: ExecutionCarrier(name, "logical_estimate") for name in self._patches
        }
        self._clock_us = 0.0
        self._revision = 0
        self._result_index = 0
        self._receipts: dict[str, ComponentReceipt] = {}
        self.calls: list[dict[str, Any]] = []
        self.waits: list[dict[str, Any]] = []
        self._waves: list[dict[str, Any]] = []

    @property
    def carriers(self) -> Mapping[str, ExecutionCarrier]:
        return self._carriers.copy()

    @property
    def clock_us(self) -> float:
        return self._clock_us

    @property
    def snapshot_id(self) -> str:
        return f"logical-estimate:{self.profile.profile_sha256}:{self._revision}"

    @property
    def used(self) -> bool:
        return bool(self._receipts)

    def describe(
        self, backend: Any, call: ComponentCall, participant_blocks: tuple[str, ...]
    ) -> ComponentExecutionSpec:
        """Request code-owned claims without physical binding or expansion."""
        result: ComponentExecutionSpec = self.profile.describe(
            call.component_id,
            tuple(self._patches[name] for name in participant_blocks),
            parameters=call.parameters,
            budget=self.layout.budget,
        )
        return result

    def execute(
        self, admission: Admission, requests: tuple[ExecutionRequest, ...]
    ) -> dict[str, tuple[ComponentReceipt, ...]]:
        """Commit one checked logical wave using only finite calibrated phases."""
        if (
            admission.snapshot_id != self.snapshot_id
            or admission.start_us != self.clock_us
        ):
            raise ValueError("STALE_ESTIMATE_ADMISSION")
        if tuple(request.invocation_id for request in requests) != admission.node_ids:
            raise ValueError("ESTIMATE_ADMISSION_MEMBERS_DIFFER")
        if not compatible_specs(tuple(node.spec for node in admission.nodes)):
            raise ValueError("INCOMPATIBLE_ESTIMATE_ADMISSION")
        joint = any(
            node.spec.shared_aod is not None
            and node.spec.shared_aod.joint_family is not None
            for node in admission.nodes
        )
        batch_entries = None
        if joint:
            lookup_batch = getattr(self.profile, "lookup_batch", None)
            if not callable(lookup_batch):
                raise ValueError("JOINT_AOD_PROFILE_REQUIRES_GROUP_CALIBRATION")
            batch_entries = lookup_batch(requests)
            if len(batch_entries) != len(requests):
                raise ValueError("JOINT_PROFILE_MEMBER_COUNT_MISMATCH")
        staged: list[
            tuple[ExecutionRequest, Any, ComponentReceipt, dict[str, Any]]
        ] = []
        result_index = self._result_index
        for member_index, (node, request) in enumerate(
            zip(admission.nodes, requests, strict=True)
        ):
            try:
                if request.bound_factory is not None:
                    raise ValueError("ESTIMATE_NATIVE_BINDING_FORBIDDEN")
                if request.invocation_id in self._receipts:
                    raise ValueError("DUPLICATE_ESTIMATE_INVOCATION")
                if (
                    self.describe(
                        request.backend, request.call, request.participant_blocks
                    )
                    != node.spec
                ):
                    raise ValueError("ESTIMATE_DECLARATION_CHANGED")
                entry = (
                    batch_entries[member_index]
                    if batch_entries is not None
                    else self.profile.lookup(
                        request.call.component_id,
                        tuple(
                            self._patches[name] for name in request.participant_blocks
                        ),
                        selection=request.selection,
                        parameters=request.call.parameters,
                    )
                )
                ends, clock = [], admission.start_us
                for duration in entry.phase_durations_us:
                    if not isfinite(duration) or duration < 0:
                        raise ValueError("INVALID_ESTIMATE_PHASE")
                    clock += duration
                    ends.append(clock)
                ready_times = tuple(
                    ends[index] + latency for index, latency in entry.measurement_phases
                )
                if len(ready_times) != node.spec.result_count:
                    raise ValueError("ESTIMATE_RESULT_DECLARATION_MISMATCH")
                availability = tuple(enumerate(ready_times, start=result_index))
                result_index += len(availability)
                receipt = ComponentReceipt(
                    request.invocation_id,
                    request.call.component_id,
                    request.participant_blocks,
                    admission.start_us,
                    clock,
                    max((clock, *ready_times)),
                    availability,
                    provenance_json=json.dumps(
                        {
                            "profile_sha256": self.profile.profile_sha256,
                            "variant": entry.key,
                            **(
                                {
                                    "joint_group_key": entry.claim["joint_group_key"],
                                    "joint_trace_sha256": entry.claim[
                                        "joint_trace_sha256"
                                    ],
                                }
                                if joint
                                else {}
                            ),
                        },
                        sort_keys=True,
                    ),
                )
                record = {
                    **receipt.to_dict(),
                    "profile_key": entry.key,
                    "selection": None
                    if request.selection is None
                    else dict(request.selection),
                    "parameters": dict(request.call.parameters),
                    "cost_segments": [
                        {
                            "start_us": admission.start_us + part["start_offset_us"],
                            "end_us": admission.start_us + part["end_offset_us"],
                            "category": part["category"],
                            "resource": part["resource"],
                        }
                        for part in entry.cost_segments
                    ],
                    "primitive_counts": dict(entry.primitive_counts),
                }
                if joint:
                    assert node.spec.shared_aod is not None
                    record.update(
                        batch_id=admission.batch_id,
                        reserved_resources=list(node.spec.exclusive_resources),
                        shared_resources=[f"aod:{node.spec.shared_aod.aod_id}"],
                        parallel_mode=node.spec.parallel_mode,
                        joint_group_key=entry.claim["joint_group_key"],
                        joint_trace_sha256=entry.claim["joint_trace_sha256"],
                        joint_resource_peaks=dict(entry.claim["joint_resource_peaks"]),
                    )
                if node.spec.parallel_mode == "profile_parallel":
                    record["reserved_resources"] = list(node.spec.exclusive_resources)
                    record["parallel_mode"] = node.spec.parallel_mode
                    if node.spec.exclusive_resources:
                        for segment in record["cost_segments"]:
                            if segment["resource"] == "aod":
                                segment["resource"] = node.spec.exclusive_resources[0]
                staged.append((request, entry, receipt, record))
            except (ValueError, TypeError, KeyError, IndexError) as error:
                raise ExecutionBindingError(
                    request.invocation_id, str(error)
                ) from error
        if admission.nodes[0].spec.parallel_mode not in (
            "local_parallel",
            "profile_parallel",
        ) and any(
            item[1].phase_durations_us != staged[0][1].phase_durations_us
            for item in staged
        ):
            raise ValueError("ESTIMATE_LOCKSTEP_PHASE_MISMATCH")
        self._result_index = result_index
        for request, _, receipt, record in staged:
            self._receipts[request.invocation_id] = receipt
            self.calls.append(record)
        self._clock_us = max(receipt.action_end_us for _, _, receipt, _ in staged)
        self._waves.append(
            {
                "batch_id": admission.batch_id,
                "invocations": list(admission.node_ids),
                "start_us": admission.start_us,
                "end_us": self.clock_us,
            }
        )
        self._revision += 1
        return {request.invocation_id: (receipt,) for request, _, receipt, _ in staged}

    def source(self, invocation_id: str) -> ComponentReceipt:
        """Return the logical source receipt; no physical source exists."""
        return self._receipts[invocation_id]

    def event_parts(
        self, receipts: tuple[ComponentReceipt, ...]
    ) -> tuple[ComponentReceipt, ...]:
        if any(self._receipts.get(item.invocation_id) != item for item in receipts):
            raise ValueError("UNKNOWN_ESTIMATE_EVENT_SOURCE")
        return receipts

    def correction_plan(
        self,
        backend: Any,
        preparation: str,
        source: ComponentReceipt,
        port: ProbabilityPort,
        observation: EventObservation,
        *,
        event_id: str,
    ) -> CorrectionPlan:
        """Forward the jointly sampled local class, never sample a second label."""
        values = observation.values
        if (
            self.source(source.invocation_id) != source
            or preparation != source.component_id
            or values.get("accepted") is not True
            or dict(port.outcome(observation.result.outcome_key).values) != values
            or port.outcome(observation.result.outcome_key).probability <= 0
            or observation.result.port_sha256 != port.content_sha256
            or f"{observation.result.occurrence.invocation_id}/event[{observation.result.occurrence.attempt}]"
            != event_id
            or not source.results_ready_us
            <= observation.released_at_us
            <= self.clock_us
            or observation.dependencies != (EventDependency.from_receipt(source),)
        ):
            raise ValueError("INVALID_ESTIMATE_CORRECTION_EVENT")
        selector = getattr(self.profile, "correction_selection", None)
        if callable(selector):
            selection = selector(preparation, values)
        else:
            if "byproduct_class" not in values:
                raise ValueError("INVALID_ESTIMATE_CORRECTION_EVENT")
            selection = {"accepted": True, "byproduct_class": values["byproduct_class"]}
        self.profile.lookup(
            preparation + "/canonicalize",
            tuple(self._patches[name] for name in source.participant_blocks),
            selection=selection,
        )
        return CorrectionPlan(selection=selection)

    def wait_until(self, time_us: float, *, reason: str) -> None:
        if (
            type(time_us) not in (float, int)
            or not isfinite(time_us)
            or time_us < 0
            or not reason
        ):
            raise ValueError("INVALID_ESTIMATE_WAIT")
        if time_us > self.clock_us:
            self.waits.append(
                {"start_us": self.clock_us, "end_us": time_us, "reason": reason}
            )
            self._clock_us = float(time_us)
            self._revision += 1

    def finalize(self) -> None:
        """A logical estimate has no physical bundle or physical validation."""
        return

    def snapshot(self) -> dict[str, Any]:
        """Export component timing and modeled cost without atom-level claims."""
        return {
            "schema": "nadit.profile_execution/1",
            "representation": self.representation,
            "profile_sha256": self.profile.profile_sha256,
            "physical_validation": "not_run",
            "logical_result_count": self._result_index,
            "calls": list(self.calls),
            "waves": list(self._waves),
            "waits": list(self.waits),
            "accounting": summarize_costs(self.calls, self.waits, self.clock_us),
        }
