"""Independent official-generator, quantum-instrument and circuit-fault checks.

The optional dependency is installed separately from the production project.
Formal baseline runners fail clearly if it is absent; ordinary installations
can skip these optional cross-simulator tests without changing the environment.
"""
from collections import Counter
from dataclasses import replace
from pathlib import Path
import sys

import pytest

_deps = Path(__file__).resolve().parents[1] / 'artifacts' / 'qec-baseline-deps'
if _deps.is_dir():
    sys.path.insert(0, str(_deps))
stim = pytest.importorskip('stim', reason='Optional canonical audit requires requirements-qec-baseline.txt')

from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_experiments.qec_pbc.canonical import canonical_memory_program
from neutral_atom_experiments.qec_pbc.canonical_audit import (
    STIM_COMMIT, STIM_SOURCE_SHA256, NativeFault, audit_canonical_memory,
    build_single_fault_decoder, compare_official_reference,
    enumerate_native_faults, native_fault_signatures, native_to_stim,
    official_reference_stim, propagate_native_fault_signature,
    verify_native_instrument)
from neutral_atom_experiments.qec_pbc.lowering import lower_to_physical


def _mask(values):
    return sum(bit << i for i, bit in enumerate(values.values()))


def _detectors(compiled, mask):
    return {d.id: mask >> i & 1 for i, d in enumerate(compiled.program.detectors)}


@pytest.fixture(scope='module', params=('Z', 'X'))
def case(request):
    source = canonical_memory_program(basis=request.param)
    compiled = lower_to_physical(source.program)
    signatures = native_fault_signatures(compiled)
    return source, compiled, signatures


