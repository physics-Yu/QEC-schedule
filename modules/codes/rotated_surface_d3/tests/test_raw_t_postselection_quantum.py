"""Ideal two-round raw-T acceptance and bounded adversarial-fault evidence.

These tests do not constitute a circuit-level distance or logical-noise study.
The raw-T production component is unchanged and no inter-round correction runs.
"""

from itertools import product
from math import sqrt

import numpy as np
import pytest
from nadit_physical_compiler.device import Position

from modules.codes.contracts.component import ComponentBinding, InvocationContext
from modules.codes.rotated_surface_d3.components.circuits import source_qasm
from modules.codes.rotated_surface_d3.components.injection import RawTComponent
from modules.codes.rotated_surface_d3.definition import CHECKS, REFERENCE_HOMES
from modules.codes.rotated_surface_d3.protocols.raw_t_postselection import (
    RawTPostselection,
)
from modules.codes.rotated_surface_d3.tests.dense_quantum import (
    action_state,
    apply_pauli,
    data_branch,
    expectation,
    source_state,
)
from modules.codes.rotated_surface_d3.tests.test_components import (  # fixture export
    device as device,  # noqa: PLC0414
)
from modules.codes.rotated_surface_d3.tests.test_components import world


@pytest.fixture(scope="module")
def sequence(device):
    template = RawTPostselection(
        extra_rounds=1, round_policy="explicit_control"
    ).compile(
        device,
        home_sites=REFERENCE_HOMES,
        origin=Position(0, 0),
        aod_id="transport",
    )
    return template.bind(
        ComponentBinding(
            "injection-patch", Position(0, 0), tuple(range(17)), "transport"
        )
    ).expand(InvocationContext("postselected-raw-t", 1200, 700, device, world(device)))


def values_for(part, bits):
    return {
        record.result.measurement_id: value
        for record, value in zip(part.measurements, bits, strict=True)
    }


def corrected_data(data, first, values):
    """Evaluate only the declared canonical relation at the final oracle boundary."""
    for relation in first.correction_relations:
        if values[relation.result.measurement_id]:
            data = apply_pauli(
                data,
                [
                    (first.wire_atoms.index(atom), axis)
                    for atom, axis in relation.pauli_atoms
                ],
            )
    return data


def check_logical_t(data, sign=1):
    for basis, support in CHECKS:
        assert expectation(data, [(q, basis) for q in support]) == pytest.approx(1)
    logical_x = ((0, "X"), (3, "X"), (6, "X"))
    logical_y = ((0, "Y"), (1, "Z"), (2, "Z"), (3, "X"), (6, "X"))
    logical_z = ((0, "Z"), (1, "Z"), (2, "Z"))
    assert expectation(data, logical_x) == pytest.approx(sign / sqrt(2))
    assert expectation(data, logical_y) == pytest.approx(sign / sqrt(2))
    assert expectation(data, logical_z) == pytest.approx(0, abs=1e-10)


def test_all_16_ideal_branches_preserved_by_second_actual_round(sequence, device):
    from modules.codes.rotated_surface_d3.tests.injection_sequence_checks import (
        action_extraction,
        extract,
        source_extraction,
    )

    assert len(sequence.parts) == 2
    first, second = sequence.parts
    assert first.description.component_id == "raw_t"
    assert second.description.component_id == "se_round"
    assert second.correction_relations == ()
    assert second.start_us >= first.action_end_us
    assert sequence.measurements == first.measurements + second.measurements
    assert sequence.acceptance_status == "pending"
    assert len(sequence.detectors) == 12
    assert sum(len(detector.measurements) == 1 for detector in sequence.detectors) == 4
    assert sum(len(detector.measurements) == 2 for detector in sequence.detectors) == 8
    for detector in sequence.detectors:
        assert detector.value is None
        assert detector.available_at_us == max(
            record.available_at_us for record in detector.measurements
        )
    initial_source = source_state(RawTComponent().source_qasm)
    initial_actions = action_state(first, device)
    se_source = source_extraction(source_qasm("se_round"))
    se_actions = action_extraction(second, device)
    total = 0.0
    for random_bits in product((0, 1), repeat=4):
        bits = (0, *random_bits[:2], 0, 0, *random_bits[2:], 0)
        first_values, second_values = values_for(first, bits), values_for(second, bits)
        source_data, source_probability = data_branch(
            initial_source, dict(enumerate(bits))
        )
        atom_data, atom_probability = data_branch(initial_actions, first_values)
        assert source_data is not None and atom_data is not None
        assert source_probability == pytest.approx(1 / 16)
        assert atom_probability == pytest.approx(source_probability)
        source_next, source_conditional = data_branch(
            extract(se_source, source_data), dict(enumerate(bits))
        )
        atom_next, atom_conditional = data_branch(
            extract(se_actions, atom_data), second_values
        )
        assert source_next is not None and atom_next is not None
        assert source_conditional == pytest.approx(1, abs=1e-10)
        assert atom_conditional == pytest.approx(1, abs=1e-10)
        assert abs(np.vdot(source_next, atom_next)) == pytest.approx(1, abs=1e-10)
        assert abs(np.vdot(atom_data, atom_next)) == pytest.approx(1, abs=1e-10)
        resolved = sequence.with_results(first_values | second_values)
        assert resolved.acceptance_status == "accepted"
        assert all(detector.value == 0 for detector in resolved.detectors)
        assert resolved.ready_for_use(resolved.results_ready_us)
        assert not resolved.ready_for_use(resolved.results_ready_us - 1e-6)
        check_logical_t(corrected_data(atom_next, first, first_values))
        total += atom_probability * atom_conditional
    assert total == pytest.approx(1, abs=1e-10)


