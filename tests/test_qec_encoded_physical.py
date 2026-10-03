"""Physical experiment inputs and independent retained-state acceptance."""
from collections import Counter
from dataclasses import replace
import random

import pytest

from neutral_atom_env.domain.operations import HardwareConfig
from neutral_atom_experiments.qec_pbc.encoded_ppm import encoded_parity_program
from neutral_atom_experiments.qec_pbc.encoded_physical import (
    encoded_cz_groups, encoded_output_audit, encoded_parity_inputs)


@pytest.mark.parametrize('basis', ('Z', 'X'))
def test_declared_platform_uses_native_hardware_and_distinct_existing_holders(basis):
    protocol = encoded_parity_program(basis=basis)
    inputs, destinations = encoded_parity_inputs(protocol)
    state = inputs.create_environment().state
    assert inputs.platform.hardware == HardwareConfig(ez_neighbor_guard_enabled=False)
    assert state.aod.rows * state.aod.columns == 98
    assert len(state.atoms) == len(destinations) == len(set(destinations.values())) == 51
    assert dict(inputs.placement) == destinations
    assert all(state.world.traps[site].enabled for site in destinations.values())
    assert all(site in state.world.traps for site in destinations.values())
    # Every authored CZ is covered. In particular C-data/C-check interactions
    # select the check carrier, whereas cross-patch CZ selects C-data.
    gates = [g for g in inputs.circuit.gates if g.gate_type == 'CZ']
    groups = list(encoded_cz_groups(state, gates, inputs.compiled, protocol.patches[2]))
    coverage = Counter(gid for _, members in groups for gid, _, _ in members)
    assert set(coverage) == {g.id for g in gates}
    by_id = {g.id: g for g in gates}
    reverse = {q: role for role in protocol.program.roles
               for key, q in inputs.compiled.bindings if key == role.id}
    for _, members in groups:
        for gid, anchor, mobile in members:
            assert {anchor, mobile} == set(by_id[gid].qubit_ids)
            if any(reverse[q].kind == 'syndrome_ancilla' for q in by_id[gid].qubit_ids):
                assert reverse[mobile].kind == 'syndrome_ancilla'
            else:
                assert reverse[mobile].patch == protocol.patches[2]


@pytest.mark.parametrize('basis', ('Z', 'X'))
def test_ideal_retained_output_and_coherence_are_checked_independently(basis):
    protocol = encoded_parity_program(basis=basis, parity_sign=-1, input_signs=(1, 0))
    inputs, _ = encoded_parity_inputs(protocol, seed=7)
    state = inputs.create_environment().state
    quantum, reports, rng = state.quantum_state, {}, random.Random(7)
    for gate in inputs.circuit.gates:
        if gate.gate_type == 'MEASURE':
            quantum, bit = quantum.measure_z(gate.qubit_ids[0], rng.getrandbits(1))
            reports[gate.id] = bit
        elif gate.gate_type == 'RESET':
            quantum, _ = quantum.reset_zero(gate.qubit_ids[0], rng.getrandbits(1))
        else:
            quantum = quantum.apply_gate(gate.gate_type, gate.qubit_ids, gate.parameters)
    measured = {gate.qubit_ids[0] for gate in inputs.circuit.gates if gate.gate_type == 'MEASURE'
                and '.final.m' in gate.id}
    final = replace(state, quantum_state=quantum, measurement_results=reports,
        atoms={q: replace(a, measured=q in measured) for q, a in state.atoms.items()})
    audit = encoded_output_audit(protocol, inputs, final)
    assert all(v for v in audit.values() if isinstance(v, bool))
    # A logical X on one output of ZZ (Z on XX) flips measured parity.
    from neutral_atom_experiments.qec_pbc.surface import logical_product
    from neutral_atom_experiments.qec_pbc.pauli import PauliProduct
    wrong = logical_product(PauliProduct(((protocol.patches[0], 'X' if basis == 'Z' else 'Z'),)))
    binding = dict(inputs.compiled.bindings)
    broken = quantum
    for role, kind in wrong.factors:
        broken = broken.apply_gate(kind, (binding[role],))
    rejected = encoded_output_audit(protocol, inputs, replace(final, quantum_state=broken))
    assert not rejected['branch_logical_parity_verified']
    assert not rejected['retained_output_coherence_verified']
