"""Independent signed Choi checks of real native cat circuits and lifetimes."""
from dataclasses import replace
from itertools import product

import pytest

stim = pytest.importorskip('stim', reason='optional pinned native Clifford instrument audit')
from neutral_atom_experiments.qec_pbc.canonical import canonical_memory_program
from neutral_atom_experiments.qec_pbc.ir import BitExpr, GateTask, PBCProgram, Role
from neutral_atom_experiments.qec_pbc.mixed_xz_cat import append_mixed_xz_cat, verify_mixed_xz_instruments
from neutral_atom_experiments.qec_pbc.pauli import PauliProduct
from neutral_atom_experiments.surface_ghz import LOGICAL_X, LOGICAL_Z, Z_CHECKS


XZ = PauliProduct((('A', 'X'), ('B', 'Z')))
ZZ = PauliProduct((('A', 'Z'), ('B', 'Z')))


def prepared_prefix(bases=('Z', 'Z'), signs=(0, 0), *, references=False, signed_sector=False):
    roles, operations, detectors, sectors = [], [], [], {}
    for patch, basis in zip(('A', 'B'), bases):
        memory = canonical_memory_program(basis=basis, rounds=2, patch=patch)
        roles.extend(memory.program.roles)
        operations.extend(op for op in memory.program.operations if not op.id.startswith(f'{patch}.final.'))
        detectors.extend(d for d in memory.program.detectors if d.boundary != 'destructive_readout')
        for kind in ('X', 'Z'):
            for check in range(4):
                sectors[patch, kind, check] = BitExpr((f'{patch}.r2.{kind}{check}',))
    frontier = (operations[-1].id,)
    def add(key, kind, targets):
        nonlocal frontier
        operations.append(GateTask(key, kind, tuple(targets), frontier))
        frontier = (key,)
    for patch, basis, sign in zip(('A', 'B'), bases, signs):
        if sign:
            kind = 'X' if basis == 'Z' else 'Z'
            for q in LOGICAL_X if kind == 'X' else LOGICAL_Z:
                add(f'{patch}.sign.{q}', kind, (f'{patch}.d{q}',))
    if references:
        for patch, basis in zip(('A', 'B'), bases):
            reference = f'ref.{patch}'
            roles.append(Role(reference, 'data'))
            add(f'{reference}.reset', 'RESET', (reference,))
            add(f'{reference}.h', 'H', (reference,))
            for q in LOGICAL_X if basis == 'Z' else LOGICAL_Z:
                if basis == 'Z':
                    add(f'{reference}.cx{q}.h', 'H', (f'{patch}.d{q}',))
                add(f'{reference}.cx{q}.cz', 'CZ', (reference, f'{patch}.d{q}'))
                if basis == 'Z':
                    add(f'{reference}.cx{q}.restore', 'H', (f'{patch}.d{q}',))
    if signed_sector:
        add('prefix.sector_flip', 'X', ('A.d0',))
        for check, support in enumerate(Z_CHECKS):
            if 0 in support:
                sectors['A', 'Z', check] = replace(sectors['A', 'Z', check], constant=1)
    return PBCProgram(tuple(roles), tuple(operations), tuple(detectors), name='real-native-encoded-prefix'), sectors


@pytest.mark.parametrize('sign', (1, -1))
def test_all_64_raw_readout_choi_branches_equal_signed_projector(sign):
    prefix, sectors = prepared_prefix(references=True)
    item = append_mixed_xz_cat(prefix, sectors, replace(XZ, sign=sign), rounds=1)
    parity_probabilities = [0.0, 0.0]
    for bits in product((0, 1), repeat=6):
        report = verify_mixed_xz_instruments((item,), reference_roles=('ref.A', 'ref.B'), seeds=(7,),
                                            forced_cat_bits=dict(zip(item.cat_measurements, bits)))
        shot, branch = report['shots'][0], report['shots'][0]['branches'][0]
        assert shot['forced_native_probability'] == 1 / 64
        assert branch['semantic_branch'] == (sum(bits) % 2) ^ int(sign == -1)
        assert branch['branch_probability_given_prefix'] == 1 / 2
        assert branch['logical_reference_paulis_checked'] == 256
        assert branch['retained_sector_checks'] == 16
        assert branch['verification']['accepted']
        parity_probabilities[branch['semantic_branch']] += shot['forced_native_probability']
    assert parity_probabilities == [1 / 2, 1 / 2]
    assert report['input_state_replaced'] is False and report['physical_executed'] is False


