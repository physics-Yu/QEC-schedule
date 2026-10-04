"""Source identity, dependency, geometry and timing checks at native lowering."""
from hashlib import sha256
from copy import deepcopy
import json
from math import sqrt

import pytest

from neutral_atom_kernel import GateSpec, Operation
from neutral_atom_strategies.native_kernel.compiler import (ARCHITECTURE_SOURCE, ENGINE, OUTPUT_SCHEMA,
    PINNED_QMAP_VERSION, TIMING_PROFILE, _contracts, _frontiers, _request_manifest, _source_sha256)
from neutral_atom_strategies.native_kernel import finalize_operations, lower_native, parse_naviz


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def result(code, gates, *, atom_ids=('Q000', 'Q001'), completed=()):
    architecture = {'rydberg_range': [[[-20, 50], [200, 100]]]}
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
        barrier_before=[], routing='strict', reuse_level=0., timing_profile=TIMING_PROFILE)


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
    'compiler_source_sha256', 'request_manifest', 'architecture_source', 'barrier_before', 'routing'])
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
