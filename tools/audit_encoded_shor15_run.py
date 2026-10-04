"""Independent stream and complex-matrix audit of one complete native run.

No project quantum/compiler modules are imported. Native IDs are indexed on
disk, and JSONL spans are read once, without loading the complete gate stream.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time

import numpy as np


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 << 20), b''):
            value.update(block)
    return value.hexdigest()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def apply_matrix_gates(gates, wires, state, *, source=False):
    """Apply standard little-endian matrices, independently of project code."""
    state = state.copy()
    indices = np.arange(len(state))
    matrices = {
        'H': np.array([[1, 1], [1, -1]], complex) / math.sqrt(2),
        'X': np.array([[0, 1], [1, 0]], complex),
        'Y': np.array([[0, -1j], [1j, 0]], complex),
        'Z': np.diag([1, -1]), 'S': np.diag([1, 1j]),
        'Sdg': np.diag([1, -1j]),
        'T': np.diag([1, np.exp(1j * math.pi / 4)]),
        'Tdg': np.diag([1, np.exp(-1j * math.pi / 4)]),
    }
    for gate in gates:
        name = gate['name']
        targets = gate['qubits'] if source else [wires.index(w) for w in gate['wires']]
        if name in ('CP', 'CZ'):
            both = ((indices >> targets[0]) & 1) & ((indices >> targets[1]) & 1)
            state[both.astype(bool)] *= (-1 if name == 'CZ' else
                                         np.exp(1j * gate['angle_radians']))
            continue
        target = targets[-1]
        low = (indices & (1 << target)) == 0
        for control in targets[:-1]:
            low &= ((indices >> control) & 1).astype(bool)
        a = indices[low]
        b = a | (1 << target)
        matrix = matrices['X' if name in ('CX', 'CCX') else name]
        left, right = state[a].copy(), state[b].copy()
        state[a] = matrix[0, 0] * left + matrix[0, 1] * right
        state[b] = matrix[1, 0] * left + matrix[1, 1] * right
    return state


def audit(directory, output, on_progress=None):
    directory, output = Path(directory), Path(output)
    require(not output.exists(), 'Fresh audit output required; old attempts are preserved')
    output.parent.mkdir(parents=True, exist_ok=True)
    database = output.with_suffix('.ids.sqlite')
    require(not database.exists(), 'Fresh native-ID database required')
    started = time.perf_counter()
    manifest = load(directory / 'manifest.json')
    require(manifest['complete'] is True and manifest['physical_executed'] is False,
            'Only a complete, explicitly reference-only run can be audited')
    for name, item in manifest['artifacts'].items():
        require(Path(name).name == name and '/' not in name and '\\' not in name,
                'Artifact path must be a single filename')
        path = directory / name
        require(path.stat().st_size == item['bytes'] and digest(path) == item['sha256'],
                'Immutable artifact hash/bytes mismatch: ' + name)
    summary, inputs = load(directory / 'summary.json'), load(directory / 'input.json')
    require(summary['logical_width'] == 12 and inputs['reference_qubits'] == 0,
            'This audit requires the complete 12-wire Shor algorithm')
    wires = inputs['program']['wires']
    require(wires == [f'phase{i}' for i in range(8)] + [f'work{i}' for i in range(4)],
            'Register wire order differs from the complete source contract')
    injections = inputs['program']['injections']
    require(len({r['resource']['wire'] for r in injections}) == len(injections),
            'Logical resource aliases are not single use')
    role_map = {r['role']: r['id'] for r in load(directory / 'roles.json')['roles']}
    require(len(set(role_map.values())) == len(role_map) == summary['declared_atom_count'],
            'Physical role bindings must be one-to-one')
    certificates = load(directory / 'certificates.json')['certificates']
    certificate_ids = set(certificates)
    frames = {}
    with (directory / 'frames.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            frame = json.loads(line)
            key = frame.pop('sha256')
            require(key == hashlib.sha256(json.dumps(frame, sort_keys=True, separators=(',', ':'),
                    allow_nan=False).encode()).hexdigest(), 'Frame hash does not bind its complete snapshot')
            require(key not in frames and len(frame['inverse_generator_images']) == 24,
                    'Full frame requires 24 signed generator images')
            frames[key] = frame
    connection = sqlite3.connect(database)
    connection.execute('PRAGMA journal_mode=OFF')
    connection.execute('PRAGMA synchronous=OFF')
    connection.execute('CREATE TABLE native_ids (id TEXT PRIMARY KEY) WITHOUT ROWID')
    counts, kinds = Counter(), Counter()
    last_gate, last_function, active, completed = None, None, {}, Counter()
    readouts, shot_gates, shot_projections = {}, Counter(), Counter()
    try:
        with (directory / 'functions.jsonl').open(encoding='utf-8') as functions, \
                (directory / 'native_gates.jsonl').open('rb') as gates, \
                (directory / 'native_projections.jsonl').open('rb') as projections:
            for line in functions:
                function = json.loads(line)
                fid, kind, shot = function['function_id'], function['kind'], function['shot_index']
                require(function['index'] == counts['functions'], 'Function ordering changed')
                require(function['depends_on'] == ([last_function] if last_function else []),
                        'Function dependency chain is discontinuous')
                require(set(function['certificate_ids']) <= certificate_ids, 'Missing kernel certificate')
                require(gates.tell() == function['gate_byte_start'] and
                        projections.tell() == function['projection_byte_start'], 'Byte spans have gaps/overlap')
                require(function['gate_start'] == counts['gates'] and
                        function['projection_start'] == counts['projections'], 'Record spans have gaps/overlap')
                ghash, phash, raw, current_ids = hashlib.sha256(), hashlib.sha256(), {}, []
                targets, signature = Counter(), []
                for _ in range(function['gate_count']):
                    data = gates.readline()
                    gate = json.loads(data)
                    ghash.update(data)
                    require(gate['index'] == counts['gates'] and gate['function_id'] == fid,
                            'Native gate index/function binding changed')
                    require(gate['depends_on'] == ([last_gate] if last_gate else []) and not gate['condition'],
                            'Selected native branch dependency chain is discontinuous')
                    require([role_map[r] for r in gate['role_ids']] == gate['qubit_ids'], 'Native role binding changed')
                    require(gate['gate_type'] in ('H', 'X', 'Y', 'Z', 'T', 'CZ', 'MEASURE', 'RESET'),
                            'A non-native gate was emitted')
                    current_ids.append((gate['id'],))
                    targets.update((gate['gate_type'], r) for r in gate['role_ids'])
                    signature.append((gate['gate_type'], [r.split('.', 1)[1] for r in gate['role_ids']]))
                    kinds[gate['gate_type']] += 1
                    if gate['gate_type'] in ('MEASURE', 'RESET'):
                        data = projections.readline()
                        projection = json.loads(data)
                        phash.update(data)
                        require(projection['index'] == counts['projections'] and
                                projection['function_id'] == fid and projection['native_gate_id'] == gate['id'] and
                                projection['kind'] == gate['gate_type'], 'M/RESET is missing an actual matching record')
                        require(type(projection['outcome']) is int and projection['outcome'] in (0, 1) and
                                math.isfinite(projection['conditional_probability']) and
                                0 < projection['conditional_probability'] <= 1 + 1e-10 and projection['source'],
                                'Invalid native projection bit/probability/source')
                        raw[gate['id']] = projection['outcome']
                        counts['projections'] += 1
                    counts['gates'] += 1
                    last_gate = gate['id']
                connection.executemany('INSERT INTO native_ids VALUES (?)', current_ids)
                shot_gates[shot] += function['gate_count']
                shot_projections[shot] += function['projection_count']
                require(gates.tell() == function['gate_byte_end'] and
                        projections.tell() == function['projection_byte_end'] and
                        ghash.hexdigest() == function['native_sha256'] and
                        phash.hexdigest() == function['projection_sha256'] and
                        len(raw) == function['projection_count'], 'Function span hash/count/endpoint mismatch')
                if kind in ('resource_prepare', 'canonical_check'):
                    require(len(function['certificate_ids']) == 1, 'Native kernel binding is ambiguous')
                    certificate = certificates[function['certificate_ids'][0]]
                    signature_hash = hashlib.sha256(json.dumps(signature, sort_keys=True, separators=(',', ':'),
                                                               allow_nan=False).encode()).hexdigest()
                    require(signature_hash == certificate['native_gate_signature_sha256'],
                            'Actual emitted gates differ from the qualified native kernel')
                if 'raw_parity' in function:
                    parity = function['raw_parity']
                    bit = parity['constant']
                    for key in parity['keys']:
                        bit ^= raw[key]
                    require(bit == parity['bit'] == function['logical_result'], 'Actual raw parity differs from semantic bit')
                if kind == 'resource_prepare':
                    require(shot not in active, 'A new resource was prepared before the previous one was released')
                    index = function['injection_index']
                    require(index == completed[shot], 'Resource injection ordering changed')
                    require(all(targets['RESET', role] >= 1 for role in role_map if role.startswith('resource.')),
                            'Resource epoch did not reset every physical role')
                    active[shot] = {'epoch': function['epoch'], 'index': index, 'joint': None, 'r': None}
                elif kind in ('cat_joint', 'resource_readout_reset', 'frame_update'):
                    current = active[shot]
                    require(current['epoch'] == function['epoch'] and current['index'] == function['injection_index'],
                            'Resource epoch/consumer binding changed')
                    if kind == 'cat_joint':
                        require(current['joint'] is None and current['r'] is None, 'Joint measurement order changed')
                        current['joint'] = function['logical_result']
                        require(function['context']['verification_accepted_before_data_coupling'],
                                'Data coupling preceded cat acceptance')
                    elif kind == 'resource_readout_reset':
                        require(current['joint'] is not None and current['r'] is None and
                                all(targets['MEASURE', f'resource.d{i}'] == targets['RESET', f'resource.d{i}'] == 1
                                    for i in range(9)), 'Resource was not read and released exactly once')
                        current['r'] = function['logical_result']
                    else:
                        context = function['context']
                        require((context['m'], context['r']) == (current['joint'], current['r']) and
                                context['source_resource_wire'] == injections[current['index']]['resource']['wire'] and
                                context['resource_wire'] == f'shot{shot}.' + context['source_resource_wire'] and
                                context['all_nine_data_reset'] and context['all_eight_aux_released'] and
                                context['environment_committed'] is False, 'Feedback/release provenance changed')
                        before, after = frames[function['frame_before_sha256']], frames[function['frame_after_sha256']]
                        require(before['ledger_length'] == current['index'] and after['ledger_length'] == current['index'] + 1,
                                'Frame did not advance exactly one correction')
                        completed[shot] += 1
                        del active[shot]
                elif kind == 'terminal_readout':
                    readouts.setdefault(shot, []).append((function['logical_result'], function['conditional_probability']))
                counts['functions'] += 1
                last_function = fid
                if on_progress and counts['functions'] % 5000 == 0:
                    on_progress(dict(counts))
            require(not gates.read(1) and not projections.read(1), 'Unbound native/projection trailing records')
        require(not active, 'An encoded resource was left unconsumed')
        require(dict(kinds) == summary['native_gate_counts'] and counts['gates'] == summary['native_gate_count'] and
                counts['projections'] == summary['native_projection_count'] and
                counts['functions'] == summary['function_count'], 'Summary is not the actual full stream')
        connection.commit()
        require(connection.execute('SELECT COUNT(*) FROM native_ids').fetchone()[0] == counts['gates'],
                'Native IDs are not globally unique')
    finally:
        connection.close()
    ct, source = load(directory / 'complete_clifford_t.json'), load(directory / 'shor15_circuit.json')
    require(ct['wires'] == wires and ct['qft_cp_count'] == 28 and ct['rz_synthesis_count'] == 84 and
            sum(g['name'] == 'CP' for g in source['gates']) == 28 and source['qubit_count'] == 12,
            'Complete source inverse-QFT/12-wire contract is missing')
    require(source['modular_constants'] == [pow(2, 1 << i, 15) for i in range(8)],
            'Modular exponentiation constants were not computed from N and a')
    zero = np.zeros(4096, complex)
    zero[0] = 1
    expected_ct = apply_matrix_gates(ct['gates'], wires, zero) * np.exp(1j * ct['global_phase_radians'])
    expected_source = apply_matrix_gates(source['gates'], wires, zero, source=True)
    reverse = np.array([int(f'{i:012b}'[::-1], 2) for i in range(4096)])
    state_errors, source_errors, terminal_errors = [], [], []
    for attempt in summary['attempts']:
        shot = attempt['shot_index']
        require(completed[shot] == len(injections) == attempt['resource_consumptions'],
                'A shot omitted resources')
        require(shot_gates[shot] == attempt['native_gate_count'] and
                shot_projections[shot] == attempt['native_projection_count'], 'Per-shot cost omitted operations such as cleanup')
        require(len(readouts[shot]) == 8 and sum(bit << i for i, (bit, _) in enumerate(readouts[shot])) == attempt['phase_outcome'],
                'Phase integer differs from all eight actual native readouts')
        saved = load(directory / f'shot{shot}_semantic_state.json')
        state = np.array([complex(*a) for a in saved['amplitudes']])[reverse]
        phase = np.exp(1j * math.pi * saved['branch_global_phase_eighth_turns'] / 8)
        state_errors.append(float(np.linalg.norm(state - phase * expected_ct)))
        source_errors.append(float(np.linalg.norm(state - phase * expected_source)))
        require(state_errors[-1] < 4e-10 and source_errors[-1] < ct['total_operator_error_budget'],
                'Complete complex state differs from independent CT/source matrices')
        probability = float(np.sum(abs(expected_ct.reshape(16, 256)[:, attempt['phase_outcome']]) ** 2))
        recorded_probability = math.prod(p for _, p in readouts[shot])
        terminal_errors.append(abs(probability - recorded_probability))
        require(terminal_errors[-1] < 4e-10, 'Terminal native branch Born probability differs from independent CT state')
        classical = attempt['classical_postprocessing']
        if classical['success']:
            order = classical['order']
            require(pow(2, order, 15) == 1 and order % 2 == 0 and
                    sorted([math.gcd(pow(2, order // 2) - 1, 15), math.gcd(pow(2, order // 2) + 1, 15)]) ==
                    sorted(classical['factors']), 'Classical factors are not derived from a verified order')
    result = {'passed': True, 'scope': 'independent full JSONL/native IDs, raw feedback/lifecycle and complex CT/source matrices',
              'native_counts': dict(counts), 'gate_types': dict(kinds), 'shot_count': len(summary['attempts']),
              'resources_per_shot': len(injections), 'complete_ct_l2_errors': state_errors,
              'exact_source_l2_errors': source_errors, 'terminal_born_probability_errors': terminal_errors,
              'manifest_sha256': digest(directory / 'manifest.json'),
              'physical_executed': False, 'wall_seconds': time.perf_counter() - started}
    output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    print(json.dumps(audit(options.run_dir, options.output,
                           on_progress=lambda value: print(json.dumps(value), flush=True)), indent=2))
