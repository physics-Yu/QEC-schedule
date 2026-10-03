"""Native phase-sensitive CY and retained signed encoded cat channels."""
from dataclasses import replace
from itertools import product

import numpy as np
import pytest

stim = pytest.importorskip('stim', reason='optional pinned exact Clifford instrument reference')
from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate
from neutral_atom_experiments.qec_pbc.canonical import canonical_memory_program
from neutral_atom_experiments.qec_pbc.encoded_resource_reference import apply_native_unitaries
from neutral_atom_experiments.qec_pbc.ir import BitExpr, GateTask, Observable, PBCProgram, Role
from neutral_atom_experiments.qec_pbc.lowering import lower_to_physical
from neutral_atom_experiments.qec_pbc.mixed_pauli_cat import (
    append_mixed_pauli_cat, audit_cat_factorized_kraus, clifford_reference_steps,
    verify_mixed_pauli_instruments,
)
from neutral_atom_experiments.qec_pbc.pauli import PauliProduct
from neutral_atom_experiments.surface_ghz import LOGICAL_X, Z_CHECKS


def prefix(patches=('A', 'B'), *, references=False, signed_sector=False):
    roles, ops, detectors, sectors = [], [], [], {}
    for patch in patches:
        memory = canonical_memory_program(patch=patch, rounds=2)
        roles.extend(memory.program.roles)
        ops.extend(o for o in memory.program.operations if not o.id.startswith(f'{patch}.final.'))
        detectors.extend(d for d in memory.program.detectors if d.boundary != 'destructive_readout')
        for kind in ('X', 'Z'):
            for i in range(4):
                sectors[patch, kind, i] = BitExpr((f'{patch}.r2.{kind}{i}',))
    frontier = (ops[-1].id,)
    def add(key, kind, targets):
        nonlocal frontier
        ops.append(GateTask(key, kind, tuple(targets), frontier))
        frontier = (key,)
    if references:
        for patch in patches:
            ref = f'ref.{patch}'
            roles.append(Role(ref, 'data'))
            add(ref + '.reset', 'RESET', (ref,))
            add(ref + '.h', 'H', (ref,))
            for q in LOGICAL_X:
                add(f'{ref}.cx{q}.h', 'H', (f'{patch}.d{q}',))
                add(f'{ref}.cx{q}.cz', 'CZ', (ref, f'{patch}.d{q}'))
                add(f'{ref}.cx{q}.restore', 'H', (f'{patch}.d{q}',))
    if signed_sector:
        add('prefix.sector_flip', 'X', (f'{patches[0]}.d0',))
        for i, support in enumerate(Z_CHECKS):
            if 0 in support:
                sectors[patches[0], 'Z', i] = replace(sectors[patches[0], 'Z', i], constant=1)
    observable = Observable('prefix.report', BitExpr((f'{patches[0]}.r2.X0',)), 'real prefix report')
    return PBCProgram(tuple(roles), tuple(ops), tuple(detectors), (observable,), 'actual-encoded-prefix'), sectors


def test_native_cy_order_global_phase_and_two_t_matrix_independently():
    # Control is the first/big-endian bit. All four complex amplitudes matter.
    h = np.array([[1, 1], [1, -1]]) / np.sqrt(2)
    t = np.diag([1, np.exp(1j * np.pi / 4)])
    cz = np.diag([1, 1, 1, -1])
    expected = np.array([[1, 0, 0, 0], [0, 1, 0, 0],
                         [0, 0, 0, -1j], [0, 0, 1j, 0]], dtype=complex)
    actual = np.kron(t @ t, np.eye(2)) @ np.kron(np.eye(2), h) @ cz @ np.kron(np.eye(2), h) @ cz
    assert np.allclose(actual, expected, atol=1e-15)
    assert np.allclose(t @ t, np.diag([1, 1j]), atol=1e-15)
    wrong_order = np.kron(t @ t, np.eye(2)) @ cz @ np.kron(np.eye(2), h) @ cz @ np.kron(np.eye(2), h)
    assert np.linalg.norm(wrong_order - expected) > 2
    pre, sectors = prefix(('A',))
    item = append_mixed_pauli_cat(pre, sectors, PauliProduct((('A', 'Y'),)), data_patches=('A',), rounds=1)
    native = tuple(replace(g, depends_on=()) for g in item.program.operations
                   if g.id.startswith(item.namespace + '.couple0.'))
    matrix = np.column_stack([apply_native_unitaries(PhysicalCircuit(native), v, (item.cat_roles[0], 'A.d0'))
                              for v in np.eye(4, dtype=complex).T])
    assert np.allclose(matrix, expected, atol=1e-15)


