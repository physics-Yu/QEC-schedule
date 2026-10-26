"""Bounded independent channel witnesses at the two newly produced distances."""

import pytest
import stim

from modules.codes.rotated_surface import definition, get_component
from modules.codes.rotated_surface.tests.test_distance_components import (
    circuit,
    pauli,
    prepared,
)
from modules.codes.rotated_surface.transversal import TransversalCNOTComponent


@pytest.mark.parametrize("distance", (9, 11))
@pytest.mark.parametrize(
    "name", ("initialize_0", "initialize_plus", "prepare_y", "raw_t")
)
def test_preparation_preserves_declared_logical_state(distance, name):
    code = definition(distance)
    component = get_component(name, distance)
    axes = (
        ("X", "Y", "Z")
        if name == "raw_t"
        else ({"initialize_0": "Z", "initialize_plus": "X", "prepare_y": "Y"}[name],)
    )
    for basis in axes:
        sim = stim.TableauSimulator(seed=19)
        sim.do(circuit(component.source_qasm, seed_basis=basis))
        bits = dict(
            zip(
                component.description.measurements,
                sim.current_measurement_record(),
                strict=True,
            )
        )
        for term in component.correction_terms:
            if bits[term.measurement_port]:
                for role, axis in term.pauli_roles:
                    getattr(sim, axis.lower())(int(role[5:-1]))
        assert all(
            sim.peek_observable_expectation(pauli(code, b, qs)) == 1
            for b, qs in code.checks
        )
        x, z = pauli(code, "X", code.logical_x), pauli(code, "Z", code.logical_z)
        logical = x if basis == "X" else z if basis == "Z" else 1j * x * z
        assert sim.peek_observable_expectation(logical) == 1


@pytest.mark.parametrize("distance", (9, 11))
@pytest.mark.parametrize("name", ("logical_s", "logical_sdag"))
def test_actual_fold_s_action_with_known_nonzero_sector(distance, name):
    code = definition(distance)
    component = get_component(name, distance)
    source = circuit(component.source_qasm)
    x, z = pauli(code, "X", code.logical_x), pauli(code, "Z", code.logical_z)
    y = 1j * x * z
    for signs in ((0,) * code.check_count, (1,) + (0,) * (code.check_count - 1)):
        for before, after in ((x, y), (y, -x), (z, z)):
            if name == "logical_sdag" and before != z:
                after = -after
            sim = prepared(code, before, signs)
            sim.do(source)
            assert sim.peek_observable_expectation(after) == 1
            bits = dict(
                zip(
                    component.description.measurements,
                    sim.current_measurement_record(),
                    strict=True,
                )
            )
            for (basis, support), (_, parity) in zip(
                code.checks, component.output_syndrome_parities, strict=True
            ):
                assert sim.peek_observable_expectation(pauli(code, basis, support)) == (
                    -1
                ) ** (sum(bits[p] for p in parity) % 2)


@pytest.mark.parametrize("distance", (9, 11))
def test_cnot_maps_both_logical_paulis(distance):
    code = definition(distance)
    unitary = circuit(TransversalCNOTComponent(distance).source_qasm).to_tableau()
    for basis, support, first, second in (
        ("X", code.logical_x, 0, code.atom_count),
        ("Z", code.logical_z, code.atom_count, 0),
    ):
        before = stim.PauliString(2 * code.atom_count)
        for q in support:
            before[first + q] = basis
        expected = before.copy()
        for q in support:
            expected[second + q] = basis
        assert unitary(before) == expected
