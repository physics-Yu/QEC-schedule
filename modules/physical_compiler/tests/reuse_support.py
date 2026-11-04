"""Maximum reuse matching across disjoint CZ layers."""

from nadit_physical_compiler.contracts import GateLayer
from nadit_physical_compiler.physical_ir import PhysicalDAG, PhysicalOperation

type Pairs = tuple[tuple[int, int], ...]


def _circuit(
    current: Pairs, following: Pairs
) -> tuple[PhysicalDAG, GateLayer, GateLayer]:
    pairs = current + following
    num_qubits = max((qubit for pair in pairs for qubit in pair), default=-1) + 1
    dag = PhysicalDAG(
        num_qubits,
        0,
        tuple(
            PhysicalOperation(index, "cz", pair, (), ())
            for index, pair in enumerate(pairs)
        ),
        (),
    )
    return (
        dag,
        GateLayer(tuple(range(len(current)))),
        GateLayer(tuple(range(len(current), len(pairs)))),
    )
