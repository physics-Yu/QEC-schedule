"""Execute one preparation's local Pauli relation, without a global frame.

A coarse joint event can choose a correction without inventing physical result
bits. The original measurement identities and delivery times remain unchanged.
With noise, applying this relation does not establish an error-free output.
"""

from dataclasses import dataclass
from math import isfinite
from re import fullmatch

from nadit_physical_compiler.device import Device, Position
from nadit_physical_compiler.state import SLMHolder

from ..._support.atom_template import AtomComponentTemplate, compile_template
from ..._support.raw_t_round_policy import RAW_T_PROTOCOL_VERSION
from ...contracts.component import (
    ComponentDescription,
    ComponentExpansion,
    CorrectionRelation,
    CorrectionTerm,
    InvocationContext,
    MeasurementOutput,
)
from ...contracts.event_probability import ProbabilityPort
from ..definition import ROLES
from ..protocols.raw_t_postselection import RawTPostselectionExpansion
from .injection import CORRECTIONS

PREPARATION_TERMS = {
    "initialize_0": tuple(
        CorrectionTerm(f"X{i}", ((f"data[{q}]", "Z"),))
        for i, q in enumerate((0, 2, 6, 8))
    ),
    "initialize_plus": tuple(
        CorrectionTerm(f"Z{i}", ((f"data[{q}]", "X"),))
        for i, q in enumerate((6, 0, 8, 2))
    ),
    "raw_t_postselection": CORRECTIONS,
}
type PreparationExpansion = ComponentExpansion | RawTPostselectionExpansion


@dataclass(frozen=True)
class CorrectionDecision:
    """Caller-selected joint event; this object contains no physical syndrome.

    For raw T, source_invocation_id names the actual first raw_t invocation,
    normally ending in /round[0]. Class bit i selects correction relation i.
    Rejected events have no byproduct_class and cannot generate a correction.
    """

    source_invocation_id: str
    event_id: str
    port_sha256: str
    byproduct_class: int | None
    accepted: bool
    available_at_us: float

    def __post_init__(self) -> None:
        """Reject invalid event identities, classes, fingerprints, or times."""
        if any(
            not isinstance(value, str) or not value.strip()
            for value in (self.source_invocation_id, self.event_id)
        ):
            raise ValueError("Correction decisions require nonempty identities.")
        if not isinstance(self.port_sha256, str) or not fullmatch(
            r"[0-9a-f]{64}", self.port_sha256
        ):
            raise ValueError("Correction decision requires a canonical SHA-256.")
        if type(self.accepted) is not bool:
            raise ValueError("Correction acceptance must be a Boolean.")
        if self.accepted:
            if (
                type(self.byproduct_class) is not int
                or not 0 <= self.byproduct_class < 16
            ):
                raise ValueError(
                    "Accepted byproduct class must be an integer in [0,15]."
                )
        elif self.byproduct_class is not None:
            raise ValueError("Rejected preparation has no usable byproduct class.")
        if (
            type(self.available_at_us) not in (int, float)
            or not isfinite(self.available_at_us)
            or self.available_at_us < 0
        ):
            raise ValueError("Correction availability must be finite and nonnegative.")


@dataclass(frozen=True)
class CorrectionApplication:
    """Real actions and their decision provenance, retaining unmodified results."""

    decision: CorrectionDecision
    source_measurements: tuple[MeasurementOutput, ...]
    selected_relations: tuple[CorrectionRelation, ...]
    expansion: ComponentExpansion


def _check_port(preparation: str, port: ProbabilityPort) -> None:
    prefix = f"rotated_surface_d3.{preparation}"
    if (
        port.port_id != prefix + ".canonical_preparation"
        or port.protocol_id != prefix
        or port.protocol_version
        != (RAW_T_PROTOCOL_VERSION if preparation == "raw_t_postselection" else "1")
    ):
        raise ValueError("Probability port does not describe this preparation.")
    seen: set[int | None] = set()
    for outcome in port.outcomes:
        values = dict(outcome.values)
        if set(values) != {"accepted", "byproduct_class"}:
            raise ValueError("Preparation events require joint acceptance and class.")
        accepted, value = values["accepted"], values["byproduct_class"]
        if type(accepted) is not bool:
            raise ValueError("Joint event acceptance must be a Boolean.")
        if accepted:
            if type(value) is not int or not 0 <= value < 16:
                raise ValueError("Accepted joint event has an invalid byproduct class.")
        elif value is not None:
            raise ValueError("Rejected joint event must have a null byproduct class.")
        if value in seen:
            raise ValueError("Preparation port repeats a joint event.")
        seen.add(value)
    if not set(range(16)) <= seen:
        raise ValueError("Preparation port must declare all sixteen classes.")


