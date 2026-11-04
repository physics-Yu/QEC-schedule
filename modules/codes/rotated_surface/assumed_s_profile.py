"""An explicit transversal-S cost overlay; all other coverage stays exact.

The overlay never manufactures missing joint calibration. S carries no measured
syndrome or atom trace and cannot be mistaken for the measured fold component.
"""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from nadit_physical_compiler.provenance import canonical_hash

from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.contracts.parallel import ComponentExecutionSpec
from modules.codes.rotated_surface_d3.protocols.fast_profile import (
    ComponentCostProfile,
    FastLayout,
    FastPatch,
)
from modules.logical_compiler.src.placement import PlacementPlan

from .factory_assumptions import TransversalSAssumption
from .fast_factory import SurfaceFactoryProfile, entry_key


class AssumedSProfile(SurfaceFactoryProfile):
    """Add one explicitly assumed local operation to a frozen cost provider.

    Args:
        base: Existing provider of all non-S costs and preparation probabilities.
        assumption: Independently versioned S timing and per-data-atom noise.
    """

    def __init__(
        self, base: SurfaceFactoryProfile, assumption: TransversalSAssumption
    ) -> None:
        self.base = base
        self.assumption = assumption
        self.distance, self.code_id = base.distance, base.code_id
        self.factory_count, self.noise_params = base.factory_count, base.noise_params
        self._patches = base._patches
        self.profile_sha256 = canonical_hash(
            {"base": base.profile_sha256, "assumed_s": assumption.to_dict()}
        )
        self.schedule_interpretation = (
            "independent declared transversal-S assumption; other operations retain "
            + getattr(base, "schedule_interpretation", "base profile coverage")
        )

    def __getattr__(self, name: str) -> Any:
        """Preserve optional batch, event and calibration hooks of the provider."""
        return getattr(self.base, name)

    def layout(
        self,
        hardware: str = "shared_aod",
        *,
        placement_plan: PlacementPlan | None = None,
    ) -> FastLayout:
        """Keep existing placement and budget, recording the independent S model."""
        layout = self.base.layout(hardware, placement_plan=placement_plan)
        return replace(
            layout,
            budget={
                **layout.budget,
                "assumed_transversal_s": self.assumption.to_dict(),
            },
        )

    def lookup(
        self,
        component_id: str,
        participants: tuple[FastPatch, ...],
        selection: Mapping[str, Any] | None = None,
        parameters: Sequence[tuple[str, Any]] | Mapping[str, Any] = (),
    ) -> ComponentCostProfile:
        """Return declared S cost, or preserve the base's exact missing-data error."""
        if component_id != "assumed_transversal_s":
            return self.base.lookup(component_id, participants, selection, parameters)
        self.member_identity(component_id, participants)
        if selection is not None or dict(parameters) != {
            "assumption_id": self.assumption.identity
        }:
            raise ValueError("TRANSVERSAL_S_ASSUMPTION_MISMATCH")
        duration = self.assumption.duration_us
        return ComponentCostProfile(
            key=entry_key(component_id, tuple(p.block_id for p in participants)),
            component_id=component_id,
            geometry=(),
            selection_class=None,
            waveform_key=self.assumption.identity,
            phase_durations_us=(duration,),
            measurement_phases=(),
            result_ready_offsets_us=(),
            cost_segments=(
                {
                    "start_offset_us": 0.0,
                    "end_offset_us": duration,
                    "category": "gate",
                    "resource": "local",
                },
            ),
            primitive_counts={"assumed_S": self.distance**2},
            events=(),
            busy=(),
            claim={
                "result_count": 0,
                "uses_aod": False,
                "model_scope": "assumed_transversal_s",
                "physical_validation": "not_applicable_to_assumption",
                "estimate_model_sha256": self.assumption.identity,
                "estimate_segments": (
                    {
                        "start_offset_us": 0.0,
                        "end_offset_us": duration,
                        "category": "gate",
                        "resource": "local",
                        "atom_count": self.distance**2,
                        "busy_atom_us": duration * self.distance**2,
                        "movement_distance_atom_um": 0.0,
                        "primitive_counts": {"assumed_S": self.distance**2},
                        "basis": "assumed_transversal_s",
                    },
                ),
            },
        )

    def describe(
        self,
        component_id: str,
        participants: tuple[FastPatch, ...],
        selection: Any = None,
        parameters: Any = (),
        *,
        budget: Mapping[str, Any],
    ) -> ComponentExecutionSpec:
        """Declare local S batching without allocating transport or results."""
        if component_id != "assumed_transversal_s":
            return self.base.describe(
                component_id, participants, selection, parameters, budget=budget
            )
        self.lookup(component_id, participants, selection, parameters)
        return ComponentExecutionSpec(
            self.code_id,
            component_id,
            self.assumption.identity,
            tuple(p.block_id for p in participants),
            (),
            (),
            "local_parallel",
            0,
        )

    def calibration_evidence(self) -> dict[str, Any]:
        """Distinguish the S hypothesis from any calibrated base costs."""
        evidence = getattr(self.base, "calibration_evidence", None)
        return {
            "base_profile_sha256": self.base.profile_sha256,
            "base": evidence() if callable(evidence) else None,
            "assumed_transversal_s": self.assumption.to_dict(),
            "physical_compilation_run": False,
        }

    def preparation_port(self, preparation: str, block_id: str) -> ProbabilityPort:
        """Preserve the base provider's explicit supply probability semantics."""
        return self.base.preparation_port(preparation, block_id)

    def to_dict(self) -> dict[str, Any]:
        """Export both identities without relabeling historical measured-S data."""
        return {
            "schema": "nadit.assumed_s_profile/1",
            "base": self.base.to_dict(),
            "assumption": self.assumption.to_dict(),
        }
