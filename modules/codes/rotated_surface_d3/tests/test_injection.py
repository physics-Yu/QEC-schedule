"""Real non-Clifford raw-T injection, local acceptance, and canonical relations."""

from dataclasses import replace
from itertools import product
from math import sqrt

import numpy as np
import pytest
from nadit_physical_compiler.atom_ir import CZPulse
from nadit_physical_compiler.device import Position

from modules.codes.rotated_surface_d3.components.injection import RawTComponent
from modules.codes.rotated_surface_d3.definition import CHECKS, REFERENCE_HOMES
from modules.codes.rotated_surface_d3.tests.dense_quantum import (
    action_state,
    apply_pauli,
    data_branch,
    expectation,
    source_state,
)
from modules.codes.rotated_surface_d3.tests.test_components import (  # pytest fixture export
    device as device,  # noqa: PLC0414
)
from modules.codes.rotated_surface_d3.tests.test_components import expand


@pytest.fixture(scope="module")
def raw_template(device):
    return RawTComponent().compile(
        device,
        home_sites=REFERENCE_HOMES,
        origin=Position(0, 0),
        aod_id="transport",
    )


def test_actual_t_matrix_is_not_a_clifford_proxy():
    output = source_state('OPENQASM 3.0; include "stdgates.inc"; qubit q; h q; t q;')
    assert np.allclose(output.vector, np.array([1, np.exp(1j * np.pi / 4)]) / sqrt(2))
    assert expectation(output.vector, ((0, "X"),)) == pytest.approx(1 / sqrt(2))
    assert expectation(output.vector, ((0, "Y"),)) == pytest.approx(1 / sqrt(2))


def test_raw_t_protocol_is_center_seed_and_original_nz_round(raw_template):
    from modules.codes.rotated_surface_d3.components.circuits import source_qasm

    component = RawTComponent()
    source = component.source_qasm
    assert component.name == "raw_t"
    assert source.splitlines().count("t q[4];") == 1
    assert source.count("reset q[") == 17
    assert source.count("cx ") == 24
    assert source.count("= measure") == 8
    se = source_qasm("se_round")
    assert source[source.index("reset q[9];") :] == se[se.index("reset q[9];") :]
    assert raw_template.expected_ideal_values == (0, None, None, 0, 0, None, None, 0)
    assert component.description.entry_requirements
    assert component.description.exit_guarantees
    assert len(raw_template.correction_terms) == 4
    with pytest.raises(ValueError):
        RawTComponent(name="unapproved_injection")


def test_acceptance_only_checks_four_boundaries():
    component = RawTComponent()
    ports = component.description.measurements
    assert component.acceptance_ports == ("X0", "X3", "Z0", "Z3")
    # This evaluates only the declared local predicate, not any noise or decoder.
    for bits in product((0, 1), repeat=4):
        values = dict(zip(ports, (0, *bits[:2], 0, 0, *bits[2:], 0), strict=True))
        assert all(values[port] == 0 for port in component.acceptance_ports)
        for bad in component.acceptance_ports:
            changed = values | {bad: 1}
            assert not all(changed[port] == 0 for port in component.acceptance_ports)


def test_bound_acceptance_and_pending_result_isolation(raw_template, device):
    first = expand(raw_template, device, invocation="first", base=800, start=1500)
    second = expand(
        raw_template,
        device,
        invocation="second",
        base=900,
        start=2500,
        ids=tuple(range(200, 217)),
    )
    assert first.acceptance_status == second.acceptance_status == "pending"
    ports = {result.port: result for result in first.measurements}
    assert first.acceptance_conditions == tuple(
        (ports[port].result, 0) for port in RawTComponent.acceptance_ports
    )
    assert first.exit_binding is not None
    assert first.exit_binding.atom_ids == first.wire_atoms
    assert first.exit_binding.origin == Position(0, 0)
    for port in RawTComponent.acceptance_ports:
        assert ports[port].available_at_us >= first.start_us
    for a, b in zip(first.measurements, second.measurements, strict=True):
        assert b.available_at_us - a.available_at_us == pytest.approx(1000)
        assert a.result != b.result
        assert b.atom_id == a.atom_id + 200
    for a, b in zip(
        first.correction_relations, second.correction_relations, strict=True
    ):
        assert b.pauli_atoms == tuple(
            (atom + 200, axis) for atom, axis in a.pauli_atoms
        )
    partial = first.with_results({ports["X0"].result.measurement_id: 0})
    assert partial.acceptance_status == "pending"
    for port in RawTComponent.acceptance_ports:
        bad = first.with_results({ports[port].result.measurement_id: 1})
        assert bad.acceptance_status == "rejected"
    boundaries_only = first.with_results(
        {
            ports[port].result.measurement_id: 0
            for port in RawTComponent.acceptance_ports
        }
    )
    assert boundaries_only.acceptance_status == "accepted"
    assert sum(result.value is None for result in boundaries_only.measurements) == 4
    for bits in product((0, 1), repeat=4):
        values = (0, *bits[:2], 0, 0, *bits[2:], 0)
        resolved = first.with_results(
            {
                result.result.measurement_id: value
                for result, value in zip(first.measurements, values, strict=True)
            }
        )
        assert resolved.acceptance_status == "accepted"
        assert resolved.correction_relations == first.correction_relations
        assert resolved.program is first.program
    assert all(
        result.value is None for result in first.measurements + second.measurements
    )
    assert first.acceptance_status == second.acceptance_status == "pending"
    assert raw_template.acceptance_ports == RawTComponent.acceptance_ports