@dataclass(frozen=True)
class PreparationCanonicalization:
    """Compile finite local corrections for an approved preparation protocol."""

    preparation: str

    def __post_init__(self) -> None:
        """Reject single-round raw T and arbitrary encoded-state corrections."""
        if self.preparation not in PREPARATION_TERMS:
            raise ValueError("Unsupported preparation canonicalization protocol.")

    def compile(
        self,
        device: Device,
        *,
        probability_port: ProbabilityPort,
        home_sites: tuple[str, ...],
        origin: Position,
        aod_id: str,
    ) -> "CompiledPreparationCorrections":
        """Compile all classes at reference geometry and freeze the joint model.

        Args follow the ordinary component compiler. probability_port must be a
        joint acceptance/class definition for this preparation. Bindings, events,
        and clocks are supplied later. Raises ValueError for mismatched ports or
        unsupported geometry, never silently substituting a logical Pauli string.
        """
        _check_port(self.preparation, probability_port)
        templates = []
        for value in range(16):
            lines = ["OPENQASM 3.0;", 'include "stdgates.inc";', "qubit[17] q;"]
            for i, term in enumerate(PREPARATION_TERMS[self.preparation]):
                if value & (1 << i):
                    lines.extend(
                        f"{basis.lower()} q[{ROLES.index(role)}];"
                        for role, basis in term.pauli_roles
                    )
            description = ComponentDescription(
                "rotated_surface_d3",
                f"canonicalize_{self.preparation}.class[{value}]",
                "1",
                ROLES,
                (),
                (
                    "Use only this preparation's accepted joint byproduct event",
                    "Wait for the preparation exit and all required results",
                    "Preserve data; keep measured ancillas at reference homes",
                ),
                (
                    "Apply only selected local physical Pauli preparation relations",
                    "Retain all atoms at their homes; ancillas unchanged",
                    "No sampled syndrome, decoder, global frame, or logical quality claim",
                ),
            )
            templates.append(
                compile_template(
                    description,
                    "\n".join(lines) + "\n",
                    device,
                    home_sites=home_sites,
                    origin=origin,
                    aod_id=aod_id,
                    expected_values=(),
                    corrections=(),
                )
            )
        return CompiledPreparationCorrections(
            self.preparation, probability_port, tuple(templates)
        )