@pytest.mark.parametrize('sign', (1, -1))
def test_signed_y_all_32_raw_encoded_choi_branches(sign):
    pre, sectors = prefix(('A',), references=True)
    item = append_mixed_pauli_cat(pre, sectors, PauliProduct((('A', 'Y'),), sign), data_patches=('A',), rounds=1)
    probabilities = [0.0, 0.0]
    for bits in product((0, 1), repeat=5):
        report = verify_mixed_pauli_instruments((item,), reference_roles=('ref.A',), seeds=(7,),
                                               forced_cat_bits=dict(zip(item.cat_measurements, bits)))
        shot, branch = report['shots'][0], report['shots'][0]['branches'][0]
        assert shot['forced_native_probability'] == 1 / 32
        assert branch['semantic_branch'] == (sum(bits) % 2) ^ int(sign == -1)
        assert branch['logical_reference_paulis_checked'] == 16
        assert branch['retained_sector_checks'] == 8
        probabilities[branch['semantic_branch']] += shot['forced_native_probability']
    assert probabilities == [0.5, 0.5]
    assert report['tt_reference_pairs'] == 1
    assert audit_cat_factorized_kraus(item)['raw_branches_checked'] == 32


@pytest.mark.parametrize('sign', (1, -1))
def test_xyz_all_raw_factorization_and_actual_three_reference_choi_probes(sign):
    pre, sectors = prefix(('A', 'B', 'C'), references=True, signed_sector=True)
    item = append_mixed_pauli_cat(pre, sectors, PauliProduct((('A', 'X'), ('B', 'Y'), ('C', 'Z')), sign),
                                 data_patches=('A', 'B', 'C'), rounds=1)
    math = audit_cat_factorized_kraus(item)
    assert math['raw_branches_checked'] == 2048 and math['cat_length'] == 11
    assert math['controlled_factor_matrix_error'] < 1e-14
    assert np.allclose(math['signed_projector_probabilities_on_choi_input'], (0.5, 0.5), atol=1e-14)
    for parity in (0, 1):
        bits = (0,) * 10 + (parity,)
        report = verify_mixed_pauli_instruments((item,), reference_roles=('ref.A', 'ref.B', 'ref.C'), seeds=(19,),
                                               forced_cat_bits=dict(zip(item.cat_measurements, bits)))
        assert report['shots'][0]['branches'][0]['logical_reference_paulis_checked'] == 4096
        assert report['shots'][0]['forced_native_probability'] == 1 / 2048
    assert verify_mixed_pauli_instruments((item,), reference_roles=('ref.A', 'ref.B', 'ref.C'), seeds=(0, 7))['passed']


@pytest.mark.parametrize('branches', tuple(product((0, 1), repeat=2)))
def test_noncommuting_yx_then_yz_reuses_nine_resources_for_all_branches(branches):
    pre, sectors = prefix(('A', 'B'), references=True, signed_sector=True)
    yx = PauliProduct((('A', 'Y'), ('B', 'X')), -1)
    yz = PauliProduct((('A', 'Y'), ('B', 'Z')))
    assert not yx.commutes_with(yz)
    first = append_mixed_pauli_cat(pre, sectors, yx, rounds=1)
    second = append_mixed_pauli_cat(first, first.output_sectors, yz, rounds=1,
                                   cat_roles=first.cat_roles, verifier_role=first.verifier_role, resource_reuse=True)
    forced = {}
    for item, branch in zip((first, second), branches):
        forced.update(zip(item.cat_measurements, (0,) * 7 + (branch ^ int(item.physical_product.sign == -1),)))
    report = verify_mixed_pauli_instruments((first, second), reference_roles=('ref.A', 'ref.B'),
                                           seeds=(7,), forced_cat_bits=forced)
    assert tuple(b['semantic_branch'] for b in report['shots'][0]['branches']) == branches
    assert report['shots'][0]['forced_native_probability'] == 1 / 65536
    assert report['passed'] and report['declared_role_count'] == 45
    assert second.program.roles == first.program.roles
    assert second.program.operations[:second.prefix_gate_count] == first.program.operations
    assert second.namespace != first.namespace
    assert not any(g.gate_type == 'RESET' and g.qubit_ids[0].startswith(('A.d', 'B.d'))
                   for g in second.program.operations[second.prefix_gate_count:])


