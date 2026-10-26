"""Shared-world factory profiles backed by exact joint-frontier calibrations.

The common scheduler proposes disjoint members; execution requires a recorded
joint trace for that exact set. Missing coverage never becomes serial fallback.
"""

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import replace
from math import isfinite
from types import MappingProxyType
from typing import Any

from nadit_physical_compiler.provenance import canonical_hash

from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.contracts.parallel import ComponentExecutionSpec, SharedAODClaim
from modules.codes.rotated_surface_d3.protocols.fast_profile import (
    ComponentCostProfile,
    FastPatch,
)
from modules.logical_compiler.src.placement import PlacementPlan

from .fast_factory import ROLES, SurfaceFactoryProfile, entry_key
from .joint_factory_contracts import STATIC_SCHEMA, static_contracts


class MissingJointCalibration(RuntimeError):
    """An offline calibration is required before this frontier can execute."""

    def __init__(
        self,
        members: tuple[str, ...],
        *,
        family: str | None = None,
        profile_sha256: str | None = None,
        placement_fingerprint: str | None = None,
        request: Mapping[str, Any] | None = None,
    ) -> None:
        self.members = tuple(sorted(members))
        self.key = canonical_hash({"members": self.members})
        self.family = family
        self.profile_sha256 = profile_sha256
        self.placement_fingerprint = placement_fingerprint
        self.request = None if request is None else deepcopy(dict(request))
        super().__init__(f"MISSING_JOINT_CALIBRATION: {self.key}: {self.members}")

    def to_dict(self) -> dict[str, Any]:
        """Describe missing work for an external runner; never execute it here."""
        return {
            "schema": "nadit.missing_joint_calibration/1",
            "reason": "joint_frontier_not_calibrated",
            "members": list(self.members),
            "member_key": self.key,
            "family": self.family,
            "profile_sha256": self.profile_sha256,
            "placement_fingerprint": self.placement_fingerprint,
            **(
                {"calibration_request": deepcopy(self.request)}
                if self.request is not None
                else {}
            ),
        }


def joint_key(members: tuple[str, ...]) -> str:
    """Identify a complete unordered frontier, retaining each ordered binding."""
    return canonical_hash({"members": tuple(sorted(members))})