@dataclass(frozen=True)
class CompiledPreparationCorrections:
    """Reusable relative templates plus the exact event model they consume."""

    preparation: str
    probability_port: ProbabilityPort
    templates: tuple[AtomComponentTemplate, ...]

    def __post_init__(self) -> None:
        """Reject incomplete classes or mismatched public template construction."""
        if self.preparation not in PREPARATION_TERMS:
            raise ValueError("Unsupported compiled preparation corrections.")
        _check_port(self.preparation, self.probability_port)
        if len(self.templates) != 16 or any(
            template.description.component_id
            != f"canonicalize_{self.preparation}.class[{value}]"
            or template.description.roles != ROLES
            or template.description.measurements
            or template.correction_terms
            for value, template in enumerate(self.templates)
        ):
            raise ValueError("Compiled corrections require sixteen matching templates.")

    def _source(self, source: PreparationExpansion) -> ComponentExpansion:
        if self.preparation == "raw_t_postselection":
            if not isinstance(source, RawTPostselectionExpansion):
                raise ValueError(
                    "Raw correction requires the complete repeated-SE protocol."
                )
            if source.acceptance_status == "rejected":
                raise ValueError(
                    "Known raw-T detector failure cannot be canonicalized."
                )
            model = self.probability_port.to_dict()["model"]
            if model["parameters"].get("extra_rounds") != len(source.parts) - 1:
                raise ValueError(
                    "Joint probability model has a different SE round count."
                )
            parameters = model["parameters"]
            if (
                parameters.get("distance") != 3
                or parameters.get("total_rounds") != len(source.parts)
                or parameters.get("round_policy") != source.round_policy
            ):
                raise ValueError(
                    "Joint probability model has a different SE round policy."
                )
            recorded_hash = model["evidence"].get("template_content_sha256")
            if (
                recorded_hash is not None
                and recorded_hash != source.template_content_sha256
            ):
                raise ValueError(
                    "Joint probability model has a different source template."
                )
            return source.parts[0]
        if (
            not isinstance(source, ComponentExpansion)
            or source.description.component_id != self.preparation
        ):
            raise ValueError(
                "Correction source does not match its preparation protocol."
            )
        return source

    def expand_after(
        self,
        source: PreparationExpansion,
        decision: CorrectionDecision,
        context: InvocationContext,
    ) -> CorrectionApplication:
        """Apply the chosen relation after the true source exit and event readiness.

        No result values are filled in or inferred. Known contradictory bits,
        wrong identities/models/layouts, rejected events, and early invocations
        raise ValueError. Coarse decisions may accompany pending physical bits.
        """
        first = self._source(source)
        if decision.source_invocation_id != first.invocation_id:
            raise ValueError("Correction decision names a different source invocation.")
        if decision.port_sha256 != self.probability_port.content_sha256:
            raise ValueError(
                "Correction decision probability-port fingerprint differs."
            )
        if not decision.accepted:
            raise ValueError(
                "A rejected preparation cannot produce usable corrections."
            )
        if not any(
            outcome.probability > 0
            and dict(outcome.values)
            == {"accepted": True, "byproduct_class": decision.byproduct_class}
            for outcome in self.probability_port.outcomes
        ):
            raise ValueError(
                "Correction decision is not a possible joint-port outcome."
            )
        if context.start_us < max(source.results_ready_us, decision.available_at_us):
            raise ValueError(
                "Correction starts before physical/result/event readiness."
            )
        if decision.available_at_us < source.results_ready_us:
            raise ValueError("Joint preparation event predates its required results.")
        source_ids = (
            {part.invocation_id for part in source.parts}
            if isinstance(source, RawTPostselectionExpansion)
            else {first.invocation_id}
        )
        if context.invocation_id in source_ids:
            raise ValueError("Correction invocation must have a fresh identity.")
        binding = source.exit_binding
        if (
            binding is None
            or binding.block_id != first.block_id
            or binding.atom_ids != first.wire_atoms
        ):
            raise ValueError("Correction source has an incompatible exit binding.")
        # Another disjoint patch may have completed while these results were
        # pending. Preserve its current state, but never accept altered local
        # carriers, a different atom inventory/wire map, or changed AOD state.
        current, previous = context.world_state, source.exit_state
        if (
            current.qubit_to_atom != previous.qubit_to_atom
            or tuple(atom.id for atom in current.atoms)
            != tuple(atom.id for atom in previous.atoms)
            or current.aod_grids != previous.aod_grids
            or any(
                current.atom(atom) != previous.atom(atom)
                or not isinstance(current.atom(atom).holder, SLMHolder)
                for atom in binding.atom_ids
            )
        ):
            raise ValueError(
                "Correction must preserve its local preparation exit and world identities."
            )
        if (
            first.description.roles != ROLES
            or first.description.code_id != "rotated_surface_d3"
            or first.description.version != "1"
        ):
            raise ValueError("Correction source uses a different role convention.")
        role_atoms = dict(zip(ROLES, binding.atom_ids, strict=True))
        ports = {measurement.port: measurement for measurement in first.measurements}
        terms = PREPARATION_TERMS[self.preparation]
        if not {term.measurement_port for term in terms} <= ports.keys():
            raise ValueError("Correction source is missing preparation result ports.")
        expected = tuple(
            CorrectionRelation(
                binding.block_id,
                ports[term.measurement_port].result,
                tuple((role_atoms[role], basis) for role, basis in term.pauli_roles),
            )
            for term in terms
        )
        if source.correction_relations != expected:
            raise ValueError(
                "Source preparation relations differ from the compiled corrections."
            )
        assert decision.byproduct_class is not None
        if isinstance(source, RawTPostselectionExpansion):
            # Acceptance fixes every boundary bit and equates adjacent rounds.
            # Check already supplied bits against this joint event, without
            # writing predicted values into unresolved physical result records.
            expected_bits = dict.fromkeys(ROLES[9:], 0)
            expected_bits.update(
                {
                    term.measurement_port: (decision.byproduct_class >> i) & 1
                    for i, term in enumerate(terms)
                }
            )
            if any(
                record.value is not None and record.value != expected_bits[record.port]
                for record in source.measurements
            ):
                raise ValueError("Joint event contradicts a received raw-T round bit.")
        selected = []
        for index, relation in enumerate(expected):
            bit = (decision.byproduct_class >> index) & 1
            observed = ports[terms[index].measurement_port].value
            if observed is not None and observed != bit:
                raise ValueError(
                    "Byproduct class contradicts a received preparation bit."
                )
            if bit:
                selected.append(relation)
        expansion = (
            self.templates[decision.byproduct_class].bind(binding).expand(context)
        )
        return CorrectionApplication(
            decision, source.measurements, tuple(selected), expansion
        )
