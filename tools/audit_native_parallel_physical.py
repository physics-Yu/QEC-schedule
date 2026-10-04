"""Independent arithmetic / Stim audit of a committed native-prefix run.

Reads immutable source and observer files; never commits simulator state.
Full operation-program validation and replay are separate producer checks.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from math import hypot, isfinite
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def pair_geometry(positions, zones, radius, intended):
    """All unordered pairs of alive occupied compute atoms, independently."""
    eligible = []
    for atom, position in positions.items():
        if position is None:
            continue
        x, y = position['x_um'], position['y_um']
        if any(z['zone_type'] == 'entanglement' and
               z['bounds']['lower']['x_um'] <= x <= z['bounds']['upper']['x_um'] and
               z['bounds']['lower']['y_um'] <= y <= z['bounds']['upper']['y_um']
               for z in zones):
            eligible.append(atom)
    actual = set()
    for i, a in enumerate(sorted(eligible)):
        for b in sorted(eligible)[i+1:]:
            pa, pb = positions[a], positions[b]
            distance = hypot(pa['x_um']-pb['x_um'], pa['y_um']-pb['y_um'])
            if distance <= radius:
                actual.add(tuple(sorted((a, b))))
    expected = {tuple(sorted(p)) for p in intended}
    if actual != expected:
        raise ValueError('Global CZ pair mismatch: ' + repr({
            'extra': sorted(actual-expected), 'missing': sorted(expected-actual)}))
    return len(actual)


def check_complete_positions(positions, carrier_ids):
    if (set(positions) != set(carrier_ids) or
            any(point is None or not all(isfinite(point[key]) for key in ('x_um', 'y_um'))
                for point in positions.values())):
        raise ValueError('Observer geometry must include every live carrier with finite coordinates')


def pauli_text(generator, n):
    x, z, phase = generator
    relative = (phase - (x & z).bit_count()) % 4
    if relative not in (0, 2):
        raise ValueError('Non-Hermitian exported stabilizer')
    return ('-' if relative == 2 else '+') + ''.join(
        'Y' if (x >> i & 1) and (z >> i & 1) else
        'X' if x >> i & 1 else 'Z' if z >> i & 1 else 'I'
        for i in range(n))


def apply_stim(sim, gate, indices):
    targets = [indices[q] for q in gate['qubit_ids']]
    kind = gate['gate_type']
    if gate.get('parameters') or gate.get('condition'):
        raise ValueError('Audit scope is an unconditional Clifford prefix')
    if kind in {'MEASURE', 'MZ', 'RESET'}:
        # This prefix has deterministic reports. Do not force a saved outcome
        # into a random branch to make equivalence appear to pass.
        expectation = sim.peek_z(targets[0])
        if expectation == 0:
            raise ValueError('Unexpected random projection in deterministic prefix')
        bit = int(expectation == -1)
        sim.reset(*targets) if kind == 'RESET' else sim.measure(*targets)
        return bit
    if kind == 'H':
        sim.h(*targets)
    elif kind == 'CZ':
        sim.cz(*targets)
    elif kind in {'X', 'Y', 'Z'}:
        getattr(sim, kind.lower())(*targets)
    else:
        raise ValueError('Unsupported independent prefix gate: ' + kind)
    return None


def check_effect_kinds(effects, by_id):
    expected = {'H': 'raman_rotation', 'X': 'raman_rotation', 'Y': 'raman_rotation',
                'Z': 'raman_rotation', 'CZ': 'entangling_pulse',
                'MEASURE': 'measurement', 'MZ': 'measurement', 'RESET': 'reset'}
    for effect in effects:
        gates = [by_id[gid] for gid in effect.get('gate_ids') or [effect['gate_id']]]
        if any(expected.get(gate['gate_type']) != effect['kind'] for gate in gates):
            raise ValueError('Physical effect kind differs from its native gate semantics')


def check_dependency_times(gates, effects):
    intervals = {gid: (effect['start'], effect['end']) for effect in effects
                 for gid in effect.get('gate_ids') or [effect['gate_id']]}
    previous = {}
    checked = 0
    for gate in gates:
        parents = set(gate.get('depends_on', []))
        parents.update(previous[q] for q in gate['qubit_ids'] if q in previous)
        for parent in parents:
            if parent not in intervals or intervals[parent][1]-intervals[gate['id']][0] > 1e-8:
                raise ValueError('Committed intervals violate a circuit dependency')
            checked += 1
        for q in gate['qubit_ids']:
            previous[q] = gate['id']
    return checked


def check_committed_intervals(effects, boundaries):
    for effect in effects:
        for gid in effect.get('gate_ids') or [effect['gate_id']]:
            for event_type, edge in [('operation_started', 'start'), ('operation_completed', 'end')]:
                boundary = boundaries.get((gid, event_type))
                if (boundary is None or boundary[1] != effect['kind'] or
                        abs(boundary[0]-effect[edge]) > 1e-8):
                    raise ValueError('Observer interval differs from its committed operation trace')


def audit(directory):
    import stim

    directory = Path(directory)
    summary = read(directory/'summary.json')
    if summary.get('status') != 'completed':
        raise ValueError('Only completed committed runs qualify')
    source = read(directory/'source-prefix.json')
    gates = read(directory/'prefix-circuit.json')['gates']
    original = source['original_native_gates']
    normalized_raw = b''.join((json.dumps(row, sort_keys=True, ensure_ascii=True,
        separators=(',', ':'), allow_nan=False)+'\n').encode('utf-8') for row in original)
    if hashlib.sha256(normalized_raw).hexdigest() != source['selected_native_prefix_sha256']:
        raise ValueError('Extracted source records disagree with their authenticated raw span')
    by_id = {g['id']: g for g in gates}
    if len(by_id) != len(gates):
        raise ValueError('Duplicate physical circuit gate identity')
    if Counter(g['id'] for g in original) != Counter(by_id.keys()):
        raise ValueError('Physical circuit must preserve the exact source gate identities')
    for g in original:
        physical = by_id[g['id']]
        if (physical['gate_type'], physical['qubit_ids']) != (g['gate_type'], g['qubit_ids']):
            raise ValueError('Physical circuit changed source gate semantics')

    initial = read(directory/'initial.json')
    final = read(directory/'checkpoint-final.json')
    if isinstance(initial, str):
        initial = json.loads(initial)
    if isinstance(final, str):
        final = json.loads(final)
    quantum = final['quantum_state']
    ids = quantum['qubit_ids']
    if initial['quantum_state']['qubit_ids'] != ids or set(initial['atoms']) != set(ids):
        raise ValueError('Quantum carriers differ from the original initial state')
    for state_quantum in (initial['quantum_state'], quantum):
        stim.Tableau.from_stabilizers([stim.PauliString(pauli_text(g, len(ids)))
                                      for g in state_quantum['generators']])
    indices = {q: i for i, q in enumerate(ids)}
    serial = stim.TableauSimulator()
    serial.set_num_qubits(len(ids))
    if any(serial.peek_observable_expectation(stim.PauliString(pauli_text(g, len(ids)))) != 1
           for g in initial['quantum_state']['generators']):
        raise ValueError('This prefix requires the authenticated all-zero physical input')
    original_bits = {}
    for g in original:
        bit = apply_stim(serial, g, indices)
        if bit is not None:
            original_bits[g['id']] = bit
    for p in source['original_native_projections']:
        if original_bits[p['native_gate_id']] != p['outcome']:
            raise ValueError('Original projection disagrees with independent Stim')

    recording = read(directory/'recording.json')
    operations = recording['operations']
    effects = [o for o in operations if o.get('gate_ids') or o.get('gate_id')]
    check_effect_kinds(effects, by_id)
    completed_ids = [g for o in effects for g in (o.get('gate_ids') or [o['gate_id']])]
    if Counter(completed_ids) != Counter(by_id.keys()):
        raise ValueError('Each circuit gate must have exactly one physical effect')
    dependency_checks = check_dependency_times(gates, effects)
    # Trace completion is authoritative; observer alone cannot prove commit.
    completions, committed_projections, boundaries = [], {}, {}
    with (directory/'trace.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            row = json.loads(line)
            event = row['event']
            row_ids = (row.get('effect_gate_ids') or row.get('gate_ids') or
                       ([row['effect_gate_id']] if row.get('effect_gate_id') else []))
            if event['event_type'] in {'operation_started', 'operation_completed'}:
                for gid in row_ids:
                    key = (gid, event['event_type'])
                    if key in boundaries:
                        raise ValueError('Duplicate committed operation boundary')
                    boundaries[key] = (event['time_us'], row['operation_type'])
            if event['event_type'] == 'operation_completed' and row.get('effect_completed'):
                completions.extend(row_ids)
                for field in ('measurement_results', 'reset_projection_results'):
                    for gid, bit in row.get(field, {}).items():
                        if gid in committed_projections or type(bit) is not int or bit not in (0, 1):
                            raise ValueError('Duplicate or invalid committed projection')
                        committed_projections[gid] = bit
    if Counter(completions) != Counter(by_id.keys()):
        raise ValueError('Committed trace has missing or duplicate native effects')
    check_committed_intervals(effects, boundaries)

    actual = stim.TableauSimulator()
    actual.set_num_qubits(len(ids))
    actual_bits = {}
    for o in sorted(effects, key=lambda o: (o['end'], o['index'])):
        for gid in o.get('gate_ids') or [o['gate_id']]:
            bit = apply_stim(actual, by_id[gid], indices)
            if bit is not None:
                actual_bits[gid] = bit
    for gid, bit in final['measurement_results'].items():
        if actual_bits[gid] != bit:
            raise ValueError('Committed measurement differs from independent Stim')
    for gid in original_bits:
        if actual_bits[gid] != original_bits[gid] or committed_projections.get(gid) != original_bits[gid]:
            raise ValueError('Reordered prefix changed a source projection')
    if committed_projections != actual_bits:
        raise ValueError('Committed M / RESET projections differ from independent ordered Stim')
    for generator in quantum['generators']:
        if actual.peek_observable_expectation(stim.PauliString(pauli_text(generator, len(ids)))) != 1:
            raise ValueError('Committed final stabilizer differs from independent Stim')
    algorithm_functions = {f['function_id'] for f in source['original_functions']
                           if f['kind'] in {'data_encode', 'canonical_check'}}
    algorithm_gates = [g for g in original if g['function_id'] in algorithm_functions]
    algorithm_ids = {q for g in algorithm_gates for q in g['qubit_ids']}
    original_constraints = 0
    for generator in serial.canonical_stabilizers():
        support = {ids[i] for i, value in enumerate(generator) if value}
        if support <= algorithm_ids:
            if actual.peek_observable_expectation(generator) != 1:
                raise ValueError('Parallel physical prefix changed the original algorithm state')
            original_constraints += 1
    if original_constraints != len(algorithm_ids):
        raise ValueError('Incomplete original algorithm state equivalence proof')

    positions, cz_checks, intended_count = {}, 0, 0
    readout_checks, raman_checks = 0, 0
    frames = recording['frames']
    frame_cursor = 0
    radius = initial['hardware']['interaction_distance_um']
    zones = initial['world']['zones']
    if recording['scene']['zones'] != zones:
        raise ValueError('Observer zones differ from the original physical world')
    pulse_batches = []
    def inside(position, zone_type):
        return any(z['zone_type'] == zone_type and
            z['bounds']['lower']['x_um'] <= position['x_um'] <= z['bounds']['upper']['x_um'] and
            z['bounds']['lower']['y_um'] <= position['y_um'] <= z['bounds']['upper']['y_um'] for z in zones)

    for pulse in sorted(effects, key=lambda o: o['start']):
        while frame_cursor < len(frames) and frames[frame_cursor]['time'] <= pulse['start']:
            for atom in frames[frame_cursor]['atom_updates']:
                positions[atom['id']] = atom['position']
            frame_cursor += 1
        check_complete_positions(positions, initial['atoms'])
        # This bounded experiment returns carriers before H and executes all
        # readout/CZ pulses with every array stationary. No sampled-motion proof.
        if any(o['kind'] == 'aod_move' and min(o['end'], pulse['end'])-max(o['start'], pulse['start']) > 1e-8
               for o in operations):
            raise ValueError('Gate overlaps motion; static arithmetic audit cannot certify it')
        pulse_gates = [by_id[g] for g in pulse.get('gate_ids') or [pulse['gate_id']]]
        if pulse['kind'] == 'entangling_pulse':
            intended = [g['qubit_ids'] for g in pulse_gates]
            intended_count += pair_geometry(positions, zones, radius, intended)
            pulse_batches.append(len(intended))
            cz_checks += 1
        elif pulse['kind'] in {'measurement', 'reset'}:
            for g in pulse_gates:
                if not inside(positions[g['qubit_ids'][0]], 'measurement'):
                    raise ValueError('Committed M / RESET carrier is outside actual MZ')
                readout_checks += 1
        elif pulse['kind'] == 'raman_rotation':
            separation = initial['hardware']['raman_minimum_separation_um']
            for gate in pulse_gates:
                q = gate['qubit_ids'][0]
                point = positions[q]
                for other, other_point in positions.items():
                    if other != q and other_point is not None and hypot(
                        point['x_um']-other_point['x_um'], point['y_um']-other_point['y_um']) < separation:
                        raise ValueError('Raman target has a spectator inside its minimum separation')
                raman_checks += 1
    if not cz_checks:
        raise ValueError('No physical CZ pulses were audited')
    expected_counts = Counter(g['gate_type'] for g in original)
    if (intended_count != expected_counts['CZ'] or
            readout_checks != expected_counts['MEASURE']+expected_counts['MZ']+expected_counts['RESET'] or
            raman_checks != sum(expected_counts[k] for k in ('H', 'X', 'Y', 'Z'))):
        raise ValueError('Geometry audits did not cover every native physical effect')
    nonzero_moves = [o for o in operations if o['kind'] == 'aod_move']
    used_devices = sorted({o.get('aod_id', 'AOD_0') for o in nonzero_moves})
    overlaps = sum(a.get('aod_id', 'AOD_0') != b.get('aod_id', 'AOD_0') and
                   min(a['end'], b['end'])-max(a['start'], b['start']) > 1e-8
                   for i, a in enumerate(nonzero_moves) for b in nonzero_moves[i+1:])
    loaded_overlaps = sum(a.get('aod_id', 'AOD_0') != b.get('aod_id', 'AOD_0') and
                         a.get('moving_count', 0) > 0 and b.get('moving_count', 0) > 0 and
                         min(a['end'], b['end'])-max(a['start'], b['start']) > 1e-8
                         for i, a in enumerate(nonzero_moves) for b in nonzero_moves[i+1:])
    result = {
        'schema': 'native-prefix-independent-physical-audit/1', 'passed': True,
        'source_native_gate_count': len(original), 'physical_gate_count': len(gates),
        'algorithm_native_gate_count': len(algorithm_gates),
        'resource_native_gate_count': len(original)-len(algorithm_gates),
        'algorithm_qubits': len(algorithm_ids), 'original_state_constraints': original_constraints,
        'original_projections': len(original_bits), 'committed_effects_once': len(completions),
        'committed_projection_checks': len(committed_projections),
        'dependency_interval_checks': dependency_checks,
        'committed_effect_interval_checks': len(gates),
        'cz_pulses_global_pair_checks': cz_checks, 'cz_native_effects': intended_count,
        'actual_mz_projection_geometry_checks': readout_checks,
        'raman_native_separation_checks': raman_checks,
        'max_cz_batch': max(pulse_batches), 'move_devices': used_devices,
        'cross_device_move_overlaps': overlaps, 'stim_version': stim.__version__,
        'cross_device_loaded_move_overlaps': loaded_overlaps,
        'physical_time_us': final['time_us'], 'full_shor_physical': False,
        'magic_factory_validated': False, 'fault_tolerance_validated': False,
        'artifact_sha256': {name: hashlib.sha256((directory/name).read_bytes()).hexdigest()
                            for name in ('source-prefix.json', 'prefix-circuit.json', 'initial.json',
                                         'checkpoint-final.json', 'recording.json', 'trace.jsonl')},
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = audit(args.directory)
    text = json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
