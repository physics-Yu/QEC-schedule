"""Grow a caller-declared canonical d3 input without another injection.

Canonical input, ownership and logical source acceptance are caller preconditions,
not facts certified here. This module checks source references, atom geometry and
result boundaries. It neither owns resource tokens nor issues canonical outputs.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from math import isclose, isfinite
from re import fullmatch
from typing import Any

from nadit_physical_compiler.device import Device, Position
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.serialization import encode_layout
from nadit_physical_compiler.state import AtomLayout, SLMHolder, validate_layout

from modules.codes._support.atom_template import AtomComponentTemplate
from modules.codes.contracts.component import (
    ComponentBinding,
    ComponentDescription,
    ComponentExpansion,
    InvocationContext,
    validate_sequence,
)

from .components import SurfaceComponent
from .definition import definition
from .geometry import SITE_PITCH_UM
from .growth import GrowthComponent, injection_indices
from .growth_decoder import GrowthDecoder, GrowthFrame


@dataclass(frozen=True, init=False)
class D3SeedInput:
    """A real component source reference with caller-owned canonical preconditions.

    ``source`` is the latest physical source/transport receipt at the seed's
    current location. Its reference does not prove a canonical quantum state.
    The caller must verify accepted source lineage, frame, ownership and epoch.
    Provenance is copied as JSON and is never interpreted as a substitute proof.
    """

    source: ComponentExpansion
    provenance_json: str

    def __init__(
        self, source: ComponentExpansion, *, provenance: Mapping[str, Any]
    ) -> None:
        if not isinstance(source, ComponentExpansion):
            raise TypeError("D3_SEED_COMPONENT_SOURCE_REQUIRED")
        binding = source.exit_binding
        if (
            source.description.code_id != "rotated_surface_d3"
            or source.description.roles != definition(3).roles
            or binding is None
            or binding.block_id != source.block_id
            or binding.atom_ids != source.wire_atoms
            or len(source.wire_atoms) != 17
            or len(set(source.wire_atoms)) != 17
            or any(type(atom) is not int or atom < 0 for atom in source.wire_atoms)
            or source.dag.num_qubits != 17
            or not source.invocation_id
            or not source.validation_checks
            or not isinstance(source.template_content_sha256, str)
            or not fullmatch(r"[0-9a-f]{64}", source.template_content_sha256)
        ):
            raise ValueError("D3_SEED_SOURCE_REFERENCE_INVALID")
        if (
            not isinstance(provenance, Mapping)
            or not provenance
            or any(not isinstance(k, str) for k in provenance)
        ):
            raise ValueError("D3_SEED_CALLER_PROVENANCE_REQUIRED")
        object.__setattr__(self, "source", source)
        object.__setattr__(
            self,
            "provenance_json",
            json.dumps(dict(provenance), sort_keys=True, allow_nan=False),
        )

    @property
    def binding(self) -> ComponentBinding:
        """Return the source's retained d3 roles; no logical relabeling occurs."""
        assert self.source.exit_binding is not None
        return self.source.exit_binding

    @property
    def provenance(self) -> dict[str, Any]:
        """Return an independent copy of the caller's unmodified provenance."""
        return dict(json.loads(self.provenance_json))

    def to_dict(self) -> dict[str, Any]:
        """Record traceable input references without a canonical-state certificate."""
        return {
            "schema": "nadit.d3_seed_input/1",
            "input_state": "canonical encoded d3; caller precondition, not verified here",
            "source_invocation_id": self.source.invocation_id,
            "source_template_sha256": self.source.template_content_sha256,
            "source_exit_world_sha256": canonical_hash(
                encode_layout(self.source.exit_state)
            ),
            "source_results_ready_us": self.source.results_ready_us,
            "binding": asdict(self.binding),
            "provenance": self.provenance,
        }


