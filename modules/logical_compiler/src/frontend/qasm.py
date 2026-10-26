"""Parse finite QASM circuit profiles and bind classical reads to producers."""

import re
from math import isfinite

from openqasm3.parser import QASM3ParsingError
from qiskit import QuantumCircuit, qasm2, qasm3
from qiskit.circuit import (
    Barrier,
    ClassicalRegister,
    Clbit,
    ForLoopOp,
    Gate,
    IfElseOp,
    Measure,
    Reset,
)
from qiskit.circuit.library import get_standard_gate_name_mapping
from qiskit.exceptions import QiskitError

from ..model import (
    Guard,
    Operation,
    ParsedCircuit,
    Predicate,
    Register,
    TranslationError,
)

_STANDARD = get_standard_gate_name_mapping()
_CLASSES = {
    gate.base_class: gate.name for gate in _STANDARD.values() if isinstance(gate, Gate)
}
_HEADER = re.compile(
    r"\A(?:\s|//[^\n]*(?:\n|\Z)|/\*.*?\*/)*OPENQASM\s+([0-9.]+)\s*;", re.DOTALL
)
_TOKENS = re.compile(
    r"""//[^\r\n]*|/\*.*?\*/|"[^"\r\n]*"|'[^'\r\n]*'|(?P<include>\binclude\b)""",
    re.DOTALL,
)


def parse_qasm(source: str, max_operations: int) -> ParsedCircuit:
    """Normalize QASM 2/3 gates, finite for loops and fixed measurement branches.

    Raises TranslationError for invalid syntax, unsupported semantics or limits.
    """
    source = source.removeprefix("\ufeff")
    header = _HEADER.match(source)
    if header is None or header[1] not in ("2.0", "3", "3.0"):
        raise TranslationError("QASM_VERSION", "Expected OPENQASM 2.0 or 3.0.")
    library = "qelib1.inc" if header[1] == "2.0" else "stdgates.inc"
    tokens = iter(_TOKENS.finditer(source))
    for token in tokens:
        if token.lastgroup == "include":
            target = next(
                (t[0] for t in tokens if not t[0].startswith(("//", "/*"))), ""
            )
            if target not in (f'"{library}"', f"'{library}'"):
                raise TranslationError(
                    "UNSUPPORTED_INCLUDE", f"Only {library!r} is supported."
                )
    try:
        circuit = (
            qasm2.loads(source, include_path=(), strict=True)
            if header[1] == "2.0"
            else qasm3.loads(source)
        )
    except (QiskitError, QASM3ParsingError, ValueError, TypeError, IndexError) as error:
        raise TranslationError("QASM_IMPORT", str(error)) from error
    try:
        normalizer = _Normalizer(max_operations)
        normalizer.visit(
            circuit, tuple(range(circuit.num_qubits)), tuple(range(circuit.num_clbits))
        )
        return ParsedCircuit(
            circuit.num_qubits,
            circuit.num_clbits,
            tuple(normalizer.operations),
            tuple(
                Register(r.name, tuple(circuit.find_bit(b).index for b in r))
                for r in circuit.qregs
            ),
            tuple(
                Register(r.name, tuple(circuit.find_bit(b).index for b in r))
                for r in circuit.cregs
            ),
        )
    except TranslationError:
        raise
    except (QiskitError, ValueError, TypeError, RecursionError) as error:
        raise TranslationError("UNSUPPORTED_SOURCE", str(error)) from error


