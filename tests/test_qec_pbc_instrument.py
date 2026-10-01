"""Verify lowered parity instruments against dense signed Pauli projectors.

The reference uses arbitrary complex inputs and explicit matrices, rather than
the project's stabilizer simulator or a reconstruction of the parity gadget.
Every native measurement branch is checked, including untouched spectators.
"""

from math import sqrt

import pytest

from neutral_atom_experiments.qec_pbc.ir import PBCProgram, PauliMeasurement, Role
from neutral_atom_experiments.qec_pbc.lowering import lower_to_physical
from neutral_atom_experiments.qec_pbc.pauli import PauliProduct


_PAULI = {
    "I": ((1, 0), (0, 1)),
    "X": ((0, 1), (1, 0)),
    "Z": ((1, 0), (0, -1)),
}
_SINGLE_GATES = {
    **_PAULI,
    "H": ((1 / sqrt(2), 1 / sqrt(2)), (1 / sqrt(2), -1 / sqrt(2))),
}


def _matrix_vector(matrix, vector):
    return [sum(entry * amplitude for entry, amplitude in zip(row, vector)) for row in matrix]


def _kron(left, right):
    return [
        [entry * local_entry for entry in row for local_entry in local_row]
        for row in left
        for local_row in right
    ]


def _signed_pauli_matrix(observable, data_roles):
    # The first role is the least significant computational basis bit.
    factors = dict(observable.factors)
    matrix = [[observable.sign]]
    for role in reversed(data_roles):
        matrix = _kron(matrix, _PAULI[factors.get(role, "I")])
    return matrix


def _norm_squared(state):
    return sum(abs(amplitude) ** 2 for amplitude in state)


def _complex_input(data_count):
    state = [complex(1 + (7 * index) % 11, (5 * index) % 13 - 6) for index in range(1 << data_count)]
    norm = sqrt(_norm_squared(state))
    return [amplitude / norm for amplitude in state]


def _native_unitary(gate, physical_indices, qubit_count):
    dimension = 1 << qubit_count
    matrix = [[0j] * dimension for _ in range(dimension)]
    targets = [physical_indices[physical_id] for physical_id in gate.qubit_ids]
    if gate.gate_type == "CZ":
        first, second = targets
        for index in range(dimension):
            matrix[index][index] = -1 if ((index >> first) & 1) and ((index >> second) & 1) else 1
    else:
        assert gate.gate_type in {"H", "X", "Z"}
        target = targets[0]
        mask = 1 << target
        local = _SINGLE_GATES[gate.gate_type]
        for column in range(dimension):
            input_bit = (column >> target) & 1
            for output_bit in (0, 1):
                row = (column & ~mask) | (output_bit << target)
                matrix[row][column] = local[output_bit][input_bit]
    return matrix


def _reset_computational_qubit(state, target):
    """Apply reset when the input qubit has a definite computational bit.

    Both the initial ancilla and each measured branch meet this condition.
    Rejecting other inputs avoids replacing a mixed reset output by a pure one.
    """

    mask = 1 << target
    probabilities = [sum(abs(amplitude) ** 2 for index, amplitude in enumerate(state)
                         if bool(index & mask) == bool(bit)) for bit in (0, 1)]
    assert min(probabilities) < 1e-14
    if probabilities[1] < 1e-14:
        return state[:]
    result = [0j] * len(state)
    for index, amplitude in enumerate(state):
        if index & mask:
            result[index ^ mask] = amplitude
    return result


def _simulate_native_branches(compiled, data_state, data_roles, bindings):
    physical_indices = {bindings[role]: index for index, role in enumerate((*data_roles, "ancilla"))}
    qubit_count = len(data_roles) + 1
    # Start in |1> so the emitted initialization RESET is necessary.
    branches = [({}, [0j] * len(data_state) + data_state[:])]
    for gate in compiled.circuit.gates:
        assert not gate.condition
        assert gate.gate_type in {"H", "X", "Z", "CZ", "RESET", "MEASURE"}
        if gate.gate_type == "MEASURE":
            target = physical_indices[gate.qubit_ids[0]]
            next_branches = []
            for outcomes, state in branches:
                for bit in (0, 1):
                    collapsed = [amplitude if ((index >> target) & 1) == bit else 0j
                                 for index, amplitude in enumerate(state)]
                    next_branches.append(({**outcomes, gate.id: bit}, collapsed))
            branches = next_branches
        elif gate.gate_type == "RESET":
            target = physical_indices[gate.qubit_ids[0]]
            branches = [(outcomes, _reset_computational_qubit(state, target)) for outcomes, state in branches]
        else:
            matrix = _native_unitary(gate, physical_indices, qubit_count)
            branches = [(outcomes, _matrix_vector(matrix, state)) for outcomes, state in branches]
    return branches


