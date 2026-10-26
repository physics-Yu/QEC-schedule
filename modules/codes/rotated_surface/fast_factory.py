"""Distance-generic, position-calibrated resource profiles for the factory runtime.

Fast execution never imports the physical compiler. Transport-bearing calls
reserve one complete AOD interval conservatively; independently addressed local
calls can overlap. A separate independent-AOD control changes the hardware budget.
Canonicalization includes a calibrated worst-case one-layer Pauli correction,
not a fabricated sample of the decoder's frame or an output-quality guarantee.
"""

from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import replace
from math import isfinite
from types import MappingProxyType
from typing import Any

from nadit_physical_compiler.device import Position
from nadit_physical_compiler.provenance import canonical_hash

from modules.codes.contracts.event_probability import ProbabilityPort
from modules.codes.contracts.factory_recipe import FactoryRecipe, ResourcePreparation
from modules.codes.contracts.parallel import ComponentExecutionSpec
from modules.codes.rotated_surface_d3.protocols.factory import (
    factory_recipe as d3_recipe,
)
from modules.codes.rotated_surface_d3.protocols.factory_experiment import (
    FactoryExperimentModel,
)
from modules.codes.rotated_surface_d3.protocols.fast_profile import (
    ComponentCostProfile,
    FastLayout,
    FastPatch,
    FastPlacement,
)
from modules.logical_compiler.src.placement import (
    BlockSpec,
    PlacementPlan,
    validate_plan,
)

from .definition import definition
from .geometry import geometry

SCHEMA = "nadit.generic_surface_factory_profile/1"
ROLES = ("W1", "W2", "W3", "W4", "W5", "R")


def factory_recipe(distance: int) -> FactoryRecipe:
    """Reuse the code-independent 4+11 circuit with explicit small-code injection."""
    definition(distance)
    code = f"rotated_surface_d{distance}"
    original = d3_recipe()

    def preparation(p: ResourcePreparation) -> ResourcePreparation:
        return replace(
            p,
            resource_kind=None if p.resource_kind is None else f"{code}/A",
            parameters=() if p.resource_kind is None else (("injection_rounds", 3),),
        )

    return replace(
        original,
        code_id=code,
        protocol_id=f"{code}.small_injection_factory_15_to_1",
        version="1",
        initial_preparations=tuple(
            preparation(p) for p in original.initial_preparations
        ),
        rotations=tuple(
            replace(r, preparation=preparation(r.preparation))
            for r in original.rotations
        ),
        output_resource_kind=f"{code}/A",
    )


