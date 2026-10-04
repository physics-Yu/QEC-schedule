"""Source identity, dependency, geometry and timing checks at native lowering."""
from hashlib import sha256
from copy import deepcopy
from dataclasses import replace
import json
from math import sqrt

import pytest

from neutral_atom_kernel import GateSpec, KernelExecutor, Operation
from neutral_atom_strategies.native_kernel.compiler import (ARCHITECTURE_SOURCE, ENGINE,
    ILLUMINATION_CONTRACT, MOTION_CONTRACT, NATIVE_SCHEDULE_CONTRACT, OUTPUT_SCHEMA,
    PINNED_QMAP_VERSION, TIMING_PROFILE, _contracts, _frontiers, _request_manifest, _source_sha256)
from neutral_atom_strategies.native_kernel import (finalize_operations, lower_native,
    parse_naviz, schedule_operations)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def result(code, gates, *, atom_ids=('Q000', 'Q001'), completed=(), architecture=None):
    architecture = deepcopy(architecture or {'arch_range': [[-20, -30], [200, 200]],
        'rydberg_range': [[[-20, 50], [200, 100]]]})
    contract = _contracts(gates, atom_ids)
    mapping = {f'atom{i}': q for i, q in enumerate(atom_ids)}
    initial, _ = parse_naviz(code)
    versions = {'mqt.qmap': PINNED_QMAP_VERSION, 'mqt.core': '3.3.3', 'qiskit': '2.2.3'}
    source_sha = _source_sha256()
    manifest = _request_manifest(block_id='test', atom_ids=atom_ids, contracts=contract,
        architecture=architecture, external=completed, boundaries=(),
        dependency_mode='explicit-global-frontiers', routing='strict', reuse_level=0.,
        versions=versions, compiler_source_sha256=source_sha,
        native_gate_order=(g['id'] for g in contract))
    return dict(schema=OUTPUT_SCHEMA, status='compiled',
        engine=ENGINE, block_id='test', code=code,
        naviz_sha256=sha256(code.encode()).hexdigest(), architecture=architecture,
        architecture_sha256=sha256(_canonical(architecture).encode()).hexdigest(),
        architecture_source=ARCHITECTURE_SOURCE,
        gate_contract=contract, gate_contract_sha256=sha256(_canonical(contract).encode()).hexdigest(),
        atom_mapping=mapping, initial_positions={mapping[q]: p for q, p in initial.items()},
        completed_dependencies=list(completed), versions=versions,
        request_manifest=manifest, request_sha256=sha256(_canonical(manifest).encode()).hexdigest(),
        compiler_source_sha256=source_sha, dependency_mode='explicit-global-frontiers',
        barrier_before=[], routing='strict', reuse_level=0., timing_profile=TIMING_PROFILE,
        native_schedule_contract=NATIVE_SCHEDULE_CONTRACT,
        illumination_contract=ILLUMINATION_CONTRACT, motion_contract=MOTION_CONTRACT)


GATES = (GateSpec('source.h0', 'H', ('Q000',)), GateSpec('source.h1', 'H', ('Q001',)),
         GateSpec('source.cz', 'CZ', ('Q000', 'Q001'), ('source.h0', 'source.h1')),
         GateSpec('source.t', 'T', ('Q001',), ('source.cz',)))
PROGRAM = '''atom (0.000, 0.000) atom0
atom (10.000, 0.000) atom1
@+ u 1.57080 0.00000 3.14159 atom0
@+ u 1.57080 0.00000 3.14159 atom1
@+ load [
atom0
atom1
]
@+ move [
(0.000, 60.000) atom0
(5.000, 60.000) atom1
]
@+ store [
atom0
atom1
]
@+ cz zone_cz0
@+ rz 0.78540 atom1
'''


