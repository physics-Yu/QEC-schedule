"""Real encoded prefix states, signed sectors and consecutive parity channels."""
from dataclasses import replace
import pytest

pytest.importorskip('stim', reason='optional pinned native Clifford audit')
from neutral_atom_experiments.surface_ghz import LOGICAL_X, LOGICAL_Z, Z_CHECKS
from neutral_atom_experiments.qec_pbc.canonical import canonical_memory_program
from neutral_atom_experiments.qec_pbc.encoded_composition import append_encoded_parity, verify_composed_instruments
from neutral_atom_experiments.qec_pbc.ir import BitExpr, GateTask, PBCProgram, Role


def prepared_prefix(bases=('Z', 'Z'), signs=(0, 0), *, references=False, signed_sector=False):
    roles, operations, detectors = [], [], []
    sectors = {}
    for patch, basis in zip(('A', 'B'), bases):
        template = canonical_memory_program(basis=basis, rounds=2, patch=patch)
        roles.extend(template.program.roles)
        operations.extend(op for op in template.program.operations if not op.id.startswith(f'{patch}.final.'))
        detectors.extend(d for d in template.program.detectors if d.boundary != 'destructive_readout')
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
    return PBCProgram(tuple(roles), tuple(operations), tuple(detectors), name='actual-encoded-prefix'), sectors


@pytest.mark.parametrize('basis', ('Z', 'X'))
@pytest.mark.parametrize('bases,signs', ((('Z', 'Z'), (0, 0)), (('X', 'X'), (1, 0)), (('Z', 'X'), (1, 1))))
def test_multiple_actual_prefix_states_preserved_without_data_repreparation(basis, bases, signs):
    prefix, sectors = prepared_prefix(bases, signs, signed_sector=True)
    composed = append_encoded_parity(prefix, sectors, basis=basis, parity_sign=-1)
    assert composed.program.roles[:len(prefix.roles)] == prefix.roles
    assert composed.program.operations[:len(prefix.operations)] == prefix.operations
    assert all(a is b for a, b in zip(composed.program.operations, prefix.operations))
    tail = composed.program.operations[len(prefix.operations):]
    assert not any(op.gate_type == 'RESET' and any(q.startswith(('A.d', 'B.d')) for q in op.targets) for op in tail)
    assert not any('prepare' in op.id and any(q.startswith(('A.', 'B.')) for q in op.targets) for op in tail)
    detectors = [d for d in composed.program.detectors if d.boundary == 'incoming_measured_sector']
    assert len(detectors) == 16
    assert any(d.expression.constant for d in detectors)
    report = verify_composed_instruments((composed,), seeds=(0, 7))
    assert report['passed'] and report['input_state_replaced'] is False


@pytest.mark.parametrize('first,second', (('Z', 'X'), ('X', 'Z'), ('Z', 'Z'), ('X', 'X')))
def test_two_consecutive_parities_retain_choi_reference_and_signed_sectors(first, second):
    prefix, sectors = prepared_prefix(('Z', 'X'), (1, 0), references=True, signed_sector=True)
    one = append_encoded_parity(prefix, sectors, basis=first, ancilla_patch='C', parity_sign=-1)
    two = append_encoded_parity(one.program, one.output_sectors, basis=second, ancilla_patch='C2')
    assert one.namespace != two.namespace
    assert two.program.operations[:two.prefix_operation_count] == one.program.operations
    assert len(two.program.roles) == 70
    report = verify_composed_instruments((one, two), reference_roles=('ref.A', 'ref.B'), seeds=(0, 7, 19))
    assert report['passed'] and report['prefix_state_replayed']
    for shot in report['shots']:
        assert len(shot['branches']) == 2
        assert all(branch['logical_reference_paulis_checked'] == 256 for branch in shot['branches'])
        assert all(branch['retained_sector_checks'] == 16 for branch in shot['branches'])
    assert report['physical_executed'] is False


def test_output_history_and_all_measurement_dependencies_are_real():
    prefix, sectors = prepared_prefix()
    composed = append_encoded_parity(prefix, sectors)
    measurement_ids = {op.id for op in composed.program.operations if op.gate_type == 'MEASURE'}
    assert all(set(expr.terms) <= measurement_ids for expr in composed.output_sectors.values())
    assert all(set(d.expression.terms) <= measurement_ids for d in composed.program.detectors)
    compiled = composed.compile()
    seen = set()
    for gate in compiled.circuit.gates:
        assert set(gate.depends_on) <= seen
        seen.add(gate.id)
    assert {c.native_cz_id for c in composed.couplings} <= seen
    assert composed.to_dict()['complete_algorithm_encoded'] is False


@pytest.mark.parametrize('bad', ('missing', 'fake', 'constant_only'))
def test_missing_or_fabricated_sector_history_is_rejected(bad):
    prefix, sectors = prepared_prefix()
    if bad == 'missing':
        sectors.pop(('A', 'X', 0))
    elif bad == 'fake':
        sectors['A', 'X', 0] = BitExpr(('external.result.not.measured',))
    else:
        sectors['A', 'X', 0] = BitExpr((), 0)
    with pytest.raises(ValueError, match='sectors|prefix measurements'):
        append_encoded_parity(prefix, sectors)


