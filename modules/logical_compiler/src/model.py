"""Immutable logical operations, measurement guards and translation evidence."""

from dataclasses import asdict, dataclass


class TranslationError(ValueError):
    """A source, capability, budget or synthesis failure with a stable code."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True, slots=True)
class Predicate:
    """Compare a little-endian classical register with an integer.

    None denotes an initially zero classical bit. Non-None entries identify
    immutable measurement occurrences, never mutable classical register slots.
    """

    bits: tuple[int | None, ...]
    value: int
    equal: bool = True

    def evaluate(self, results: dict[int, int]) -> bool:
        """Evaluate supplied bits; missing results raise KeyError."""
        actual = 0
        for offset, reference in enumerate(self.bits):
            bit = 0 if reference is None else results[reference]
            if bit not in (0, 1):
                raise ValueError("Measurement results must be bits.")
            actual |= bit << offset
        return (actual == self.value) == self.equal


@dataclass(frozen=True, slots=True)
class Guard:
    """A conjunction of branch predicates, including nested conditions."""

    predicates: tuple[Predicate, ...]

    @property
    def references(self) -> tuple[int, ...]:
        """Return stable measurement dependencies in identity order."""
        return tuple(
            sorted({r for p in self.predicates for r in p.bits if r is not None})
        )

    def evaluate(self, results: dict[int, int]) -> bool:
        """Evaluate the conjunction without sampling or modifying results."""
        return all(p.evaluate(results) for p in self.predicates)


@dataclass(frozen=True, slots=True)
class Operation:
    """One logical instruction with immutable source and measurement identities."""

    name: str
    qubits: tuple[int, ...]
    params: tuple[float, ...] = ()
    clbits: tuple[int, ...] = ()
    source_ids: tuple[int, ...] = ()
    guard: Guard | None = None
    result_id: int | None = None
    component: str | None = None


@dataclass(frozen=True, slots=True)
class Register:
    """A source register name and its flattened wire indices."""

    name: str
    bits: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ParsedCircuit:
    """Normalized logical source before synthesis and initialization insertion."""

    num_qubits: int
    num_clbits: int
    operations: tuple[Operation, ...]
    quantum_registers: tuple[Register, ...]
    classical_registers: tuple[Register, ...]


@dataclass(frozen=True, slots=True)
class SynthesisRecord:
    """Numerically checked spectral-norm error for one emitted RZ approximation."""

    source_ids: tuple[int, ...]
    angle: float
    allocated_error: float
    measured_error: float
    emitted_gates: int


@dataclass(frozen=True, slots=True)
class TranslationResult:
    """A logical DAG and synthesis evidence, not an executable atom program."""

    code: str
    scheme: str
    num_qubits: int
    num_clbits: int
    operations: tuple[Operation, ...]
    edges: tuple[tuple[int, int], ...]
    target_operations: tuple[str, ...]
    error_budget: float
    synthesis: tuple[SynthesisRecord, ...]
    input_state: str
    source_sha256: str
    qiskit_version: str
    quantum_registers: tuple[Register, ...]
    classical_registers: tuple[Register, ...]
    execution_ready: bool = False

    @property
    def synthesis_error_bound(self) -> float:
        """Sum checked errors, including mutually exclusive branches conservatively."""
        return sum(record.measured_error for record in self.synthesis)

    @property
    def measurements(self) -> tuple[Operation, ...]:
        """Return measurements in output order, with stable result identities."""
        return tuple(op for op in self.operations if op.name == "measure")

    def to_dict(self) -> dict[str, object]:
        """Return JSON-compatible translation records and derived resource counts."""
        document = asdict(self)
        document.update(
            schema="nadit.logical_translation/1",
            stage="logical_translation",
            synthesis_error_bound=self.synthesis_error_bound,
            t_count=sum(op.name in ("t", "tdg") for op in self.operations),
        )
        return document