def test_exact_source_ids_zone_and_project_move_timing():
    program = lower_native(result(PROGRAM, GATES), GATES)
    assert [op.kind for op in program.operations] == ['GATE', 'GATE', 'LOAD', 'MOVE', 'STORE', 'CZ', 'GATE']
    assert [gid for op in program.operations for gid in op.gate_ids] == [g.id for g in GATES]
    move = program.operations[3]
    assert move.duration_us == pytest.approx(200 * sqrt(60 / 110))
    assert move.positions == (('Q000', (0., 60.)), ('Q001', (5., 60.)))
    pulse = program.operations[5]
    assert pulse.duration_us == .36
    assert pulse.metadata['zone_ids'] == ('zone_cz0',)
    assert pulse.metadata['cz_pairs'] == (('Q000', 'Q001'),)
    assert pulse.metadata['source_line'] == 17
    assert pulse.metadata['bound_positions_before'] == (('Q000', (0., 60.)), ('Q001', (5., 60.)))
    assert dict(program.final_positions) == {'Q000': (0., 60.), 'Q001': (5., 60.)}


def test_cross_wire_dependency_does_not_merge_into_one_native_pulse():
    gates = (GateSpec('first', 'H', ('Q000',)), GateSpec('second', 'H', ('Q001',), ('first',)))
    code = '''atom (0, 0) atom0
atom (10, 0) atom1
@+ u 1.57080 0 3.14159 [
atom0
atom1
]
'''
    with pytest.raises(ValueError, match='unmet dependency'):
        lower_native(result(code, gates))


def test_cross_wire_dependency_native_order_is_checked():
    gates = (GateSpec('first', 'H', ('Q000',)), GateSpec('second', 'H', ('Q001',), ('first',)))
    code = 'atom (0, 0) atom0\natom (10, 0) atom1\n@+ u 1.57080 0 3.14159 atom1\n@+ u 1.57080 0 3.14159 atom0\n'
    with pytest.raises(ValueError, match='unmet dependency'):
        lower_native(result(code, gates))


def test_incidental_spectator_pair_is_not_invented_as_a_gate():
    with pytest.raises(ValueError, match='unintended'):
        lower_native(result(PROGRAM, GATES), initial_positions={
            'Q000': (0., 0.), 'Q001': (10., 0.), 'spectator': (10., 60.)})


def test_unilluminated_spectator_is_preserved():
    lowered = lower_native(result(PROGRAM, GATES), initial_positions={
        'Q000': (0., 0.), 'Q001': (10., 0.), 'spectator': (10., 140.)})
    assert lowered.final_positions['spectator'] == (10., 140.)


def test_nonpartner_margin_is_checked_at_pulse():
    with pytest.raises(ValueError, match='nonpartner separation'):
        lower_native(result(PROGRAM, GATES), initial_positions={
            'Q000': (0., 0.), 'Q001': (10., 0.), 'spectator': (0., 68.)})


def test_no_teleportation_to_native_initial_positions():
    with pytest.raises(ValueError, match='explicit transport'):
        lower_native(result(PROGRAM, GATES), initial_positions={'Q000': (1., 0.), 'Q001': (10., 0.)})


def test_missing_report_is_rejected_before_operations_are_built():
    gates = (GateSpec('feedback.h', 'H', ('Q000',), ('measurement.report',)),)
    code = 'atom (0, 0) atom0\natom (10, 0) atom1\n@+ u 1.57080 0 3.14159 atom0\n'
    with pytest.raises(ValueError, match='not committed'):
        lower_native(result(code, gates, completed=('measurement.report',)), completed_dependencies=())
    assert lower_native(result(code, gates, completed=('measurement.report',))).operations[0].gate_ids == ('feedback.h',)


def test_parameter_and_missing_gate_checks():
    with pytest.raises(ValueError, match='parameter mismatch'):
        lower_native(result(PROGRAM.replace('0.78540', '1.57080'), GATES))
    with pytest.raises(ValueError, match='not executed exactly once'):
        lower_native(result(PROGRAM.replace('@+ rz 0.78540 atom1\n', ''), GATES))


@pytest.mark.parametrize('operation', ['measure atom0', 'reset atom0', 'unknown atom0'])
def test_nonunitary_and_unknown_syntax_are_not_dropped(operation):
    with pytest.raises(ValueError, match='unsupported operation'):
        parse_naviz('atom (0, 0) atom0\n@+ ' + operation + '\n')


