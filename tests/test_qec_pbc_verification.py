"""Small branch, signed-state and fail-closed native replay checks."""

from types import MappingProxyType

import pytest

from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate
from neutral_atom_env.quantum.stabilizer import StabilizerState
from neutral_atom_experiments.qec_pbc.verification import verify_native_quantum


def _gate(gate_id, kind, *qubits, **kwargs):
    return PhysicalGate(gate_id, kind, qubits, **kwargs)


@pytest.mark.parametrize("measurement_bit", (0, 1))
def test_random_bell_projection_reset_and_reported_feedback(measurement_bit):
    initial = StabilizerState.zero(("a", "b"))
    circuit = PhysicalCircuit((
        _gate("ha", "H", "a"),
        _gate("hb", "H", "b"),
        _gate("cz", "CZ", "a", "b"),
        _gate("hb2", "H", "b"),
        _gate("read", "MEASURE", "a"),
        _gate("reset", "RESET", "a"),
        _gate("correct", "X", "b", condition=(("read", 1),)),
    ))
    reported = MappingProxyType({"read": measurement_bit})
    projections = MappingProxyType({"reset": measurement_bit})
    initial_description = initial.to_dict()
    audit = verify_native_quantum(circuit, initial, StabilizerState.zero(("a", "b")), reported, projections)

    assert audit["reference_state_equal"]
    assert audit["measurements_complete"] and audit["reset_projections_complete"]
    assert audit["conditions_verified"]
    assert audit["reference_expectations"] == 2
    assert audit["skipped_gate_ids"] == (() if measurement_bit else ("correct",))
    assert ("correct" in audit["applied_gate_ids"]) == bool(measurement_bit)
    assert initial.to_dict() == initial_description
    assert dict(reported) == {"read": measurement_bit}
    assert dict(projections) == {"reset": measurement_bit}


def test_fixed_readout_flip_controls_reported_feedback_and_checks_projection_truth():
    initial = StabilizerState.zero(("q",)).apply_gate("X", ("q",))
    circuit = PhysicalCircuit((
        _gate("flipped", "MEASURE", "q", readout_flip=True),
        _gate("active", "X", "q", condition=(("flipped", 0),)),
        _gate("inactive", "Z", "q", condition=(("flipped", 1),)),
        _gate("reset", "RESET", "q"),
        _gate("final", "MEASURE", "q"),
    ))
    audit = verify_native_quantum(circuit, initial, StabilizerState.zero(("q",)),
                                  {"flipped": 0, "final": 0}, {"reset": 0})
    assert audit["reference_state_equal"]
    assert audit["applied_gate_ids"] == ("flipped", "active", "reset", "final")
    assert audit["skipped_gate_ids"] == ("inactive",)
    with pytest.raises(ValueError, match="impossible projection"):
        verify_native_quantum(circuit, initial, StabilizerState.zero(("q",)),
                              {"flipped": 1, "final": 0}, {"reset": 0})


def test_conditions_apply_and_of_distinct_earlier_reported_bits():
    initial = StabilizerState.zero(("a", "b"))
    circuit = PhysicalCircuit((
        _gate("prepare", "X", "a"),
        _gate("ma", "MEASURE", "a"),
        _gate("mb", "MEASURE", "b"),
        _gate("active", "X", "a", condition=(("ma", 1), ("mb", 0))),
        _gate("inactive", "Z", "a", condition=(("ma", 0), ("mb", 0))),
    ))
    audit = verify_native_quantum(circuit, initial, initial, {"ma": 1, "mb": 0}, {})
    assert audit["reference_state_equal"]
    assert audit["applied_gate_ids"] == ("prepare", "ma", "mb", "active")
    assert audit["skipped_gate_ids"] == ("inactive",)


@pytest.mark.parametrize("phase", (1, 3))
def test_signed_y_generators_have_correct_hermitian_phase(phase):
    initial = StabilizerState(("q",), ((1, 1, phase),))
    final = StabilizerState(("q",), ((1, 1, (phase + 2) % 4),))
    circuit = PhysicalCircuit((_gate("z", "Z", "q"),))
    audit = verify_native_quantum(circuit, initial, final, {}, {})
    assert audit["reference_state_equal"]
    assert not verify_native_quantum(circuit, initial, initial, {}, {})["reference_state_equal"]