def test_complete_prefix_raw_history_outputs_and_coupling_boundary_are_preserved():
    pre, sectors = prefix(('A', 'B'), references=True)
    item = append_mixed_pauli_cat(pre, sectors, PauliProduct((('A', 'Y'), ('B', 'X'))), rounds=1)
    compiled, old = item.compile(), lower_to_physical(pre)
    assert compiled.circuit.gates[:len(old.circuit.gates)] == old.circuit.gates
    assert item.program.roles[:len(pre.roles)] == pre.roles
    assert item.program.detectors[:len(pre.detectors)] == pre.detectors
    assert item.program.observables[:len(pre.observables)] == pre.observables
    assert compiled.measurements[:len(old.measurements)] == old.measurements
    tail = item.program.operations[item.prefix_gate_count:]
    phases = {g: p.kind for p in item.phases for g in p.gate_ids}
    coupling = [i for i, g in enumerate(tail) if phases[g.id] == 'data_coupling']
    assert coupling == list(range(min(coupling), max(coupling) + 1))
    assert not any(g.gate_type in ('RESET', 'MEASURE') for g in tail[min(coupling):max(coupling) + 1])
    metadata = item.to_dict()
    assert metadata['native_t_gates'] == 2
    for key in ('tracked_env_t_supported', 'pbc_gate_task_extended', 'physical_executed',
                'fault_tolerance_audited', 'magic_resource_consumed', 'complete_algorithm_encoded'):
        assert metadata[key] is False


@pytest.mark.parametrize('sign', (1, -1))
def test_two_y_factors_keep_both_cat_phases_and_all_1024_raw_branches(sign):
    pre, sectors = prefix(references=True)
    item = append_mixed_pauli_cat(pre, sectors, PauliProduct((('A', 'Y'), ('B', 'Y')), sign), rounds=1)
    algebra = audit_cat_factorized_kraus(item)
    assert algebra['raw_branches_checked'] == 1024
    assert sum(g.gate_type == 'T' for g in item.program.operations) == 4
    for parity in (0, 1):
        report = verify_mixed_pauli_instruments((item,), reference_roles=('ref.A', 'ref.B'), seeds=(7,),
            forced_cat_bits=dict(zip(item.cat_measurements, (0,) * 9 + (parity,))))
        branch = report['shots'][0]['branches'][0]
        assert branch['semantic_branch'] == parity ^ int(sign == -1)
        assert branch['logical_reference_paulis_checked'] == 256 and report['tt_reference_pairs'] == 2


@pytest.mark.parametrize('bad', ('cat', 'syndrome'))
def test_reference_atoms_cannot_alias_resources_or_encoding_auxiliaries(bad):
    pre, sectors = prefix(('A',))
    item = append_mixed_pauli_cat(pre, sectors, PauliProduct((('A', 'Y'),)), data_patches=('A',), rounds=1)
    ref = item.cat_roles[0] if bad == 'cat' else 'A.X0'
    with pytest.raises(ValueError, match='external data roles'):
        verify_mixed_pauli_instruments((item,), reference_roles=(ref,), seeds=(7,))


def test_tracked_env_single_t_remains_rejected_and_report_bits_cannot_be_invented():
    from neutral_atom_env.quantum import StabilizerState
    state = StabilizerState.zero(('Q000',))
    with pytest.raises(ValueError, match='Non-Clifford|non-Clifford'):
        state.apply_gate('T', ('Q000',))
    pre, sectors = prefix(('A',))
    item = append_mixed_pauli_cat(pre, sectors, PauliProduct((('A', 'Y'),)), data_patches=('A',), rounds=1)
    reports = {key: 0 for key in item.verification_measurements}
    reports[item.verification_measurements[0]] = False
    with pytest.raises(ValueError, match='integer bits'):
        item.verification_status(reports)
    with pytest.raises(ValueError, match='actual cat report IDs'):
        verify_mixed_pauli_instruments((item,), seeds=(7,), forced_cat_bits={'invented': 0})


