"""Surface component costs with explicit center-distance transport estimates.

This provider uses the common logical scheduler and never creates atom objects.
It retains archived intrinsic costs, while shared lockstep motion is a geometric
model assumption and is deliberately not labeled as physical joint calibration.
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import replace
from itertools import accumulate
from math import isfinite
from typing import Any

from nadit_physical_compiler.provenance import canonical_hash

from modules.codes.contracts.parallel import ComponentExecutionSpec
from modules.codes.rotated_surface_d3.protocols.fast_profile import (
    ComponentCostProfile,
    FastLayout,
    FastPatch,
)
from modules.logical_compiler.src.placement import (
    BlockSpec,
    PlacementPlan,
    PlacementRequest,
    VerticalFactoryPlacement,
    place,
)

from .center_costs import center_component_cost, reference_digest
from .fast_factory import ROLES, SurfaceFactoryProfile, acceptance_port, entry_key
from .geometry import geometry


def center_factory_plan(
    distance: int, count: int, *, gap_um: float = 40
) -> PlacementPlan:
    """Place six blocks per factory without constructing Device or AtomLayout."""
    if type(count) is not int or count < 1:
        raise ValueError("INVALID_CENTER_FACTORY_COUNT")
    code = f"rotated_surface_d{distance}"
    blocks = tuple(
        BlockSpec(f"factory{i}/{role}", code, distance, f"factory{i}", role)
        for i in range(count)
        for role in ROLES
    )
    return place(
        PlacementRequest(blocks, {code: geometry(code, distance)}),
        VerticalFactoryPlacement(ROLES, patch_gap_um=gap_um, factory_gap_um=gap_um),
    )


def _partitions(segments: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Keep category integrals compact; these bins are not native action order."""
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for segment in segments:
        basis = (
            "block_center_transport"
            if segment["basis"] == "center_distance_estimate"
            else "calibration_intrinsic"
        )
        resource = (
            "aod:transport" if segment["resource"] == "aod" else segment["resource"]
        )
        key = segment["category"], resource, basis
        row = groups.setdefault(
            key,
            {
                "category": key[0],
                "resource": resource,
                "basis": basis,
                "duration_us": 0.0,
                "atom_count": 0,
                "busy_atom_us": 0.0,
                "movement_distance_atom_um": 0.0,
                "primitive_counts": Counter(),
            },
        )
        row["duration_us"] += segment["duration_us"]
        row["atom_count"] = max(row["atom_count"], segment["atom_count"])
        row["busy_atom_us"] += segment["busy_atom_us"]
        row["movement_distance_atom_um"] += segment["movement_distance_atom_um"]
        row["primitive_counts"].update(segment["primitive_counts"])
    clock = 0.0
    result = []
    for row in groups.values():
        duration = row.pop("duration_us")
        row.update(start_offset_us=clock, end_offset_us=clock + duration)
        row["primitive_counts"] = dict(row["primitive_counts"])
        result.append(row)
        clock += duration
    return tuple(result)