@dataclass(frozen=True, init=False)
class D3SeedGrowth:
    """Existing deformation plus ordinary SE; default total target rounds is d."""

    distance: int
    growth_rounds: int

    def __init__(self, distance: int, growth_rounds: int | None = None) -> None:
        GrowthComponent(distance)
        rounds = distance if growth_rounds is None else growth_rounds
        if type(rounds) is not int or rounds < 2:
            raise ValueError("D3_SEED_GROWTH_REQUIRES_AT_LEAST_TWO_ROUNDS")
        object.__setattr__(self, "distance", distance)
        object.__setattr__(self, "growth_rounds", rounds)

    @property
    def identity(self) -> dict[str, Any]:
        """Expose the exact sequence and existing decoder convention."""
        return {
            "protocol": "d3_seed_growth",
            "version": "1",
            "input_distance": 3,
            "target_distance": self.distance,
            "growth_rounds": self.growth_rounds,
            "postselection": False,
            "decoder": "phenomenological_mwpm_open_boundary/1",
        }

    @property
    def component_sources(self) -> tuple[str, ...]:
        """Return unchanged code-owned sources, without injection or all-Y bounds."""
        return (
            GrowthComponent(self.distance).source_qasm,
            *(
                [SurfaceComponent("se_round", self.distance).source_qasm]
                * (self.growth_rounds - 1)
            ),
        )

    @property
    def acceptance_ports(self) -> tuple[str, ...]:
        """Nonzero growth syndromes are decoded, never rejected."""
        return ()

    @property
    def description(self) -> ComponentDescription:
        code = definition(self.distance)
        return ComponentDescription(
            f"rotated_surface_d{self.distance}",
            "d3_seed_growth",
            "1",
            code.roles,
            tuple(
                f"growth[{r}].{port}"
                for r in range(self.growth_rounds)
                for port in code.check_roles
            ),
            (
                "Caller guarantees canonical encoded d3 input and owns every declared atom",
                "Seed already occupies injection_indices; disjoint outer atoms explicitly supplied",
            ),
            (
                "Existing growth and ordinary SE only; no injection or postselection",
                "Complete syndrome history and explicit GrowthFrame; no automatic canonical output",
                "No logical error-rate or circuit-noise decoder guarantee",
            ),
        )

    def compile(
        self,
        device: Device,
        *,
        home_sites: tuple[str, ...],
        origin: Position,
        aod_id: str,
    ) -> D3SeedGrowthTemplate:
        """Compile the two existing primitives once, retaining caller timing/noise."""
        if len(home_sites) != definition(self.distance).atom_count or len(
            set(home_sites)
        ) != len(home_sites):
            raise ValueError("D3_SEED_GROWTH_TARGET_HOMES_MISMATCH")
        return D3SeedGrowthTemplate(
            self,
            GrowthComponent(self.distance).compile(
                device, home_sites=home_sites, origin=origin, aod_id=aod_id
            ),
            SurfaceComponent("se_round", self.distance).compile(
                device, home_sites=home_sites, origin=origin, aod_id=aod_id
            ),
        )


