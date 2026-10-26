"""Select a concrete code before parsing and translate to a logical DAG."""

from dataclasses import replace
from hashlib import sha256
from math import isfinite
from pathlib import Path

import qiskit

from modules.codes.registry import get_entry

from .dag import build_edges
from .frontend.qasm import parse_qasm
from .model import Operation, TranslationError, TranslationResult
from .translation.optimize import simplify
from .translation.synthesis import decompose, synthesize


def loads_qasm(
    source: str,
    *,
    code: str,
    scheme: str = "clifford_t",
    error_budget: float = 1e-6,
    input_state: str = "zero",
    max_operations: int = 100_000,
) -> TranslationResult:
    """Translate QASM to code-selected logical operations and dependencies.

    Args:
        source: QASM 2/3 source in the documented finite-circuit profile.
        code: Required concrete-code identifier; there is no default code.
        scheme: Scheme declared by that code.
        error_budget: Total synthesis tolerance in spectral operator norm.
        input_state: 'zero' initializes logical inputs; 'external' preserves
            arbitrary input states and emits no implicit initialization.
        max_operations: Positive bound on source expansion and output size.

    Returns:
        Logical operations, component references, DAG and synthesis evidence.

    Raises:
        TranslationError: For unsupported sources, code/scheme selection,
            resource/precision limits or failed approximation verification.
    """
    try:
        entry = get_entry(code, scheme)
    except ValueError as error:
        label, _, detail = str(error).partition(": ")
        raise TranslationError(label, detail) from error
    if not isfinite(error_budget) or not 0 < error_budget <= 1:
        raise TranslationError(
            "ERROR_BUDGET", "Expected a finite error budget in (0, 1]."
        )
    if input_state not in ("zero", "external"):
        raise TranslationError("INPUT_STATE", "Expected 'zero' or 'external'.")
    if (
        isinstance(max_operations, bool)
        or not isinstance(max_operations, int)
        or max_operations < 1
    ):
        raise TranslationError(
            "EXPANSION_LIMIT", "max_operations must be a positive integer."
        )
    parsed = parse_qasm(source, max_operations)
    initializers = (
        tuple(Operation("initialize_0", (q,)) for q in range(parsed.num_qubits))
        if input_state == "zero"
        else ()
    )
    operations = simplify(initializers + parsed.operations)
    operations = simplify(decompose(operations, entry.gates, max_operations))
    operations, evidence = synthesize(operations, error_budget, max_operations)
    operations = simplify(operations)
    targets = entry.gates + entry.initializers + ("measure", "barrier", "global_phase")
    if any(op.name not in targets for op in operations):
        raise TranslationError(
            "TARGET_GATE_SET", "Synthesis returned an undeclared operation."
        )
    bound = tuple(
        replace(op, component=entry.component_for(op.name)) for op in operations
    )
    return TranslationResult(
        code=entry.code,
        scheme=entry.scheme,
        num_qubits=parsed.num_qubits,
        num_clbits=parsed.num_clbits,
        operations=bound,
        edges=build_edges(bound),
        target_operations=targets,
        error_budget=error_budget,
        synthesis=evidence,
        input_state=input_state,
        source_sha256=sha256(source.encode("utf-8")).hexdigest(),
        qiskit_version=qiskit.__version__,
        quantum_registers=parsed.quantum_registers,
        classical_registers=parsed.classical_registers,
    )


def load_qasm(
    path: str | Path,
    *,
    code: str,
    scheme: str = "clifford_t",
    error_budget: float = 1e-6,
    input_state: str = "zero",
    max_operations: int = 100_000,
) -> TranslationResult:
    """Read a UTF-8 QASM file and translate using loads_qasm's explicit options.

    Raises OSError for file access and TranslationError for translation failures.
    """
    return loads_qasm(
        Path(path).read_text(encoding="utf-8-sig"),
        code=code,
        scheme=scheme,
        error_budget=error_budget,
        input_state=input_state,
        max_operations=max_operations,
    )
