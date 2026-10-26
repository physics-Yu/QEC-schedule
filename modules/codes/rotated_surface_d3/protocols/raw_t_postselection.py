"""Required raw-T usage: unchanged injection plus repeated ordinary SE.

This local composition checks first-round boundary values and adjacent-round
syndrome parities. It owns neither a frame nor a decoder, retry loop, or noise
model. The temporal boundary remains open after the final extraction round.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from functools import reduce
from math import isfinite
from operator import xor
from typing import ClassVar

from nadit_physical_compiler.device import Device, Position
from nadit_physical_compiler.provenance import canonical_hash
from nadit_physical_compiler.state import AtomLayout

from ..._support.atom_template import AtomComponentTemplate
from ..._support.raw_t_round_policy import (
    RAW_T_PROTOCOL_VERSION,
    resolve_postselection_rounds,
)
from ...contracts.component import (
    ComponentBinding,
    ComponentExpansion,
    CorrectionRelation,
    InvocationContext,
    MeasurementOutput,
    validate_sequence,
)
from ..components import get_component
from ..components.injection import ACCEPTANCE_PORTS, RawTComponent
from ..definition import ROLES


def _check_rounds(count: int) -> None:
    if type(count) is not int or count < 1:
        raise ValueError("Raw-T use requires at least one additional SE round.")


@dataclass(frozen=True)
class PostselectionDetector:
    """One local parity with exact measurement identities and delivery times."""

    name: str
    measurements: tuple[MeasurementOutput, ...]

    @property
    def value(self) -> int | None:
        """Return the XOR, or pending if any contributing bit is unavailable."""
        values = tuple(m.value for m in self.measurements)
        if any(value is None for value in values):
            return None
        return reduce(xor, (v for v in values if v is not None), 0)

    @property
    def available_at_us(self) -> float:
        """Return the latest input-result delivery time, without advancing clocks."""
        return max(m.available_at_us for m in self.measurements)


@dataclass(frozen=True)
class RawTPostselectionExpansion:
    """A complete injection sequence; only its acceptance qualifies local use.

    A primitive part's acceptance_status still describes its four boundary
    checks. Consumers use this sequence's ready_for_use instead. Accepted here
    means these detectors passed, not that the logical magic state is error-free.
    """

    parts: tuple[ComponentExpansion, ...]
    template_content_sha256: str
    round_policy: str = field(default="distance", kw_only=True)
    protocol_id: ClassVar[str] = "raw_t_postselection"
    version: ClassVar[str] = RAW_T_PROTOCOL_VERSION
    postselection_scope: ClassVar[str] = "first_boundary_and_adjacent_round_parities"
    terminal_boundary: ClassVar[str] = "open_after_last_se"

    def __post_init__(self) -> None:
        _check_rounds(len(self.parts) - 1)
        resolve_postselection_rounds(
            3, self.extra_rounds, round_policy=self.round_policy
        )
        first = self.parts[0]
        if first.description.component_id != "raw_t" or any(
            p.description.component_id != "se_round" for p in self.parts[1:]
        ):
            raise ValueError(
                "Postselection requires raw_t followed only by ordinary SE."
            )
        for part in self.parts:
            if (
                part.block_id != first.block_id
                or part.description.code_id != "rotated_surface_d3"
                or part.description.roles != ROLES
                or part.wire_atoms != first.wire_atoms
                or tuple(m.port for m in part.measurements) != ROLES[9:]
                or part.exit_binding != first.exit_binding
            ):
                raise ValueError(
                    "All rounds must retain the same block, roles and ports."
                )
        validate_sequence(self.parts)

    @property
    def distance(self) -> int:
        """Return this concrete code's distance."""
        return 3

    @property
    def extra_rounds(self) -> int:
        """Return actual rounds after the raw-T primitive."""
        return len(self.parts) - 1

    @property
    def total_rounds(self) -> int:
        """Count all SE rounds, including raw-T's first extraction."""
        return len(self.parts)

    @property
    def measurements(self) -> tuple[MeasurementOutput, ...]:
        """Return all raw results; repeated port names keep distinct invocations."""
        return tuple(m for part in self.parts for m in part.measurements)

    @property
    def detectors(self) -> tuple[PostselectionDetector, ...]:
        """Return four boundary conditions and eight parities per later round."""
        rounds = tuple({m.port: m for m in p.measurements} for p in self.parts)
        boundary = tuple(
            PostselectionDetector(f"boundary.{port}", (rounds[0][port],))
            for port in ACCEPTANCE_PORTS
        )
        temporal = tuple(
            PostselectionDetector(
                f"round[{r}].{port}", (rounds[r - 1][port], rounds[r][port])
            )
            for r in range(1, len(rounds))
            for port in ROLES[9:]
        )
        return boundary + temporal

    @property
    def acceptance_status(self) -> str:
        """Reject any nonzero detector; accept only after all detector bits arrive."""
        values = tuple(d.value for d in self.detectors)
        if 1 in values:
            return "rejected"
        return "pending" if None in values else "accepted"

    @property
    def action_end_us(self) -> float:
        """Return final physical completion, independent of result delivery."""
        return self.parts[-1].action_end_us

    @property
    def results_ready_us(self) -> float:
        """Return completion of actions and all detection/canonicalization results."""
        return max(p.results_ready_us for p in self.parts)

    @property
    def exit_state(self) -> AtomLayout:
        """Return the complete world after the final extraction round."""
        return self.parts[-1].exit_state

    @property
    def exit_binding(self) -> ComponentBinding | None:
        """Return canonical output roles without applying any physical correction."""
        return self.parts[-1].exit_binding

    @property
    def correction_relations(self) -> tuple[CorrectionRelation, ...]:
        """Keep first-round branch relations; later accepted signs agree with them."""
        return self.parts[0].correction_relations

    def ready_for_use(self, at_us: float) -> bool:
        """Check received bits and physical/result completion at a caller time."""
        if not isfinite(at_us) or at_us < 0:
            raise ValueError("Use time must be finite and nonnegative.")
        return self.acceptance_status == "accepted" and at_us >= self.results_ready_us

    def with_results(self, values: Mapping[int, int]) -> "RawTPostselectionExpansion":
        """Attach received bits immutably; no sampling, correction or retry occurs."""
        known = {m.result.measurement_id for m in self.measurements}
        if not values.keys() <= known:
            raise ValueError("Received an unknown injection-sequence measurement ID.")
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


