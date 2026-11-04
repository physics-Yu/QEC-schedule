"""Small immutable component invocation contracts; no frame or scheduler state."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from math import isfinite
from typing import Protocol

from nadit_physical_compiler.atom_ir import AtomProgram
from nadit_physical_compiler.compiler import CompiledOperation
from nadit_physical_compiler.device import Device, Position
from nadit_physical_compiler.physical_ir import PhysicalDAG, ResultRef
from nadit_physical_compiler.state import AtomLayout


@dataclass(frozen=True)
class ComponentDescription:
    """Static identity, role order, result ports and explicit entry/exit semantics."""

    code_id: str
    component_id: str
    version: str
    roles: tuple[str, ...]
    measurements: tuple[str, ...]
    entry_requirements: tuple[str, ...]
    exit_guarantees: tuple[str, ...]


@dataclass(frozen=True)
class ComponentBinding:
    """Bind ordered roles to atoms and an origin; optional site IDs disambiguate.

    `site_ids` maps template site keys to actual Device site IDs. Omission uses
    unique coordinate lookup. Binding never moves atoms into the entry layout.
    """

    block_id: str
    origin: Position
    atom_ids: tuple[int, ...]
    aod_id: str
    site_ids: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class InvocationContext:
    """Caller-owned world/time and globally reserved measurement-ID range.

    The caller reserves result_id_base through base + result-port-count - 1.
    Components do not own a global clock, result allocator or quantum state.
    """

    invocation_id: str
    start_us: float
    result_id_base: int
    device: Device
    world_state: AtomLayout

    def __post_init__(self) -> None:
        if not self.invocation_id or not isfinite(self.start_us) or self.start_us < 0:
            raise ValueError(
                "Invocation requires an identity and nonnegative finite time."
            )
        if type(self.result_id_base) is not int or self.result_id_base < 0:
            raise ValueError("Measurement-ID base must be a nonnegative integer.")


@dataclass(frozen=True)
class MeasurementOutput:
    """One physical result with stable invocation/port identity and availability.

    expected_ideal_value is preparation metadata, not a sampled bit or a rule
    for rejecting noisy outcomes. None denotes an unknown or random outcome.
    """

    invocation_id: str
    port: str
    result: ResultRef
    atom_id: int
    available_at_us: float
    expected_ideal_value: int | None
    value: int | None = None


@dataclass(frozen=True)
class CorrectionTerm:
    """Static conditional Pauli relation, not an applied correction or decoder."""

    measurement_port: str
    pauli_roles: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class CorrectionRelation:
    """Apply the listed Pauli iff result=1 to select the canonical preparation.

    This is a symbolic relation for later frame handling. No runtime subsystem
    in this contract evaluates, accumulates or propagates frame updates.
    """

    block_id: str
    result: ResultRef
    pauli_atoms: tuple[tuple[int, str], ...]


@dataclass(frozen=True)
class ComponentExpansion:
    """A composable invocation: local-time actions, global-time outputs, layouts.

    DAG wire indices use wire_atoms; the public world retains its original wire
    map. Native operation IDs are local to this invocation. Consumers must keep
    invocation identity when combining provenance across component boundaries.

    exit_binding names canonical roles after physical permutations. Joint
    operations instead return explicit participant_bindings and their exits.
    output_syndrome_parities are local XOR equations: input.* names prior
    stabilizer signs; other terms name this invocation's measurement ports.
    These records do not evaluate or propagate a global frame.
    """

    description: ComponentDescription
    invocation_id: str
    block_id: str
    start_us: float
    entry_state: AtomLayout
    exit_state: AtomLayout
    wire_atoms: tuple[int, ...]
    program: AtomProgram
    dag: PhysicalDAG
    operations: tuple[CompiledOperation, ...]
    measurements: tuple[MeasurementOutput, ...]
    correction_relations: tuple[CorrectionRelation, ...]
    validation_checks: tuple[str, ...]
    exit_binding: ComponentBinding | None = None
    acceptance_conditions: tuple[tuple[ResultRef, int], ...] = ()
    output_syndrome_parities: tuple[tuple[str, tuple[str, ...]], ...] = ()
    participant_bindings: tuple[ComponentBinding, ...] = ()
    exit_participant_bindings: tuple[ComponentBinding, ...] = ()
    template_content_sha256: str = ""

    @property
    def acceptance_status(self) -> str:
        """Evaluate only the local predicate from received bits, without feedback.

        A known failed condition rejects immediately. Otherwise missing bits
        leave acceptance pending. Availability times remain caller obligations.
        """
        if not self.acceptance_conditions:
            return "not_applicable"
        values = {r.result: r.value for r in self.measurements}
        if any(
            values[result] is not None and values[result] != expected
            for result, expected in self.acceptance_conditions
        ):
            return "rejected"
        if any(values[result] is None for result, _ in self.acceptance_conditions):
            return "pending"
        return "accepted"

    @property
    def action_end_us(self) -> float:
        """Return the exit time using the same ordered additions as atom replay."""
        cursor = self.start_us
        for step in self.program.steps:
            cursor += step.duration_us
        return cursor

    @property
    def results_ready_us(self) -> float:
        """Return completion including pending results, without advancing time."""
        return max(
            (self.action_end_us, *(r.available_at_us for r in self.measurements))
        )

    def with_results(self, values: Mapping[int, int]) -> "ComponentExpansion":
        """Attach received values immutably; reject unknown IDs or conflicting bits.

        This does not advance clocks or apply corrections. A consumer must still
        respect each output's availability time before using it for feedback.
        """
        known = {r.result.measurement_id: r for r in self.measurements}
        if not values.keys() <= known.keys():
            raise ValueError("Received an unknown component measurement ID.")
        for mid, value in values.items():
            if type(value) is not int or value not in (0, 1):
                raise ValueError("Measurement values must be integer bits.")
            if known[mid].value is not None and known[mid].value != value:
                raise ValueError(
                    "Cannot replace a previously received measurement value."
                )
        return replace(
            self,
            measurements=tuple(
                replace(r, value=values.get(r.result.measurement_id, r.value))
                for r in self.measurements
            ),
        )


class BoundComponent(Protocol):
    """A bound template can expand under the caller's current complete world."""

    def expand(self, context: InvocationContext) -> ComponentExpansion:
        """Return validated atom actions or reject the current physical binding."""
        ...


class ComponentTemplate(Protocol):
    """A reusable template contains definitions and action structure, never bits."""

    @property
    def description(self) -> ComponentDescription:
        """Return the component's public static contract."""
        ...

    def bind(self, binding: ComponentBinding) -> BoundComponent:
        """Bind participant identity, relative origin, atoms and device resources."""
        ...


def validate_sequence(parts: Sequence[ComponentExpansion]) -> None:
    """Check an explicitly ordered call chain; do not schedule or alter it.

    Result-dependent operations additionally require their own ready-time checks.
    Unconditional components consume no earlier measurement bits.
    """
    invocations: set[str] = set()
    results: set[int] = set()
    previous: ComponentExpansion | None = None
    for part in parts:
        ids = {r.result.measurement_id for r in part.measurements}
        if part.invocation_id in invocations or results & ids:
            raise ValueError("Sequence repeats an invocation or measurement identity.")
        if previous is not None and (
            part.entry_state != previous.exit_state
            or part.start_us < previous.action_end_us
        ):
            raise ValueError(
                "Sequence has incompatible layouts or overlapping actions."
            )
        invocations.add(part.invocation_id)
        results |= ids
        previous = part
