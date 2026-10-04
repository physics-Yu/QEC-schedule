from collections import Counter
from dataclasses import asdict, replace
import hashlib
import json

import pytest

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.circuit import PhysicalCircuit, DynamicGateDAG
from neutral_atom_env.domain.models import PhysicalGate, ZoneType
from neutral_atom_experiments.qec_pbc.canonical import canonical_memory_program
from neutral_atom_experiments.qec_pbc.encoded_resource_reference import build_css_isometry, build_encoded_resource
from neutral_atom_experiments.qec_pbc.parallel_prefix import (
    build_parallel_prefix_platform, create_parallel_prefix_environment, load_native_parallel_prefix)
from neutral_atom_experiments.qec_pbc.surface import patch_roles
from neutral_atom_strategies.scheduling.parallel_patch import run_parallel_patch


def _encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':')) + '\n').encode()


@pytest.fixture
def saved_prefix(tmp_path):
    """A portable native source generated from the pinned protocol components."""
    patches = tuple(f'phase{i}' for i in range(8)) + tuple(f'work{i}' for i in range(4))
    roles = [{'role': role.id, 'kind': role.kind, 'patch': patch, 'id': f'Q{i * 17 + j:03d}'}
        for i, patch in enumerate(patches) for j, role in enumerate(patch_roles(patch))]
    roles.extend({'role': role.id, 'kind': role.kind, 'patch': 'resource', 'id': f'Q{204 + j:03d}'}
        for j, role in enumerate(patch_roles('resource')))
    mapping = {r['role']: r['id'] for r in roles}
    functions, gates, projections = [], [], []
    for patch in patches:
        namespace = f'shot0.encode.{patch}'
        reset = tuple(PhysicalGate(namespace + f'.reset{i}', 'RESET', (role.id,))
            for i, role in enumerate(patch_roles(patch)))
        encoder = build_css_isometry(patch=patch, namespace=namespace,
            data_qubits=tuple(f'{patch}.d{i}' for i in range(9)))
        template = canonical_memory_program(patch=patch, rounds=1)
        retained = {g for phase in template.phases if phase.round_index is not None for g in phase.gate_ids}
        canonical = tuple(PhysicalGate(namespace + '.check.' + op.id, op.gate_type, op.targets)
            for op in template.program.operations if op.id in retained)
        for kind, block in (('data_encode', reset + encoder.isometry_circuit.gates), ('canonical_check', canonical)):
            start, projection_start = len(gates), len(projections)
            for gate in block:
                gates.append({'index': len(gates), 'id': gate.id, 'gate_type': gate.gate_type,
                    'role_ids': list(gate.qubit_ids), 'qubit_ids': [mapping[q] for q in gate.qubit_ids],
                    'depends_on': [gates[-1]['id']] if gates else [], 'condition': []})
                if gate.gate_type in ('MEASURE', 'RESET'):
                    projections.append({'native_gate_id': gate.id, 'kind': gate.gate_type,
                        'outcome': 0, 'conditional_probability': 1.})
            functions.append({'index': len(functions), 'kind': kind, 'shot_index': 0,
                'injection_index': None, 'context': {'patch': patch}, 'function_id': f'function.{len(functions):07d}',
                'gate_start': start, 'gate_end': len(gates), 'projection_start': projection_start,
                'projection_count': len(projections) - projection_start,
                'native_sha256': hashlib.sha256(b''.join(_encoded(g) for g in gates[start:])).hexdigest(),
                'projection_sha256': hashlib.sha256(b''.join(_encoded(g) for g in projections[projection_start:])).hexdigest()})
    producer = build_encoded_resource(sign=-1, patch='resource',
        bindings={role.id: role.id for role in patch_roles('resource')}, namespace='shot0.resource00000.producer')
    start, projection_start = len(gates), len(projections)
    for gate in producer.circuit.gates:
        gates.append({'index': len(gates), 'id': gate.id, 'gate_type': gate.gate_type,
            'role_ids': list(gate.qubit_ids), 'qubit_ids': [mapping[q] for q in gate.qubit_ids],
            'depends_on': [gates[-1]['id']], 'condition': []})
        if gate.gate_type in ('MEASURE', 'RESET'):
            projections.append({'native_gate_id': gate.id, 'kind': gate.gate_type, 'outcome': 0, 'conditional_probability': 1.})
    functions.append({'index': 24, 'kind': 'resource_prepare', 'function_id': 'function.0000024',
        'gate_start': start, 'gate_end': len(gates), 'projection_start': projection_start,
        'projection_count': len(projections) - projection_start,
        'native_sha256': hashlib.sha256(b''.join(_encoded(g) for g in gates[start:])).hexdigest(),
        'projection_sha256': hashlib.sha256(b''.join(_encoded(g) for g in projections[projection_start:])).hexdigest()})
    role_value = {'schema': 'encoded-native-roles/1', 'roles': roles, 'algorithm_patches': patches}
    roles_raw = _encoded(role_value)
    (tmp_path / 'roles.json').write_bytes(roles_raw)
    for name, rows in (('functions', functions), ('native_gates', gates), ('native_projections', projections)):
        (tmp_path / (name + '.jsonl')).write_bytes(b''.join(_encoded(row) for row in rows))
    (tmp_path / 'manifest.json').write_bytes(_encoded({'schema': 'encoded-native-run-manifest/1', 'complete': True,
        'artifacts': {'roles.json': {'sha256': hashlib.sha256(roles_raw).hexdigest()}}}))
    return tmp_path