@pytest.mark.parametrize('bad', ('single', 'separated', 'wrong_atom', 'bypass_successor', 'wire_bypass', 'native_s', 'tdg'))
def test_exact_tt_adapter_rejects_nonqualifying_fragments(bad):
    gates = [PhysicalGate('t0', 'T', ('c',)), PhysicalGate('t1', 'T', ('c',), depends_on=('t0',))]
    if bad == 'single':
        gates.pop()
    elif bad == 'separated':
        gates.insert(1, PhysicalGate('interleaved', 'H', ('other',), depends_on=('t0',)))
    elif bad == 'wrong_atom':
        gates[1] = replace(gates[1], qubit_ids=('other',))
    elif bad == 'bypass_successor':
        gates.append(PhysicalGate('leak', 'CZ', ('c', 'data'), depends_on=('t0',)))
    elif bad == 'wire_bypass':
        gates.append(PhysicalGate('leak', 'H', ('c',)))
    else:
        gates = [replace(gates[0], gate_type='S' if bad == 'native_s' else 'Tdg')]
    with pytest.raises(ValueError, match='reference'):
        clifford_reference_steps(PhysicalCircuit(tuple(gates)))


def test_qualifying_tt_adapter_preserves_native_ids_and_allows_only_completed_pair_successors():
    gates = (PhysicalGate('t0', 'T', ('c',)), PhysicalGate('t1', 'T', ('c',), depends_on=('t0',)),
             PhysicalGate('h', 'H', ('c',), depends_on=('t1',)))
    steps = clifford_reference_steps(PhysicalCircuit(gates))
    assert steps[0].gate_type == 'S' and steps[0].native_gate_ids == ('t0', 't1')
    assert gates[0].gate_type == gates[1].gate_type == 'T'


def test_real_cat_fault_is_rejected_before_coupling():
    pre, sectors = prefix(('A',))
    item = append_mixed_pauli_cat(pre, sectors, PauliProduct((('A', 'Y'),)), data_patches=('A',), rounds=1)
    gates = list(item.program.operations)
    pos = next(i for i, g in enumerate(gates) if '.verify.r1.link0.reset' in g.id)
    fault = PhysicalGate('actual.cat.xfault', 'X', (item.cat_roles[0],), depends_on=gates[pos].depends_on)
    gates[pos] = replace(gates[pos], depends_on=(fault.id,))
    gates.insert(pos, fault)
    bad = replace(item, program=replace(item.program, operations=tuple(gates)))
    with pytest.raises(AssertionError, match='verification rejected before'):
        verify_mixed_pauli_instruments((bad,), seeds=(7,))
    with pytest.raises(ValueError, match='pending'):
        item.verification_status({})


def test_wrong_signed_history_is_rejected_by_actual_prefix_replay():
    pre, sectors = prefix(('A',), signed_sector=True)
    sectors['A', 'Z', 2] = replace(sectors['A', 'Z', 2], constant=0)
    item = append_mixed_pauli_cat(pre, sectors, PauliProduct((('A', 'Y'),)), data_patches=('A',), rounds=1)
    with pytest.raises(AssertionError, match='incoming signed sector'):
        verify_mixed_pauli_instruments((item,), seeds=(7,))


@pytest.mark.parametrize('bad', ('partial', 'dirty', 'implicit'))
def test_resource_epoch_rejects_incomplete_or_unreleased_reuse(bad):
    pre, sectors = prefix(('A',))
    word = PauliProduct((('A', 'Y'),))
    first = append_mixed_pauli_cat(pre, sectors, word, data_patches=('A',), rounds=1)
    kwargs = dict(data_patches=('A',), rounds=1, cat_roles=first.cat_roles,
                  verifier_role=first.verifier_role, resource_reuse=bad != 'implicit')
    if bad == 'partial':
        target = first.cat_roles[0]
        ops = tuple(replace(g, gate_type='H') if '.readout.cat0.measure' in g.id else g for g in first.program.operations)
        records = tuple(m for m in first.program.measurements if m.raw_gate_id not in {g.id for g in ops if g.gate_type == 'H'})
        # Existing observable references the removed real measurement: preserve
        # valid output history using an earlier actual report for this fixture.
        old, replacement = first.cat_measurements[0], next(iter(sectors.values())).terms[0]
        obs = tuple(replace(o, expression=BitExpr(tuple(replacement if t == old else t for t in o.expression.terms), o.expression.constant))
                    if old in o.expression.terms else o for o in first.program.observables)
        first = replace(first, program=replace(first.program, operations=ops, measurements=records, observables=obs))
    elif bad == 'dirty':
        g = PhysicalGate('dirty.cat', 'H', (first.cat_roles[0],), depends_on=(first.program.operations[-1].id,))
        first = replace(first, program=replace(first.program, operations=(*first.program.operations, g)))
    with pytest.raises(ValueError, match='Reuse|fresh'):
        append_mixed_pauli_cat(first, first.output_sectors, word, **kwargs)


