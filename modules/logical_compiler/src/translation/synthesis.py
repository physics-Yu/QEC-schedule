"""Exact basis translation followed by independently checked RZ synthesis."""

from dataclasses import replace
from fractions import Fraction
from math import isfinite, pi

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit.equivalence_library import SessionEquivalenceLibrary
from qiskit.circuit.library import get_standard_gate_name_mapping
from qiskit.exceptions import QiskitError
from qiskit.quantum_info import Operator
from qiskit.synthesis.discrete_basis import gridsynth_rz
from qiskit.transpiler import PassManager
from qiskit.transpiler.passes import BasisTranslator

from ..model import Operation, SynthesisRecord, TranslationError

_GATES = get_standard_gate_name_mapping()
_MIN_LOCAL_ERROR = 1e-12
_PHASE_WORDS = {
    0: (),
    1: ("t",),
    2: ("s",),
    3: ("s", "t"),
    4: ("z",),
    5: ("z", "t"),
    6: ("sdg",),
    7: ("tdg",),
}


def _append_circuit(
    output: list[Operation], circuit: QuantumCircuit, source: Operation
) -> None:
    if circuit.global_phase:
        output.append(
            replace(
                source,
                name="global_phase",
                qubits=(),
                params=(float(circuit.global_phase),),
            )
        )
    for item in circuit.data:
        output.append(
            replace(
                source,
                name=item.operation.name,
                qubits=tuple(
                    source.qubits[circuit.find_bit(q).index] for q in item.qubits
                ),
                params=tuple(float(p) for p in item.operation.params),
            )
        )


def decompose(
    operations: tuple[Operation, ...], gates: tuple[str, ...], limit: int
) -> tuple[Operation, ...]:
    """Translate defined standard gates exactly into Clifford+RZ+T and CX.

    Unsupported decompositions and expansion overflows raise TranslationError.
    """
    basis = (*gates, "rz", "id")
    translator = PassManager(BasisTranslator(SessionEquivalenceLibrary, list(basis)))
    cache: dict[tuple[str, tuple[float, ...]], QuantumCircuit] = {}
    output: list[Operation] = []
    for op in operations:
        if not all(isfinite(p) for p in op.params):
            raise TranslationError(
                "NONFINITE_PARAMETER",
                f"Source {op.source_ids} has nonfinite parameters.",
            )
        if op.name in basis + (
            "initialize_0",
            "initialize_plus",
            "measure",
            "barrier",
            "global_phase",
        ):
            output.append(op)
        else:
            key = op.name, op.params
            if key not in cache:
                try:
                    gate = _GATES[op.name].to_mutable()
                    gate.params = list(op.params)
                    circuit = QuantumCircuit(len(op.qubits))
                    circuit.append(gate, range(len(op.qubits)))
                    cache[key] = translator.run(circuit)
                except (QiskitError, KeyError, ValueError) as error:
                    raise TranslationError(
                        "GATE_DECOMPOSITION",
                        f"Source {op.source_ids}, gate {op.name}: {error}",
                    ) from error
            _append_circuit(output, cache[key], op)
        if len(output) > limit:
            raise TranslationError(
                "EXPANSION_LIMIT", f"Decomposition exceeds {limit} operations."
            )
    return tuple(output)


def _exact_power(angle: float) -> int | None:
    power = Fraction(angle) / Fraction(pi / 4)
    return power.numerator if power.denominator == 1 else None


def _checked_rotation(angle: float, allowance: float) -> tuple[QuantumCircuit, float]:
    if allowance < _MIN_LOCAL_ERROR:
        raise TranslationError(
            "PRECISION_UNSUPPORTED",
            f"Local budget {allowance} is below the supported "
            f"double-precision floor {_MIN_LOCAL_ERROR}.",
        )
    approximation = gridsynth_rz(angle, allowance / 4)
    target = np.diag([np.exp(-0.5j * angle), np.exp(0.5j * angle)])
    measured = float(np.linalg.norm(Operator(approximation).data - target, 2))
    if not isfinite(measured) or measured > allowance:
        raise TranslationError(
            "SYNTHESIS_PRECISION_NOT_MET",
            f"RZ({angle}): measured error {measured}, budget {allowance}.",
        )
    return approximation, measured


def synthesize(
    operations: tuple[Operation, ...], error_budget: float, limit: int
) -> tuple[tuple[Operation, ...], tuple[SynthesisRecord, ...]]:
    """Synthesize arbitrary RZ angles within a total spectral-norm error budget.

    All branch occurrences count toward the conservative total. Numerical matrix
    checks include global phase. Synthesis and output limits fail explicitly.
    """
    count = sum(
        op.name == "rz" and _exact_power(op.params[0]) is None for op in operations
    )
    allowance = error_budget / max(1, count)
    cache: dict[float, tuple[QuantumCircuit, float]] = {}
    output: list[Operation] = []
    records: list[SynthesisRecord] = []
    for op in operations:
        if op.name != "rz":
            output.append(op)
        else:
            angle = op.params[0]
            power = _exact_power(angle)
            if power is not None:
                if angle:
                    output.append(
                        replace(
                            op, name="global_phase", qubits=(), params=(-angle / 2,)
                        )
                    )
                output.extend(
                    replace(op, name=name, params=())
                    for name in _PHASE_WORDS[power % 8]
                )
            else:
                if angle not in cache:
                    cache[angle] = _checked_rotation(angle, allowance)
                approximation, measured = cache[angle]
                _append_circuit(output, approximation, op)
                records.append(
                    SynthesisRecord(
                        op.source_ids,
                        angle,
                        allowance,
                        measured,
                        len(approximation.data),
                    )
                )
        if len(output) > limit:
            raise TranslationError(
                "EXPANSION_LIMIT", f"Synthesis exceeds {limit} operations."
            )
    return tuple(output), tuple(records)