@dataclass(frozen=True, init=False)
class RawTPostselectionTemplate:
    """Reuse the original injection and SE templates, without fusing their circuits."""

    raw_t: AtomComponentTemplate
    se_round: AtomComponentTemplate
    extra_rounds: int
    round_policy: str

    def __init__(
        self,
        raw_t: AtomComponentTemplate,
        se_round: AtomComponentTemplate,
        extra_rounds: int | None = None,
        *,
        round_policy: str = "distance",
    ) -> None:
        """Resolve normal d3 rounds or a deliberately labeled control."""
        object.__setattr__(self, "raw_t", raw_t)
        object.__setattr__(self, "se_round", se_round)
        object.__setattr__(self, "round_policy", round_policy)
        object.__setattr__(
            self,
            "extra_rounds",
            resolve_postselection_rounds(3, extra_rounds, round_policy=round_policy),
        )
        self.__post_init__()

    def __post_init__(self) -> None:
        resolve_postselection_rounds(
            3, self.extra_rounds, round_policy=self.round_policy
        )
        if (
            self.raw_t.description.component_id,
            self.se_round.description.component_id,
        ) != ("raw_t", "se_round"):
            raise ValueError("Use the original raw_t and ordinary se_round templates.")
        if any(
            template.description.code_id != "rotated_surface_d3"
            or template.description.roles != ROLES
            for template in (self.raw_t, self.se_round)
        ):
            raise ValueError("Raw-T templates must use the concrete d3 code and roles.")

    @property
    def distance(self) -> int:
        """Return this concrete template's code distance."""
        return 3

    @property
    def total_rounds(self) -> int:
        """Count all SE rounds, including raw-T's first extraction."""
        return self.extra_rounds + 1

    @property
    def content_sha256(self) -> str:
        """Identify both immutable templates and the complete postselection protocol."""
        return canonical_hash(
            {
                "protocol": RawTPostselectionExpansion.protocol_id,
                "version": RawTPostselectionExpansion.version,
                "raw_t": self.raw_t.content_sha256,
                "se_round": self.se_round.content_sha256,
                "extra_rounds": self.extra_rounds,
                "distance": self.distance,
                "total_rounds": self.total_rounds,
                "round_policy": self.round_policy,
                "scope": RawTPostselectionExpansion.postselection_scope,
                "terminal_boundary": RawTPostselectionExpansion.terminal_boundary,
            }
        )

    def bind(self, binding: ComponentBinding) -> "BoundRawTPostselection":
        """Bind both component roles; each expansion checks the complete world."""
        self.raw_t.bind(binding)
        self.se_round.bind(binding)
        return BoundRawTPostselection(self, binding)


