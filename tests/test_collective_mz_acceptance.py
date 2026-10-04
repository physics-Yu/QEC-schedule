"""Independent actual-service acceptance, report commits and cold recovery.

Small authored fixtures exercise ordinary Executor/VisualRecorder operations.
Full 221 RESET / 96 MEASURE / 96 RESET qualification uses the same auditor on
the separately produced complete 3006-gate source-prefix artifact.
"""
from dataclasses import replace
from collections import Counter
import importlib.util
import hashlib
import json
from pathlib import Path

import pytest

from neutral_atom_env.circuit import DynamicGateDAG, PhysicalCircuit
from neutral_atom_env.domain.models import (
    Atom, GridCoord, HolderRef, HolderType, PhysicalGate, Position2D, Rectangle, StaticTrap,
)
from neutral_atom_env.quantum.stabilizer import StabilizerState
from neutral_atom_env.replay.serializer import primitive
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.visualization import VisualRecorder
from neutral_atom_env.world import PlacementState
from neutral_atom_strategies.scheduling.collective_mz import compile_collective_mz

from test_rigid_readout_placement import service_state


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('collective_audit', ROOT / 'tools/audit_collective_mz.py')
audit_tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit_tool)


def collective_state(*, count=4, reset_only=False, grid=False, reverse_placement=False):
    state = service_state()
    if grid:
        assert count == 48
        points = {f'Q{i:03d}': Position2D(10 + 10 * (i % 8), 20 + 10 * (i // 8)) for i in range(count)}
        primary = replace(state.aod, rows=6, columns=8, row_offsets_um=None,
            enabled_rows=(False,) * 6, enabled_columns=(False,) * 8)
        mz = replace(state.world.zones[0], bounds=Rectangle(Position2D(0, -120), Position2D(100, -20)))
        state = replace(state, aod=primary, aods={'AOD_0': primary},
            world=replace(state.world, zones=(mz, *state.world.zones[1:])))
    else:
        points = {f'Q{i:03d}': Position2D(10 + 40 * (i // 2), 20 + 20 * (i % 2)) for i in range(count)}
    if reverse_placement:
        points = dict(zip(points, reversed(tuple(points.values()))))
    traps = {}
    for q, point in points.items():
        traps[q] = StaticTrap(q, GridCoord(int(point.x_um / 5), int(point.y_um / 5)), point, True)
        target = Position2D(point.x_um, point.y_um - (100 if grid else 60))
        traps['mz.' + q] = StaticTrap('mz.' + q,
            GridCoord(int(target.x_um / 5), int(target.y_um / 5)), target, False)
    first_kind = 'RESET' if reset_only else 'MEASURE'
    gates = tuple(PhysicalGate(f's.{q}', first_kind, (q,)) for q in points)
    if not reset_only:
        # Include an explicit all-M -> all-R barrier on disjoint carriers.
        parents = tuple(g.id for g in gates)
        gates += tuple(PhysicalGate(f'r.{q}', 'RESET', (q,), depends_on=parents) for q in points)
    state = replace(state, world=replace(state.world, traps=traps),
        atoms={q: Atom(q) for q in points},
        placement=PlacementState({q: HolderRef(HolderType.STATIC, q) for q in points}),
        dag=DynamicGateDAG(PhysicalCircuit(gates)), slm_enabled=None,
        quantum_state=StabilizerState.zero(tuple(points)))
    roles = {q: {'patch': 'fixture', 'role': f'd{i % 8}' if grid else q,
                 'kind': 'service', 'aod_id': 'AOD_0'} for i, q in enumerate(points)}
    return state, tuple(g for g in gates if g.gate_type == first_kind), roles


def write(directory, name, value):
    (directory / name).write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding='utf-8')


def read(directory, name):
    return json.loads((directory / name).read_text(encoding='utf-8'))


def recorded_service(directory, *, count=4, reset_only=False, grid=False, reverse_frontier=False, reverse_placement=False):
    state, gates, roles = collective_state(count=count, reset_only=reset_only,
        grid=grid, reverse_placement=reverse_placement)
    if reverse_frontier:
        gates = tuple(reversed(gates))
    initial = state.snapshot()
    plan, resets, evidence = compile_collective_mz(state, gates, roles)
    assert state.snapshot() == initial, 'Compilation changed live state'
    recorder = VisualRecorder(state)
    executor = Executor(state)
    executor.submit(plan)
    while state.event_queue:
        event = executor.step()
        recorder.observe(state, event)
    replay = SimulationState.restore(initial)
    executor = Executor(replay)
    executor.submit(plan)
    executor.run()
    assert replay.snapshot() == state.snapshot()
    write(directory, 'initial.json', json.loads(initial))
    write(directory, 'checkpoint-final.json', json.loads(state.snapshot()))
    write(directory, 'recording.json', recorder.payload())
    write(directory, 'plans.json', [primitive(plan)])
    write(directory, 'decisions.json', [{'decision': 0,
        'kind': gates[0].gate_type, 'gate_ids': [g.id for g in gates],
        'included_reset_gate_ids': [g.id for g in resets], 'plan_id': plan.id,
        'start_us': 0., 'end_us': state.time_us, 'duration_us': plan.estimated_duration_us,
        'collective_mz_evidence': evidence}])
    (directory / 'trace.jsonl').write_text('\n'.join(state.trace.records) + '\n', encoding='utf-8')
    return state, plan, evidence


@pytest.fixture
def recorded(tmp_path):
    recorded_service(tmp_path)
    return tmp_path


def test_real_two_wave_mz_accumulation_one_measure_one_reset_and_home_return(recorded):
    result = audit_tool.audit(recorded, expected_measurement_size=4)
    assert result['passed'] and result['native_gate_count'] == 8
    service = result['services'][0]
    assert service['collection_wave_sizes'] == [2, 2]
    assert service['return_wave_sizes'] == [2, 2]
    assert service['native_pulse_sizes'] == [4, 4]
    assert result['original_projection_count'] == 8
    initial, final = read(recorded, 'initial.json'), read(recorded, 'checkpoint-final.json')
    assert initial['placement'] == final['placement']
    assert final['measurement_results'] == {f's.Q{i:03d}': 0 for i in range(4)}
    assert all(not a['measured'] for a in final['atoms'].values())


def test_initial_reset_is_one_actual_service_after_all_waves_not_per_transport_trip(tmp_path):
    _, _, evidence = recorded_service(tmp_path, reset_only=True)
    result = audit_tool.audit(tmp_path, expected_initial_reset_size=4)
    assert result['services'][0]['collection_wave_sizes'] == [2, 2]
    assert result['services'][0]['native_pulse_sizes'] == [4]
    assert evidence['transport_capacity'] == {'AOD_0': 12}
    assert result['original_projection_count'] == 4


def test_real_48_carrier_batch_commits_all_48_reports_then_original_48_resets(tmp_path):
    recorded_service(tmp_path, count=48, grid=True)
    result = audit_tool.audit(tmp_path, expected_measurement_size=48)
    assert result['native_gate_count'] == 96 and result['original_projection_count'] == 96
    assert result['services'][0]['collection_wave_sizes'] == [48]
    assert result['services'][0]['native_pulse_sizes'] == [48, 48]


@pytest.mark.parametrize('ordering', ('frontier', 'placement'))
def test_actual_canonical_binding_permutation_preserves_carriers_and_native_pulse_order(tmp_path, ordering):
    _, plan, evidence = recorded_service(tmp_path,
        reverse_frontier=True, reverse_placement=ordering == 'placement')
    ops = {op.id: op for op in plan.operations}
    differing = 0
    for wave in evidence['collection_waves']:
        load = next(ops[key] for key in wave['operation_ids'] if ops[key].operation_type.value == 'aod_load')
        actual = [binding.atom_id for binding in load.transfer_bindings]
        assert len(actual) == len(set(actual))
        assert Counter(actual) == Counter(wave['atom_ids'])
        differing += actual != wave['atom_ids']
    assert differing, 'Fixture must actually exercise binding-order canonicalization'
    decision = read(tmp_path, 'decisions.json')[0]
    pulse = next(op for op in plan.operations if op.operation_type.value == 'measurement')
    assert list(pulse.effect_gate_ids) == decision['gate_ids']
    assert audit_tool.audit(tmp_path, expected_measurement_size=4)['passed']


@pytest.mark.parametrize('problem', ('missing', 'duplicated'))
def test_transport_wave_permutation_does_not_allow_missing_or_repeated_carriers(recorded, problem):
    decisions = read(recorded, 'decisions.json')
    wave = decisions[0]['collective_mz_evidence']['collection_waves'][0]
    if problem == 'missing':
        wave['atom_ids'].pop()
    else:
        wave['atom_ids'][1] = wave['atom_ids'][0]
    write(recorded, 'decisions.json', decisions)
    with pytest.raises(ValueError, match='carrier metadata differs from real bindings'):
        audit_tool.audit(recorded)


@pytest.mark.parametrize('boundary', ('first_collection_done', 'second_load_started',
    'measurement_started', 'measurement_completed', 'reset_started', 'return_load_started'))
def test_cold_checkpoint_continues_pending_plan_once_with_identical_reports_rng_and_history(boundary):
    state, gates, roles = collective_state()
    before = state.snapshot()
    plan, _, evidence = compile_collective_mz(state, gates, roles)
    first_offload = next(o.id for o in plan.operations if o.operation_type.value == 'aod_offload')
    second_load = [o.id for o in plan.operations if o.operation_type.value == 'aod_load'][1]
    measure = next(o.id for o in plan.operations if o.operation_type.value == 'measurement')
    reset = next(o.id for o in plan.operations if o.operation_type.value == 'reset')
    return_load = [o.id for o in plan.operations if o.operation_type.value == 'aod_load'][2]
    target = {
        'first_collection_done': (first_offload, 'operation_completed'),
        'second_load_started': (second_load, 'operation_started'),
        'measurement_started': (measure, 'operation_started'),
        'measurement_completed': (measure, 'operation_completed'),
        'reset_started': (reset, 'operation_started'),
        'return_load_started': (return_load, 'operation_started'),
    }[boundary]
    executor = Executor(state)
    executor.submit(plan)
    while state.event_queue:
        event = executor.step()
        if (event.operation_id, event.event_type.value) == target:
            break
    else:
        pytest.fail('Requested real checkpoint boundary did not occur')
    assert state.event_queue and state.active_plan
    prefix = state.snapshot()
    if boundary == 'first_collection_done':
        assert state.measurement_results == {}
        assert sum(h.holder_type == HolderType.STATIC and h.holder_id.startswith('mz.')
                   for h in state.placement.atom_to_holder.values()) == 2
        assert not state.placement.mobile_occupancy
    if boundary == 'measurement_started':
        assert state.measurement_results == {}
    if boundary in {'measurement_completed', 'reset_started', 'return_load_started'}:
        assert state.measurement_results == {g.id: 0 for g in gates}
    resumed = SimulationState.restore(prefix)
    Executor(resumed).run()  # Drain the original accepted plan, no resubmission.
    executor.run()
    assert resumed.snapshot() == state.snapshot()
    baseline = SimulationState.restore(before)
    full = Executor(baseline)
    full.submit(plan)
    full.run()
    assert baseline.snapshot() == state.snapshot()
    effects = [json.loads(r) for r in resumed.trace.records if json.loads(r).get('effect_completed')]
    assert [r['operation_type'] for r in effects] == ['measurement', 'reset']
    assert all(len(r['effect_gate_ids']) == 4 for r in effects)
    assert resumed.measurement_results == {g.id: 0 for g in gates}


def test_service_size_claim_cannot_replace_actual_full_native_batch(recorded):
    with pytest.raises(ValueError, match='All final syndrome'):
        audit_tool.audit(recorded, expected_measurement_size=96)


def test_self_consistent_wrong_mz_slot_metadata_cannot_override_actual_holder(recorded):
    decisions = read(recorded, 'decisions.json')
    evidence = decisions[0]['collective_mz_evidence']
    evidence['target_traps']['Q000'] = 'mz.Q001'
    write(recorded, 'decisions.json', decisions)
    with pytest.raises(ValueError, match='metadata disagrees'):
        audit_tool.audit(recorded)


def test_claimed_route_cannot_override_executed_load_move_offload(recorded):
    decisions = read(recorded, 'decisions.json')
    decisions[0]['collective_mz_evidence']['collection_waves'][0]['loaded_route_um'][1][0] += 2.5
    write(recorded, 'decisions.json', decisions)
    with pytest.raises(ValueError, match='loaded route'):
        audit_tool.audit(recorded)


def test_wrong_home_claim_cannot_certify_a_different_return(recorded):
    decisions = read(recorded, 'decisions.json')
    decisions[0]['collective_mz_evidence']['return_waves'][0]['target_traps']['Q000'] = 'Q001'
    write(recorded, 'decisions.json', decisions)
    with pytest.raises(ValueError, match='home/MZ slot identity'):
        audit_tool.audit(recorded)


def test_recording_cannot_put_one_target_outside_mz_at_common_service(recorded):
    recording = read(recorded, 'recording.json')
    pulse = next(o for o in recording['operations'] if o['kind'] == 'measurement')
    start = next(f for f in recording['frames'] if f['time'] == pulse['start'] and
                 f['active_operations'] and f['active_gate_ids'])
    # Authored frames are sparse; an inserted false update must still fail.
    start['atom_updates'].append({'id': 'Q000', 'holder': {'holder_type': 'static', 'holder_id': 'mz.Q000'},
        'position': {'x_um': 10., 'y_um': 20.}, 'activity': 'measuring', 'measured': False})
    write(recorded, 'recording.json', recording)
    with pytest.raises(ValueError, match='stationary MZ SLM support'):
        audit_tool.audit(recorded)


def test_measurement_reports_cannot_be_visible_in_start_frame(recorded):
    recording = read(recorded, 'recording.json')
    first = next(f for f in recording['frames'] if f['active_gate_ids'] and
                 any(g.startswith('s.') for g in f['active_gate_ids']))
    first['measurement_results'] = {f's.Q{i:03d}': 0 for i in range(4)}
    write(recorded, 'recording.json', recording)
    with pytest.raises(ValueError, match='readout END commit'):
        audit_tool.audit(recorded)


def test_persistent_historical_reports_cannot_be_erased_by_reset(recorded):
    recording = read(recorded, 'recording.json')
    recording['frames'][-1]['measurement_results'] = {}
    write(recorded, 'recording.json', recording)
    with pytest.raises(ValueError, match='readout END commit'):
        audit_tool.audit(recorded)


def test_original_measure_native_effect_cannot_be_omitted_from_recorded_pulse(recorded):
    recording = read(recorded, 'recording.json')
    next(o for o in recording['operations'] if o['kind'] == 'measurement')['gate_ids'].pop()
    write(recorded, 'recording.json', recording)
    with pytest.raises(ValueError, match='committed operation'):
        audit_tool.audit(recorded)


def test_same_plan_id_changed_native_gate_cannot_replace_accepted_plan(recorded):
    plans = read(recorded, 'plans.json')
    next(o for o in plans[0]['operations'] if o['operation_type'] == 'measurement')['gate_ids'][0] = 'r.Q000'
    write(recorded, 'plans.json', plans)
    with pytest.raises(ValueError, match='PLAN_STARTED'):
        audit_tool.audit(recorded)


def test_original_source_span_and_projection_reference_are_independently_authenticated(recorded):
    original = read(recorded, 'initial.json')['circuit']['gates']
    raw = b''.join((json.dumps(g, sort_keys=True, separators=(',', ':')) + '\n').encode() for g in original)
    source = {'original_native_gates': original,
        'selected_native_prefix_sha256': hashlib.sha256(raw).hexdigest(),
        'original_native_projections': [{'native_gate_id': g['id'], 'outcome': 0} for g in original]}
    write(recorded, 'source-prefix.json', source)
    result = audit_tool.audit(recorded)
    assert result['original_native_source_span_checked']
    assert result['artifact_sha256']['source-prefix.json'] == hashlib.sha256(
        (recorded / 'source-prefix.json').read_bytes()).hexdigest()
    source['original_native_gates'][0]['gate_type'] = 'RESET'
    write(recorded, 'source-prefix.json', source)
    with pytest.raises(ValueError, match='source span authentication'):
        audit_tool.audit(recorded)


def test_known_prefix_schema_and_explicit_false_flip_preserve_every_authored_field(recorded):
    circuit = read(recorded, 'initial.json')['circuit']
    exported = {'schema': 'encoded-native-parallel-prefix-circuit/1',
        'gates': [dict(gate, readout_flip=False) for gate in circuit['gates']]}
    write(recorded, 'prefix-circuit.json', exported)
    result = audit_tool.audit(recorded)
    assert result['passed']
    assert result['artifact_sha256']['prefix-circuit.json'] == hashlib.sha256(
        (recorded / 'prefix-circuit.json').read_bytes()).hexdigest()


@pytest.mark.parametrize('change', ('true_flip', 'integer_false', 'unknown_gate',
    'unknown_header', 'unknown_schema', 'dependency', 'condition', 'qubits', 'parameters', 'gate_order'))
def test_only_known_prefix_serialization_differences_are_allowed(recorded, change):
    circuit = read(recorded, 'initial.json')['circuit']
    exported = {'schema': 'encoded-native-parallel-prefix-circuit/1',
        'gates': [dict(gate, readout_flip=False) for gate in circuit['gates']]}
    gate = exported['gates'][0]
    if change == 'true_flip':
        gate['readout_flip'] = True
    elif change == 'integer_false':
        gate['readout_flip'] = 0
    elif change == 'unknown_gate':
        gate['implicit_basis'] = 'X'
    elif change == 'unknown_header':
        exported['unknown'] = True
    elif change == 'unknown_schema':
        exported['schema'] = 'physical-circuit/1'
    elif change == 'dependency':
        gate['depends_on'] = ['s.Q001']
    elif change == 'condition':
        gate['condition'] = [['s.Q001', 1]]
    elif change == 'qubits':
        gate['qubit_ids'] = ['Q001']
    elif change == 'parameters':
        gate['parameters'] = [1.]
    else:
        exported['gates'].reverse()
    write(recorded, 'prefix-circuit.json', exported)
    with pytest.raises(ValueError, match='(readout_flip|attribute|schema|differs from original initial circuit)'):
        audit_tool.audit(recorded)


def test_original_source_reordering_cannot_change_qubits_even_if_counts_stay_equal(recorded):
    original = read(recorded, 'initial.json')['circuit']['gates']
    original[0]['qubit_ids'] = ['Q001']
    raw = b''.join((json.dumps(g, sort_keys=True, separators=(',', ':')) + '\n').encode() for g in original)
    write(recorded, 'source-prefix.json', {'original_native_gates': original,
        'selected_native_prefix_sha256': hashlib.sha256(raw).hexdigest()})
    with pytest.raises(ValueError, match='native semantics changed'):
        audit_tool.audit(recorded)


def test_original_source_projection_cannot_be_replaced_by_self_consistent_observer_metadata(recorded):
    original = read(recorded, 'initial.json')['circuit']['gates']
    raw = b''.join((json.dumps(g, sort_keys=True, separators=(',', ':')) + '\n').encode() for g in original)
    write(recorded, 'source-prefix.json', {'original_native_gates': original,
        'selected_native_prefix_sha256': hashlib.sha256(raw).hexdigest(),
        'original_native_projections': [{'native_gate_id': g['id'], 'outcome': int(g['id'] == 's.Q000')}
                                        for g in original]})
    with pytest.raises(ValueError, match='original source projection'):
        audit_tool.audit(recorded)


@pytest.mark.parametrize('problem', ('empty', 'missing', 'dependent', 'mask_outside', 'phase_outside', 'boolean_mask'))
def test_final_quantum_generator_claim_must_be_a_complete_independent_pure_state(recorded, problem):
    final = read(recorded, 'checkpoint-final.json')
    generators = final['quantum_state']['generators']
    if problem == 'empty':
        generators.clear()
    elif problem == 'missing':
        generators.pop()
    elif problem == 'dependent':
        generators[0] = generators[1]
    elif problem == 'mask_outside':
        generators[0][0] = 1 << len(final['quantum_state']['qubit_ids'])
    elif problem == 'phase_outside':
        generators[0][2] += 4
    else:
        generators[0][0] = False
    write(recorded, 'checkpoint-final.json', final)
    with pytest.raises(ValueError, match='complete independent generator set'):
        audit_tool.audit(recorded)


def test_service_while_an_unrelated_aod_moves_is_rejected_by_independent_frames(recorded):
    recording = read(recorded, 'recording.json')
    first = next(f for f in recording['frames'] if f['active_gate_ids'])
    first['aods']['AOD_0']['is_moving'] = True
    write(recorded, 'recording.json', recording)
    with pytest.raises(ValueError, match='moving AOD'):
        audit_tool.audit(recorded)


def test_projection_cannot_be_forged_consistently_in_trace_recording_and_checkpoint(recorded):
    final, recording = read(recorded, 'checkpoint-final.json'), read(recorded, 'recording.json')
    rows = [json.loads(r) for r in final['trace']]
    for row in rows:
        if 's.Q000' in row.get('measurement_results', {}):
            row['measurement_results']['s.Q000'] = 1
    final['trace'] = [json.dumps(r, sort_keys=True, separators=(',', ':')) for r in rows]
    final['measurement_results']['s.Q000'] = 1
    for frame in recording['frames']:
        if 's.Q000' in frame['measurement_results']:
            frame['measurement_results']['s.Q000'] = 1
    next(o for o in recording['operations'] if o['kind'] == 'measurement')['measurement_results']['s.Q000'] = 1
    write(recorded, 'checkpoint-final.json', final)
    write(recorded, 'recording.json', recording)
    (recorded / 'trace.jsonl').write_text('\n'.join(final['trace']) + '\n', encoding='utf-8')
    with pytest.raises(ValueError, match='independent native Stim'):
        audit_tool.audit(recorded)


def test_missing_destination_is_fail_closed_and_does_not_mutate_live_holder_state():
    state, gates, roles = collective_state()
    traps = dict(state.world.traps)
    del traps['mz.Q000']
    state = replace(state, world=replace(state.world, traps=traps), slm_enabled=None)
    initial = state.snapshot()
    with pytest.raises(Exception, match='Declare each MZ SLM destination'):
        compile_collective_mz(state, gates, roles)
    assert state.snapshot() == initial