def required_variants(distance: int) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Enumerate finite component/role coverage before any stochastic experiment."""
    recipe = factory_recipe(distance)
    variants: set[tuple[str, tuple[str, ...]]] = set()
    for p in (*recipe.initial_preparations, *(r.preparation for r in recipe.rotations)):
        variants.add((p.component_id, (p.role,)))
        variants.add((p.canonicalization_id + "/canonicalize", (p.role,)))
    calls = [*recipe.final_measurement_calls, *recipe.accepted_output_calls]
    for r in recipe.rotations:
        calls.extend(
            (
                *r.compute_calls,
                *r.uncompute_calls,
                r.consumption.cx_call,
                r.consumption.mz_call,
            )
        )
        calls.extend(c for branch in r.consumption.branches for c in branch.calls)
    variants.update((c.component_id, c.participant_roles) for c in calls)
    return tuple(sorted(variants))


def entry_key(component: str, blocks: Sequence[str]) -> str:
    """Stable key preserving participant order, absolute placement and direction."""
    return component + ":" + ",".join(blocks)


def acceptance_port(
    probability: float,
    *,
    preparation: str,
    evidence: Mapping[str, Any],
    kind: str = "estimated",
) -> ProbabilityPort:
    """Binary acceptance only; no unmeasured correction-class label is invented."""
    return ProbabilityPort.from_dict(
        {
            "schema": "nadit.event_probability/1",
            "port_id": preparation + ".acceptance",
            "protocol_id": "small_injection_then_growth",
            "protocol_version": "3",
            "model": {
                "id": "generic_surface_factory.supply.v1",
                "kind": kind,
                "assumptions": [
                    "Small-code acceptance only; accepted inputs have separately assumed quality",
                    "Growth and decoder-conditioned correction occur only after acceptance",
                ],
                "parameters": {"injection_distance": 3, "injection_rounds": 3},
                "evidence": dict(evidence),
            },
            "outcomes": [
                {
                    "key": "accepted",
                    "probability": probability,
                    "values": {"accepted": True},
                    "branch_id": "grow",
                },
                {
                    "key": "rejected",
                    "probability": 1 - probability,
                    "values": {"accepted": False},
                    "branch_id": "retry",
                },
            ],
            "branches": [
                {"key": "grow", "transition": "continue", "steps": []},
                {"key": "retry", "transition": "retry", "steps": []},
            ],
        }
    )


class SurfaceFactoryProfile:
    """Immutable finite coverage for any odd distance and positive module count.

    Missing positions/operations fail closed. Calibration is an explicit separate
    operation. Stored metadata distinguishes validated physical timing from the
    canonicalization envelope and from illustrative acceptance estimates.
    """

    def __init__(self, document: Mapping[str, Any]) -> None:
        self._document = deepcopy(dict(document))
        document = self._document
        if document.get("schema") != SCHEMA:
            raise ValueError("INVALID_GENERIC_FACTORY_PROFILE_SCHEMA")
        self.distance = document["distance"]
        self.code_id = f"rotated_surface_d{definition(self.distance).distance}"
        self.factory_count = document["factory_count"]
        if type(self.factory_count) is not int or self.factory_count < 1:
            raise ValueError("Factory count must be a positive integer.")
        self.noise_params = deepcopy(document["noise_params"])
        self._patches: dict[str, FastPatch] = {}
        for row in document["patches"]:
            patch = FastPatch(
                row["block_id"],
                row["factory_id"],
                row["role"],
                row["slot"],
                Position(*row["origin"]),
                self.code_id,
                self.distance,
            )
            if patch.block_id in self._patches:
                raise ValueError("DUPLICATE_PROFILE_PATCH")
            self._patches[patch.block_id] = patch
        if len(self._patches) != 6 * self.factory_count:
            raise ValueError("INCOMPLETE_PROFILE_LAYOUT")
        entries: dict[str, ComponentCostProfile] = {}
        self.entries: Mapping[str, ComponentCostProfile] = entries
        for key, row in document["entries"].items():
            phases = tuple(row["phase_durations_us"])
            if not phases or any(
                type(v) not in (int, float) or not isfinite(v) or v < 0 for v in phases
            ):
                raise ValueError("INVALID_GENERIC_PROFILE_DURATION")
            measurement_phases = tuple(tuple(p) for p in row["measurement_phases"])
            if any(
                type(i) is not int
                or not 0 <= i < len(phases)
                or not isfinite(latency)
                or latency < 0
                for i, latency in measurement_phases
            ):
                raise ValueError("INVALID_GENERIC_PROFILE_RESULTS")
            entries[key] = ComponentCostProfile(
                key,
                row["component_id"],
                (),
                None,
                key,
                phases,
                measurement_phases,
                tuple(
                    sum(phases[: i + 1]) + latency for i, latency in measurement_phases
                ),
                tuple(row["cost_segments"]),
                row["primitive_counts"],
                (),
                (),
                {"result_count": len(measurement_phases), "uses_aod": row["uses_aod"]},
            )
        for factory in self.layout().factories:
            if tuple(p.role for p in factory.patches) != ROLES:
                raise ValueError("INCOMPLETE_PROFILE_FACTORY_ROLES")
            for component, roles in required_variants(self.distance):
                self.lookup(
                    component,
                    tuple(factory.bindings[r] for r in roles),
                    parameters=(("injection_rounds", 3),)
                    if component == "raw_t_postselection"
                    else (),
                )
            for role in ROLES[1:]:
                ProbabilityPort.from_dict(
                    self._document["raw_ports"][factory.bindings[role].block_id]
                )
        self.entries = MappingProxyType(entries)
        self.profile_sha256 = canonical_hash(self._document)

    def to_dict(self) -> dict[str, Any]:
        """Return an independent portable cache document."""
        return deepcopy(self._document)

    @property
    def code_ids(self) -> tuple[str, ...]:
        """Return all current concrete carrier codes, in deterministic order."""
        return tuple(sorted({patch.code_id for patch in self._patches.values()}))

    @property
    def factory_distances(self) -> Mapping[str, int]:
        """Return per-factory distances; global distance is a legacy anchor only."""
        return MappingProxyType(
            {
                f"factory{i}": self.factory_identity(f"factory{i}")[1]
                for i in range(self.factory_count)
            }
        )

    def factory_identity(self, factory_id: str) -> tuple[str, int]:
        """Resolve six same-code factory roles or reject incomplete/mixed roles.

        Consumers must use this identity when constructing a factory process;
        the profile's legacy code_id/distance describes only its first factory.
        """
        patches = tuple(self._patches.get(f"{factory_id}/{role}") for role in ROLES)
        first = patches[0]
        if first is None or any(
            patch is None
            or (patch.factory_id, patch.role, patch.code_id, patch.distance)
            != (factory_id, role, first.code_id, first.distance)
            for role, patch in zip(ROLES, patches, strict=True)
        ):
            raise ValueError("INCOMPLETE_PROFILE_FACTORY_ROLES")
        return first.code_id, first.distance

    def member_identity(
        self, component_id: str, participants: tuple[FastPatch, ...]
    ) -> tuple[str, int]:
        """Resolve one component's actual code; cross-code CNOTs are unsupported.

        Every participant must be a current calibrated carrier. Multiple members
        of a joint wave may differ, but one component may never mix code/distance.
        """
        if len(participants) != (2 if component_id == "transversal_cnot" else 1) or len(
            {patch.block_id for patch in participants}
        ) != len(participants):
            raise ValueError("UNCALIBRATED_GENERIC_PARTICIPANTS")
        if any(self._patches.get(p.block_id) != p for p in participants):
            raise ValueError("UNCALIBRATED_GENERIC_POSITION")
        first = participants[0]
        if any(
            (patch.code_id, patch.distance) != (first.code_id, first.distance)
            for patch in participants
        ):
            raise ValueError("UNCALIBRATED_GENERIC_PARTICIPANT_CODE_MISMATCH")
        return first.code_id, first.distance

    def _validate_placement(self, plan: PlacementPlan) -> None:
        """Require an explicit plan to match every calibrated carrier exactly."""
        validate_plan(plan)
        expected_blocks = {
            patch.block_id: BlockSpec(
                patch.block_id,
                patch.code_id,
                patch.distance,
                patch.factory_id,
                patch.role,
            )
            for patch in self._patches.values()
        }
        if (
            {block.block_id: block for block in plan.blocks} != expected_blocks
            or plan.geometries
            != {
                patch.code_id: geometry(patch.code_id, patch.distance)
                for patch in self._patches.values()
            }
            or any(
                plan.placements[block_id].origin != patch.origin
                or plan.placements[block_id].orientation != "standard"
                for block_id, patch in self._patches.items()
            )
        ):
            raise ValueError("UNCALIBRATED_GENERIC_PLACEMENT")

    def layout(
        self,
        hardware: str = "shared_aod",
        *,
        placement_plan: PlacementPlan | None = None,
    ) -> FastLayout:
        """Return calibrated carriers, optionally carrying an identical user plan.

        A supplied plan must match code geometry, identities and positions or
        raises ValueError. This handoff never changes hardware budgets or creates
        atoms; a different placement requires explicit new calibration.
        """
        if hardware not in ("shared_aod", "independent_aod_control"):
            raise ValueError("Unknown hardware budget.")
        if placement_plan is not None:
            self._validate_placement(placement_plan)
        factories = tuple(
            FastPlacement(
                f"factory{i}",
                tuple(self._patches[f"factory{i}/{role}"] for role in ROLES),
            )
            for i in range(self.factory_count)
        )
        return FastLayout(
            factories,
            {
                "hardware": hardware,
                "aod_count": 1 if hardware == "shared_aod" else self.factory_count,
                "independent_control_assumption": hardware != "shared_aod",
                "independent_control_scope": "per-module AOD and independently addressable gate/readout control; not a same-budget hardware comparison",
                "aod_id": "transport",
                "aod_max_rows": None,
                "aod_max_columns": None,
                "max_readout_atoms": None,
                "factory_count": self.factory_count,
                "patch_count": self.factory_count * 6,
                "atom_count_estimate": sum(
                    definition(patch.distance).atom_count
                    for patch in self._patches.values()
                ),
                "representation": "logical_estimate",
                "reservation_policy": "transport-bearing component reserves its AOD until return-home; conservative upper bound; no unvalidated co-batching",
            },
            placement_plan=placement_plan,
        )

    def lookup(
        self,
        component_id: str,
        participants: tuple[FastPatch, ...],
        selection: Mapping[str, Any] | None = None,
        parameters: Sequence[tuple[str, Any]] | Mapping[str, Any] = (),
    ) -> ComponentCostProfile:
        """Admit only calibrated carriers, direction, code and injection policy."""
        self.member_identity(component_id, participants)
        if dict(parameters) != (
            {"injection_rounds": 3} if component_id == "raw_t_postselection" else {}
        ):
            raise ValueError("UNCALIBRATED_GENERIC_PARAMETERS")
        if selection is not None and (
            not component_id.endswith("/canonicalize")
            or dict(selection)
            != {"accepted": True, "correction_policy": "one_pauli_layer_bound"}
        ):
            raise ValueError("INVALID_GENERIC_CORRECTION_SELECTION")
        try:
            return self.entries[
                entry_key(component_id, tuple(p.block_id for p in participants))
            ]
        except KeyError as error:
            raise ValueError("UNCALIBRATED_GENERIC_COMPONENT") from error

    def describe(
        self,
        component_id: str,
        participants: tuple[FastPatch, ...],
        selection: Mapping[str, Any] | None = None,
        parameters: Sequence[tuple[str, Any]] | Mapping[str, Any] = (),
        *,
        budget: Mapping[str, Any],
    ) -> ComponentExecutionSpec:
        """Expose conservative resource leases to the common frontier scheduler."""
        entry = self.lookup(component_id, participants, selection, parameters)
        owner = (
            "transport"
            if budget["hardware"] == "shared_aod"
            else participants[0].factory_id
        )
        return ComponentExecutionSpec(
            self.member_identity(component_id, participants)[0],
            component_id,
            "generic-resource-estimate",
            tuple(p.block_id for p in participants),
            (),
            (f"aod:{owner}",) if entry.claim["uses_aod"] else (),
            "profile_parallel",
            entry.claim["result_count"],
        )

    def correction_selection(
        self, preparation: str, values: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Select a cost bound after acceptance, without sampling a Pauli frame."""
        if preparation not in ("raw_t_postselection", "initialize_plus") or values != {
            "accepted": True
        }:
            raise ValueError("INVALID_GENERIC_ACCEPTED_EVENT")
        return {"accepted": True, "correction_policy": "one_pauli_layer_bound"}

    def preparation_port(self, preparation: str, block_id: str) -> ProbabilityPort:
        """Return the position-specific injection model or ideal plus reference."""
        if preparation == "initialize_plus":
            return acceptance_port(
                1,
                preparation=preparation,
                evidence={"profile_sha256": self.profile_sha256},
                kind="ideal_exact",
            )
        if preparation != "raw_t_postselection":
            raise ValueError("Unsupported preparation.")
        return ProbabilityPort.from_dict(self._document["raw_ports"][block_id])