class _Normalizer:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.operations: list[Operation] = []
        self.latest: dict[int, int] = {}
        self.visits = 0

    def emit(
        self,
        name: str,
        qubits: tuple[int, ...],
        params: tuple[float, ...],
        clbits: tuple[int, ...],
        guard: Guard | None,
    ) -> None:
        if not all(isfinite(p) for p in params):
            raise TranslationError(
                "NONFINITE_PARAMETER", f"Gate {name!r} has nonfinite parameters."
            )
        if len(self.operations) >= self.limit:
            raise TranslationError(
                "EXPANSION_LIMIT", f"Source exceeds {self.limit} operations."
            )
        identity = len(self.operations)
        result = identity if name == "measure" else None
        self.operations.append(
            Operation(name, qubits, params, clbits, (identity,), guard, result)
        )
        if result is not None:
            self.latest[clbits[0]] = result

    def visit(
        self,
        circuit: QuantumCircuit,
        qmap: tuple[int, ...],
        cmap: tuple[int, ...],
        guard: Guard | None = None,
        depth: int = 0,
    ) -> None:
        if depth > 128:
            raise TranslationError(
                "EXPANSION_LIMIT", "Source nesting exceeds 128 levels."
            )
        if circuit.parameters:
            raise TranslationError(
                "UNSUPPORTED_PARAMETERS", "Bind all input parameters first."
            )
        if circuit.layout is not None:
            raise TranslationError(
                "UNSUPPORTED_ADDRESSING", "Physical addressing is not a logical wire."
            )
        if circuit.global_phase:
            self.emit("global_phase", (), (float(circuit.global_phase),), (), guard)
        for item in circuit.data:
            self.visits += 1
            if self.visits > self.limit:
                raise TranslationError(
                    "EXPANSION_LIMIT", f"Source expansion exceeds {self.limit} visits."
                )
            op = item.operation
            qubits = tuple(qmap[circuit.find_bit(q).index] for q in item.qubits)
            clbits = tuple(cmap[circuit.find_bit(c).index] for c in item.clbits)
            if isinstance(op, ForLoopOp):
                indices, parameter, body = op.params
                if len(indices) > self.limit - self.visits:
                    raise TranslationError(
                        "EXPANSION_LIMIT", "For loop exceeds expansion budget."
                    )
                for index in indices:
                    bound = (
                        body.assign_parameters({parameter: index})
                        if parameter in body.parameters
                        else body
                    )
                    self.visit(bound, qubits, clbits, guard, depth + 1)
            elif isinstance(op, IfElseOp):
                self.branch(circuit, op, qubits, clbits, cmap, guard, depth)
            elif isinstance(op, (Measure, Reset, Barrier)):
                if isinstance(op, Measure) and guard is not None:
                    raise TranslationError(
                        "UNSUPPORTED_CONDITIONAL_MEASUREMENT",
                        "Branch measurement writes require classical merge semantics.",
                    )
                self.emit(
                    "initialize_0" if isinstance(op, Reset) else op.name,
                    qubits,
                    (),
                    clbits,
                    guard,
                )
            elif isinstance(op, Gate):
                if _CLASSES.get(op.base_class) == op.name:
                    self.emit(
                        op.name,
                        qubits,
                        tuple(float(p) for p in op.params),
                        clbits,
                        guard,
                    )
                elif op.definition is not None:
                    self.visit(op.definition, qubits, clbits, guard, depth + 1)
                else:
                    raise TranslationError(
                        "UNSUPPORTED_OPAQUE_GATE",
                        f"Gate {op.name!r} has no definition.",
                    )
            else:
                raise TranslationError(
                    "UNSUPPORTED_CONTROL_FLOW",
                    f"Operation {op.name!r} is outside the finite logical DAG profile.",
                )

    def branch(
        self,
        circuit: QuantumCircuit,
        op: IfElseOp,
        qubits: tuple[int, ...],
        clbits: tuple[int, ...],
        cmap: tuple[int, ...],
        guard: Guard | None,
        depth: int,
    ) -> None:
        raw = op.condition
        if not isinstance(raw, tuple):
            raise TranslationError(
                "UNSUPPORTED_CONDITION", "Expected bit/register equality."
            )
        target, value = raw
        bits = (
            (target,)
            if isinstance(target, Clbit)
            else tuple(target)
            if isinstance(target, ClassicalRegister)
            else ()
        )
        if not bits:
            raise TranslationError(
                "UNSUPPORTED_CONDITION", "Expected a classical bit or register."
            )
        refs = tuple(self.latest.get(cmap[circuit.find_bit(bit).index]) for bit in bits)
        for branch, block in enumerate(op.blocks):
            predicate = Predicate(refs, int(value), branch == 0)
            # Conditional measurements remain unsupported for constant guards too.
            combined = Guard((() if guard is None else guard.predicates) + (predicate,))
            self.visit(block, qubits, clbits, combined, depth + 1)
