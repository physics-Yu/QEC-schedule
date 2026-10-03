"""Pure verification of a native ideal Clifford execution using observed bits.

This replay checks quantum semantics independently of atom routing and timing.
It consumes reported measurement and reset projection records; it does not
sample replacement outcomes, choose corrections, or act as a QEC decoder.
"""

from collections.abc import Mapping

from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.quantum.stabilizer import StabilizerState


_SUPPORTED = frozenset({"H", "X", "Y", "Z", "CZ", "MEASURE", "RESET"})


def _validated_bits(bits: Mapping[str, int], expected: set[str], description: str) -> dict[str, int]:
    if not isinstance(bits, Mapping):
        raise ValueError(f"{description} must be a mapping of integer bits")
    result = dict(bits)
    missing = expected - result.keys()
    if missing:
        raise KeyError(f"Missing {description}: {sorted(missing)}")
    extra = result.keys() - expected
    if extra:
        raise ValueError(f"Unexpected {description}: {sorted(map(repr, extra))}")
    if any(type(bit) is not int or bit not in (0, 1) for bit in result.values()):
        raise ValueError(f"{description} must contain integer bits 0 or 1")
    return result


def _signed_generator_expectation(state: StabilizerState, qubit_ids, generator) -> tuple[int, int]:
    """Express i**phase X**x Z**z as a signed tensor of I/X/Y/Z."""

    x, z, phase = generator
    mapping = {}
    for index, qubit_id in enumerate(qubit_ids):
        bit = 1 << index
        if x & bit:
            mapping[qubit_id] = "Y" if z & bit else "X"
        elif z & bit:
            mapping[qubit_id] = "Z"
    # Each Y already contains a factor i in its XZ representation.
    residual_phase = (phase - (x & z).bit_count()) % 4
    if residual_phase not in (0, 2):
        raise ValueError("Reference stabilizer is not Hermitian")
    expected = 1 if residual_phase == 0 else -1
    return state.expectation(mapping), expected


def verify_native_quantum(
    circuit: PhysicalCircuit,
    initial: StabilizerState,
    final: StabilizerState,
    reported_bits: Mapping[str, int],
    reset_projection_bits: Mapping[str, int],
) -> dict[str, object]:
    """Replay native gates and compare the resulting pure state to ``final``.

    Both bit mappings must contain exactly their respective native gate IDs.
    Measurement projection uses the reported bit XOR a declared readout flip;
    conditional X/Z gates use earlier *reported* bits.  A supplied bit that
    contradicts a deterministic quantum outcome is rejected.  Final states
    may use different qubit or generator orderings; equality is established
    through all independent signed reference stabilizers.
    """

    if any(gate.gate_type not in _SUPPORTED for gate in circuit.gates):
        raise ValueError("Native quantum verification supports H/X/Y/Z/CZ/MEASURE/RESET only")
    measured_ids = {gate.id for gate in circuit.gates if gate.gate_type == "MEASURE"}
    reset_ids = {gate.id for gate in circuit.gates if gate.gate_type == "RESET"}
    reported = _validated_bits(reported_bits, measured_ids, "measurement results")
    resets = _validated_bits(reset_projection_bits, reset_ids, "reset projections")
    reference = initial
    consumed: dict[str, int] = {}
    applied: list[str] = []
    skipped: list[str] = []

    for gate in circuit.gates:
        # Check every condition reference before AND evaluation, including
        # terms that Python's ordinary all() could otherwise short-circuit.
        for measurement_id, _ in gate.condition:
            if measurement_id not in consumed:
                raise KeyError(f"Condition requires an earlier reported measurement: {measurement_id}")
        if not all(consumed[measurement_id] == bit for measurement_id, bit in gate.condition):
            skipped.append(gate.id)
            continue
        applied.append(gate.id)
        if gate.gate_type == "MEASURE":
            requested = reported[gate.id] ^ int(gate.readout_flip)
            reference, outcome = reference.measure_z(gate.qubit_ids[0], requested)
            if outcome != requested:
                raise ValueError(f"{gate.id}: reported measurement selects an impossible projection branch")
            consumed[gate.id] = reported[gate.id]
        elif gate.gate_type == "RESET":
            requested = resets[gate.id]
            reference, outcome = reference.reset_zero(gate.qubit_ids[0], requested)
            if outcome != requested:
                raise ValueError(f"{gate.id}: reset projection selects an impossible branch")
        else:
            reference = reference.apply_gate(gate.gate_type, gate.qubit_ids, gate.parameters)

    equal = set(reference.qubit_ids) == set(final.qubit_ids)
    checked = 0
    if equal:
        for generator in reference.generators:
            actual, expected = _signed_generator_expectation(final, reference.qubit_ids, generator)
            equal = equal and actual == expected
            checked += 1
    return {
        "reference_state_equal": equal,
        "measurements_complete": set(consumed) == measured_ids,
        "reset_projections_complete": set(resets) == reset_ids,
        "conditions_verified": True,
        "reference_expectations": checked,
        "applied_gate_ids": tuple(applied),
        "skipped_gate_ids": tuple(skipped),
    }