@pytest.mark.parametrize('branches', tuple(product((0, 1), repeat=2)))
def test_noncommuting_sequence_recycles_same_seven_resources_for_all_branches(branches):
    assert not XZ.commutes_with(ZZ)
    prefix, sectors = prepared_prefix(references=True, signed_sector=True)
    first = append_mixed_xz_cat(prefix, sectors, replace(XZ, sign=-1), rounds=1)
    second = append_mixed_xz_cat(first.program, first.output_sectors, ZZ, rounds=1,
                                cat_roles=first.cat_roles, verifier_role=first.verifier_role,
                                resource_reuse=True)
    assert len(second.program.roles) == 43 and second.program.roles == first.program.roles
    assert second.namespace != first.namespace
    assert all(a is b for a, b in zip(second.program.operations, first.program.operations))
    forced = {}
    for item, branch in zip((first, second), branches):
        forced.update(zip(item.cat_measurements, (0, 0, 0, 0, 0, branch ^ int(item.logical_product.sign == -1))))
    report = verify_mixed_xz_instruments((first, second), reference_roles=('ref.A', 'ref.B'), seeds=(19,), forced_cat_bits=forced)
    shot = report['shots'][0]
    assert tuple(b['semantic_branch'] for b in shot['branches']) == branches
    assert all(b['branch_probability_given_prefix'] == 1 / 2 for b in shot['branches'])
    assert shot['forced_native_probability'] == 1 / 4096
    tail = second.program.operations[second.prefix_operation_count:]
    assert {op.targets[0] for op in tail if '.prepare.reset' in op.id} == {*first.cat_roles, first.verifier_role}
    assert not any(op.gate_type == 'RESET' and any(q.startswith(('A.d', 'B.d')) for q in op.targets) for op in tail)


@pytest.mark.parametrize('bases,signs', ((('Z', 'Z'), (1, 0)), (('X', 'X'), (1, 1)), (('Z', 'X'), (0, 1))))
def test_actual_signed_prefix_sectors_and_input_states(bases, signs):
    prefix, sectors = prepared_prefix(bases, signs, signed_sector=True)
    item = append_mixed_xz_cat(prefix, sectors, replace(XZ, sign=-1), rounds=1)
    report = verify_mixed_xz_instruments((item,), seeds=(0, 7))
    assert report['passed']
    assert any(d.expression.constant for d in item.program.detectors if d.boundary == 'incoming_measured_sector')


def test_native_gate_sidecar_dependencies_and_report_bits_are_complete():
    from collections import Counter
    prefix, sectors = prepared_prefix()
    item = append_mixed_xz_cat(prefix, sectors, XZ)
    compiled = item.compile()
    tail = compiled.circuit.gates[len(prefix.operations):]
    assert Counter(g.gate_type for g in tail) == {'H': 735, 'CZ': 319, 'RESET': 129, 'MEASURE': 112}
    assert len(tail) == 1295
    assert {c.native_cz_id for c in item.couplings} == {g.id for g in tail if g.gate_type == 'CZ'}
    assert len([d for d in item.program.detectors if d.id.startswith(item.namespace + '.')]) == 106
    gates = {g.id: g for g in compiled.circuit.gates}
    def ancestors(gid):
        found, pending = set(), list(gates[gid].depends_on)
        while pending:
            key = pending.pop()
            if key not in found:
                found.add(key)
                pending.extend(gates[key].depends_on)
        return found
    assert {key + '__g000' for key in item.verification_measurements} <= ancestors(item.coupling_entry_id + '__g000')
    assert {op.id for op in prefix.operations} <= {op.id for op in item.program.operations}
    assert item.program.operations[:item.prefix_operation_count] == prefix.operations
    output = next(o for o in item.program.observables if o.id == item.observable_id)
    assert output.expression.terms == item.cat_measurements
    assert not any(g.condition for g in tail)
    metadata = item.to_dict()
    assert metadata['verification']['runtime_abort_implemented'] is False
    assert metadata['fault_tolerance_audited'] is False


