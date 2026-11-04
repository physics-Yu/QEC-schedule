"""Fixed d3 postselection followed by conditional ordinary code growth.

Only the injection stage may reject. Growth is a separate invocation and can
start only after actual accepted results have arrived. Resource-only callers
may compile both templates but must not turn compiler fixture bits into an
acceptance event. Frames are explicit and must be carried by the logical caller.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, ClassVar

from nadit_physical_compiler.cost.noise.config import resolve
from nadit_physical_compiler.device import Device, Position
from nadit_physical_compiler.provenance import canonical_hash

from modules.codes._support.atom_template import AtomComponentTemplate, compile_template
from modules.codes.contracts.component import (
    ComponentBinding,
    ComponentExpansion,
    InvocationContext,
    validate_sequence,
)
from modules.codes.contracts.event_probability import ProbabilityPort

from .components import SurfaceComponent
from .definition import definition
from .growth import GrowthComponent, injection_indices
from .growth_decoder import GrowthDecoder, GrowthFrame
from .raw_t_postselection import (
    DirectRawTPostselection,
    RawTPostselectionExpansion,
    RawTPostselectionTemplate,
)


@dataclass(frozen=True)
class InjectionStage:
    """The small-patch result event; it is not yet a target-distance output."""

    sequence: RawTPostselectionExpansion
    target_binding: ComponentBinding
    preparation_sha256: str

    @property
    def acceptance_status(self) -> str:
        """Evaluate only the fixed d3 predicates."""
        return self.sequence.acceptance_status

    def with_results(self, values: Mapping[int, int]) -> "InjectionStage":
        """Attach actual received injection bits without executing growth."""
        return replace(self, sequence=self.sequence.with_results(values))


@dataclass(frozen=True)
class GrowthExpansion:
    """Accepted injection plus ordinary target checks; no growth rejection port."""

    injection: InjectionStage
    parts: tuple[ComponentExpansion, ...]
    distance: int

    def __post_init__(self) -> None:
        if self.injection.acceptance_status != "accepted":
            raise ValueError("Growth output requires accepted injection results.")
        if (self.distance == 3 and self.parts) or (
            self.distance > 3 and len(self.parts) < 2
        ):
            raise ValueError("Growth output has the wrong target SE history.")
        if self.parts and (
            self.parts[0].description.component_id != "grow_from_d3"
            or any(p.description.component_id != "se_round" for p in self.parts[1:])
            or any(
                p.description.code_id != f"rotated_surface_d{self.distance}"
                for p in self.parts
            )
        ):
            raise ValueError("Growth output contains an unrelated code component.")
        validate_sequence((*self.injection.sequence.parts, *self.parts))

    @property
    def results_ready_us(self) -> float:
        """All growth and injection outcomes must arrive before frame delivery."""
        return (
            self.parts[-1].results_ready_us
            if self.parts
            else self.injection.sequence.results_ready_us
        )

    def with_results(self, values: Mapping[int, int]) -> "GrowthExpansion":
        """Attach growth outcomes, rejecting unrelated result identities."""
        known = {m.result.measurement_id for p in self.parts for m in p.measurements}
        if not values.keys() <= known:
            raise ValueError("Unknown growth measurement ID.")
        return replace(
            self,
            parts=tuple(
                p.with_results(
                    {
                        m.result.measurement_id: values[m.result.measurement_id]
                        for m in p.measurements
                        if m.result.measurement_id in values
                    }
                )
                for p in self.parts
            ),
        )

    def decode(
        self, at_us: float, *, decoder: GrowthDecoder | None = None
    ) -> GrowthFrame:
        """Deliver an explicit frame after complete results, never postselect growth.

        This does not apply physical Paulis. The caller must propagate this frame
        through subsequent logical gates or compile an explicit correction.
        """
        from math import isfinite

        if not isfinite(at_us) or at_us < self.results_ready_us:
            raise ValueError("Growth results have not arrived at the caller's time.")
        if self.parts:
            history = [[m.value for m in p.measurements] for p in self.parts]
            if any(v is None for row in history for v in row):
                raise ValueError("Growth decoding requires received measurement bits.")
            selected = decoder or GrowthDecoder(self.distance)
            if selected.distance != self.distance:
                raise ValueError("Decoder distance disagrees with growth output.")
            return selected.decode(
                [[int(v) for v in row if v is not None] for row in history]
            )
        # At d3 the protocol has no deformation. Retain the established ideal
        # injection canonicalization on accepted constant-syndrome histories.
        sequence = self.injection.sequence
        values = {m.result: m.value for m in sequence.measurements}
        positions = {a: i for i, a in enumerate(self.injection.target_binding.atom_ids)}
        x = z = 0
        for relation in sequence.correction_relations:
            if values[relation.result]:
                for atom, basis in relation.pauli_atoms:
                    q = positions[atom]
                    if basis in ("X", "Y"):
                        x ^= 1 << q
                    if basis in ("Z", "Y"):
                        z ^= 1 << q
        return GrowthFrame(x, z, "accepted_d3_injection_frame/1")


@dataclass(frozen=True)
class StagedRawTTemplate:
    """Reusable injection and growth templates with a versioned stage identity."""

    protocol: "RawTPostselection"
    injection: RawTPostselectionTemplate
    growth: AtomComponentTemplate | None
    se_round: AtomComponentTemplate | None

    @property
    def content_sha256(self) -> str:
        """Fingerprint source, layout, device and stage policy for cache admission."""
        return canonical_hash(
            {
                **self.protocol.identity,
                "injection": self.injection.content_sha256,
                "growth": None if self.growth is None else self.growth.content_sha256,
                "se_round": None
                if self.se_round is None
                else self.se_round.content_sha256,
            }
        )

    def bind(self, binding: ComponentBinding) -> "BoundStagedRawT":
        """Bind the target patch; the small stage uses its explicitly mapped subset."""
        if len(binding.atom_ids) != definition(self.protocol.distance).atom_count:
            raise ValueError("Target binding has the wrong distance/atom count.")
        small = replace(
            binding,
            atom_ids=tuple(
                binding.atom_ids[i] for i in injection_indices(self.protocol.distance)
            ),
        )
        self.injection.bind(small)
        if self.growth is not None:
            self.growth.bind(binding)
        return BoundStagedRawT(self, binding, small)


@dataclass(frozen=True)
class BoundStagedRawT:
    """Caller-owned decision boundary between injection and growth."""

    template: StagedRawTTemplate
    binding: ComponentBinding
    injection_binding: ComponentBinding

    def expand(self, context: InvocationContext) -> InjectionStage:
        """Execute only injection; rejected attempts never execute outer resets."""
        return InjectionStage(
            self.template.injection.bind(self.injection_binding).expand(context),
            self.binding,
            self.template.content_sha256,
        )

    def grow(
        self, accepted: InjectionStage, context: InvocationContext
    ) -> GrowthExpansion:
        """Expand growth only after actual accepted, available injection results."""
        if (
            accepted.preparation_sha256 != self.template.content_sha256
            or accepted.target_binding != self.binding
        ):
            raise ValueError(
                "Injection event belongs to another preparation or binding."
            )
        sequence = accepted.sequence
        if (
            sequence.template_content_sha256 != self.template.injection.content_sha256
            or sequence.parts[0].wire_atoms != self.injection_binding.atom_ids
        ):
            raise ValueError(
                "Injection source does not match this growth continuation."
            )
        if not sequence.ready_for_use(context.start_us):
            raise ValueError(
                "Growth requires an accepted injection with available results."
            )
        if context.world_state != sequence.exit_state:
            raise ValueError("Growth must continue from the accepted injection world.")
        if context.result_id_base <= max(
            m.result.measurement_id for m in sequence.measurements
        ):
            raise ValueError(
                "Growth result allocation overlaps the injection allocation."
            )
        parts: list[ComponentExpansion] = []
        start, world, base = (
            context.start_us,
            context.world_state,
            context.result_id_base,
        )
        for r in range(self.template.protocol.growth_rounds):
            template = self.template.growth if r == 0 else self.template.se_round
            assert template is not None
            part = template.bind(self.binding).expand(
                InvocationContext(
                    f"{context.invocation_id}/growth[{r}]",
                    start,
                    base,
                    context.device,
                    world,
                )
            )
            parts.append(part)
            start, world = part.action_end_us, part.exit_state
            base += len(part.measurements)
        validate_sequence((*sequence.parts, *parts))
        return GrowthExpansion(accepted, tuple(parts), self.template.protocol.distance)


@dataclass(frozen=True, init=False)
class RawTPostselection:
    """Postselect only d3 injection, then grow and decode at the target distance.

    Defaults preserve the agreed three small-patch SE rounds. Growth uses d
    ordinary rounds including the deformation round (zero for target d3).
    injection_rounds=2 explicitly selects the two-round Li-style timing variant.
    """

    distance: int
    injection_rounds: int
    growth_rounds: int
    version: ClassVar[str] = "3"

    def __init__(
        self, distance: int, injection_rounds: int = 3, growth_rounds: int | None = None
    ) -> None:
        """Resolve target-dependent growth while keeping injection size fixed."""
        object.__setattr__(self, "distance", distance)
        object.__setattr__(self, "injection_rounds", injection_rounds)
        object.__setattr__(
            self,
            "growth_rounds",
            (0 if distance == 3 else distance)
            if growth_rounds is None
            else growth_rounds,
        )
        self.__post_init__()

    def __post_init__(self) -> None:
        definition(self.distance)
        if type(self.injection_rounds) is not int or self.injection_rounds < 2:
            raise ValueError("Postselection needs at least two d3 injection rounds.")
        if type(self.growth_rounds) is not int or (
            self.growth_rounds != 0 if self.distance == 3 else self.growth_rounds < 2
        ):
            raise ValueError("Use zero growth rounds at d3, at least two otherwise.")

    @property
    def identity(self) -> dict[str, Any]:
        """Expose the complete protocol identity for logical requests and caches."""
        return {
            "protocol": "small_injection_then_growth",
            "version": self.version,
            "target_distance": self.distance,
            "injection_distance": 3,
            "injection_rounds": self.injection_rounds,
            "growth_rounds": self.growth_rounds,
            "postselection_scope": "d3_injection_only",
            "growth_decoder": "phenomenological_mwpm_open_boundary/1",
        }

    def compile(
        self,
        device: Device,
        *,
        home_sites: tuple[str, ...],
        origin: Position,
        aod_id: str,
    ) -> StagedRawTTemplate:
        """Compile both branches, without executing or accepting either branch."""
        if len(home_sites) != definition(self.distance).atom_count:
            raise ValueError("Target homes disagree with target code distance.")
        small_homes = tuple(home_sites[i] for i in injection_indices(self.distance))
        outer_homes = tuple(s for s in home_sites if s not in small_homes)
        seed_templates = []
        for name in ("raw_t", "se_round"):
            component = SurfaceComponent(name, 3)
            compiled = compile_template(
                component.description,
                component.source_qasm,
                device,
                home_sites=small_homes,
                spectator_home_sites=outer_homes,
                origin=origin,
                aod_id=aod_id,
                expected_values=tuple(
                    0 if p in component.acceptance_ports else None
                    for p in component.description.measurements
                ),
                corrections=component.correction_terms,
            )
            seed_templates.append(
                replace(compiled, acceptance_ports=component.acceptance_ports)
            )
        seed = RawTPostselectionTemplate(
            seed_templates[0],
            seed_templates[1],
            self.injection_rounds - 1,
            round_policy="explicit_control",
        )
        growth = se = None
        if self.distance > 3:
            growth = GrowthComponent(self.distance).compile(
                device, home_sites=home_sites, origin=origin, aod_id=aod_id
            )
            se = SurfaceComponent("se_round", self.distance).compile(
                device, home_sites=home_sites, origin=origin, aod_id=aod_id
            )
        return StagedRawTTemplate(self, seed, growth, se)

    def acceptance_port(
        self,
        stage: InjectionStage,
        device: Device,
        *,
        noise_params: Mapping[str, Any],
        **estimator: Any,
    ) -> ProbabilityPort:
        """Evaluate the actual small trajectory; exclude growth from acceptance."""
        if len(stage.target_binding.atom_ids) != definition(
            self.distance
        ).atom_count or stage.sequence.parts[0].wire_atoms != tuple(
            stage.target_binding.atom_ids[i] for i in injection_indices(self.distance)
        ):
            raise ValueError(
                "Injection probability request has a different target binding."
            )
        seed = DirectRawTPostselection(
            3, self.injection_rounds - 1, round_policy="explicit_control"
        )
        base = seed.acceptance_port(
            stage.sequence, device, noise_params=noise_params, **estimator
        )
        data = base.to_dict()
        data["port_id"] = f"rotated_surface_d{self.distance}.small_injection.acceptance"
        data["protocol_id"] = "small_injection_then_growth"
        data["protocol_version"] = self.version
        data["model"]["id"] = "small_injection_then_growth.acceptance.v3"
        # Acceptance is an intermediate event, not a target-distance delivery.
        data["outcomes"][0]["branch_id"] = "grow"
        data["branches"][0] = {"key": "grow", "transition": "continue", "steps": []}
        data["model"]["parameters"]["staged_protocol"] = self.identity
        data["model"]["evidence"]["preparation_sha256"] = stage.preparation_sha256
        data["model"]["evidence"]["injection_port_sha256"] = base.content_sha256
        data["model"]["evidence"]["growth_quality_estimated"] = False
        return ProbabilityPort.from_dict(data)

    def validate_acceptance_port(
        self,
        port: ProbabilityPort,
        template: StagedRawTTemplate,
        *,
        noise_params: Mapping[str, Any],
    ) -> None:
        """Reject old all-d caches and stale stage/layout/timing identities."""
        data = port.to_dict()
        if (
            data["protocol_id"] != "small_injection_then_growth"
            or data["protocol_version"] != self.version
            or data["model"]["parameters"].get("staged_protocol") != self.identity
            or data["model"]["evidence"].get("preparation_sha256")
            != template.content_sha256
            or data["model"]["evidence"].get("noise_params_hash")
            != canonical_hash(resolve(noise_params))
        ):
            raise ValueError(
                "Raw-T probability cache does not match the staged preparation."
            )