def test_default_full_memory_has_independent_distance_three_evidence(case):
    source, compiled, signatures = case
    report = audit_canonical_memory(source, compiled)
    assert report['passed'] and report['status'] == 'passed'
    assert not report['counterexamples']
    assert report['source']['commit'] == STIM_COMMIT
    assert report['source']['sha256'] == STIM_SOURCE_SHA256
    assert report['official_reference']['interaction_layers'] == 12
    assert report['official_reference']['detector_equations'] == 24
    assert report['ideal_instrument']['seeds'] == [0, 1, 7, 19]
    assert report['official_noiseless_samples'] == {
        'shots': 128, 'seed': 0, 'detector_events': 0, 'observable_flips': 0}
    counts = Counter(g.gate_type for g in compiled.circuit.gates)
    assert report['native_fault_count'] == 3 * counts['H'] + 15 * counts['CZ'] + counts['RESET'] + counts['MEASURE']
    assert report['native_fault_count'] == (1658 if source.program.memory_contract.basis == 'Z' else 1712)
    assert report['fault_counts']['reset_flip'] == 41
    assert report['fault_counts']['measurement_report'] == 33
    assert report['independent_pauli_frame']['passed']
    assert report['independent_pauli_frame']['mechanisms_checked'] == len(signatures)
    assert report['all_single_faults_corrected']
    distance = report['fault_distance']
    assert distance['distance'] == 3
    assert distance['no_undetectable_single_fault']
    assert distance['no_undetectable_fault_pair']
    assert not distance['single_counterexamples'] and not distance['pair_counterexamples']
    # All mutually exclusive alternatives at one gate are excluded from pairs.
    per_gate = Counter(s.fault.gate_id for s in signatures)
    expected_pairs = len(signatures) * (len(signatures) - 1) // 2
    expected_pairs -= sum(n * (n - 1) // 2 for n in per_gate.values())
    assert distance['enumerated_distinct_operation_pairs'] == expected_pairs
    assert len(report['faults']) == len(signatures)
    assert 'transport and idle intervals excluded' in report['fault_model']['interval']


def test_every_fault_signature_matches_deterministic_stim_replay_and_independent_frame(case):
    _, compiled, signatures = case
    for signature in signatures:
        assert propagate_native_fault_signature(compiled, signature.fault) == signature
        d, o = native_to_stim(compiled, fault=signature.fault).compile_detector_sampler(seed=7).sample(
            1, separate_observables=True)
        assert sum(int(bit) << i for i, bit in enumerate(d[0])) == signature.detector_mask, signature.fault.id
        assert sum(int(bit) << i for i, bit in enumerate(o[0])) == signature.observable_mask, signature.fault.id


def test_each_gate_failure_class_also_matches_project_quantum_instrument(case):
    _, compiled, signatures = case
    first_cz = next(g.id for g in compiled.circuit.gates if g.gate_type == 'CZ')
    # Full 15-outcome CZ mechanism, each reset/readout phase, and representative
    # 1Q axes cross-check the project's true projection against Stim, not only
    # the two independent signature algorithms.
    selected = [s for s in signatures if s.fault.gate_id == first_cz]
    for kind in ('reset_flip', 'measurement_report', 'after_pauli'):
        candidates = [s for s in signatures if s.fault.kind == kind]
        selected.extend((candidates[0], candidates[len(candidates) // 2], candidates[-1]))
    for signature in {s.fault.id: s for s in selected}.values():
        for result in verify_native_instrument(compiled, seeds=(0, 19), fault=signature.fault):
            assert _mask(result['detectors']) == signature.detector_mask
            assert _mask(result['observables']) == signature.observable_mask


def test_detector_only_dictionary_corrects_every_single_fault_and_rejects_unknowns(case):
    _, compiled, signatures = case
    decoder = build_single_fault_decoder(compiled, signatures)
    assert decoder.decode(_detectors(compiled, 0)) == {o.id: 0 for o in compiled.program.observables}
    for signature in signatures:
        outputs = {'detectors': _detectors(compiled, signature.detector_mask),
                   'observables': {o.id: signature.observable_mask >> i & 1
                                   for i, o in enumerate(compiled.program.observables)}}
        assert decoder.correct_outputs(outputs) == {o.id: 0 for o in compiled.program.observables}
    unknown = (1 << len(decoder.detector_ids)) - 1
    assert unknown not in dict(decoder.entries)
    with pytest.raises(ValueError, match='outside the validated'):
        decoder.decode(_detectors(compiled, unknown))
    with pytest.raises(ValueError, match='full detector history'):
        decoder.decode({})
    invalid = _detectors(compiled, 0)
    invalid[next(iter(invalid))] = False
    with pytest.raises(ValueError, match='integer bits'):
        decoder.decode(invalid)


def test_three_terminal_report_faults_are_an_exact_undetectable_logical_witness(case):
    source, compiled, signatures = case
    report = audit_canonical_memory(source, compiled, seeds=(7,), reference_shots=8, include_faults=False)
    ids = report['fault_distance']['weight_three_terminal_report_witness']
    by_id = {s.fault.id: s for s in signatures}
    witness = [by_id[key] for key in ids]
    assert len({s.fault.gate_id for s in witness}) == 3
    assert all(s.fault.kind == 'measurement_report' for s in witness)
    d, o = native_to_stim(compiled, faults=tuple(s.fault for s in witness)).compile_detector_sampler(seed=19).sample(
        8, separate_observables=True)
    assert not d.any() and o.all()
    # Distance three implies one-fault correction, not correction of every
    # two-fault history. Two pieces of the witness look like its third piece.
    decoder = build_single_fault_decoder(compiled, signatures)
    pair_d = witness[0].detector_mask ^ witness[1].detector_mask
    pair_o = witness[0].observable_mask ^ witness[1].observable_mask
    observed = {key: pair_o >> i & 1 for i, key in enumerate(decoder.observable_ids)}
    assert any(decoder.correct_outputs({'detectors': _detectors(compiled, pair_d),
                                        'observables': observed}).values())


def test_report_fault_leaves_true_projection_unchanged(case):
    _, compiled, signatures = case
    fault = next(s.fault for s in signatures if s.fault.id.startswith('A.final.m0__g000:report_flip'))
    clean = verify_native_instrument(compiled, seeds=(7,))[0]
    faulty = verify_native_instrument(compiled, seeds=(7,), fault=fault)[0]
    raw = dict(clean['raw_measurements'])
    raw[fault.gate_id] ^= 1
    assert faulty['raw_measurements'] == raw
    # The instrument helper compares every signed full-state generator after
    # every quantum readout; an M(1) report flip changes no quantum state.
    assert _mask(faulty['observables']) == 1


def test_missing_terminal_detectors_produce_real_logical_conflicts_and_failed_report(case):
    source, compiled, _ = case
    program = replace(source.program, detectors=tuple(d for d in source.program.detectors
                                                     if d.boundary != 'destructive_readout'))
    broken_source = replace(source, program=program)
    broken_compiled = replace(compiled, program=program)
    signatures = native_fault_signatures(broken_compiled)
    assert any(s.detector_mask == 0 and s.observable_mask for s in signatures)
    with pytest.raises(ValueError, match='Conflicting zero-or-one-fault'):
        build_single_fault_decoder(broken_compiled, signatures)
    failed = audit_canonical_memory(broken_source, broken_compiled)
    assert not failed['passed'] and failed['status'] == 'failed'
    assert failed['counterexamples'] and 'Detector parity equations' in failed['counterexamples'][0]['message']


def test_lost_native_basis_restore_is_rejected_before_fault_claim(case):
    source, compiled, _ = case
    phase = next(phase for phase in source.phases if phase.kind == 'cx_target_restore')
    gid = phase.native_gate_ids[0]
    gates = tuple(replace(g, gate_type='X') if g.id == gid else g for g in compiled.circuit.gates)
    broken = replace(compiled, circuit=PhysicalCircuit(gates))
    failed = audit_canonical_memory(source, broken)
    assert not failed['passed']
    assert 'Native primitive differs' in failed['counterexamples'][0]['message']


def test_missing_native_phase_barrier_is_rejected(case):
    source, compiled, _ = case
    phase = next(phase for phase in source.phases if phase.kind == 'cx_cz')
    gid = phase.native_gate_ids[0]
    gates = tuple(replace(g, depends_on=()) if g.id == gid else g for g in compiled.circuit.gates)
    failed = audit_canonical_memory(source, replace(compiled, circuit=PhysicalCircuit(gates)))
    assert not failed['passed']
    assert 'dependency barriers' in failed['counterexamples'][0]['message']


@pytest.mark.parametrize('basis', ('Z', 'X'))
def test_reference_handles_role_names_and_nondefault_binding_order(basis):
    source = canonical_memory_program(basis=basis, patch='code.data')
    bindings = {role.id: f'Q{90-i:03d}' for i, role in enumerate(reversed(source.program.roles))}
    compiled = lower_to_physical(source.program, bindings)
    assert compare_official_reference(source, compiled)['passed']
    assert official_reference_stim(source).num_measurements == 33
    assert native_to_stim(compiled).num_detectors == 24
    assert len(verify_native_instrument(compiled, seeds=(1, 7))) == 2


def test_source_pin_and_dependency_fail_closed(case, monkeypatch):
    source, compiled, _ = case
    wrong_pin = replace(source, source_commit='unverified-source')
    failed = audit_canonical_memory(wrong_pin, compiled)
    assert not failed['passed'] and 'source pin' in failed['counterexamples'][0]['message']
    monkeypatch.setattr(stim, '__version__', '0.0.0')
    with pytest.raises(RuntimeError, match='pinned to Stim 1.15.0'):
        audit_canonical_memory(source, compiled)
    monkeypatch.setattr(stim, '__version__', '1.15.0')
    monkeypatch.setitem(sys.modules, 'stim', None)
    with pytest.raises(RuntimeError, match='requires isolated stim==1.15.0'):
        native_to_stim(compiled)


def test_fault_replay_model_rejects_wrong_location_and_same_operation_alternatives(case):
    _, compiled, signatures = case
    report = next(s.fault for s in signatures if s.fault.kind == 'measurement_report')
    invalid = replace(report, gate_id=compiled.circuit.gates[0].id)
    with pytest.raises(ValueError, match='declared native location'):
        native_to_stim(compiled, fault=invalid)
    with pytest.raises(ValueError, match='distinct native operations'):
        native_to_stim(compiled, faults=(report, report))
    with pytest.raises(ValueError, match='one fault or a fault tuple'):
        native_to_stim(compiled, fault=report, faults=(report,))
    with pytest.raises(ValueError, match='declared native location'):
        propagate_native_fault_signature(compiled, NativeFault('fake', report.gate_id, 'after_pauli'))


@pytest.mark.parametrize('kwargs', ({'seeds': ()}, {'seeds': (False,)}, {'reference_shots': 0}))
def test_empty_evidence_cannot_be_marked_as_a_pass(kwargs):
    source = canonical_memory_program()
    with pytest.raises(ValueError, match='Audit requires'):
        audit_canonical_memory(source, lower_to_physical(source.program), **kwargs)