def test_verification_reports_reject_nonzero_and_missing_bits_without_hidden_controller():
    prefix, sectors = prepared_prefix()
    item = append_mixed_xz_cat(prefix, sectors, XZ, rounds=1)
    reports = {key: 0 for key in item.verification_measurements}
    assert item.verification_status(reports)['accepted']
    reports[item.verification_measurements[0]] = 1
    status = item.verification_status(reports)
    assert status['status'] == 'rejected' and status['before_operation'] == item.coupling_entry_id
    assert status['runtime_abort_implemented'] is False and status['retry_implemented'] is False
    reports.pop(item.verification_measurements[-1])
    with pytest.raises(ValueError, match='pending'):
        item.verification_status(reports)
    reports[item.verification_measurements[-1]] = False
    with pytest.raises(ValueError, match='integer'):
        item.verification_status(reports)


@pytest.mark.parametrize('bad', ('Y', 'identity', 'unknown_patch', 'physical_data', 'same_patch', 'missing_sector', 'fake_sector', 'constant_only', 'pending', 'dirty_syndrome', 'consumed_data', 'wrong_role'))
def test_invalid_input_contracts_fail_closed(bad):
    prefix, sectors = prepared_prefix()
    word, kwargs = XZ, {'rounds': 1}
    if bad == 'Y':
        word = PauliProduct((('A', 'Y'), ('B', 'Z')))
    elif bad == 'identity':
        word = PauliProduct(())
    elif bad == 'unknown_patch':
        word = PauliProduct((('C', 'X'),))
    elif bad == 'physical_data':
        word = PauliProduct((('A.d0', 'X'),))
    elif bad == 'same_patch':
        kwargs['data_patches'] = ('A', 'A')
    elif bad == 'missing_sector':
        sectors.pop(('A', 'X', 0))
    elif bad == 'fake_sector':
        sectors['A', 'X', 0] = BitExpr(('future-or-external-result',))
    elif bad == 'constant_only':
        sectors['A', 'X', 0] = BitExpr((), 1)
    elif bad == 'pending':
        kwargs['pending_operations'] = ('uncommitted-native-gate',)
    elif bad in ('dirty_syndrome', 'consumed_data'):
        op = GateTask('prefix.dirty', 'H' if bad == 'dirty_syndrome' else 'MEASURE',
                      ('A.X0' if bad == 'dirty_syndrome' else 'A.d0',), (prefix.operations[-1].id,))
        prefix = replace(prefix, operations=(*prefix.operations, op))
    else:
        prefix = replace(prefix, roles=tuple(replace(r, local=99) if r.id == 'A.d0' else r for r in prefix.roles))
    with pytest.raises(ValueError):
        append_mixed_xz_cat(prefix, sectors, word, **kwargs)


@pytest.mark.parametrize('bad', ('alias_data', 'alias_verifier', 'wrong_length', 'implicit_reuse', 'fresh_reuse', 'dirty_cat', 'dirty_verifier', 'boolean'))
def test_resource_lifecycle_is_explicit_and_rejects_aliases_and_unreleased_atoms(bad):
    prefix, sectors = prepared_prefix()
    first = append_mixed_xz_cat(prefix, sectors, XZ, rounds=1)
    kwargs = {'rounds': 1}
    if bad == 'alias_data':
        kwargs['cat_roles'] = ('A.d0', 'c1', 'c2', 'c3', 'c4', 'c5')
    elif bad == 'alias_verifier':
        kwargs['cat_roles'], kwargs['verifier_role'] = ('c0', 'c1', 'c2', 'c3', 'c4', 'c5'), 'c0'
    elif bad == 'wrong_length':
        kwargs['cat_roles'] = ('c0',)
    elif bad == 'fresh_reuse':
        kwargs['resource_reuse'] = True
    elif bad == 'boolean':
        kwargs['resource_reuse'] = 1
    else:
        prefix, sectors = first.program, first.output_sectors
        kwargs.update(cat_roles=first.cat_roles, verifier_role=first.verifier_role)
        if bad != 'implicit_reuse':
            kwargs['resource_reuse'] = True
            target = first.cat_roles[0] if bad == 'dirty_cat' else first.verifier_role
            op = GateTask('resource.dirty', 'H', (target,), (prefix.operations[-1].id,))
            prefix = replace(prefix, operations=(*prefix.operations, op))
    with pytest.raises(ValueError):
        append_mixed_xz_cat(prefix, sectors, XZ, **kwargs)


def test_wrong_signed_sector_detected_by_actual_native_replay():
    prefix, sectors = prepared_prefix(signed_sector=True)
    sectors['A', 'Z', 2] = replace(sectors['A', 'Z', 2], constant=0)
    item = append_mixed_xz_cat(prefix, sectors, XZ, rounds=1)
    with pytest.raises(AssertionError, match='incoming measured sector'):
        verify_mixed_xz_instruments((item,), seeds=(0,))