@pytest.mark.parametrize('count', (1, 2, 4, 12))
def test_bounded_selection_preserves_all_native_roles_and_reports(saved_prefix, count):
    prefix = load_native_parallel_prefix(saved_prefix, patch_count=count)
    assert len(prefix.circuit.gates) == 249 * count
    assert len(prefix.bindings) == 17 * count
    assert len(prefix.source['original_native_projections']) == 33 * count
    assert Counter(g.gate_type for g in prefix.circuit.gates) == Counter(H=148 * count, CZ=68 * count,
        MEASURE=8 * count, RESET=25 * count)
    assert {g.id for g in prefix.circuit.gates} == {g['id'] for g in prefix.source['original_native_gates']}
    assert len(DynamicGateDAG(prefix.circuit).ready_gates()) == 17 * count


def test_canonical_safety_barriers_are_retained_and_patch_serial_edges_removed(saved_prefix):
    prefix = load_native_parallel_prefix(saved_prefix)
    bindings = dict(prefix.bindings)
    reverse = {q: role for role, q in bindings.items()}
    gates = {g.id: g for g in prefix.circuit.gates}
    for gate in gates.values():
        for parent in gate.depends_on:
            assert reverse[gate.qubit_ids[0]].split('.')[0] == reverse[gates[parent].qubit_ids[0]].split('.')[0]
    phase = next(p for p in prefix.phases if p['id'].endswith('r1.layer2.cz'))
    for key in phase['gate_ids']:
        assert len(gates[key].depends_on) == 6
        assert all('.r1.layer2.target_h.' in key for key in gates[key].depends_on)


@pytest.mark.parametrize('tamper', ('native', 'raw', 'role', 'function', 'truncated'))
def test_saved_prefix_corruption_is_rejected(saved_prefix, tamper):
    if tamper == 'truncated':
        (saved_prefix / 'native_gates.jsonl').write_bytes(b'')
    else:
        name = {'native': 'native_gates.jsonl', 'raw': 'native_projections.jsonl', 'role': 'roles.json', 'function': 'functions.jsonl'}[tamper]
        path = saved_prefix / name
        if tamper == 'role':
            value = json.loads(path.read_text())
            value['roles'][0]['id'] = 'Q999'
            path.write_bytes(_encoded(value))
        else:
            lines = path.read_bytes().splitlines(keepends=True)
            value = json.loads(lines[0])
            value[{'native': 'gate_type', 'raw': 'outcome', 'function': 'kind'}[tamper]] = {'native': 'H', 'raw': 1, 'function': 'resource_prepare'}[tamper]
            lines[0] = _encoded(value)
            path.write_bytes(b''.join(lines))
    with pytest.raises(ValueError):
        load_native_parallel_prefix(saved_prefix)