def _density_matrix(state):
    return [[left * right.conjugate() for right in state] for left in state]


def _assert_instrument(observable, data_roles, coupling_order):
    roles = tuple(Role(role, "data") for role in data_roles) + (Role("ancilla", "parity_ancilla"),)
    program = PBCProgram(roles, (PauliMeasurement("parity", observable, "ancilla", coupling_order),))
    # Deliberately bind role order to nonmonotonic physical IDs.
    bindings = {role: f"Q{20 - 3 * index:03d}" for index, role in enumerate((*data_roles, "ancilla"))}
    compiled = lower_to_physical(program, bindings)
    input_state = _complex_input(len(data_roles))
    pauli_state = _matrix_vector(_signed_pauli_matrix(observable, data_roles), input_state)
    branches = _simulate_native_branches(compiled, input_state, data_roles, bindings)
    assert len(branches) == 2
    seen_semantic_bits = set()
    probabilities = []

    for raw_outcomes, native_state in branches:
        semantic_bit = compiled.semantic_results(raw_outcomes)["parity"]
        seen_semantic_bits.add(semantic_bit)
        eigenvalue = (-1) ** semantic_bit
        projected = [(amplitude + eigenvalue * transformed) / 2
                     for amplitude, transformed in zip(input_state, pauli_state)]
        expected_probability = _norm_squared(projected)
        native_probability = _norm_squared(native_state)
        assert 0.01 < expected_probability < 0.99
        assert native_probability == pytest.approx(expected_probability, abs=1e-12)
        probabilities.append(native_probability)

        # Release RESET leaves the ancilla in |0>; retaining the full data
        # vector includes correlations with spectators in the comparison.
        data_dimension = len(input_state)
        assert sum(abs(amplitude) ** 2 for amplitude in native_state[data_dimension:]) < 1e-14
        actual_data = [amplitude / sqrt(native_probability) for amplitude in native_state[:data_dimension]]
        expected_data = [amplitude / sqrt(expected_probability) for amplitude in projected]
        actual_density = _density_matrix(actual_data)
        expected_density = _density_matrix(expected_data)
        for actual_row, expected_row in zip(actual_density, expected_density):
            assert actual_row == pytest.approx(expected_row, abs=1e-12)

        raw_bit = next(iter(raw_outcomes.values()))
        assert semantic_bit == raw_bit ^ int(observable.sign == -1)

    assert seen_semantic_bits == {0, 1}
    assert sum(probabilities) == pytest.approx(1, abs=1e-12)
    return input_state


@pytest.mark.parametrize("sign", (-1, 1))
@pytest.mark.parametrize("coupling_order", (("data0", "data1", "data2"), ("data2", "data0", "data1")))
def test_three_factor_instrument_preserves_an_entangled_spectator(sign, coupling_order):
    observable = PauliProduct((("data0", "X"), ("data1", "Z"), ("data2", "X")), sign)
    state = _assert_instrument(observable, ("data0", "data1", "data2", "spectator"), coupling_order)

    # The spectator is not in a product state with the measured data.
    half = len(state) // 2
    spectator_density = [[sum(state[index + row * half] * state[index + column * half].conjugate()
                              for index in range(half)) for column in (0, 1)] for row in (0, 1)]
    purity = sum(abs(entry) ** 2 for row in spectator_density for entry in row)
    assert purity < 1 - 1e-6


@pytest.mark.parametrize("basis", ("X", "Z"))
@pytest.mark.parametrize("sign", (-1, 1))
def test_single_factor_instrument_has_both_nonzero_signed_branches(basis, sign):
    observable = PauliProduct((("data0", basis),), sign)
    _assert_instrument(observable, ("data0", "spectator"), ("data0",))