def test_nonencoded_input_cannot_be_silently_projected_into_an_accepted_input():
    prefix, sectors = prepared_prefix()
    dirty = GateTask('prefix.nonencoded_h', 'H', ('A.d0',), (prefix.operations[-1].id,))
    prefix = replace(prefix, operations=(*prefix.operations, dirty))
    item = append_mixed_xz_cat(prefix, sectors, XZ, rounds=1)
    with pytest.raises(AssertionError, match='codespace'):
        verify_mixed_xz_instruments((item,), seeds=(7,))


def test_real_cat_verifier_nonzero_is_rejected_at_pre_data_boundary():
    prefix, sectors = prepared_prefix()
    item = append_mixed_xz_cat(prefix, sectors, XZ, rounds=1)
    operations = list(item.program.operations)
    location = next(i for i, op in enumerate(operations) if '.verify.r1.link0.reset' in op.id)
    fault = GateTask(item.namespace + '.test.cat_x_fault', 'X', (item.cat_roles[0],), (operations[location - 1].id,))
    operations.insert(location, fault)
    altered = replace(item, program=replace(item.program, operations=tuple(operations)))
    with pytest.raises(AssertionError, match='verification rejected before data coupling'):
        verify_mixed_xz_instruments((altered,), seeds=(7,))


def test_measurement_from_an_older_resource_epoch_is_not_a_release_certificate():
    prefix, sectors = prepared_prefix()
    first = append_mixed_xz_cat(prefix, sectors, XZ, rounds=1)
    h = GateTask('resource.new_unread_epoch.h', 'H', (first.cat_roles[0],), (first.program.operations[-1].id,))
    reset = GateTask('resource.new_unread_epoch.reset', 'RESET', (first.cat_roles[0],), (h.id,))
    dirty = replace(first.program, operations=(*first.program.operations, h, reset))
    with pytest.raises(ValueError, match='real destructive measurement'):
        append_mixed_xz_cat(dirty, first.output_sectors, XZ, rounds=1, cat_roles=first.cat_roles,
                            verifier_role=first.verifier_role, resource_reuse=True)


def test_choi_prefix_has_two_real_maximally_entangled_logical_reference_pairs():
    prefix, _ = prepared_prefix(references=True)
    from neutral_atom_experiments.qec_pbc.lowering import lower_to_physical
    compiled = lower_to_physical(prefix)
    index = {role: i for i, (role, _) in enumerate(compiled.bindings)}
    qindex = {qubit: index[role] for role, qubit in compiled.bindings}
    actual = stim.TableauSimulator(seed=7)
    actual.set_num_qubits(len(index))
    for gate in compiled.circuit.gates:
        circuit = stim.Circuit()
        circuit.append({'RESET': 'R', 'MEASURE': 'M'}.get(gate.gate_type, gate.gate_type),
                       [qindex[q] for q in gate.qubit_ids])
        actual.do(circuit)
    for patch in ('A', 'B'):
        for kind, support in (('X', LOGICAL_X), ('Z', LOGICAL_Z)):
            word = stim.PauliString(len(index))
            word[index[f'ref.{patch}']] = kind
            for q in support:
                word[index[f'{patch}.d{q}']] = kind
            assert actual.peek_observable_expectation(word) == 1


def test_single_patch_factor_remains_nontrivial_and_uses_four_resource_roles():
    prefix, sectors = prepared_prefix(references=True)
    item = append_mixed_xz_cat(prefix, sectors, PauliProduct((('A', 'X'),), -1), rounds=1)
    assert len(item.cat_roles) == 3 and len(item.program.roles) == 40
    assert verify_mixed_xz_instruments((item,), reference_roles=('ref.A', 'ref.B'), seeds=(7,))['passed']


@pytest.mark.parametrize('bad', ('data', 'cat', 'unknown', 'duplicate'))
def test_reference_audit_requires_actual_external_data_roles(bad):
    prefix, sectors = prepared_prefix(references=True)
    item = append_mixed_xz_cat(prefix, sectors, XZ, rounds=1)
    refs = {'data': ('A.d0',), 'cat': (item.cat_roles[0],),
            'unknown': ('unknown.reference',), 'duplicate': ('ref.A', 'ref.A')}[bad]
    with pytest.raises(ValueError, match='reference|Reference'):
        verify_mixed_xz_instruments((item,), reference_roles=refs, seeds=(7,))