def test_fixed_platform_has_no_storage_zone_and_real_measurement_permission(saved_prefix):
    prefix = load_native_parallel_prefix(saved_prefix)
    platform, placement, metadata = build_parallel_prefix_platform(prefix)
    assert platform.world.grid_spacing_um == 5
    assert len(placement) == 204
    assert {zone.zone_type for zone in platform.world.zones} == {ZoneType.ENTANGLEMENT, ZoneType.MEASUREMENT}
    assert platform.hardware.interaction_distance_um == 6
    assert (platform.hardware.interaction_offset.x_um, platform.hardware.interaction_offset.y_um) == (-3, -3)
    assert platform.aod.rows * platform.aod.columns == 12
    assert len(metadata['patches']) == 12
    points = [platform.world.traps[site].position for site in placement.values()]
    assert min((a.x_um - b.x_um) ** 2 + (a.y_um - b.y_um) ** 2
        for i, a in enumerate(points) for b in points[i + 1:]) >= 100


def test_true_two_patch_cz_batch_executor_graph_state_and_original_initial_replay(saved_prefix):
    prefix = load_native_parallel_prefix(saved_prefix, patch_count=2)
    binding = dict(prefix.bindings)
    gates = []
    for patch in prefix.patches:
        for i in (0, 8):
            gates.append(PhysicalGate(f'{patch}.h{i}', 'H', (binding[f'{patch}.d{i}'],)))
        gates.append(PhysicalGate(f'{patch}.nonneighbor.cz', 'CZ', (binding[f'{patch}.d0'], binding[f'{patch}.d8'])))
    prefix = replace(prefix, circuit=PhysicalCircuit(tuple(gates)))
    env, _, _, metadata = create_parallel_prefix_environment(prefix)
    initial, plans = env.snapshot(), []
    result = run_parallel_patch(env, atom_roles=metadata['atom_roles'], on_plan=lambda plan, row: plans.append(plan))
    assert result.status == 'completed', result.diagnostics
    cz = [row for row in result.decision_log if row['kind'] == 'CZ']
    assert len(cz) == 1 and cz[0]['batch_size'] == 2
    for patch in prefix.patches:
        assert env.state.quantum_state.expectation({binding[f'{patch}.d0']: 'X', binding[f'{patch}.d8']: 'Z'}) == 1
        assert env.state.quantum_state.expectation({binding[f'{patch}.d0']: 'Z', binding[f'{patch}.d8']: 'X'}) == 1
    replay = NeutralAtomEnv.restore(initial)
    for plan in plans:
        replay.submit(plan)
        replay.run()
    assert replay.snapshot() == env.snapshot()


def test_true_mz_reports_and_reset_share_visit_preserve_every_gate(saved_prefix):
    prefix = load_native_parallel_prefix(saved_prefix, patch_count=2)
    binding = dict(prefix.bindings)
    gates = []
    for patch in prefix.patches:
        q = binding[f'{patch}.X0']
        gates.extend((PhysicalGate(f'{patch}.h', 'H', (q,)), PhysicalGate(f'{patch}.m', 'MEASURE', (q,)),
            PhysicalGate(f'{patch}.r', 'RESET', (q,), depends_on=(f'{patch}.m',))))
    prefix = replace(prefix, circuit=PhysicalCircuit(tuple(gates)))
    env, _, _, metadata = create_parallel_prefix_environment(prefix)
    result = run_parallel_patch(env, atom_roles=metadata['atom_roles'])
    assert result.status == 'completed', result.diagnostics
    assert set(env.state.measurement_results) == {f'{patch}.m' for patch in prefix.patches}
    row = next(row for row in result.decision_log if row['kind'] == 'MEASURE')
    assert row['batch_size'] == 2 and len(row['included_reset_gate_ids']) == 2
    assert env.state.dag.completed
    assert all(env.state.quantum_state.expectation({binding[f'{patch}.X0']: 'Z'}) == 1 for patch in prefix.patches)


