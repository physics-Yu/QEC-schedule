"""Independent checks of multi-factory SE source identity and dependencies."""

from collections import Counter

import pytest
import qiskit.qasm3
import stim

from experiments.msd.parallel_se_source import assemble_se
from experiments.msd.standard import ExperimentSpec, build_world
from modules.codes.rotated_surface import definition, get_component


def _clifford_source(source, *, unitary_only=True):
    """Parse source independently, retaining nonunitaries when requested."""
    parsed = qiskit.qasm3.loads(source)
    circuit = stim.Circuit(f"I {parsed.num_qubits - 1}")
    names = {"h": "H", "cx": "CX"}
    if not unitary_only:
        names |= {"reset": "R", "measure": "M"}
    for item in parsed.data:
        if item.operation.name in names:
            circuit.append(
                names[item.operation.name],
                [parsed.find_bit(q).index for q in item.qubits],
            )
        else:
            assert item.operation.name in ("barrier", "reset", "measure")
    return circuit


@pytest.mark.parametrize(
    "distance,indices", ((3, (0,)), (3, (0, 1, 2, 3)), (5, (3, 1)), (7, (0, 1)))
)
def test_joint_instances_keep_disjoint_wires_results_and_local_barriers(
    distance, indices
):
    world = build_world(ExperimentSpec(distance, 4))
    original_state = world.state
    assembled = assemble_se(world, indices)
    code, dag = definition(distance), assembled.dag
    assert world.state == original_state
    assert assembled.factory_indices == indices
    assert assembled.atom_ids == tuple(
        atom for i in indices for atom in world.patch(i, "W1").binding.atom_ids
    )
    assert len(assembled.atom_ids) == dag.num_qubits == len(indices) * code.atom_count
    assert (
        assembled.expected_results == dag.num_clbits == len(indices) * code.check_count
    )
    assert set(assembled.node_owners) == set(indices)
    assert all(
        assembled.node_owners[a] == assembled.node_owners[b] for a, b in dag.edges
    )
    for node, owner in zip(dag.nodes, assembled.node_owners, strict=True):
        local_index = indices.index(owner)
        assert all(q // code.atom_count == local_index for q in node.qubits)
        if node.name == "barrier":
            assert node.qubits == tuple(
                range(
                    local_index * code.atom_count, (local_index + 1) * code.atom_count
                )
            )
    results = [
        (n.result.measurement_id, owner)
        for n, owner in zip(dag.nodes, assembled.node_owners, strict=True)
        if n.result is not None
    ]
    assert assembled.measurement_owners == tuple(results)
    assert len({mid for mid, _ in results}) == assembled.expected_results
    assert Counter(owner for _, owner in results) == {
        i: code.check_count for i in indices
    }
    # Native children share source IDs only within their own source operation.
    source_owner = {}
    for node, owner in zip(dag.nodes, assembled.node_owners, strict=True):
        assert source_owner.setdefault(node.source_id, owner) == owner
    predecessors = {b for _, b in dag.edges}
    roots = [n for n in dag.nodes if n.id not in predecessors]
    assert len(roots) == len(indices) * code.check_count
    assert all(n.name == "reset" for n in roots)
    assert Counter(assembled.node_owners[n.id] for n in roots) == {
        i: code.check_count for i in indices
    }


@pytest.mark.parametrize("serial", (False, True))
def test_composition_is_exact_tensor_product_clifford_and_preserves_all_measurements(
    serial,
):
    world = build_world(ExperimentSpec(5, 4))
    indices = (2, 0, 3)
    assembled = assemble_se(world, indices, serial=serial)
    code = definition(5)
    local = _clifford_source(get_component("se_round", 5).source_qasm).to_tableau()
    expected = local + local + local
    assert _clifford_source(assembled.source_qasm).to_tableau() == expected
    if serial:
        shared = [
            n
            for n, owner in zip(assembled.dag.nodes, assembled.node_owners, strict=True)
            if owner == -1
        ]
        assert len(shared) == len(indices) - 1
        assert all(
            n.name == "barrier" and len(n.qubits) == 3 * code.atom_count for n in shared
        )
        predecessors = {b for _, b in assembled.dag.edges}
        roots = [n for n in assembled.dag.nodes if n.id not in predecessors]
        assert len(roots) == code.check_count
        assert all(assembled.node_owners[n.id] == indices[0] for n in roots)


@pytest.mark.parametrize("indices", ((), (0, 0), (-1,), (4,), (True,), (0.0,)))
def test_invalid_factory_selection_rejected(indices):
    world = build_world(ExperimentSpec(3, 4))
    with pytest.raises(ValueError, match="factory"):
        assemble_se(world, indices)


@pytest.mark.parametrize("distance", (3, 5))
def test_each_factory_measurement_and_logical_state_remain_independent(distance):
    world = build_world(ExperimentSpec(distance, 4))
    assembled = assemble_se(world, (3, 1, 2))
    code = definition(distance)
    total = assembled.dag.num_qubits
    generators, expected_bits, logicals = [], [], []

    def pauli(position, basis, support):
        result = stim.PauliString(total)
        for q in support:
            result[position * code.atom_count + q] = basis
        return result

    for position in range(3):
        signs = tuple(int(i == position) for i in range(code.check_count))
        expected_bits.extend(signs)
        generators.extend(
            (-1) ** bit * pauli(position, basis, support)
            for bit, (basis, support) in zip(signs, code.checks, strict=True)
        )
        x, z = (
            pauli(position, "X", code.logical_x),
            pauli(position, "Z", code.logical_z),
        )
        logical = (x, 1j * x * z, z)[position]
        logicals.append(logical)
        generators.append(logical)
        generators.extend(
            pauli(position, "Z", (q,)) for q in range(code.data_count, code.atom_count)
        )
    simulator = stim.TableauSimulator(seed=7)
    simulator.set_inverse_tableau(stim.Tableau.from_stabilizers(generators).inverse())
    simulator.do(_clifford_source(assembled.source_qasm, unitary_only=False))
    assert simulator.current_measurement_record() == expected_bits
    assert all(
        simulator.peek_observable_expectation(logical) == 1 for logical in logicals
    )
    for position in range(3):
        for check_index, (basis, support) in enumerate(code.checks):
            assert simulator.peek_observable_expectation(
                pauli(position, basis, support)
            ) == (-1 if check_index == position else 1)