@dataclass(frozen=True)
class D3SeedGrowthTemplate:
    """Reusable existing primitives; this template contains no source bits."""

    protocol: D3SeedGrowth
    growth: AtomComponentTemplate
    se_round: AtomComponentTemplate

    def __post_init__(self) -> None:
        code = definition(self.protocol.distance)
        if (
            any(
                template.description.component_id != name
                or template.description.code_id != f"rotated_surface_d{code.distance}"
                or template.description.roles != code.roles
                or template.description.measurements != code.check_roles
                or template.acceptance_ports
                for template, name in (
                    (self.growth, "grow_from_d3"),
                    (self.se_round, "se_round"),
                )
            )
            or self.growth.home_sites != self.se_round.home_sites
        ):
            raise ValueError("D3_SEED_GROWTH_TEMPLATE_MISMATCH")

    @property
    def content_sha256(self) -> str:
        return canonical_hash(
            {
                **self.protocol.identity,
                "growth": self.growth.content_sha256,
                "se_round": self.se_round.content_sha256,
            }
        )

    def bind(
        self,
        seed: D3SeedInput,
        target_binding: ComponentBinding,
        *,
        outer_atom_ids: tuple[int, ...],
    ) -> BoundD3SeedGrowth:
        """Bind exact existing atom sets; do not allocate, move or acquire atoms."""
        if not isinstance(seed, D3SeedInput) or not isinstance(
            target_binding, ComponentBinding
        ):
            raise TypeError("D3_SEED_GROWTH_BINDINGS_REQUIRED")
        code, indices = (
            definition(self.protocol.distance),
            injection_indices(self.protocol.distance),
        )
        atoms = target_binding.atom_ids
        if (
            len(atoms) != code.atom_count
            or len(set(atoms)) != len(atoms)
            or any(type(a) is not int or a < 0 for a in atoms)
        ):
            raise ValueError("D3_SEED_GROWTH_TARGET_ATOMS_MISMATCH")
        if seed.binding.atom_ids != tuple(atoms[i] for i in indices):
            raise ValueError("D3_SEED_GROWTH_SEED_ROLE_MAPPING_MISMATCH")
        if outer_atom_ids != tuple(
            atom for i, atom in enumerate(atoms) if i not in indices
        ):
            raise ValueError("D3_SEED_GROWTH_OUTER_ATOMS_MISMATCH")
        expected = Position(
            target_binding.origin.x,
            target_binding.origin.y + 2 * (code.distance - 3) * SITE_PITCH_UM,
        )
        if seed.binding.aod_id != target_binding.aod_id or not _same(
            seed.binding.origin, expected
        ):
            raise ValueError("D3_SEED_GROWTH_SEED_GEOMETRY_MISMATCH")
        self.growth.bind(target_binding)
        self.se_round.bind(target_binding)
        return BoundD3SeedGrowth(self, seed, target_binding, outer_atom_ids)


def _same(left: Position, right: Position) -> bool:
    return all(
        isfinite(a) and isfinite(b) and isclose(a, b, rel_tol=0, abs_tol=1e-9)
        for a, b in ((left.x, right.x), (left.y, right.y))
    )


@dataclass(frozen=True)
class BoundD3SeedGrowth:
    """An exact current-world continuation with one caller-owned result-ID stream."""

    template: D3SeedGrowthTemplate
    seed: D3SeedInput
    target_binding: ComponentBinding
    outer_atom_ids: tuple[int, ...]

    def expand(self, context: InvocationContext) -> D3SeedGrowthExpansion:
        self.template.bind(
            self.seed, self.target_binding, outer_atom_ids=self.outer_atom_ids
        )
        source, target, protocol = (
            self.seed.source,
            self.target_binding,
            self.template.protocol,
        )
        if context.world_state != source.exit_state:
            raise ValueError("D3_SEED_GROWTH_SOURCE_WORLD_MISMATCH")
        if context.start_us < source.results_ready_us:
            raise ValueError("D3_SEED_GROWTH_SOURCE_NOT_READY")
        names = {
            context.invocation_id,
            *(
                f"{context.invocation_id}/growth[{r}]"
                for r in range(protocol.growth_rounds)
            ),
        }
        if source.invocation_id in names or context.result_id_base <= max(
            (m.result.measurement_id for m in source.measurements), default=-1
        ):
            raise ValueError("D3_SEED_GROWTH_SOURCE_IDENTITY_OVERLAP")
        validate_layout(context.device, context.world_state)
        for atom_id, (x, y) in zip(
            target.atom_ids,
            definition(protocol.distance).reference_coordinates,
            strict=True,
        ):
            atom = context.world_state.atom(atom_id)
            expected = Position(
                target.origin.x + x * SITE_PITCH_UM, target.origin.y + y * SITE_PITCH_UM
            )
            if (
                not isinstance(atom.holder, SLMHolder)
                or not _same(atom.position, expected)
                or not _same(
                    context.device.site(atom.holder.site_id).position, expected
                )
            ):
                raise ValueError("D3_SEED_GROWTH_CURRENT_ATOM_GEOMETRY_MISMATCH")
        parts: list[ComponentExpansion] = []
        start, world, base = (
            context.start_us,
            context.world_state,
            context.result_id_base,
        )
        for r in range(protocol.growth_rounds):
            template = self.template.growth if r == 0 else self.template.se_round
            part = template.bind(target).expand(
                InvocationContext(
                    f"{context.invocation_id}/growth[{r}]",
                    start,
                    base,
                    context.device,
                    world,
                )
            )
            parts.append(part)
            start, world, base = (
                part.action_end_us,
                part.exit_state,
                base + len(part.measurements),
            )
        return D3SeedGrowthExpansion(
            self.seed, tuple(parts), target, protocol, self.template.content_sha256
        )


