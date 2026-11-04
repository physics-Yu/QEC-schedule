"""Independently compare coherent and adaptive-QFT output distributions.

The coherent reference uses Qiskit's unitary statevector. The semiclassical
reference enumerates every measurement branch with explicit NumPy amplitudes,
removing measured qubits only when no later quantum action addresses them.
This checks the counting-register marginal, not the final arithmetic register.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from qiskit import qasm3
from qiskit.quantum_info import Statevector

ROOT = Path(__file__).resolve().parent
COHERENT = ROOT.parents[1] / "small_circuit/shor/inputs"
BUILD = ROOT / "build"


def coherent_distribution(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    """Read QASM and obtain the exact terminal counting-register marginal."""
    circuit = qasm3.loads(path.read_text(encoding="utf-8"))
    unitary = circuit.copy_empty_like()
    mapping: dict[int, int] = {}
    started = measured = False
    for item in circuit.data:
        name = item.operation.name
        if name == "reset":
            if started:
                raise ValueError("The coherent reference expects leading resets.")
            continue
        if name == "barrier":
            continue
        if name == "measure":
            measured = True
            bit = circuit.find_bit(item.clbits[0]).index
            mapping[bit] = circuit.find_bit(item.qubits[0]).index
            continue
        if measured:
            raise ValueError("The coherent reference requires terminal measurements.")
        started = True
        unitary.append(item.operation, item.qubits)
    if sorted(mapping) != list(range(circuit.num_clbits)):
        raise ValueError("Every output bit must have exactly one measurement.")
    vector = Statevector.from_instruction(unitary).data
    indices = np.arange(vector.size, dtype=np.uint64)
    output = np.zeros(vector.size, dtype=np.int64)
    for bit, qubit in mapping.items():
        output |= (((indices >> qubit) & 1) << bit).astype(np.int64)
    distribution = np.bincount(
        output, weights=np.abs(vector) ** 2, minlength=1 << circuit.num_clbits
    )
    return distribution, {
        "num_qubits": circuit.num_qubits,
        "num_bits": circuit.num_clbits,
        "coherent_operation_counts": dict(circuit.count_ops()),
        "measurement_qubit_by_bit": {str(k): v for k, v in mapping.items()},
    }


def adaptive_operations(path: Path) -> tuple[list[dict[str, Any]], int, int]:
    """Import QASM control flow independently of the physical-compiler parser."""
    circuit = qasm3.loads(path.read_text(encoding="utf-8"))
    operations: list[dict[str, Any]] = []

    def flatten(block, qmap, cmap, guard=None):
        for item in block.data:
            op = item.operation
            qubits = [qmap[block.find_bit(q).index] for q in item.qubits]
            bits = [cmap[block.find_bit(b).index] for b in item.clbits]
            if op.name == "if_else":
                if guard is not None or len(op.blocks) > 1:
                    raise ValueError(
                        "Only single-bit if blocks without else are expected."
                    )
                condition_bit, value = op.condition
                bit = cmap[block.find_bit(condition_bit).index]
                flatten(op.blocks[0], qubits, bits, (bit, int(value)))
            else:
                record = {
                    "name": op.name,
                    "qubits": qubits,
                    "bits": bits,
                    "guard": guard,
                }
                if op.name not in ("barrier", "measure", "reset"):
                    record["matrix"] = np.asarray(op.to_matrix(), dtype=complex)
                operations.append(record)

    flatten(circuit, list(range(circuit.num_qubits)), list(range(circuit.num_clbits)))
    return operations, circuit.num_qubits, circuit.num_clbits


def apply_matrix(
    vector: np.ndarray, wires: list[int], matrix: np.ndarray
) -> np.ndarray:
    """Apply a small dense gate with explicit little-endian index arithmetic."""
    indices = np.arange(vector.size)
    mask = sum(1 << wire for wire in wires)
    bases = indices[(indices & mask) == 0]
    blocks = np.stack(
        [
            bases | sum(((state >> j) & 1) << wire for j, wire in enumerate(wires))
            for state in range(1 << len(wires))
        ]
    )
    result = vector.copy()
    result[blocks] = matrix @ vector[blocks]
    return result


def adaptive_distribution(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    """Enumerate all Born branches, including low-probability outcomes."""
    operations, nq, nb = adaptive_operations(path)
    vector = np.zeros(1 << nq, dtype=complex)
    vector[0] = 1
    branches = [(vector, list(range(nq)), 0)]
    known_bits: set[int] = set()
    started = False
    for index, op in enumerate(operations):
        name = op["name"]
        if name == "barrier":
            continue
        if name == "reset":
            if started:
                raise ValueError("Only leading initialization resets are supported.")
            continue
        started = True
        if name == "measure":
            qubit, bit = op["qubits"][0], op["bits"][0]
            if bit in known_bits:
                raise ValueError("An output bit is written twice.")
            if any(
                qubit in later["qubits"]
                for later in operations[index + 1 :]
                if later["name"] != "barrier"
            ):
                raise ValueError("A measured qubit is addressed again.")
            following = []
            for state, active, output in branches:
                wire = active.index(qubit)
                remaining = [q for q in active if q != qubit]
                indices = np.arange(state.size)
                for value in (0, 1):
                    projected = state[((indices >> wire) & 1) == value]
                    # Do not renormalize: squared norm is the joint branch probability.
                    if np.any(projected):
                        following.append(
                            (projected, remaining, output | (value << bit))
                        )
            branches = following
            known_bits.add(bit)
        else:
            guard = op["guard"]
            if guard is not None and guard[0] not in known_bits:
                raise ValueError("A conditional gate reads an unavailable output bit.")
            following = []
            for state, active, output in branches:
                if guard is None or ((output >> guard[0]) & 1) == guard[1]:
                    state = apply_matrix(
                        state, [active.index(q) for q in op["qubits"]], op["matrix"]
                    )
                following.append((state, active, output))
            branches = following
    if known_bits != set(range(nb)):
        raise ValueError("Not every output bit was measured.")
    distribution = np.zeros(1 << nb)
    for state, _, output in branches:
        distribution[output] += float(np.vdot(state, state).real)
    return distribution, {
        "enumerated_nonzero_branches": len(branches),
        "semiclassical_operation_counts": dict(
            Counter(op["name"] for op in operations)
        ),
        "conditional_phase_count": sum(op["guard"] is not None for op in operations),
    }


def order_distribution(bits: int, order: int) -> np.ndarray:
    """Construct the finite-register order-finding formula independently."""
    size = 1 << bits
    y = np.arange(size)
    probabilities = np.zeros(size)
    for remainder in range(order):
        positions = np.arange(remainder, size, order)
        sums = np.exp(2j * np.pi * np.outer(y, positions) / size).sum(axis=1)
        probabilities += np.abs(sums) ** 2 / size**2
    return probabilities


def check(n: int, coherent: Path, adaptive: Path) -> dict[str, Any]:
    """Compare full marginals and record their source hashes and probabilities."""
    reference, metadata = coherent_distribution(coherent)
    derived, adaptive_metadata = adaptive_distribution(adaptive)
    maximum_error = float(np.max(np.abs(reference - derived)))
    if maximum_error >= 1e-10 or abs(float(reference.sum()) - 1) >= 1e-10:
        raise AssertionError((n, maximum_error, reference.sum(), derived.sum()))
    formula = order_distribution(metadata["num_bits"], 4 if n == 15 else 6)
    formula_error = float(np.max(np.abs(reference - formula)))
    return {
        "n": n,
        "coherent_source": coherent.name,
        "semiclassical_source": adaptive.name,
        "coherent_sha256": hashlib.sha256(coherent.read_bytes()).hexdigest(),
        "semiclassical_sha256": hashlib.sha256(adaptive.read_bytes()).hexdigest(),
        **metadata,
        **adaptive_metadata,
        "coherent_vs_semiclassical_max_absolute_error": maximum_error,
        "coherent_probability_sum": float(reference.sum()),
        "semiclassical_probability_sum": float(derived.sum()),
        "finite_register_order_formula_max_absolute_error": formula_error,
        "matches_order_formula": formula_error < 1e-10,
        "output_convention": "b[0] is LSB; bitstring is b[m-1]...b[0]",
        "ideal_probabilities": {
            format(i, f"0{metadata['num_bits']}b"): float(p)
            for i, p in enumerate(reference)
        },
    }


def main() -> None:
    """Write one reproducible exact-distribution evidence report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coherent-dir", type=Path, default=COHERENT)
    parser.add_argument(
        "--semiclassical-dir", type=Path, default=BUILD / "semiclassical"
    )
    args = parser.parse_args()
    results = [
        check(
            n, args.coherent_dir / f"n{n}.qasm3", args.semiclassical_dir / f"n{n}.qasm3"
        )
        for n in (15, 21)
    ]
    report = {
        "schema": "nadit.simplified-shor-reference/1",
        "scope": "Exact counting-register marginal equivalence only; no final-A residue claim; no noise calibration claim.",
        "circuits": results,
    }
    target = BUILD / "reference-report.json"
    target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for item in results:
        print(json.dumps({k: v for k, v in item.items() if k != "ideal_probabilities"}))
    print(target)


if __name__ == "__main__":
    main()
