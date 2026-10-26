"""Code-owned component sources for complete-world joint factory calibration."""

from dataclasses import dataclass
from functools import cache

import qiskit.qasm3
from qiskit import QuantumCircuit

from .components import SurfaceComponent, get_component
from .definition import definition
from .growth import GrowthComponent, injection_indices
from .transversal import TransversalCNOTComponent


@dataclass(frozen=True)
class FactoryComponentSource:
    """Source wires index the concatenated ordered participant atom bindings."""

    source_qasm: str
    wire_indices: tuple[int, ...]
    result_count: int


def _sequence(parts: list[str]) -> QuantumCircuit:
    circuits = [qiskit.qasm3.loads(source) for source in parts]
    result = QuantumCircuit(circuits[0].num_qubits, sum(c.num_clbits for c in circuits))
    offset = 0
    for index, circuit in enumerate(circuits):
        if index:
            result.barrier(*result.qubits)
        result.compose(
            circuit,
            qubits=result.qubits,
            clbits=result.clbits[offset : offset + circuit.num_clbits],
            inplace=True,
        )
        offset += circuit.num_clbits
    return result


@cache
def factory_component_source(component: str, distance: int) -> FactoryComponentSource:
    """Retain d3 injection, accepted-only growth, actual S and native recipe gates."""
    code = definition(distance)
    indices = tuple(range(code.atom_count))
    if component == "raw_t_postselection":
        parts = [
            SurfaceComponent("raw_t", 3).source_qasm,
            *[SurfaceComponent("se_round", 3).source_qasm] * 2,
        ]
        indices = injection_indices(distance)
    elif component.endswith("/canonicalize"):
        correction = QuantumCircuit(code.atom_count)
        for q in range(code.data_count):
            correction.y(q)
        parts = []
        if component == "raw_t_postselection/canonicalize" and distance > 3:
            parts = [
                GrowthComponent(distance).source_qasm,
                *[SurfaceComponent("se_round", distance).source_qasm] * (distance - 1),
            ]
        elif component not in (
            "raw_t_postselection/canonicalize",
            "initialize_plus/canonicalize",
        ):
            raise ValueError(f"Unsupported factory correction {component!r}")
        parts.append(qiskit.qasm3.dumps(correction))
    elif component == "transversal_cnot":
        parts = [TransversalCNOTComponent(distance).source_qasm]
        indices = tuple(range(2 * code.atom_count))
    else:
        parts = [get_component(component, distance).source_qasm]
    circuit = _sequence(parts)
    if circuit.num_qubits != len(indices):
        raise ValueError("Factory source and participant wire mapping disagree")
    return FactoryComponentSource(
        qiskit.qasm3.dumps(circuit), indices, circuit.num_clbits
    )
