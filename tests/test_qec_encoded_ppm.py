"""Encoded PPM semantics, native faults and explicit failure boundaries."""
from dataclasses import replace
from pathlib import Path
import sys

import pytest

_deps = Path(__file__).resolve().parents[1] / 'artifacts' / 'qec-baseline-deps'
if _deps.is_dir():
    sys.path.insert(0, str(_deps))
stim = pytest.importorskip('stim', reason='Encoded parity audit requires pinned Stim 1.15.0')

from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_experiments.qec_pbc.canonical_audit import (
    build_single_fault_decoder, native_fault_signatures, native_to_stim)
from neutral_atom_experiments.qec_pbc.encoded_ppm import (
    audit_encoded_parity, compile_encoded_parity, encoded_parity_program,
    retained_output_expectations, verify_encoded_parity_instrument)
from neutral_atom_experiments.qec_pbc.lowering import lower_to_physical


@pytest.fixture(scope='module', params=('Z', 'X'))
def calibration(request):
    basis = request.param
    protocol = encoded_parity_program(basis=basis, input_bases=(basis, basis))
    compiled = compile_encoded_parity(protocol)
    report = audit_encoded_parity(protocol, compiled)
    return protocol, compiled, report


def test_calibrated_parity_has_independent_single_fault_decoder_and_distance_witness(calibration):
    protocol, compiled, report = calibration
    assert report['passed'], report
    assert not report['counterexamples']
    assert report['independent_pauli_frame_passed'] and report['all_single_faults_corrected']
    assert not report['undetected_single_faults'] and not report['undetected_pairs']
    assert report['native_fault_count'] == (10230 if protocol.basis == 'Z' else 10338)
    assert report['detector_count'] == 136
    assert report['gate_counts'] == {
        'RESET': 195, 'H': 1044 if protocol.basis == 'Z' else 1080,
        'CZ': 450, 'MEASURE': 153}
    assert len(report['weight_three_terminal_report_witness']) == 3
    assert 'transport/idle/loss' in report['scope']
    assert 'general fault' not in protocol.to_dict()['claim']
    assert len(compiled.circuit.gates) == (1842 if protocol.basis == 'Z' else 1878)


def test_every_native_fault_and_three_report_witness_matches_decoder(calibration):
    _, compiled, report = calibration
    signatures = native_fault_signatures(compiled)
    decoder = build_single_fault_decoder(compiled, signatures)
    entries = dict(decoder.entries)
    assert all(entries[s.detector_mask] == s.observable_mask for s in signatures)
    by_id = {s.fault.id: s.fault for s in signatures}
    faults = tuple(by_id[key] for key in report['weight_three_terminal_report_witness'])
    detectors, observables = native_to_stim(compiled, faults=faults).compile_detector_sampler(seed=7).sample(
        4, separate_observables=True)
    assert not detectors.any() and observables.all()
    with pytest.raises(ValueError, match='outside the validated'):
        decoder.decode({key: 1 for key in decoder.detector_ids})


@pytest.mark.parametrize('basis', ('Z', 'X'))
@pytest.mark.parametrize('sign', (-1, 1))
def test_both_choi_branches_preserve_arbitrary_data_reference_channel(basis, sign):
    protocol = encoded_parity_program(basis=basis, parity_sign=sign)
    report = verify_encoded_parity_instrument(protocol, seeds=(0, 7))
    assert report['passed']
    assert len(report['branches']) == 4
    assert {b['physical_branch'] for b in report['branches']} == {0, 1}
    assert all(b['branch_probability'] == .5 and b['passed'] for b in report['branches'])
    assert all(b['semantic_branch'] == b['physical_branch'] ^ int(sign == -1)
               for b in report['branches'])
    assert all(len(b['output_reference_generators']) == 4 for b in report['branches'])


@pytest.mark.parametrize('basis', ('Z', 'X'))
def test_signed_inputs_nondefault_patch_names_and_reversed_bindings(basis):
    protocol = encoded_parity_program(basis=basis, patches=('left.code', 'right.code', 'resource.code'),
        input_bases=('Z', 'X'), input_signs=(1, 1), parity_sign=-1)
    bindings = {role.id: f'Q{200-i:03d}' for i, role in enumerate(reversed(protocol.program.roles))}
    compiled = compile_encoded_parity(protocol, bindings)
    assert verify_encoded_parity_instrument(protocol, compiled, seeds=(3,))['passed']


@pytest.mark.parametrize('basis', ('Z', 'X'))
def test_resources_sector_transfer_and_native_wire_order_are_explicit(basis):
    protocol = encoded_parity_program(basis=basis)
    compiled = compile_encoded_parity(protocol)
    assert len(protocol.program.roles) == 51
    assert sum(r.kind == 'data' for r in protocol.program.roles) == 27
    assert sum(r.kind == 'syndrome_ancilla' for r in protocol.program.roles) == 24
    assert {p for p in protocol.output_patches} == {'A', 'B'}
    assert len([p for p in protocol.phases if p.kind == 'encoded_cx_cz']) == 2
    assert len([c for c in protocol.couplings if 'ppm.cx' in c.check_id]) == 18
    transfer = {d.id: d for d in protocol.program.detectors if d.boundary == 'transversal_check_sector_transfer'}
    assert len(transfer) == 24
    if basis == 'Z':
        assert transfer['A.det.r4.X0'].expression.terms == ('A.r3.X0', 'C.r3.X0', 'A.r4.X0')
        assert transfer['C.det.r4.Z0'].expression.terms == ('C.r3.Z0', 'A.r3.Z0', 'B.r3.Z0', 'C.r4.Z0')
    else:
        assert transfer['A.det.r4.Z0'].expression.terms == ('A.r3.Z0', 'C.r3.Z0', 'A.r4.Z0')
        assert transfer['C.det.r4.X0'].expression.terms == ('C.r3.X0', 'A.r3.X0', 'B.r3.X0', 'C.r4.X0')
    seen, last_wire = set(), {}
    for gate in compiled.circuit.gates:
        assert set(gate.depends_on) <= seen
        for q in gate.qubit_ids:
            if q in last_wire:
                assert last_wire[q] in gate.depends_on
            last_wire[q] = gate.id
        seen.add(gate.id)
    assert all(g.gate_type in ('H', 'X', 'Z', 'CZ', 'MEASURE', 'RESET') for g in compiled.circuit.gates)