def test_all_27_between_round_single_data_paulis_are_detected(sequence, device):
    from modules.codes.rotated_surface_d3.tests.injection_sequence_checks import (
        action_extraction,
        extract,
        source_extraction,
    )

    first, second = sequence.parts
    before = (0, 1, 1, 0, 0, 1, 0, 0)
    first_values = values_for(first, before)
    data, probability = data_branch(action_state(first, device), first_values)
    assert data is not None and probability == pytest.approx(1 / 16)
    se_source = source_extraction(source_qasm("se_round"))
    se_actions = action_extraction(second, device)
    for wire, error_axis in product(range(9), "XYZ"):
        deltas = tuple(
            int(wire in support and error_axis != basis) for basis, support in CHECKS
        )
        assert any(deltas)
        after = tuple(bit ^ delta for bit, delta in zip(before, deltas, strict=True))
        faulty = apply_pauli(data, ((wire, error_axis),))
        source_data, p_source = data_branch(
            extract(se_source, faulty), dict(enumerate(after))
        )
        atom_data, p_atom = data_branch(
            extract(se_actions, faulty), values_for(second, after)
        )
        assert source_data is not None and atom_data is not None
        assert p_source == pytest.approx(1, abs=1e-10)
        assert p_atom == pytest.approx(1, abs=1e-10)
        assert abs(np.vdot(source_data, atom_data)) == pytest.approx(1, abs=1e-10)
        observed = sequence.with_results(first_values | values_for(second, after))
        assert observed.acceptance_status == "rejected"
        detected = {
            detector.measurements[-1].port: detector.value
            for detector in observed.detectors
            if len(detector.measurements) == 2
        }
        assert detected == {
            record.port: delta
            for record, delta in zip(second.measurements, deltas, strict=True)
        }


@pytest.mark.parametrize("index", (1, 2, 5, 6))
def test_first_bulk_readout_flip_passes_old_rule_but_fails_round_parity(
    index, sequence
):
    first, second = sequence.parts
    truth = (0, 1, 0, 0, 0, 1, 1, 0)
    recorded = list(truth)
    recorded[index] ^= 1
    first_values = values_for(first, recorded)
    assert first.with_results(first_values).acceptance_status == "accepted"
    rejected = sequence.with_results(first_values | values_for(second, truth))
    assert rejected.acceptance_status == "rejected"
    assert sum(detector.value for detector in rejected.detectors) == 1


def test_seed_phase_fault_can_pass_both_rounds_with_wrong_logical_state(
    sequence, device
):
    from modules.codes.rotated_surface_d3.tests.injection_sequence_checks import (
        action_extraction,
        extract,
    )

    first, second = sequence.parts
    # A source-level Z fault after preparing the central physical T state changes
    # the logical state without changing deterministic boundary information.
    faulty_source = RawTComponent().source_qasm.replace("t q[4];", "t q[4];\nz q[4];")
    bits = (0, 1, 0, 0, 0, 1, 1, 0)
    data, p_first = data_branch(source_state(faulty_source), dict(enumerate(bits)))
    assert data is not None and p_first == pytest.approx(1 / 16)
    final, p_second = data_branch(
        extract(action_extraction(second, device), data), values_for(second, bits)
    )
    assert final is not None and p_second == pytest.approx(1, abs=1e-10)
    first_values = values_for(first, bits)
    accepted = sequence.with_results(first_values | values_for(second, bits))
    assert accepted.acceptance_status == "accepted"
    assert all(detector.value == 0 for detector in accepted.detectors)
    check_logical_t(corrected_data(final, first, first_values), sign=-1)