def test_y_native_unitary_and_distinct_final_generator_basis_are_supported():
    initial = StabilizerState.zero(("a", "b"))
    circuit = PhysicalCircuit((
        _gate("ha", "H", "a"),
        _gate("hb", "H", "b"),
        _gate("cz", "CZ", "a", "b"),
        _gate("hb2", "H", "b"),
        _gate("ya", "Y", "a"),
        _gate("ya2", "Y", "a"),
    ))
    # Bell |Phi+> has -YY and +ZZ generators; reference evolution instead
    # produces +XX and +ZZ. Reverse qubit order as well.
    final = StabilizerState(("b", "a"), ((3, 3, 0), (0, 3, 0)))
    audit = verify_native_quantum(circuit, initial, final, {}, {})
    assert audit["reference_state_equal"]
    assert audit["reference_expectations"] == 2


def test_two_y_reference_generator_sign_is_compared_semantically():
    initial = StabilizerState(("a", "b"), ((3, 3, 0), (0, 3, 0)))
    final = StabilizerState(("a", "b"), ((3, 0, 0), (0, 3, 0)))
    assert initial != final
    audit = verify_native_quantum(PhysicalCircuit(()), initial, final, {}, {})
    assert audit["reference_state_equal"]


def test_wrong_final_state_or_qubit_set_returns_false():
    initial = StabilizerState.zero(("q",))
    circuit = PhysicalCircuit((_gate("x", "X", "q"),))
    assert not verify_native_quantum(circuit, initial, initial, {}, {})["reference_state_equal"]
    audit = verify_native_quantum(circuit, initial, StabilizerState.zero(("other",)), {}, {})
    assert not audit["reference_state_equal"]
    assert audit["reference_expectations"] == 0


@pytest.fixture
def reset_then_read():
    return PhysicalCircuit((_gate("reset", "RESET", "q"), _gate("read", "MEASURE", "q")))


@pytest.mark.parametrize("bad_bit", (True, False, 0.0, 1.0, -1, 2, "0", None))
@pytest.mark.parametrize("which", ("measurement", "reset"))
def test_noninteger_bits_are_rejected(reset_then_read, bad_bit, which):
    state = StabilizerState.zero(("q",))
    reported = {"read": bad_bit if which == "measurement" else 0}
    resets = {"reset": bad_bit if which == "reset" else 0}
    with pytest.raises(ValueError, match="integer bits"):
        verify_native_quantum(reset_then_read, state, state, reported, resets)


@pytest.mark.parametrize(
    "reported,resets,error",
    [
        ({}, {"reset": 0}, KeyError),
        ({"read": 0}, {}, KeyError),
        ({"read": 0, "extra": 0}, {"reset": 0}, ValueError),
        ({"read": 0}, {"reset": 0, "extra": 0}, ValueError),
    ],
)
def test_complete_exact_measurement_and_reset_key_sets_are_required(reset_then_read, reported, resets, error):
    state = StabilizerState.zero(("q",))
    with pytest.raises(error):
        verify_native_quantum(reset_then_read, state, state, reported, resets)


def test_impossible_deterministic_reset_projection_is_rejected(reset_then_read):
    state = StabilizerState.zero(("q",))
    with pytest.raises(ValueError, match="reset projection selects an impossible"):
        verify_native_quantum(reset_then_read, state, state, {"read": 0}, {"reset": 1})


def test_random_reset_branch_preserves_correlations_with_other_qubits():
    initial = StabilizerState(("a", "b"), ((3, 0, 0), (0, 3, 0)))
    circuit = PhysicalCircuit((_gate("reset", "RESET", "a"),))
    for bit in (0, 1):
        final = StabilizerState.zero(("a", "b"))
        if bit:
            final = final.apply_gate("X", ("b",))
        assert verify_native_quantum(circuit, initial, final, {}, {"reset": bit})["reference_state_equal"]


def test_condition_reference_is_checked_before_and_short_circuit():
    state = StabilizerState.zero(("a", "b"))
    circuit = PhysicalCircuit((
        _gate("first", "MEASURE", "a"),
        _gate("future", "MEASURE", "b"),
        _gate("conditional", "X", "a", condition=(("first", 1), ("future", 0))),
    ))
    # Simulate corrupted serialized ordering. Ordinary PhysicalCircuit
    # construction already rejects this; the independent verifier checks it
    # even when the first equality is false and would short-circuit AND.
    first, future, conditional = circuit.gates
    object.__setattr__(circuit, "gates", (first, conditional, future))
    with pytest.raises(KeyError, match="earlier reported measurement: future"):
        verify_native_quantum(circuit, state, state, {"first": 0, "future": 0}, {})


def test_unsupported_native_gate_is_rejected_without_approximation():
    state = StabilizerState.zero(("q",))
    circuit = PhysicalCircuit((_gate("t", "T", "q"),))
    with pytest.raises(ValueError, match="supports H/X/Y/Z/CZ/MEASURE/RESET only"):
        verify_native_quantum(circuit, state, state, {}, {})