def test_move_without_load_and_duplicate_move_fail():
    with pytest.raises(ValueError, match='without AOD support'):
        lower_native(result(PROGRAM.replace('@+ load [\natom0\natom1\n]\n', ''), GATES))
    with pytest.raises(ValueError, match='duplicate move'):
        parse_naviz('atom (0, 0) atom0\n@+ move [\n(5, 0) atom0\n(10, 0) atom0\n]\n')


def test_digest_and_source_contract_tampering_are_rejected():
    native = result(PROGRAM, GATES)
    native['code'] += '@+ rz 0.78540 atom1\n'
    with pytest.raises(ValueError, match='NAViz digest'):
        lower_native(native)


def test_atom_mapping_dictionary_order_does_not_relabel_source_wires():
    native = result(PROGRAM, GATES)
    native['atom_mapping'] = {'atom1': 'Q001', 'atom0': 'Q000'}
    assert lower_native(native, GATES).operations[0].atoms == ('Q000',)
    native = result(PROGRAM, GATES)
    native['gate_contract'][0]['id'] = 'different-id'
    with pytest.raises(ValueError, match='gate-contract digest'):
        lower_native(native)


def test_linear_direct_dependency_frontiers_keep_ids_and_wire_order():
    gates = (GateSpec('a', 'H', ('Q000',)), GateSpec('b', 'H', ('Q001',), ('a',)),
             GateSpec('c', 'H', ('Q000',), ('b',)))
    contracts = _contracts(gates, ('Q000', 'Q001'))
    ordered, barriers, mode = _frontiers(contracts, (), None)
    assert [g['id'] for g in ordered] == ['a', 'b', 'c']
    assert barriers == {'b', 'c'}
    assert mode == 'direct-dependency-rank-global-frontiers'
    with pytest.raises(ValueError, match='unsupported unitary'):
        _contracts((GateSpec('m', 'MEASURE', ('Q000',)),), ('Q000',))


def test_explicit_empty_configure_uses_previous_full_axes_and_retains_spares():
    lowered = lower_native(result(PROGRAM, GATES))
    ops = finalize_operations(lowered.operations, lowered.initial_positions,
        initial_axes={'AOD_0': {'x_um': (-20., -10.), 'y_um': (-30., -20.)}},
        bounds=(-20., -30., 200., 200.))
    configure = ops[2]
    assert configure.kind == 'CONFIGURE'
    assert configure.duration_us == pytest.approx(200 * sqrt(30 / 110))
    assert configure.metadata['source_axes']['rows'] == (-30., -20.)
    assert configure.metadata['target_axes']['rows'] == (0., 2.)
    store = next(op for op in ops if op.kind == 'STORE')
    assert store.metadata['target_axes']['columns'] == (0., 5.)
    assert store.metadata['target_axes']['rows'] == (60., 62.)
    assert store.metadata['active_rows'] == ()
    assert [gid for op in ops for gid in op.gate_ids] == [g.id for g in GATES]


def test_partial_load_positions_disabled_lines_without_moving_carried_atoms():
    ops = (Operation('load0', 'LOAD', ('Q000',), 15.),
           Operation('move0', 'MOVE', ('Q000',), 1., positions=(('Q000', (0., 60.)),)),
           Operation('load1', 'LOAD', ('Q001',), 15.),
           Operation('store', 'STORE', ('Q000', 'Q001'), 15.))
    finalized = finalize_operations(ops, {'Q000': (0., 0.), 'Q001': (10., 0.)},
        initial_axes={'AOD_0': {'columns': (-20., -10.), 'rows': (-30., -20.)}},
        bounds=(-20., -30., 200., 200.))
    support = next(op for op in finalized if op.id == 'load1:spare-positioning')
    assert support.positions == (('Q000', (0., 60.)),)
    assert support.metadata['target_axes']['columns'] == (0., 10.)
    assert support.metadata['target_axes']['rows'] == (0., 60.)
    assert support.duration_us > 0