def test_source_prefix_serial_and_template_parallel_match_independent_stim(saved_prefix):
    stim = pytest.importorskip('stim')
    prefix = load_native_parallel_prefix(saved_prefix)
    def execute(rows):
        sim = stim.TableauSimulator()
        sim.set_num_qubits(204)
        reports = {}
        for gate in rows:
            row = gate if isinstance(gate, dict) else asdict(gate)
            targets = [int(q[1:]) for q in row['qubit_ids']]
            if row['gate_type'] == 'H':
                sim.h(*targets)
            elif row['gate_type'] == 'CZ':
                sim.cz(*targets)
            elif row['gate_type'] == 'MEASURE':
                reports[row['id']] = int(sim.measure(*targets))
            else:
                sim.reset(*targets)
        return sim.canonical_stabilizers(), reports
    original = execute(prefix.source['original_native_gates'])
    remaining = list(prefix.circuit.gates)
    last, reordered = {}, []
    while remaining:
        ready = [gate for gate in remaining if all(parent in last for parent in gate.depends_on) and
            not any(set(gate.qubit_ids) & set(earlier.qubit_ids) for earlier in remaining[:remaining.index(gate)])]
        assert ready
        for gate in ready:
            remaining.remove(gate)
            reordered.append(gate)
            last[gate.id] = True
    assert execute(reordered) == original
    assert set(original[1].values()) == {0}


def test_same_saved_resource_prefix_stops_before_t_and_has_independent_right_device(saved_prefix):
    prefix = load_native_parallel_prefix(saved_prefix, patch_count=2, include_magic=True)
    assert len(prefix.circuit.gates) == 2 * 249 + 18
    assert len(prefix.bindings) == 51
    assert not any(g.gate_type == 'T' for g in prefix.circuit.gates)
    assert prefix.source['selected_gate_spans'] == [[0, 498], [2988, 3006]]
    assert prefix.source['partial_functions'][0]['stop_before_native_gate_id'].endswith('.logical_input.t0')
    env, platform, _, metadata = create_parallel_prefix_environment(prefix)
    assert set(env.state.aods) == {'AOD_0', 'AOD_MAGIC'}
    assert env.state.aods['AOD_0'].envelope.upper.x_um < env.state.aods['AOD_MAGIC'].envelope.lower.x_um
    assert len([row for row in metadata['atom_roles'].values() if row['aod_id'] == 'AOD_MAGIC']) == 17


def test_dual_actual_mz_transport_and_combined_reset_before_resource_h(saved_prefix):
    prefix = load_native_parallel_prefix(saved_prefix, patch_count=2, include_magic=True)
    wanted = {f'shot0.encode.{patch}.reset0' for patch in prefix.patches}
    wanted.update(g.id for g in prefix.circuit.gates if 'resource00000.producer.' in g.id)
    prefix = replace(prefix, circuit=PhysicalCircuit(tuple(g for g in prefix.circuit.gates if g.id in wanted)))
    env, _, _, metadata = create_parallel_prefix_environment(prefix)
    initial, plans = env.snapshot(), []
    result = run_parallel_patch(env, atom_roles=metadata['atom_roles'], on_plan=lambda plan, row: plans.append(plan))
    assert result.status == 'completed', result.diagnostics
    assert result.decision_log[0]['actual_concurrent_aods'] == ['AOD_0', 'AOD_MAGIC']
    plan = plans[0]
    moves = [(op, next(i for i in plan.operation_intervals if i.operation_id == op.id))
        for op in plan.operations if op.operation_type.value == 'aod_move']
    assert any(a.aod_id != b.aod_id and max(aa.start_us, bb.start_us) < min(aa.end_us, bb.end_us)
        for a, aa in moves for b, bb in moves)
    resets = [op for op in plan.operations if op.operation_type.value == 'reset']
    assert len(resets) == 1 and len(resets[0].gate_ids) == 19
    binding = dict(prefix.bindings)
    assert env.state.quantum_state.expectation({binding['resource.d0']: 'X'}) == 1
    replay = NeutralAtomEnv.restore(initial)
    for plan in plans:
        replay.submit(plan)
        replay.run()
    assert replay.snapshot() == env.snapshot()