@pytest.mark.parametrize('basis', ('Z', 'X'))
def test_clean_retained_logical_constraints_have_true_quantum_expectation(basis):
    protocol = encoded_parity_program(basis=basis, input_signs=(1, 0), parity_sign=-1)
    compiled = compile_encoded_parity(protocol)
    qindex = {q: i for i, (_, q) in enumerate(compiled.bindings)}
    bindings = dict(compiled.bindings)
    for seed in (0, 7):
        sim, raw = stim.TableauSimulator(seed=seed), {}
        sim.set_num_qubits(51)
        for gate in compiled.circuit.gates:
            indices = [qindex[q] for q in gate.qubit_ids]
            if gate.gate_type == 'MEASURE':
                raw[gate.id] = int(sim.measure(indices[0]))
            else:
                step = stim.Circuit()
                step.append({'RESET': 'R'}.get(gate.gate_type, gate.gate_type), indices)
                sim.do(step)
        words = retained_output_expectations(protocol, compiled.semantic_results(raw))
        assert len(words) == 18
        for word in words:
            physical = stim.PauliString(51)
            physical.sign = word.sign
            for role, kind in word.factors:
                physical[qindex[bindings[role]]] = kind
            assert sim.peek_observable_expectation(physical) == 1


def test_missing_ancilla_closing_checks_fails_native_fault_audit(calibration):
    protocol, compiled, _ = calibration
    program = replace(protocol.program, detectors=tuple(d for d in protocol.program.detectors
                                                       if d.boundary != 'destructive_readout'))
    broken = replace(protocol, program=program)
    report = audit_encoded_parity(broken, replace(compiled, program=program))
    assert not report['passed']
    assert 'Conflicting zero-or-one-fault' in report['counterexamples'][0]['message']


def test_wrong_native_transversal_gate_changes_choi_channel():
    protocol = encoded_parity_program()
    compiled = compile_encoded_parity(protocol)
    phase = next(p for p in protocol.phases if p.kind == 'encoded_cx_target_h')
    gid = phase.native_gate_ids[0]
    gates = tuple(replace(g, gate_type='X') if g.id == gid else g for g in compiled.circuit.gates)
    with pytest.raises((ValueError, AssertionError)):
        verify_encoded_parity_instrument(protocol, replace(compiled, circuit=PhysicalCircuit(gates)), seeds=(0,))


@pytest.mark.parametrize('mutation', ('barrier', 'coupling'))
def test_protocol_sidecar_or_native_barrier_edit_is_rejected(mutation):
    protocol = encoded_parity_program()
    compiled = compile_encoded_parity(protocol)
    if mutation == 'barrier':
        phase = next(p for p in protocol.phases if p.kind == 'encoded_cx_cz')
        gid = phase.native_gate_ids[0]
        gates = tuple(replace(g, depends_on=()) if g.id == gid else g for g in compiled.circuit.gates)
        compiled = replace(compiled, circuit=PhysicalCircuit(gates))
    else:
        protocol = replace(protocol, couplings=protocol.couplings[:-1])
    with pytest.raises(ValueError, match='barrier|sidecar'):
        verify_encoded_parity_instrument(protocol, compiled, seeds=(0,))


def test_diagnostic_data_closure_cannot_be_called_nondestructive():
    protocol = encoded_parity_program(close_data_basis='X')
    assert len(protocol.program.observables) == 3
    assert len(protocol.program.detectors) == 144
    with pytest.raises(ValueError, match='destructive data closure'):
        verify_encoded_parity_instrument(protocol)
    with pytest.raises(ValueError, match='nondestructive'):
        retained_output_expectations(protocol, {})


def test_fail_closed_for_random_dem_contract_and_unvalidated_ft_request():
    protocol = encoded_parity_program()
    with pytest.raises(ValueError, match='parity-eigenbasis'):
        audit_encoded_parity(protocol)
    with pytest.raises(ValueError, match='No validated fault-tolerant'):
        lower_to_physical(protocol.program, require_fault_tolerant=True)
    with pytest.raises(TypeError, match='EncodedParity'):
        compile_encoded_parity(protocol.program)
    with pytest.raises(ValueError, match='nonnegative'):
        verify_encoded_parity_instrument(protocol, seeds=())


@pytest.mark.parametrize('kwargs', ({'basis': 'Y'}, {'rounds': 0}, {'rounds': False},
    {'patches': ('A', 'A', 'C')}, {'input_bases': ('Y', 'X')}, {'input_signs': (True, 0)},
    {'parity_sign': 0}, {'close_data_basis': 'Y'}))
def test_invalid_encoded_protocol_is_rejected(kwargs):
    with pytest.raises(ValueError, match='Encoded parity'):
        encoded_parity_program(**kwargs)
