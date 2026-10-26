"""Execute admitted component waves from explicit calibrated summaries only.

This adapter creates logical receipts, never atom programs or physical bindings.
Its profile and placement are code-owned objects with lookup/describe interfaces.
The protocol state machine, scheduler and resource ledger remain shared.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
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
from .phases import PhaseInvocation, PhaseSchedule, schedule_phases


def _retime_entry(entry: Any, identity: str, plan: PhaseSchedule) -> Any:
    """Project one shared schedule into the existing component cost record."""
    durations, measurements, offsets, segments = [], [], [], []
    now = 0.0
    for step in plan.steps:
        if identity not in step["members"]:
            continue
        start, end = step["start_us"], step["end_us"]
        if start > now:
            durations.append(start - now)
        durations.append(end - start)
        for _ in range(step["results"]):
            measurements.append((len(durations) - 1, step["latency_us"]))
            offsets.append(end + step["latency_us"])
        for resource in step["resources"] or ["none"]:
            segments.append(
                {
                    "start_offset_us": start,
                    "end_offset_us": end,
                    "category": step["category"],
                    "resource": resource,
                }
            )
        now = end
    return replace(
        entry,
        phase_durations_us=tuple(durations),
        measurement_phases=tuple(measurements),
        result_ready_offsets_us=tuple(offsets),
        cost_segments=tuple(segments),
    )


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
        object_plan = None
        object_entries = None
        if admission.nodes[0].spec.parallel_mode == "object_wave":
            instantiate = getattr(self.profile, "instantiate_wave", None)
            if not callable(instantiate):
                raise ValueError("OBJECT_WAVE_REQUIRES_PHASE_PROVIDER")
            entries = instantiate(requests)
            if len(entries) != len(requests):
                raise ValueError("OBJECT_WAVE_MEMBER_COUNT_MISMATCH")
            object_plan = schedule_phases(
                tuple(
                    PhaseInvocation(
                        request.invocation_id,
                        node.spec.code_id,
                        request.call.component_id,
                        entry.stages,
                    )
                    for request, node, entry in zip(
                        requests, admission.nodes, entries, strict=True
                    )
                ),
                timeout_seconds=getattr(self.profile, "wave_timeout_seconds", 5.0),
            )
            object_entries = tuple(
                _retime_entry(entry, request.invocation_id, object_plan)
                for request, entry in zip(requests, entries, strict=True)
            )
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
                    object_entries[member_index]
                    if object_entries is not None
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
                staged.append((request, entry, receipt, record))
            except (ValueError, TypeError, KeyError, IndexError) as error:
                raise ExecutionBindingError(
                    request.invocation_id, str(error)
                ) from error
        if admission.nodes[0].spec.parallel_mode not in (
            "local_parallel",
            "object_wave",
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
                **(
                    {
                        "stage_schedule": list(object_plan.steps),
                        "stage_waits": list(object_plan.waits),
                        "resource_busy_us": object_plan.resource_busy_us,
                        "stage_time_basis": "relative_to_wave_start",
                        "representation": "logical_estimate",
                    }
                    if object_plan is not None
                    else {}
                ),
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
        """Use the declared correction-selection policy without another random draw."""
        values = observation.values
        select_correction = getattr(self.profile, "correction_selection", None)
        if (
            self.source(source.invocation_id) != source
            or preparation != source.component_id
            or values.get("accepted") is not True
            or dict(port.outcome(observation.result.outcome_key).values) != values
            or port.outcome(observation.result.outcome_key).probability <= 0
            or observation.result.port_sha256 != port.content_sha256
            or (
                f"{observation.result.occurrence.invocation_id}/event["
                f"{observation.result.occurrence.attempt}]"
            )
            != event_id
            or not source.results_ready_us
            <= observation.released_at_us
            <= self.clock_us
            or (not callable(select_correction) and "byproduct_class" not in values)
            or observation.dependencies != (EventDependency.from_receipt(source),)
        ):
            raise ValueError("INVALID_ESTIMATE_CORRECTION_EVENT")
        selection = (
            select_correction(preparation, values)
            if callable(select_correction)
            else {"accepted": True, "byproduct_class": values["byproduct_class"]}
        )
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