def test_consumed_resource_reuse_is_rejected():
    prefix, sectors = prepared_prefix()
    first = append_encoded_parity(prefix, sectors)
    with pytest.raises(ValueError, match='must be fresh'):
        append_encoded_parity(first.program, first.output_sectors, ancilla_patch='C')


def test_unreleased_syndrome_auxiliary_is_rejected_without_implicit_reset():
    prefix, sectors = prepared_prefix()
    operation = GateTask('prefix.ancilla_dirty', 'H', ('A.X0',), (prefix.operations[-1].id,))
    dirty = replace(prefix, operations=(*prefix.operations, operation))
    with pytest.raises(ValueError, match='reset/released'):
        append_encoded_parity(dirty, sectors)


def test_wrong_signed_sector_is_detected_in_native_replay():
    prefix, sectors = prepared_prefix(signed_sector=True)
    sectors['A', 'Z', 2] = replace(sectors['A', 'Z', 2], constant=0)
    composed = append_encoded_parity(prefix, sectors)
    with pytest.raises(AssertionError, match='incoming/transported sector'):
        verify_composed_instruments((composed,), seeds=(0,))


@pytest.mark.parametrize('first_basis,second_basis', (('Z', 'X'), ('X', 'Z'), ('Z', 'Z'), ('X', 'X')))
def test_explicit_joint_resource_reuse_reprepares_same_patch_and_preserves_channel(first_basis, second_basis):
    prefix, sectors = prepared_prefix(('Z', 'X'), (1, 0), references=True, signed_sector=True)
    first = append_encoded_parity(prefix, sectors, basis=first_basis, ancilla_patch='C', parity_sign=-1)
    second = append_encoded_parity(first.program, first.output_sectors, basis=second_basis,
                                    ancilla_patch='C', resource_reuse=True)
    assert second.program.roles == first.program.roles
    assert len(second.program.roles) == 53
    assert second.resource_reused and second.namespace != first.namespace
    assert second.program.operations[:second.prefix_operation_count] == first.program.operations
    reset_phase = next(phase for phase in second.phases if phase.kind == 'initialize_reset')
    tail_map = {op.id: op for op in second.program.operations[second.prefix_operation_count:]}
    reset_targets = {tail_map[key].targets[0] for key in reset_phase.gate_ids}
    assert reset_targets == {role.id for role in first.program.roles if role.patch == 'C'}
    assert not any(op.gate_type == 'RESET' and any(q.startswith(('A.d', 'B.d')) for q in op.targets) for op in tail_map.values())
    if second_basis == 'X':
        prepare = next(phase for phase in second.phases if phase.kind == 'data_prepare_h')
        assert {tail_map[key].targets[0] for key in prepare.gate_ids} == {f'C.d{i}' for i in range(9)}
    report = verify_composed_instruments((first, second), reference_roles=('ref.A', 'ref.B'), seeds=(0, 7, 19))
    assert report['passed'] and report['input_state_replaced'] is False
    assert all(branch['logical_reference_paulis_checked'] == 256 for shot in report['shots'] for branch in shot['branches'])
    assert second.to_dict()['resource_epoch'] != first.to_dict()['resource_epoch']
    assert second.to_dict()['magic_factory_reuse'] is False


def _remove_readout(program, removed):
    operations = tuple(op for op in program.operations if op.id not in removed)
    measured = {op.id for op in operations if op.gate_type == 'MEASURE'}
    return replace(program, operations=operations,
                   detectors=tuple(d for d in program.detectors if set(d.expression.terms) <= measured),
                   observables=tuple(o for o in program.observables if set(o.expression.terms) <= measured))


@pytest.mark.parametrize('incomplete', ('one_data', 'all_data', 'syndrome'))
def test_resource_reuse_rejects_partial_unconsumed_or_unreleased_patch(incomplete):
    prefix, sectors = prepared_prefix()
    first = append_encoded_parity(prefix, sectors)
    program = first.program
    if incomplete == 'one_data':
        program = _remove_readout(program, {f'{first.namespace}.C.final.m8'})
    elif incomplete == 'all_data':
        program = _remove_readout(program, {f'{first.namespace}.C.final.m{i}' for i in range(9)})
    else:
        dirty = GateTask('resource.syndrome_dirty', 'H', ('C.X0',), (program.operations[-1].id,))
        program = replace(program, operations=(*program.operations, dirty))
    with pytest.raises(ValueError, match='destructive MEASURE/RESET|syndrome auxiliary'):
        append_encoded_parity(program, first.output_sectors, resource_reuse=True)


def test_resource_reuse_requires_existing_complete_canonical_roles_and_boolean():
    prefix, sectors = prepared_prefix()
    with pytest.raises(ValueError, match='existing complete canonical'):
        append_encoded_parity(prefix, sectors, resource_reuse=True)
    with pytest.raises(ValueError, match='explicit boolean'):
        append_encoded_parity(prefix, sectors, resource_reuse=1)
    first = append_encoded_parity(prefix, sectors)
    changed = replace(first.program, roles=tuple(replace(role, local=10) if role.id == 'C.d0' else role for role in first.program.roles))
    with pytest.raises(ValueError, match='complete canonical'):
        append_encoded_parity(changed, first.output_sectors, resource_reuse=True)