class CenterSurfaceFactoryProfile(SurfaceFactoryProfile):
    """Same-component lockstep estimates on one configurable shared AOD.

    Readout rows preserve the source ordering. All rows translate by the same
    amount into disjoint upper-half-plane destinations. The model checks block
    identity, relative displacement and homogeneous component families; atomic
    capture closure, collisions and finite row/column capacity are unverified.
    """

    def __setattr__(self, name: str, value: Any) -> None:
        if getattr(self, "_sealed", False):
            raise AttributeError("CENTER_PROFILE_IS_IMMUTABLE")
        object.__setattr__(self, name, value)

    @property
    def references(self) -> dict[str, Any]:
        """Return independent provenance, never a mutable live cost table."""
        return deepcopy(self._references)

    @property
    def noise_params(self) -> dict[str, Any]:
        """Return an independent copy of the archived reference noise controls."""
        return deepcopy(self._noise_params)

    def __init__(
        self,
        references: Mapping[str, Any],
        distance: int,
        count: int,
        *,
        gap_um: float = 40,
        readout_gap_um: float = 50,
        movement_us_per_um: float = 1,
        cnot_target_offset_um: tuple[float, float] = (0, 0),
    ) -> None:
        self.plan = center_factory_plan(distance, count, gap_um=gap_um)
        if any(
            type(v) not in (float, int) or not isfinite(v) or v <= 0
            for v in (readout_gap_um, movement_us_per_um)
        ):
            raise ValueError("INVALID_CENTER_TRANSPORT_CONFIGURATION")
        if len(cnot_target_offset_um) != 2 or any(
            type(v) not in (float, int) or not isfinite(v)
            for v in cnot_target_offset_um
        ):
            raise ValueError("INVALID_CENTER_CNOT_TARGET")
        if references["payload_sha256"] != reference_digest(references["payload"]):
            raise ValueError("CENTER_REFERENCE_HASH_MISMATCH")
        self._references = deepcopy(dict(references))
        self.distance, self.factory_count = distance, count
        self.code_id = f"rotated_surface_d{distance}"
        self._noise_params = deepcopy(references["payload"]["noise_params"])
        self.readout_gap_um, self.movement_us_per_um = (
            readout_gap_um,
            movement_us_per_um,
        )
        self.cnot_target_offset_um = (
            cnot_target_offset_um[0],
            cnot_target_offset_um[1],
        )
        self.translation_y_um = (
            readout_gap_um + 20 * distance + (count - 1) * (20 * distance + gap_um)
        )
        self._patches = {
            b.block_id: FastPatch(
                b.block_id,
                str(b.factory_id),
                str(b.role),
                ROLES.index(str(b.role)),
                self.plan.placements[b.block_id].origin,
                b.code,
                b.distance,
            )
            for b in self.plan.blocks
        }
        self._document = {
            "schema": "nadit.surface_center_profile/1",
            "reference_payload_sha256": references["payload_sha256"],
            "placement": self.plan.to_dict(),
            "readout_common_translation_y_um": self.translation_y_um,
            "movement_us_per_um": movement_us_per_um,
            "cnot_target_offset_um": list(cnot_target_offset_um),
            "reference_supply_probability_geometry_recomputed": False,
            "atomic_legality_verified": False,
            "cost_partition": "category_integrals_not_native_order",
        }
        self.profile_sha256 = canonical_hash(self._document)
        self.schedule_interpretation = "homogeneous component lockstep under explicit block-center geometry model on one AOD; not atom-level validation"
        self._entries: dict[str, ComponentCostProfile] = {}
        self._sealed = True

    def layout(
        self,
        hardware: str = "shared_aod",
        *,
        placement_plan: PlacementPlan | None = None,
    ) -> FastLayout:
        """Expose only the modeled layout and one shared AOD."""
        if hardware != "shared_aod":
            raise ValueError("CENTER_MODEL_REQUIRES_ONE_SHARED_AOD")
        if placement_plan is not None and placement_plan != self.plan:
            raise ValueError("CENTER_MODEL_PLACEMENT_CHANGED")
        layout = super().layout(hardware, placement_plan=self.plan)
        return replace(
            layout,
            budget={
                **layout.budget,
                "reservation_policy": self.schedule_interpretation,
                "estimate_model_sha256": self.profile_sha256,
                "readout_common_translation_y_um": self.translation_y_um,
            },
        )

    def _cost(
        self, component_id: str, participants: tuple[FastPatch, ...]
    ) -> ComponentCostProfile:
        key = entry_key(component_id, tuple(p.block_id for p in participants))
        if key in self._entries:
            return self._entries[key]
        centers = tuple(
            (p.origin.x + 10 * self.distance, p.origin.y + 10 * self.distance)
            for p in participants
        )
        cost = center_component_cost(
            self._references,
            distance=self.distance,
            component_id=component_id,
            centers=centers,
            readout_center=(centers[0][0], centers[0][1] + self.translation_y_um),
            movement_us_per_um=self.movement_us_per_um,
            cnot_target_offset_um=self.cnot_target_offset_um,
        )
        original_ends = list(accumulate(cost["phase_durations_us"]))
        boundaries = sorted(
            {
                cost["duration_us"],
                *(original_ends[i] for i, _ in cost["measurement_phases"]),
            }
        )
        phases = tuple(
            right - left
            for left, right in zip([0.0, *boundaries[:-1]], boundaries, strict=True)
        )
        measurement_phases = tuple(
            (boundaries.index(original_ends[i]), latency)
            for i, latency in cost["measurement_phases"]
        )
        detail = _partitions(cost["segments"])
        entry = ComponentCostProfile(
            key,
            component_id,
            (),
            None,
            self.profile_sha256,
            phases,
            measurement_phases,
            tuple(
                original_ends[i] + latency for i, latency in cost["measurement_phases"]
            ),
            tuple(
                {
                    k: row[k]
                    for k in (
                        "start_offset_us",
                        "end_offset_us",
                        "category",
                        "resource",
                    )
                }
                for row in detail
            ),
            cost["primitive_counts"],
            (),
            (),
            {
                "result_count": len(measurement_phases),
                "uses_aod": any(row["resource"].startswith("aod") for row in detail),
                "estimate_model_sha256": self.profile_sha256,
                "estimate_segments": detail,
            },
        )
        self._entries[key] = entry
        return entry

    def lookup(
        self,
        component_id: str,
        participants: tuple[FastPatch, ...],
        selection: Mapping[str, Any] | None = None,
        parameters: Sequence[tuple[str, Any]] | Mapping[str, Any] = (),
    ) -> ComponentCostProfile:
        """Validate one code-owned interface and compute its finite macro cost."""
        self.member_identity(component_id, participants)
        if dict(parameters) != (
            {"injection_rounds": 3} if component_id == "raw_t_postselection" else {}
        ):
            raise ValueError("CENTER_COMPONENT_PARAMETERS_CHANGED")
        if selection is not None and (
            not component_id.endswith("/canonicalize")
            or dict(selection)
            != {"accepted": True, "correction_policy": "one_pauli_layer_bound"}
        ):
            raise ValueError("CENTER_CORRECTION_SELECTION_INVALID")
        return self._cost(component_id, participants)

    def describe(
        self,
        component_id: str,
        participants: tuple[FastPatch, ...],
        selection: Any = None,
        parameters: Any = (),
        *,
        budget: Mapping[str, Any],
    ) -> ComponentExecutionSpec:
        """Batch the same operation with the same signed relative geometry."""
        entry = self.lookup(component_id, participants, selection, parameters)
        if (
            budget.get("aod_count") != 1
            or budget.get("estimate_model_sha256") != self.profile_sha256
        ):
            raise ValueError("CENTER_MODEL_DEVICE_CHANGED")
        anchor = participants[0].origin
        key = canonical_hash(
            {
                "model": self.profile_sha256,
                "component": component_id,
                "relative": [
                    (p.origin.x - anchor.x, p.origin.y - anchor.y) for p in participants
                ],
                "parameters": dict(parameters),
            }
        )
        return ComponentExecutionSpec(
            self.code_id,
            component_id,
            key,
            tuple(p.block_id for p in participants),
            (),
            (),
            "profile_parallel",
            entry.claim["result_count"],
            estimate_batch_key=key,
        )

    def lookup_batch(
        self, requests: tuple[Any, ...]
    ) -> tuple[ComponentCostProfile, ...]:
        """Resolve a homogeneous wave without adding up independent AOD times."""
        layout = self.layout()
        specs = tuple(
            self.describe(
                r.call.component_id,
                tuple(self._patches[b] for b in r.participant_blocks),
                r.selection,
                r.call.parameters,
                budget=layout.budget,
            )
            for r in requests
        )
        if not specs or len({spec.estimate_batch_key for spec in specs}) != 1:
            raise ValueError("CENTER_MODEL_BATCH_GEOMETRY_MISMATCH")
        return tuple(
            self.lookup(
                r.call.component_id,
                tuple(self._patches[b] for b in r.participant_blocks),
                r.selection,
                r.call.parameters,
            )
            for r in requests
        )

    def preparation_port(self, preparation: str, block_id: str) -> Any:
        """Use an archived supply reference; do not infer new detector probabilities."""
        if preparation == "initialize_plus":
            return acceptance_port(
                1,
                preparation=preparation,
                evidence={"scope": "ideal_initialization_reference"},
                kind="ideal_exact",
            )
        if preparation != "raw_t_postselection" or block_id not in self._patches:
            raise ValueError("INVALID_CENTER_PREPARATION")
        role = self._patches[block_id].role
        record = self._references["payload"]["distances"][str(self.distance)][
            "raw_acceptance"
        ][role]
        return acceptance_port(
            record["probability"],
            preparation=preparation,
            evidence={
                "scope": "archived_singleton_supply_reference_held_fixed_across_geometry",
                "source_port_sha256": record["port_sha256"],
                "geometry_noise_recomputed": False,
                "reference_payload_sha256": self._references["payload_sha256"],
            },
        )

    def calibration_evidence(self) -> dict[str, Any]:
        """Report the calibrated versus modeled and excluded quantities."""
        return {
            **self._document,
            "physical_compilation_run": False,
            "raw_acceptance": "archived reference fixed across N; not a new detector simulation",
            "exposure": "addressed atoms plus modeled idle; spectator illumination and correlations unqualified",
        }
