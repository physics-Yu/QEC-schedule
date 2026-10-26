"""Shared-world factory profiles backed by exact joint-frontier calibrations.

The common scheduler proposes disjoint members; execution requires a recorded
joint trace for that exact set. Missing coverage never becomes serial fallback.
"""

from collections.abc import Mapping
from dataclasses import replace
from math import isfinite
from typing import Any

from nadit_physical_compiler.provenance import canonical_hash

from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.contracts.parallel import ComponentExecutionSpec, SharedAODClaim

from .fast_factory import SurfaceFactoryProfile, entry_key


class MissingJointCalibration(RuntimeError):
    """An offline calibration is required before this frontier can execute."""

    def __init__(self, members: tuple[str, ...]) -> None:
        self.members = tuple(sorted(members))
        self.key = canonical_hash({"members": self.members})
        super().__init__(f"MISSING_JOINT_CALIBRATION: {self.key}: {self.members}")


def joint_key(members: tuple[str, ...]) -> str:
    """Identify a complete unordered frontier, retaining each ordered binding."""
    return canonical_hash({"members": tuple(sorted(members))})


class JointSurfaceFactoryProfile(SurfaceFactoryProfile):
    """Finite exact group coverage for arbitrary distance and module count."""

    def __init__(self, document: Mapping[str, Any]) -> None:
        super().__init__(document)
        self.joint_family = str(document["joint_calibration"]["family"])
        self.groups = self._document.setdefault("joint_groups", {})
        self.schedule_interpretation = "exact shared-device joint-frontier calibration; physical scheduler resolves within-wave conflicts"

    def layout(self, hardware: str = "shared_aod") -> Any:
        """Keep the agreed single AOD and vertical layout."""
        if hardware != "shared_aod":
            raise ValueError("JOINT_FACTORY_REQUIRES_ORIGINAL_SHARED_DEVICE")
        layout = super().layout(hardware)
        budget = dict(layout.budget)
        limits = self._document["joint_calibration"].get("limits", {})
        budget.update(
            reservation_policy="exact joint-frontier physical calibration on one shared AOD",
            independent_control_scope=None,
            aod_max_rows=limits.get("max_rows"),
            aod_max_columns=limits.get("max_columns"),
            max_readout_atoms=limits.get("max_readout_atoms"),
        )
        return replace(layout, budget=budget)

    def describe(
        self,
        component_id: str,
        participants: tuple[Any, ...],
        selection: Any = None,
        parameters: Any = (),
        *,
        budget: Mapping[str, Any],
    ) -> ComponentExecutionSpec:
        """Declare shared composition; exact capacities/timing are checked per group."""
        entry = self.lookup(component_id, participants, selection, parameters)
        if budget["hardware"] != "shared_aod" or budget["aod_count"] != 1:
            raise ValueError("JOINT_FACTORY_DEVICE_BUDGET_CHANGED")
        identity = entry_key(component_id, tuple(p.block_id for p in participants))
        claim = SharedAODClaim(
            aod_id="transport",
            row_trajectory_key=self.joint_family,
            column_min=min(p.origin.x for p in participants),
            column_max=max(p.origin.x for p in participants),
            peak_rows=None,
            peak_columns=None,
            max_rows=budget["aod_max_rows"],
            max_columns=budget["aod_max_columns"],
            readout_channel="camera",
            peak_readout_atoms=None,
            max_readout_atoms=budget["max_readout_atoms"],
            joint_family=self.joint_family,
            joint_member=identity,
        )
        return ComponentExecutionSpec(
            self.code_id,
            component_id,
            self.joint_family,
            tuple(p.block_id for p in participants),
            (),
            (),
            "shared_aod_lockstep",
            entry.claim["result_count"],
            claim,
        )

    def group(self, members: tuple[str, ...]) -> dict[str, Any]:
        """Read an exact calibration; no physical compiler is imported or called."""
        key = joint_key(members)
        if key not in self.groups:
            raise MissingJointCalibration(members)
        result: dict[str, Any] = self.groups[key]
        if (
            tuple(sorted(result["members"])) != tuple(sorted(members))
            or result["family"] != self.joint_family
            or result["validation_ok"] is not True
        ):
            raise ValueError("INVALID_JOINT_CALIBRATION_IDENTITY")
        phases = result["phase_durations_us"]
        if not phases or any(
            type(t) not in (int, float) or not isfinite(t) or t < 0 for t in phases
        ):
            raise ValueError("INVALID_JOINT_CALIBRATION_PHASES")
        duration = sum(phases)
        if any(
            type(result[k]) is not int or result[k] < 0
            for k in ("peak_rows", "peak_columns", "peak_readout_atoms")
        ):
            raise ValueError("INVALID_JOINT_RESOURCE_PEAK")
        for item in result["members"].values():
            if any(
                type(i) is not int
                or not 0 <= i < len(phases)
                or not isfinite(latency)
                or latency < 0
                for i, latency in item["measurement_phases"]
            ):
                raise ValueError("INVALID_JOINT_MEASUREMENT_PHASE")
            if any(
                not 0
                <= segment["start_offset_us"]
                <= segment["end_offset_us"]
                <= duration + 1e-7
                for segment in item["cost_segments"]
            ):
                raise ValueError("INVALID_JOINT_COST_INTERVAL")
        return result

    def lookup_batch(self, requests: tuple[Any, ...]) -> tuple[Any, ...]:
        """Return per-member result times and costs from one actual joint trace."""
        members = tuple(
            entry_key(r.call.component_id, r.participant_blocks) for r in requests
        )
        group = self.group(members)
        limits = self._document["joint_calibration"].get("limits", {})
        for peak, limit in (
            ("peak_rows", "max_rows"),
            ("peak_columns", "max_columns"),
            ("peak_readout_atoms", "max_readout_atoms"),
        ):
            if limits.get(limit) is not None and group[peak] > limits[limit]:
                raise ValueError("JOINT_CALIBRATION_EXCEEDS_DEVICE_CAPACITY")
        entries = []
        for request, member in zip(requests, members, strict=True):
            base = self.lookup(
                request.call.component_id,
                tuple(self._patches[b] for b in request.participant_blocks),
                request.selection,
                request.call.parameters,
            )
            item = group["members"][member]
            phases = tuple(group["phase_durations_us"])
            measurements = tuple(tuple(pair) for pair in item["measurement_phases"])
            if len(measurements) != base.claim["result_count"]:
                raise ValueError("JOINT_RESULT_COVERAGE_MISMATCH")
            entries.append(
                replace(
                    base,
                    phase_durations_us=phases,
                    measurement_phases=measurements,
                    result_ready_offsets_us=tuple(
                        sum(phases[: i + 1]) + latency for i, latency in measurements
                    ),
                    cost_segments=tuple(item["cost_segments"]),
                    primitive_counts=item["primitive_counts"],
                    claim={
                        **base.claim,
                        "joint_group_key": joint_key(members),
                        "joint_trace_sha256": group["trace_sha256"],
                        "joint_resource_peaks": {
                            k: group[k]
                            for k in ("peak_rows", "peak_columns", "peak_readout_atoms")
                        },
                    },
                )
            )
        return tuple(entries)

    def preparation_event_port(self, preparation: str, source: Any) -> ProbabilityPort:
        """Bind injection acceptance to the same jointly compiled source receipt."""
        if preparation == "initialize_plus":
            return self.preparation_port(preparation, source.participant_blocks[0])
        key = source.provenance["joint_group_key"]
        group = self.groups[key]
        if group["trace_sha256"] != source.provenance["joint_trace_sha256"]:
            raise ValueError("JOINT_PREPARATION_TRACE_MISMATCH")
        member = entry_key(preparation, source.participant_blocks)
        return ProbabilityPort.from_dict(group["raw_ports"][member])