class JointSurfaceFactoryProfile(SurfaceFactoryProfile):
    """Finite exact group coverage for arbitrary distance and module count."""

    def __init__(self, document: Mapping[str, Any]) -> None:
        self._placement_plan: PlacementPlan | None = None
        if document.get("schema") == STATIC_SCHEMA:
            self._initialize_static(document)
        else:
            super().__init__(document)
        self.joint_family = str(document["joint_calibration"]["family"])
        self.groups = self._document.setdefault("joint_groups", {})
        self.schedule_interpretation = "exact shared-device joint-frontier calibration; physical scheduler resolves within-wave conflicts"

    @classmethod
    def from_placement(
        cls,
        plan: PlacementPlan,
        *,
        family: str,
        noise_params: Mapping[str, Any],
        limits: Mapping[str, int | None] | None = None,
        metadata: Mapping[str, Any] | None = None,
        additional_calls: Sequence[tuple[str, tuple[str, ...]]] = (),
    ) -> "JointSurfaceFactoryProfile":
        """Create static coverage without singleton compilation or probability data.

        The caller supplies a validated placement and calibration-family identity.
        Additional calls extend coverage only for existing code-owned sources.
        Actual costs and raw probabilities must arrive as joint group records.
        Raises ValueError for incompatible geometry or incomplete factory roles.
        """
        contracts = static_contracts(plan, additional_calls)
        first = plan.blocks[0]
        mixed = len({block.code for block in plan.blocks}) > 1
        if not isinstance(family, str) or not family:
            raise ValueError("JOINT_STATIC_FAMILY_REQUIRED")
        return cls(
            {
                "schema": STATIC_SCHEMA,
                "distance": first.distance,
                "factory_count": len(plan.blocks) // len(ROLES),
                "noise_params": deepcopy(dict(noise_params)),
                "placement": plan.to_dict(),
                "source_contracts": {
                    key: value.to_dict(include_code_identity=mixed)
                    for key, value in contracts.items()
                },
                "additional_calls": [
                    [component, list(blocks)] for component, blocks in additional_calls
                ],
                "joint_calibration": {"family": family, "limits": dict(limits or {})},
                "joint_groups": {},
                "metadata": deepcopy(dict(metadata or {})),
            }
        )

    def _initialize_static(self, document: Mapping[str, Any]) -> None:
        self._document = deepcopy(dict(document))
        self._placement_plan = PlacementPlan.from_dict(document["placement"])
        plan = self._placement_plan
        additional = tuple(
            (item[0], tuple(item[1])) for item in document.get("additional_calls", ())
        )
        contracts = static_contracts(plan, additional)
        mixed = len({block.code for block in plan.blocks}) > 1
        if document["source_contracts"] != {
            key: value.to_dict(include_code_identity=mixed)
            for key, value in contracts.items()
        }:
            raise ValueError("JOINT_STATIC_CONTRACT_CHANGED")
        self.distance = plan.blocks[0].distance
        self.code_id = plan.blocks[0].code
        self.factory_count = len(plan.blocks) // len(ROLES)
        if (document["distance"], document["factory_count"]) != (
            self.distance,
            self.factory_count,
        ):
            raise ValueError("JOINT_STATIC_PROFILE_IDENTITY_MISMATCH")
        self.noise_params = deepcopy(dict(document["noise_params"]))
        self._patches = {
            block.block_id: FastPatch(
                block.block_id,
                str(block.factory_id),
                str(block.role),
                ROLES.index(str(block.role)),
                plan.placements[block.block_id].origin,
                block.code,
                block.distance,
            )
            for block in plan.blocks
        }
        self._validate_placement(plan)
        self.contracts = MappingProxyType(contracts)
        self.entries = MappingProxyType({})
        self.profile_sha256 = canonical_hash(self._document)

    def lookup(
        self,
        component_id: str,
        participants: tuple[Any, ...],
        selection: Mapping[str, Any] | None = None,
        parameters: Sequence[tuple[str, Any]] | Mapping[str, Any] = (),
    ) -> Any:
        """Check a source contract; only lookup_batch can return calibrated costs."""
        if self._placement_plan is None:
            return super().lookup(component_id, participants, selection, parameters)
        self.member_identity(component_id, participants)
        key = entry_key(component_id, tuple(p.block_id for p in participants))
        if key not in self.contracts:
            raise ValueError("UNCALIBRATED_GENERIC_COMPONENT")
        contract = self.contracts[key]
        if dict(parameters) != dict(contract.parameters):
            raise ValueError("UNCALIBRATED_GENERIC_PARAMETERS")
        if selection is not None and (
            not component_id.endswith("/canonicalize")
            or dict(selection)
            != {"accepted": True, "correction_policy": "one_pauli_layer_bound"}
        ):
            raise ValueError("INVALID_GENERIC_CORRECTION_SELECTION")
        return contract

    def layout(
        self,
        hardware: str = "shared_aod",
        *,
        placement_plan: PlacementPlan | None = None,
    ) -> Any:
        """Keep one AOD and accept only a plan matching the calibrated positions.

        Raises ValueError for changed hardware or placement; joint resource
        limits remain those recorded by this profile.
        """
        if hardware != "shared_aod":
            raise ValueError("JOINT_FACTORY_REQUIRES_ORIGINAL_SHARED_DEVICE")
        if placement_plan is None:
            placement_plan = self._placement_plan
        layout = super().layout(hardware, placement_plan=placement_plan)
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
            joint_code_ids=self.code_ids if len(self.code_ids) > 1 else (),
        )
        return ComponentExecutionSpec(
            self.member_identity(component_id, participants)[0],
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
            raise MissingJointCalibration(
                members,
                family=self.joint_family,
                profile_sha256=self.profile_sha256,
                placement_fingerprint=None
                if self._placement_plan is None
                else self._placement_plan.geometry_fingerprint,
            )
        result: dict[str, Any] = self.groups[key]
        return self._validate_group_record(result, members)

    def _validate_group_record(
        self, result: dict[str, Any], members: tuple[str, ...]
    ) -> dict[str, Any]:
        """Validate one exact record independently of the cache index strategy."""
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
        group = self.group_for_requests(requests)
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
            values: dict[str, Any] = {
                "phase_durations_us": phases,
                "measurement_phases": measurements,
                "result_ready_offsets_us": tuple(
                    sum(phases[: i + 1]) + latency for i, latency in measurements
                ),
                "cost_segments": tuple(item["cost_segments"]),
                "primitive_counts": item["primitive_counts"],
                "claim": {
                    **base.claim,
                    "joint_group_key": group.get(
                        "profile_group_key", joint_key(members)
                    ),
                    "joint_trace_sha256": group["trace_sha256"],
                    "joint_resource_peaks": {
                        k: group[k]
                        for k in ("peak_rows", "peak_columns", "peak_readout_atoms")
                    },
                },
            }
            if self._placement_plan is None:
                entries.append(replace(base, **values))
            else:
                entries.append(
                    ComponentCostProfile(
                        key=member,
                        component_id=request.call.component_id,
                        geometry=(),
                        selection_class=None,
                        waveform_key=self.joint_family,
                        events=(),
                        busy=(),
                        **values,
                    )
                )
        return tuple(entries)

    def group_for_requests(self, requests: tuple[Any, ...]) -> dict[str, Any]:
        """Resolve the exact frontier; stateful adapters may include call parameters."""
        return self.group(
            tuple(
                entry_key(r.call.component_id, r.participant_blocks) for r in requests
            )
        )

    def preparation_port(self, preparation: str, block_id: str) -> ProbabilityPort:
        """Require actual source receipts for static-profile raw acceptance."""
        if self._placement_plan is not None and preparation == "raw_t_postselection":
            raise ValueError("JOINT_PREPARATION_REQUIRES_SOURCE_RECEIPT")
        return super().preparation_port(preparation, block_id)

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
