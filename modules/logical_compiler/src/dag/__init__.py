"""Dependency construction for translated logical operations."""

from ..model import Operation


def build_edges(operations: tuple[Operation, ...]) -> tuple[tuple[int, int], ...]:
    """Construct wire, classical-write and immutable-result dependencies."""
    last_qubit: dict[int, int] = {}
    last_write: dict[int, int] = {}
    producers: dict[int, int] = {}
    edges: set[tuple[int, int]] = set()
    for index, op in enumerate(operations):
        for qubit in op.qubits:
            if qubit in last_qubit:
                edges.add((last_qubit[qubit], index))
            last_qubit[qubit] = index
        if op.guard:
            for result in op.guard.references:
                edges.add((producers[result], index))
        if op.result_id is not None:
            producers[op.result_id] = index
            for bit in op.clbits:
                if bit in last_write:
                    edges.add((last_write[bit], index))
                last_write[bit] = index
    return tuple(sorted(edges))