@pytest.mark.parametrize('bad', ('fake_history', 'pending', 'alias', 'consumed_data', 'orientation'))
def test_invalid_input_contracts_fail_closed(bad):
    pre, sectors = prefix(('A',))
    kwargs = dict(data_patches=('A',), rounds=1)
    if bad == 'fake_history':
        sectors['A', 'X', 0] = BitExpr(('fake-or-future',))
    elif bad == 'pending':
        kwargs['pending_operations'] = ('uncommitted',)
    elif bad == 'alias':
        kwargs['cat_roles'] = ('A.d0', 'c1', 'c2', 'c3', 'c4')
    elif bad == 'consumed_data':
        op = GateTask('consumed', 'MEASURE', ('A.d0',), (pre.operations[-1].id,))
        pre = replace(pre, operations=(*pre.operations, op))
    else:
        pre = replace(pre, roles=tuple(replace(r, local=99) if r.id == 'A.d0' else r for r in pre.roles))
    with pytest.raises(ValueError):
        append_mixed_pauli_cat(pre, sectors, PauliProduct((('A', 'Y'),)), **kwargs)


def test_thirteen_patch_joint_structure_has_sixty_three_cat_atoms_without_alias_or_false_audit():
    patches = tuple(f'P{i:02d}' for i in range(13))
    pre, sectors = prefix(patches)
    item = append_mixed_pauli_cat(pre, sectors, PauliProduct(tuple((p, 'Y' if i < 12 else 'Z') for i, p in enumerate(patches)), -1),
                                 data_patches=patches, rounds=1)
    compiled = item.compile()
    assert len(item.cat_roles) == 63 and len(item.program.roles) == 13 * 17 + 64
    assert len(set(dict(compiled.bindings).values())) == len(item.program.roles)
    assert len(clifford_reference_steps(compiled.circuit)) > 0
    assert sum(g.gate_type == 'T' for g in item.program.operations) == 24
    with pytest.raises(ValueError, match='six logical'):
        verify_mixed_pauli_instruments((item,), seeds=(7,))
    with pytest.raises(ValueError, match='at most 16'):
        audit_cat_factorized_kraus(item)


def test_all_raw_proof_rejects_actual_readout_release_extra_coupling_and_sidecar_mutations():
    pre, sectors = prefix(('A',))
    item = append_mixed_pauli_cat(pre, sectors, PauliProduct((('A', 'Y'),)), data_patches=('A',), rounds=1)
    assert audit_cat_factorized_kraus(item)['actual_native_readout_bras_contracted']
    for mutation in ('h_to_z', 'missing_h', 'reset_before_measure', 'extra_coupling', 'verification_cz', 'report_flip'):
        gates, phases, records = list(item.program.operations), list(item.phases), item.program.measurements
        hpos = next(i for i, g in enumerate(gates) if '.readout.cat0.h' in g.id)
        if mutation in ('h_to_z', 'reset_before_measure'):
            gates[hpos] = replace(gates[hpos], gate_type='Z' if mutation == 'h_to_z' else 'RESET')
        elif mutation == 'missing_h':
            removed = gates.pop(hpos)
            gates[hpos] = replace(gates[hpos], depends_on=removed.depends_on)
            phases = [p for p in phases if removed.id not in p.gate_ids]
        elif mutation == 'extra_coupling':
            pos = next(i for i, g in enumerate(gates) if '.couple0.z' in g.id)
            fault = PhysicalGate(item.namespace + '.couple0.extra', 'X', ('A.d0',), depends_on=(gates[pos].id,))
            gates[pos + 1] = replace(gates[pos + 1], depends_on=(fault.id,))
            gates.insert(pos + 1, fault)
            phasepos = next(i for i, p in enumerate(phases) if gates[pos].id in p.gate_ids)
            phases.insert(phasepos + 1, replace(phases[phasepos], id=fault.id, gate_ids=(fault.id,), depends_on=fault.depends_on))
        elif mutation == 'verification_cz':
            pos = next(i for i, g in enumerate(gates) if '.verify.r1.link0.left.cz' in g.id)
            gates[pos] = replace(gates[pos], qubit_ids=(item.cat_roles[1], item.verifier_role))
        else:
            records = tuple(replace(m, bit_flip=1) if m.result_id == item.cat_measurements[0] else m for m in records)
        changed = replace(item, program=replace(item.program, operations=tuple(gates), measurements=records), phases=tuple(phases))
        with pytest.raises(ValueError, match='native cat fragment|sidecar'):
            audit_cat_factorized_kraus(changed)
