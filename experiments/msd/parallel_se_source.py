"""Assemble independent W1 syndrome rounds in one physical source DAG."""

from dataclasses import dataclass

import qiskit.qasm3
from nadit_physical_compiler.frontend import loads_qasm
from nadit_physical_compiler.physical_ir import PhysicalDAG
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister

from modules.codes.rotated_surface import definition, get_component

from .standard import ExperimentWorld


@dataclass(frozen=True)
class JointSESource:
    """Immutable source and identity mapping for N SE instances on N W1 blocks.

    All other atoms remain spectators in the supplied complete world. Native
    children can share a source ID within one operation; measurement source IDs
    are globally distinct. A node owner of -1 denotes a serial-control barrier.
    """

    source_qasm: str
    dag: PhysicalDAG
    factory_indices: tuple[int, ...]
    atom_ids: tuple[int, ...]
    node_owners: tuple[int, ...]
    measurement_owners: tuple[tuple[int, int], ...]
    expected_results: int


def assemble_se(
    world: ExperimentWorld,
    factory_indices: tuple[int, ...],
    *,
    serial: bool = False,
) -> JointSESource:
    """Compose existing SE circuits with disjoint registers and explicit barriers.

    Args:
        world: The unchanged complete experiment world and standard device.
        factory_indices: Nonempty ordered selection of distinct factory indices.
        serial: Insert a barrier across selected blocks between invocations for
            a serial control. False keeps every source barrier local to its W1.
    Returns:
        One source DAG, explicit participant atom map, and immutable ownership.
    Raises:
        ValueError: If a factory selection or source/ownership invariant is invalid.
    """
    if (
        not factory_indices
        or any(
            type(index) is not int or not 0 <= index < world.spec.pipelines
            for index in factory_indices
        )
        or len(set(factory_indices)) != len(factory_indices)
    ):
        raise ValueError("Select distinct valid factory indices for at least one SE.")
    indices = tuple(factory_indices)
    code = definition(world.spec.distance)
    local = qiskit.qasm3.loads(
        get_component("se_round", world.spec.distance).source_qasm
    )
    if (local.num_qubits, local.num_clbits) != (code.atom_count, code.check_count):
        raise ValueError("SE source wire counts disagree with the factory code.")
    quantum = tuple(QuantumRegister(code.atom_count, f"q_f{i}") for i in indices)
    classical = tuple(ClassicalRegister(code.check_count, f"m_f{i}") for i in indices)
    combined = QuantumCircuit(*quantum, *classical)
    for position, (qubits, clbits) in enumerate(zip(quantum, classical, strict=True)):
        if serial and position:
            combined.barrier(*combined.qubits)
        combined.compose(local, qubits=qubits, clbits=clbits, inplace=True)
    source = qiskit.qasm3.dumps(combined)
    dag = loads_qasm(source)
    owners = []
    for node in dag.nodes:
        participants = {indices[q // code.atom_count] for q in node.qubits}
        if len(participants) == 1:
            owner = participants.pop()
        elif serial and node.name == "barrier" and participants == set(indices):
            owner = -1
        else:
            raise ValueError("SE source unexpectedly couples factory instances.")
        if any(indices[c // code.check_count] != owner for c in node.clbits):
            raise ValueError("SE classical wire crosses a factory boundary.")
        owners.append(owner)
    if not serial and any(owners[a] != owners[b] for a, b in dag.edges):
        raise ValueError("Joint SE source contains a cross-factory dependency.")
    measurements = tuple(
        (node.result.measurement_id, owner)
        for node, owner in zip(dag.nodes, owners, strict=True)
        if node.result is not None
    )
    expected_results = len(indices) * code.check_count
    if len(measurements) != expected_results or len(dict(measurements)) != len(
        measurements
    ):
        raise ValueError(
            "SE source does not retain distinct factory result identities."
        )
    return JointSESource(
        source,
        dag,
        indices,
        tuple(
            atom
            for index in indices
            for atom in world.patch(index, "W1").binding.atom_ids
        ),
        tuple(owners),
        measurements,
        expected_results,
    )