@dataclass(frozen=True)
class BoundRawTPostselection:
    """Caller-bound unconditional rounds with separate measurement identities."""

    template: RawTPostselectionTemplate
    binding: ComponentBinding

    def expand(self, context: InvocationContext) -> RawTPostselectionExpansion:
        """Expand consecutive rounds; reserve 8*(1+extra_rounds) result IDs."""
        parts: list[ComponentExpansion] = []
        start, world = context.start_us, context.world_state
        for r in range(1 + self.template.extra_rounds):
            template = self.template.raw_t if r == 0 else self.template.se_round
            part = template.bind(self.binding).expand(
                InvocationContext(
                    f"{context.invocation_id}/round[{r}]",
                    start,
                    context.result_id_base + 8 * r,
                    context.device,
                    world,
                )
            )
            parts.append(part)
            start, world = part.action_end_us, part.exit_state
        return RawTPostselectionExpansion(
            tuple(parts),
            self.template.content_sha256,
            round_policy=self.template.round_policy,
        )


@dataclass(frozen=True, init=False)
class RawTPostselection:
    """Normal d3 use has three total rounds; short controls require a label."""

    extra_rounds: int
    round_policy: str
    version: ClassVar[str] = RAW_T_PROTOCOL_VERSION

    def __init__(
        self,
        extra_rounds: int | None = None,
        *,
        round_policy: str = "distance",
    ) -> None:
        """Select two extra SE rounds unless an explicit_control is supplied."""
        object.__setattr__(self, "round_policy", round_policy)
        object.__setattr__(
            self,
            "extra_rounds",
            resolve_postselection_rounds(3, extra_rounds, round_policy=round_policy),
        )

    @property
    def distance(self) -> int:
        """Return this concrete protocol's code distance."""
        return 3

    @property
    def total_rounds(self) -> int:
        """Count all SE rounds, including raw-T's first extraction."""
        return self.extra_rounds + 1

    def compile(
        self,
        device: Device,
        *,
        home_sites: tuple[str, ...],
        origin: Position,
        aod_id: str,
    ) -> RawTPostselectionTemplate:
        """Compile each original component once; reuse SE for every later round."""
        return RawTPostselectionTemplate(
            RawTComponent().compile(
                device, home_sites=home_sites, origin=origin, aod_id=aod_id
            ),
            get_component("se_round").compile(
                device, home_sites=home_sites, origin=origin, aod_id=aod_id
            ),
            self.extra_rounds,
            round_policy=self.round_policy,
        )