class SurfaceFactoryBackend:
    """Code-owned events and assumed input quality for the common coordinator."""

    def __init__(
        self,
        profile: SurfaceFactoryProfile,
        execution: Any,
        model: FactoryExperimentModel,
    ) -> None:
        self.profile, self.execution, self.model = profile, execution, model

    def preparation_event(
        self, preparation: str, source: Any, parameters: Mapping[str, Any] | None = None
    ) -> ProbabilityPort:
        """Resolve a supply event only for a committed own receipt."""
        if self.execution.source(
            source.invocation_id
        ) != source or parameters != self.model.parameters(self.profile.noise_params):
            raise ValueError("INVALID_GENERIC_PREPARATION_SOURCE")
        joint_port = getattr(self.profile, "preparation_event_port", None)
        if callable(joint_port):
            port: ProbabilityPort = joint_port(preparation, source)
            return port
        return self.profile.preparation_port(preparation, source.participant_blocks[0])

    def preparation_quality(
        self, preparation: str, parameters: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Input quality is an explicit theory control, independent of rejection."""
        return self.model.reference_quality(preparation)

    def resolve_event(
        self, selector: str, parameters: Mapping[str, Any] | None = None
    ) -> ProbabilityPort:
        """Retain the existing theoretical T-consumption feedback model."""
        if selector != "t_consumption":
            raise ValueError("Generic final event requires committed source receipts.")
        return self.model.consumption_event(parameters)

    def resolve_event_from_sources(
        self,
        selector: str,
        parts: tuple[Any, ...],
        parameters: Mapping[str, Any],
        *,
        event_id: str,
    ) -> ProbabilityPort:
        """Use the complete four-bit joint check distribution after measured exits."""
        if selector != "factory_mx":
            return self.resolve_event(selector, parameters)
        if len(parts) != 4 or any(
            self.execution.source(p.invocation_id) != p
            or p.results_ready_us > self.execution.clock_us
            for p in parts
        ):
            raise ValueError("GENERIC_FACTORY_CHECKS_NOT_READY")
        return self.model.final_theory_event(parameters)

    def output_quality(self, factory_port: ProbabilityPort) -> dict[str, Any]:
        """Return reference quality; do not claim a decoded physical output LER."""
        return self.model.output_quality(factory_port)