def test_axis_capacity_failure_does_not_change_native_endpoints():
    lowered = lower_native(result(PROGRAM, GATES))
    with pytest.raises(ValueError, match='capacity'):
        finalize_operations(lowered.operations, lowered.initial_positions,
            initial_axes={'AOD_0': {'columns': (0.,), 'rows': (0.,)}}, bounds=(-20., -30., 200., 200.))
    assert lowered.operations[3].positions == (('Q000', (0., 60.)), ('Q001', (5., 60.)))


def test_request_hash_cannot_be_replaced_by_an_arbitrary_valid_sha256():
    native = result(PROGRAM, GATES)
    native['request_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='request digest mismatch'):
        lower_native(native, GATES)


@pytest.mark.parametrize('field', ['schema', 'versions', 'request_sha256',
    'compiler_source_sha256', 'request_manifest', 'architecture_source', 'barrier_before', 'routing',
    'native_schedule_contract', 'illumination_contract', 'motion_contract'])
def test_required_provenance_fields_cannot_be_deleted(field):
    native = result(PROGRAM, GATES)
    del native[field]
    with pytest.raises(ValueError, match='missing'):
        lower_native(native, GATES)


@pytest.mark.parametrize('manifest', [{}, None, {'schema': 'neutral-atom-native-request/1'}])
def test_empty_or_partial_manifest_is_rejected_even_with_a_matching_hash(manifest):
    native = result(PROGRAM, GATES)
    native['request_manifest'] = manifest
    native['request_sha256'] = sha256(_canonical(manifest).encode()).hexdigest()
    with pytest.raises(ValueError, match='request manifest'):
        lower_native(native, GATES)


@pytest.mark.parametrize(('field', 'value'), [('routing', 'relaxed'), ('reuse_level', 1.),
    ('barrier_before', ['source.cz']), ('block_id', 'different-block')])
def test_request_fields_are_reconstructed_instead_of_trusting_saved_sha(field, value):
    native = result(PROGRAM, GATES)
    native[field] = value
    with pytest.raises(ValueError, match='request manifest'):
        lower_native(native, GATES)


def test_manifest_configuration_tamper_fails_despite_recomputed_saved_hash():
    native = result(PROGRAM, GATES)
    native['request_manifest']['native_configuration']['trials'] = 100
    native['request_sha256'] = sha256(_canonical(native['request_manifest']).encode()).hexdigest()
    with pytest.raises(ValueError, match='request manifest'):
        lower_native(native, GATES)


def test_rehashed_source_forgery_is_rejected_against_independent_original_gates():
    native = result(PROGRAM, GATES)
    native['gate_contract'][0]['id'] = 'forged.source.h0'
    native['gate_contract'][2]['depends_on'][0] = 'forged.source.h0'
    native['gate_contract_sha256'] = sha256(_canonical(native['gate_contract']).encode()).hexdigest()
    native['request_manifest']['gates'] = deepcopy(native['gate_contract'])
    native['request_manifest']['native_gate_order'][0] = 'forged.source.h0'
    native['request_sha256'] = sha256(_canonical(native['request_manifest']).encode()).hexdigest()
    with pytest.raises(ValueError, match='Requested source gates differ'):
        lower_native(native, GATES)


def test_source_atom_index_cannot_be_forged_even_with_rehashed_contract():
    native = result(PROGRAM, GATES)
    native['gate_contract'][0]['qubits'] = [1]
    native['gate_contract_sha256'] = sha256(_canonical(native['gate_contract']).encode()).hexdigest()
    with pytest.raises(ValueError, match='canonically bind'):
        lower_native(native)


def test_versions_schema_and_compiler_source_are_mandatory_contracts():
    native = result(PROGRAM, GATES)
    native['versions']['mqt.qmap'] = '3.10.0'
    with pytest.raises(ValueError, match='pinned QMAP'):
        lower_native(native)
    native = result(PROGRAM, GATES); native['schema'] = 'neutral-atom-native-output/unknown'
    with pytest.raises(ValueError, match='output schema'):
        lower_native(native)
    native = result(PROGRAM, GATES); native['compiler_source_sha256'] = '0' * 64
    with pytest.raises(ValueError, match='current implementation'):
        lower_native(native)


def test_initial_position_metadata_must_match_raw_native_declarations():
    native = result(PROGRAM, GATES)
    native['initial_positions']['Q000'] = (1., 0.)
    with pytest.raises(ValueError, match='raw atom declarations'):
        lower_native(native)


def test_native_bracketed_one_qubit_targets_remain_one_simultaneous_pulse():
    gates = GATES[:2]
    code = '''atom (0, 0) atom0
atom (10, 0) atom1
@+ u 1.57080 0 3.14159 [
atom0
atom1
]
'''
    lowered = lower_native(result(code, gates), gates)
    operations = schedule_operations(lowered.operations)
    assert len(operations) == 1
    pulse = operations[0]
    assert pulse.atoms == ('Q000', 'Q001')
    assert pulse.gate_ids == ('source.h0', 'source.h1')
    assert pulse.start_us == 0.
    assert pulse.end_us == 1.
    assert pulse.duration_us == 1.
    assert pulse.depends_on == ()
    assert pulse.metadata['native_grouped_targets'] is True
    assert lowered.native_instructions[0]['source_line'] == 3
    executor = KernelExecutor(lowered.initial_positions, gates)
    observed = executor.run(executor.bind_block('native-batch', operations,
        native_provenance=lowered.provenance, execution_mode='scheduled'))
    assert observed.time_us == 1.
    assert set(observed.completed_gate_ids) == {g.id for g in gates}


def test_distinct_native_after_end_instructions_are_not_invented_as_parallel():
    code = 'atom (0, 0) atom0\natom (10, 0) atom1\n'
    code += '@+ u 1.57080 0 3.14159 atom0\n@+ u 1.57080 0 3.14159 atom1\n'
    lowered = lower_native(result(code, GATES[:2]), GATES[:2])
    first, second = schedule_operations(lowered.operations)
    assert (first.start_us, second.start_us) == (0., 1.)
    assert (first.end_us, second.end_us) == (1., 2.)
    assert second.depends_on == (first.id,)
    assert second.start_us + second.duration_us == 2.
    assert lowered.provenance['native_general_concurrent_schedule'] is False
    assert lowered.provenance['native_independent_multi_aod_schedule'] is False
    assert lowered.provenance['native_synchronized_multi_target_batches'] is True
    executor = KernelExecutor(lowered.initial_positions, GATES[:2])
    observed = executor.run(executor.bind_block('native-after-end', (first, second),
        native_provenance=lowered.provenance, execution_mode='scheduled'))
    assert observed.time_us == 2.
    with pytest.raises(ValueError, match='unsupported syntax'):
        parse_naviz(code.replace('@+ u', '@= u'))


def test_native_transport_groups_stay_whole_after_full_rf_schedule_binding():
    lowered = lower_native(result(PROGRAM, GATES), GATES)
    finalized = finalize_operations(lowered.operations, lowered.initial_positions,
        initial_axes={'AOD_0': {'columns': (-20., -10.), 'rows': (-30., -20.)}},
        bounds=(-20., -30., 200., 200.))
    scheduled = schedule_operations(finalized)
    cursor = 0.
    for index, op in enumerate(scheduled):
        assert op.start_us == pytest.approx(cursor)
        assert op.end_us == cursor + op.duration_us
        assert op.depends_on == (() if index == 0 else (scheduled[index - 1].id,))
        cursor += op.duration_us
    load = next(op for op in scheduled if op.kind == 'LOAD')
    move = next(op for op in scheduled if op.kind == 'MOVE')
    store = next(op for op in scheduled if op.kind == 'STORE')
    assert load.atoms == move.atoms == store.atoms == ('Q000', 'Q001')
    assert load.duration_us == store.duration_us == 15.
    assert load.metadata['native_grouped_targets'] is True
    assert move.motion_profile == 'row_column'
    assert move.metadata['motion_progress'] == '3s**2-2s**3'
    assert len(move.metadata['target_axes']['rows']) == 2
    assert move.start_us == pytest.approx(load.start_us + 15.)
    config = next(op for op in scheduled if op.kind == 'CONFIGURE')
    assert config.id in load.depends_on
    assert config.motion_profile == 'row_column'
    assert config.metadata['motion_progress'] == '3s**2-2s**3'
    with pytest.raises(ValueError, match='before binding'):
        finalize_operations(scheduled, lowered.initial_positions,
            initial_axes={'AOD_0': {'columns': (-20., -10.), 'rows': (-30., -20.)}},
            bounds=(-20., -30., 200., 200.))


@pytest.mark.parametrize('epoch', (0., 100.1))
def test_native_full_rf_schedule_reaches_event_kernel_with_common_cubic_motion(epoch):
    lowered = lower_native(result(PROGRAM, GATES), GATES)
    axes = {'AOD_0': {'columns': (-20., -10.), 'rows': (-30., -20.)}}
    operations = schedule_operations(finalize_operations(lowered.operations,
        lowered.initial_positions, initial_axes=axes, bounds=(-20., -30., 200., 200.)))
    movement = next(op for op in operations if op.kind == 'MOVE')
    executor = KernelExecutor(lowered.initial_positions, GATES, initial_aod_axes=axes)
    executor.wait_until(epoch)
    time = epoch + movement.start_us + .25 * movement.duration_us
    halfway = executor.run(executor.bind_block('native-cubic', operations,
        native_provenance=lowered.provenance, execution_mode='scheduled'), until_us=time)
    fraction = 3 * .25 ** 2 - 2 * .25 ** 3
    assert halfway.positions['Q000'] == pytest.approx((0., 60. * fraction))
    assert halfway.positions['Q001'] == pytest.approx((10. - 5. * fraction, 60. * fraction))
    assert halfway.committed_positions['Q000'] == (0., 0.)
    assert halfway.committed_positions['Q001'] == (10., 0.)
    first, second = executor.evaluate(), executor.evaluate()
    assert first == second
    assert executor.observe().version == halfway.version
    finished = executor.run()
    assert finished.time_us == epoch + operations[-1].end_us
    assert dict(finished.positions) == dict(lowered.final_positions)
    assert set(finished.completed_gate_ids) == {g.id for g in GATES}
    flat = tuple(replace(op, start_us=epoch + op.start_us, end_us=epoch + op.end_us)
                 for op in operations)
    replay = KernelExecutor(lowered.initial_positions, GATES, initial_aod_axes=axes)
    replay_finished = replay.run(replay.bind_block('native-flat-replay', flat,
        native_provenance=lowered.provenance, execution_mode='scheduled'))
    assert replay_finished.time_us == finished.time_us
    assert replay_finished.positions == finished.positions
    assert replay_finished.completed_gate_ids == finished.completed_gate_ids


def test_end_chain_binding_preserves_dependencies_and_rejects_rebinding_or_forward_edges():
    ops = (Operation('a', 'WAIT', duration_us=3.), Operation('b', 'WAIT', duration_us=2.),
           Operation('c', 'WAIT', duration_us=1., depends_on=('a',), resources=('extra',)))
    bound = schedule_operations(ops, start_us=10.)
    assert [op.start_us for op in bound] == [10., 13., 15.]
    assert [op.end_us for op in bound] == [13., 15., 16.]
    assert bound[-1].depends_on == ('a', 'b')
    assert bound[-1].resources == ('extra',)
    with pytest.raises(ValueError, match='already bound'):
        schedule_operations(bound)
    with pytest.raises(ValueError, match='earlier schedule prefix'):
        schedule_operations((Operation('a', 'WAIT', depends_on=('missing',)),))
    with pytest.raises(ValueError, match='unique identities'):
        schedule_operations((ops[0], ops[0]))


def test_nonzero_epoch_end_chain_retains_original_relative_payload_and_replays_flat_endpoints():
    epoch = 100.1
    operations = schedule_operations(tuple(Operation(f'wait.{i}', 'WAIT', duration_us=d)
        for i, d in enumerate((.3, .2, .36, 1., 0., 200 * sqrt(60 / 110)))))
    assert operations[0].end_us == .3
    assert epoch + operations[0].end_us - epoch != operations[0].end_us
    assert all(left.end_us == right.start_us for left, right in zip(operations, operations[1:]))
    executor = KernelExecutor({'Q000': (0., 0.)})
    executor.wait_until(epoch)
    executor.run(executor.bind_block('fractional', operations, execution_mode='scheduled'),
        until_us=epoch + .1)
    payload = executor.checkpoint()['active_block']['operations']
    assert [op['start_us'] for op in payload] == [op.start_us for op in operations]
    assert [op['end_us'] for op in payload] == [op.end_us for op in operations]
    block_event = next(row for row in executor.journal if row['event'] == 'BLOCK_STARTED')
    assert block_event['operations_hash'] == sha256(_canonical(payload).encode()).hexdigest()
    restored = KernelExecutor.restore(executor.checkpoint_json(include_journal=True))
    assert restored.checkpoint()['active_block']['operations'] == payload
    completed, restored_completed = executor.run(), restored.run()
    assert restored_completed == completed
    flat = tuple(replace(op, start_us=epoch + op.start_us, end_us=epoch + op.end_us)
                 for op in operations)
    assert all(left.end_us == right.start_us for left, right in zip(flat, flat[1:]))
    replay = KernelExecutor({'Q000': (0., 0.)})
    replay_completed = replay.run(replay.bind_block('fractional-flat', flat, execution_mode='scheduled'))
    assert replay_completed.time_us == completed.time_us == epoch + operations[-1].end_us
    assert replay_completed.completed_operation_ids == completed.completed_operation_ids


def test_global_y_band_includes_spectators_outside_the_native_local_rectangle():
    architecture = {'arch_range': [[-20, -30], [200, 200]],
        'rydberg_range': [[[-10, 50], [10, 100]]]}
    native = result(PROGRAM, GATES, architecture=architecture)
    with pytest.raises(ValueError, match='unintended CZ pair'):
        lower_native(native, GATES, initial_positions={'Q000': (0., 0.), 'Q001': (10., 0.),
            'spectator.a': (150., 60.), 'spectator.b': (155., 60.)})
    lowered = lower_native(native, GATES, initial_positions={
        'Q000': (0., 0.), 'Q001': (10., 0.), 'spectator': (150., 60.)})
    pulse = next(op for op in lowered.operations if op.kind == 'CZ')
    assert pulse.metadata['zone_bounds']['zone_cz0'] == ((-20., 50.), (200., 100.))
    assert pulse.metadata['native_zone_bounds']['zone_cz0'] == ((-10., 50.), (10., 100.))
    assert pulse.metadata['world_bounds'] == ((-20., -30.), (200., 200.))
    assert pulse.metadata['illumination_scope'] == ILLUMINATION_CONTRACT
    assert ('spectator', (150., 60.)) in pulse.metadata['bound_positions_before']


@pytest.mark.parametrize('architecture', [
    {'rydberg_range': [[[-20, 50], [200, 100]]]},
    {'arch_range': [[-20, -30], [200, 200]], 'rydberg_range': []},
    {'arch_range': [[-20, -30], [200, 200]], 'rydberg_range': [[[-20, 50], [200, 220]]]},
])
def test_global_illumination_requires_declared_world_and_in_bounds_y_bands(architecture):
    with pytest.raises(ValueError, match='arch_range|rydberg_range|outside the physical world'):
        lower_native(result(PROGRAM, GATES, architecture=architecture), GATES)


@pytest.mark.parametrize('field', ['native_schedule_contract', 'illumination_contract', 'motion_contract'])
def test_new_execution_contract_cannot_be_forged_with_a_rehashed_manifest(field):
    native = result(PROGRAM, GATES)
    native[field] = 'forged'
    native['request_manifest'][field] = 'forged'
    native['request_sha256'] = sha256(_canonical(native['request_manifest']).encode()).hexdigest()
    with pytest.raises(ValueError, match='schedule/illumination/motion provenance'):
        lower_native(native, GATES)