@dataclass(frozen=True)
class D3SeedGrowthExpansion:
    """Pending measured history; decoding returns a frame and never marks it applied."""

    seed: D3SeedInput
    parts: tuple[ComponentExpansion, ...]
    target_binding: ComponentBinding
    protocol: D3SeedGrowth
    template_content_sha256: str

    def __post_init__(self) -> None:
        code = definition(self.protocol.distance)
        if len(self.parts) != self.protocol.growth_rounds or any(
            part.description.component_id != ("grow_from_d3" if r == 0 else "se_round")
            or part.description.code_id != f"rotated_surface_d{code.distance}"
            or part.description.roles != code.roles
            or part.wire_atoms != self.target_binding.atom_ids
            or part.exit_binding != self.target_binding
            or part.acceptance_conditions
            or tuple(m.port for m in part.measurements) != code.check_roles
            for r, part in enumerate(self.parts)
        ):
            raise ValueError("D3_SEED_GROWTH_RESULT_HISTORY_MISMATCH")
        base = self.parts[0].measurements[0].result.measurement_id
        if base <= max(
            (m.result.measurement_id for m in self.seed.source.measurements), default=-1
        ) or any(
            measurement.invocation_id != part.invocation_id
            or measurement.result.measurement_id != base + r * code.check_count + index
            for r, part in enumerate(self.parts)
            for index, measurement in enumerate(part.measurements)
        ):
            raise ValueError("D3_SEED_GROWTH_RESULT_IDENTITY_MISMATCH")
        if self.parts[0].start_us < self.seed.source.results_ready_us:
            raise ValueError("D3_SEED_GROWTH_SOURCE_NOT_READY")
        validate_sequence((self.seed.source, *self.parts))

    @property
    def results_ready_us(self) -> float:
        return max(part.results_ready_us for part in self.parts)

    @property
    def exit_state(self) -> AtomLayout:
        return self.parts[-1].exit_state

    def with_results(self, values: Mapping[int, int]) -> D3SeedGrowthExpansion:
        known = {
            m.result.measurement_id for part in self.parts for m in part.measurements
        }
        if not values.keys() <= known:
            raise ValueError("D3_SEED_GROWTH_UNKNOWN_MEASUREMENT_ID")
        return replace(
            self,
            parts=tuple(
                part.with_results(
                    {
                        m.result.measurement_id: values[m.result.measurement_id]
                        for m in part.measurements
                        if m.result.measurement_id in values
                    }
                )
                for part in self.parts
            ),
        )

    def decode(
        self, at_us: float, *, decoder: GrowthDecoder | None = None
    ) -> GrowthFrame:
        """Return the existing decoder's explicit frame after all outcomes arrive."""
        if (
            type(at_us) not in (int, float)
            or not isfinite(at_us)
            or at_us < self.results_ready_us
        ):
            raise ValueError("D3_SEED_GROWTH_RESULTS_NOT_READY")
        history = [[m.value for m in part.measurements] for part in self.parts]
        if any(value is None for row in history for value in row):
            raise ValueError("D3_SEED_GROWTH_RESULTS_NOT_RECEIVED")
        selected = decoder or GrowthDecoder(self.protocol.distance)
        if selected.distance != self.protocol.distance:
            raise ValueError("D3_SEED_GROWTH_DECODER_DISTANCE_MISMATCH")
        return selected.decode(
            [[int(value) for value in row if value is not None] for row in history]
        )