def test_all_16_raw_t_branches_match_actual_atoms(raw_template, device):
    component = RawTComponent()
    expansion = expand(raw_template, device, invocation="raw-t", base=800, start=2500)
    assert expansion.exit_state == expansion.entry_state
    assert len(expansion.measurements) == 8
    assert all(result.value is None for result in expansion.measurements)
    assert all(result.available_at_us >= 2500 for result in expansion.measurements)
    source = source_state(component.source_qasm)
    actual = action_state(expansion, device)
    assert abs(np.vdot(source.vector, actual.vector)) == pytest.approx(1, abs=1e-10)
    total = 0.0
    for bits in product((0, 1), repeat=4):
        values = (0, *bits[:2], 0, 0, *bits[2:], 0)
        atom_values = {
            result.result.measurement_id: value
            for result, value in zip(expansion.measurements, values, strict=True)
        }
        source_data, source_probability = data_branch(source, dict(enumerate(values)))
        atom_data, atom_probability = data_branch(actual, atom_values)
        assert source_probability == pytest.approx(1 / 16, abs=1e-11)
        assert atom_probability == pytest.approx(source_probability, abs=1e-11)
        assert source_data is not None and atom_data is not None
        assert abs(np.vdot(source_data, atom_data)) == pytest.approx(1, abs=1e-10)
        total += atom_probability
        for (basis, support), value in zip(CHECKS, values, strict=True):
            assert expectation(
                atom_data, [(q, basis) for q in support]
            ) == pytest.approx(1 - 2 * value, abs=1e-10)
        # Only the oracle applies the returned relation; production does not.
        for relation in expansion.correction_relations:
            if atom_values[relation.result.measurement_id]:
                atom_data = apply_pauli(
                    atom_data,
                    [
                        (expansion.wire_atoms.index(a), p)
                        for a, p in relation.pauli_atoms
                    ],
                )
        for basis, support in CHECKS:
            assert expectation(
                atom_data, [(q, basis) for q in support]
            ) == pytest.approx(1)
        logical_x = ((0, "X"), (3, "X"), (6, "X"))
        logical_y = ((0, "Y"), (1, "Z"), (2, "Z"), (3, "X"), (6, "X"))
        logical_z = ((0, "Z"), (1, "Z"), (2, "Z"))
        assert expectation(atom_data, logical_x) == pytest.approx(1 / sqrt(2))
        assert expectation(atom_data, logical_y) == pytest.approx(1 / sqrt(2))
        assert expectation(atom_data, logical_z) == pytest.approx(0, abs=1e-10)
    assert total == pytest.approx(1, abs=1e-10)
    for index in (0, 3, 4, 7):
        impossible = dict.fromkeys(range(8), 0) | {index: 1}
        assert data_branch(source, impossible)[1] == pytest.approx(0, abs=1e-12)


def test_dense_oracle_uses_actions_not_source_dag(raw_template, device):
    expansion = expand(raw_template, device)
    source = source_state(RawTComponent().source_qasm)
    removed = False
    steps = []
    for step in expansion.program.steps:
        actions = []
        for action in step.actions:
            if isinstance(action, CZPulse) and not removed:
                removed = True
            else:
                actions.append(action)
        steps.append(replace(step, actions=tuple(actions)))
    changed = replace(expansion, program=replace(expansion.program, steps=tuple(steps)))
    assert removed
    assert abs(np.vdot(source.vector, action_state(changed, device).vector)) < 0.99
