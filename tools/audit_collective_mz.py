"""Independent saved-operation audit of stable-SLM collective MZ services.

This reads source, accepted plans, committed events and observer frames. It does
not import the collective compiler or accept its evidence flags as proof. Full
continuous collision validation and exact whole-run replay remain separate.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from math import hypot, isclose, isfinite
from pathlib import Path


def read(path):
    value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    return json.loads(value) if isinstance(value, str) else value


def _ids(operation):
    return list(operation.get('effect_gate_ids') or operation.get('gate_ids') or
                ([operation.get('effect_gate_id') or operation.get('gate_id')]
                 if operation.get('effect_gate_id') or operation.get('gate_id') else []))


def _same(a, b):
    return len(a) == len(b) and all(isfinite(x) and isfinite(y) and
        isclose(x, y, rel_tol=0, abs_tol=1e-7) for x, y in zip(a, b))


def _point(value):
    return [value['x_um'], value['y_um']]


def _inside(point, zones):
    return any(z['zone_type'] == 'measurement' and
        all(z['bounds']['lower'][key] <= point[key] <= z['bounds']['upper'][key]
            for key in ('x_um', 'y_um')) for z in zones)


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _reference_helpers():
    spec = importlib.util.spec_from_file_location('collective_native_oracle',
        Path(__file__).with_name('audit_native_parallel_physical.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _generator_texts(quantum, helper, n):
    generators = quantum['generators']
    if len(generators) != n or any(len(g) != 3 or any(type(v) is not int for v in g) or
        not (0 <= g[0] < 1 << n and 0 <= g[1] < 1 << n and 0 <= g[2] < 4)
        for g in generators):
        raise ValueError('Quantum state requires a complete independent generator set with valid Pauli masks')
    return [helper.pauli_text(g, n) for g in generators]


def _normalized_circuit(circuit):
    """Only the two authored prefix serialization differences are permitted."""
    if set(circuit) not in ({'gates'}, {'gates', 'schema'}) or (
        'schema' in circuit and circuit['schema'] != 'encoded-native-parallel-prefix-circuit/1'):
        raise ValueError('Unknown saved prefix circuit schema or attribute')
    fields = {'id', 'gate_type', 'qubit_ids', 'parameters', 'condition', 'depends_on'}
    normalized = []
    for gate in circuit['gates']:
        if set(gate) not in (fields, fields | {'readout_flip'}):
            raise ValueError('Unknown or missing saved native gate attribute')
        if 'readout_flip' in gate and (type(gate['readout_flip']) is not bool or gate['readout_flip']):
            raise ValueError('Prefix serialization must preserve false readout_flip')
        normalized.append({key: gate[key] for key in fields})
    return {'gates': normalized}


def _source_checks(directory, initial):
    normalized_initial = _normalized_circuit(initial['circuit'])
    gates = normalized_initial['gates']
    by_id = {g['id']: g for g in gates}
    if len(by_id) != len(gates):
        raise ValueError('Duplicate authored native gate identity')
    source_path = directory / 'source-prefix.json'
    source = read(source_path) if source_path.exists() else None
    original = source['original_native_gates'] if source else gates
    if Counter(g['id'] for g in original) != Counter(by_id.keys()):
        raise ValueError('Exact original native gate identities must be preserved')
    if source:
        raw = b''.join((json.dumps(g, sort_keys=True, ensure_ascii=True,
            separators=(',', ':'), allow_nan=False) + '\n').encode('utf-8') for g in original)
        if hashlib.sha256(raw).hexdigest() != source['selected_native_prefix_sha256']:
            raise ValueError('Original native source span authentication failed')
    for gate in original:
        actual = by_id[gate['id']]
        if any(actual.get(key, []) != gate.get(key, [])
               for key in ('gate_type', 'qubit_ids', 'parameters', 'condition')):
            raise ValueError('Authored native semantics changed')
    circuit_path = directory / 'prefix-circuit.json'
    if circuit_path.exists() and _normalized_circuit(read(circuit_path)) != normalized_initial:
        raise ValueError('Saved prefix circuit differs from original initial circuit')
    return by_id, original, source


def _trace_checks(directory, initial, final, plans, operations, by_id):
    plan_map = {p['id']: p for p in plans}
    if len(plan_map) != len(plans):
        raise ValueError('Duplicate accepted plan identity')
    op_map = {(p['id'], o['id']): o for p in plans for o in p['operations']}
    intervals = {(p['id'], i['operation_id']):
        (p['initial_time_us'] + i['start_us'], p['initial_time_us'] + i['end_us'])
        for p in plans for i in p['operation_intervals']}
    if set(intervals) != set(op_map):
        raise ValueError('Missing accepted operation interval')
    rows = []
    # PLAN_STARTED embeds a complete immutable plan. Compare its full content
    # once, then release that second decoded copy instead of keeping a large
    # duplicate of every accepted plan throughout the geometry audit.
    with (directory / 'trace.jsonl').open(encoding='utf-8-sig') as stream:
        for line in stream:
            if not line.strip():
                continue
            if len(rows) >= len(final['trace']):
                raise ValueError('Standalone trace differs from saved committed checkpoint')
            saved = final['trace'][len(rows)]
            row = json.loads(line)
            if not (isinstance(saved, str) and line.rstrip('\r\n') == saved):
                if row != (json.loads(saved) if isinstance(saved, str) else saved):
                    raise ValueError('Standalone trace differs from saved committed checkpoint')
            event = row['event']
            if event['event_type'] == 'plan_started':
                pid = event.get('plan_id')
                if pid not in plan_map or event.get('plan') != plan_map[pid]:
                    raise ValueError('Accepted plan content differs from actual PLAN_STARTED')
                del event['plan']
            rows.append(row)
    if len(rows) != len(final['trace']):
        raise ValueError('Standalone trace differs from saved committed checkpoint')
    initial_rows = [json.loads(r) if isinstance(r, str) else r for r in initial['trace']]
    if rows[:len(initial_rows)] != initial_rows:
        raise ValueError('Committed history did not preserve original initial prefix')
    starts, ends, snapshots, completed, projections = {}, {}, {}, [], {}
    started_plans, completed_plans = [], []
    ordered_starts = []
    for row in rows[len(initial_rows):]:
        event = row['event']
        pid, oid = event.get('plan_id'), event.get('operation_id')
        kind = event['event_type']
        if kind == 'plan_started':
            if not _same([event['time_us']], [plan_map[pid]['initial_time_us']]):
                raise ValueError('Accepted plan origin differs from committed start time')
            started_plans.append(pid)
        elif kind == 'plan_completed':
            completed_plans.append(pid)
        elif kind in {'operation_started', 'operation_completed'}:
            key = (pid, oid)
            op = op_map.get(key)
            if op is None or row['operation_type'] != op['operation_type'] or _ids(row) != _ids(op):
                raise ValueError('Committed operation changed accepted primitive or native effects')
            edge = 0 if kind == 'operation_started' else 1
            if not _same([event['time_us']], [intervals[key][edge]]):
                raise ValueError('Committed operation time changed its accepted interval')
            boundary = starts if kind == 'operation_started' else ends
            if key in boundary:
                raise ValueError('Duplicate committed operation boundary')
            boundary[key] = row
            if kind == 'operation_started':
                ordered_starts.append(key)
            if kind == 'operation_completed' and row.get('effect_completed'):
                completed.extend(_ids(row))
        for field in ('measurement_results', 'reset_projection_results'):
            bits = row.get(field, {})
            if bits and (kind != 'operation_completed' or not row.get('effect_completed')):
                raise ValueError('Projection report committed before readout completion')
            expected_type = {'MEASURE', 'MZ'} if field == 'measurement_results' else {'RESET'}
            for gid, bit in bits.items():
                if gid in projections or gid not in _ids(row) or by_id[gid]['gate_type'] not in expected_type:
                    raise ValueError('Projection identity or commit boundary changed')
                if type(bit) is not int or bit not in (0, 1):
                    raise ValueError('Projection report is not a binary integer')
                projections[gid] = bit
        snapshots[row['state_version']] = row
    if started_plans != list(plan_map) or completed_plans != list(plan_map):
        raise ValueError('Every accepted plan must start and finish once in saved order')
    if set(starts) != set(op_map) or set(ends) != set(op_map):
        raise ValueError('Missing committed operation boundary')
    for key, op in op_map.items():
        if any(intervals[(key[0], parent)][1] > intervals[key][0] + 1e-8 for parent in op['depends_on']):
            raise ValueError('Accepted primitive dependency overlaps its predecessor')
    if Counter(completed) != Counter(by_id.keys()):
        raise ValueError('Each original native effect must complete exactly once')
    expected_projections = {g for g, v in by_id.items() if v['gate_type'] in {'MEASURE', 'MZ', 'RESET'}}
    if set(projections) != expected_projections:
        raise ValueError('Native projection history is incomplete')
    if len(operations) != len(ordered_starts):
        raise ValueError('Observer operation count differs from committed operation starts')
    observed = {}
    for record, key in zip(operations, ordered_starts):
        op, start, end = op_map[key], starts[key], ends[key]
        if (record['plan_id'] != key[0] or record['kind'] != op['operation_type'] or
            _ids(record) != _ids(op) or record.get('aod_id', 'AOD_0') != op.get('aod_id', 'AOD_0') or
            not _same([record['start'], record['end']],
                      [start['event']['time_us'], end['event']['time_us']]) or
            not _same([record['end'] - record['start']], [op['duration_us']])):
            raise ValueError('Observer interval differs from actual committed operation')
        observed[key] = record
    return rows, starts, ends, observed, snapshots, projections


def _frame_checks(initial, final, recording, rows):
    """Reports are available only in the exact completion-version frame."""
    frames = recording['frames']
    base = len(initial['trace'])
    if len(frames) != len(rows) - base + 1 or frames[0]['version'] != initial['version']:
        raise ValueError('Observer must contain every original committed version')
    reports = dict(initial['measurement_results'])
    completed = sum(v['status'] == 'completed' for v in initial['dag'].values())
    maps = {}
    atoms = {}
    slm = dict(initial['slm_enabled'])
    for index, frame in enumerate(frames):
        if index:
            row = rows[base + index - 1]
            if frame['version'] != row['state_version'] or not _same([frame['time']], [row['event']['time_us']]):
                raise ValueError('Observer frame is not at its committed event/version')
            reports.update(row.get('measurement_results', {}))
            if row.get('effect_completed'):
                completed += len(_ids(row))
        if frame['measurement_results'] != reports:
            raise ValueError('Report availability differs from actual readout END commit')
        if frame['gate_counts'].get('completed', 0) != completed:
            raise ValueError('Observer native completion count differs from committed effects')
        if frame.get('slm_enabled') is not None:
            slm = frame['slm_enabled']
        for atom in frame['atom_updates']:
            if atom['id'] not in initial['atoms']:
                raise ValueError('Observer introduced a foreign carrier')
            atoms[atom['id']] = atom
        if set(atoms) != set(initial['atoms']):
            raise ValueError('Observer omitted a live physical carrier')
        # Save only requested boundary frames later, without duplicating the
        # whole timeline of atom dictionaries for this large prefix.
        maps[frame['version']] = (frame, slm)
    if reports != final['measurement_results']:
        raise ValueError('Final checkpoint changed committed historical reports')
    return maps


def _boundary_atoms(recording, needed):
    atoms, result = {}, {}
    for frame in recording['frames']:
        atoms.update({a['id']: a for a in frame['atom_updates']})
        if frame['version'] in needed:
            result[frame['version']] = dict(atoms)
    if set(result) != needed:
        raise ValueError('Missing requested committed geometry frame')
    return result


def _validate_service_plan(plan, decision, initial, starts, ends, observed, frame_maps, atom_frames):
    evidence = decision['collective_mz_evidence']
    operations = plan['operations']
    op_map = {o['id']: o for o in operations}
    if len(op_map) != len(operations):
        raise ValueError('Duplicate collective primitive identity')
    gates = {g['id']: g for g in initial['circuit']['gates']}
    traps = initial['world']['traps']
    zones = initial['world']['zones']
    registry = initial.get('aods') or {'AOD_0': initial['aod']}
    pulse_ops = [o for o in operations if _ids(o)]
    expected_kinds = ['reset'] if decision['kind'] == 'RESET' else ['measurement', 'reset']
    if [o['operation_type'] for o in pulse_ops] != expected_kinds:
        raise ValueError('Collective cohort must have one common native service per kind')
    ids = decision['gate_ids']
    reset_ids = decision.get('included_reset_gate_ids', [])
    atoms = [gates[gid]['qubit_ids'][0] for gid in ids]
    if len(set(ids)) != len(ids) or len(set(atoms)) != len(atoms):
        raise ValueError('Collective native IDs and target carriers must be distinct')
    if _ids(pulse_ops[0]) != ids or (reset_ids and _ids(pulse_ops[-1]) != reset_ids):
        raise ValueError('Decision gate IDs do not match executed service pulse')
    if decision['kind'] == 'MEASURE' and {gates[g]['qubit_ids'][0] for g in reset_ids} != set(atoms):
        raise ValueError('Every measured carrier needs its original successor RESET')
    if any(gates[g]['gate_type'] != decision['kind'] for g in ids) or any(gates[g]['gate_type'] != 'RESET' for g in reset_ids):
        raise ValueError('Decision changed native service kind')
    first_version = starts[(plan['id'], operations[0]['id'])]['state_version']
    homes = {q: initial['placement']['atom_to_holder'][q] for q in atoms}
    if any(h['holder_type'] != 'static' for h in homes.values()):
        raise ValueError('Collective cohort did not begin at actual static home supports')
    if any(atom_frames[first_version][q]['holder'] != homes[q] or not _same(
        _point(atom_frames[first_version][q]['position']), _point(traps[homes[q]['holder_id']]['position'])) for q in atoms):
        raise ValueError('Collective cohort departed from a different original home holder')
    targets = {q: 'mz.' + homes[q]['holder_id'] for q in atoms}
    if (evidence['plan_id'] != plan['id'] or evidence['gate_ids'] != ids or
        evidence['included_reset_gate_ids'] != reset_ids or evidence['atom_ids'] != atoms or
        evidence['service_cohort_size'] != len(atoms) or evidence['target_traps'] != targets or
        evidence['original_holder_ids'] != {q: h['holder_id'] for q, h in homes.items()}):
        raise ValueError('Collective metadata disagrees with original native cohort and homes')
    if evidence['transport_capacity'] != {k: a['rows'] * a['columns'] for k, a in registry.items()}:
        raise ValueError('Transport capacity metadata changed actual AOD footprint')
    if any(t not in traps or not _inside(traps[t]['position'], zones) for t in targets.values()):
        raise ValueError('Collective targets are not predeclared real MZ SLM slots')
    wave_ids, wave_targets, wave_sources = [], {'collect': [], 'return': []}, {'collect': [], 'return': []}
    for direction, waves in (('collect', evidence['collection_waves']), ('return', evidence['return_waves'])):
        for wave in waves:
            selected = [op_map.get(oid) for oid in wave['operation_ids']]
            if not selected or any(o is None for o in selected) or wave['direction'] != direction:
                raise ValueError('Transport wave references missing actual primitive')
            loads = [o for o in selected if o['operation_type'] == 'aod_load']
            offloads = [o for o in selected if o['operation_type'] == 'aod_offload']
            if len(loads) != 1 or len(offloads) != 1 or any(_ids(o) for o in selected):
                raise ValueError('Each transport wave needs actual LOAD/OFFLOAD and no projection')
            load, offload = loads[0], offloads[0]
            bindings, destinations = load['transfer_bindings'], offload['transfer_bindings']
            qs = [b['atom_id'] for b in bindings]
            target_qs = [b['atom_id'] for b in destinations]
            # Transfer bindings use the compiler/backend's canonical order.
            # Wave metadata retains source-frontier order; only its carrier
            # permutation is nonsemantic. Native pulse IDs stay exact above.
            if (len(qs) != len(set(qs)) or len(target_qs) != len(set(target_qs)) or
                len(wave['atom_ids']) != len(set(wave['atom_ids'])) or
                Counter(qs) != Counter(wave['atom_ids']) or Counter(target_qs) != Counter(qs)):
                raise ValueError('Transport wave carrier metadata differs from real bindings')
            aod_id = load.get('aod_id', 'AOD_0')
            if wave['aod_id'] != aod_id or any(o.get('aod_id', 'AOD_0') != aod_id for o in selected):
                raise ValueError('Transport wave device identity changed')
            source = {b['atom_id']: b['static_trap_id'] for b in bindings}
            target = {b['atom_id']: b['static_trap_id'] for b in destinations}
            intended_source = {q: homes[q]['holder_id'] if direction == 'collect' else targets[q] for q in qs}
            intended_target = {q: targets[q] if direction == 'collect' else homes[q]['holder_id'] for q in qs}
            if source != intended_source or target != intended_target or wave['source_traps'] != source or wave['target_traps'] != target:
                raise ValueError('Transport wave does not preserve original home/MZ slot identity')
            if {b['atom_id']: b['cell'] for b in bindings} != {b['atom_id']: b['cell'] for b in destinations}:
                raise ValueError('Rigid transport wave changed actual capture cell identity')
            if wave['capture_cells'] != {b['atom_id']: [b['cell']['row'], b['cell']['column'], b['cell'].get('aod_id', 'AOD_0')] for b in bindings}:
                raise ValueError('Capture-cell metadata differs from actual LOAD')
            if wave['source_positions_um'] != {q: _point(traps[t]['position']) for q, t in source.items()} or wave['target_positions_um'] != {q: _point(traps[t]['position']) for q, t in target.items()}:
                raise ValueError('Transport wave position metadata differs from declared world')
            start = starts[(plan['id'], load['id'])]['state_version']
            end = ends[(plan['id'], offload['id'])]['state_version']
            for version, expected in ((start, source), (end, target)):
                for q, trap_id in expected.items():
                    atom = atom_frames[version][q]
                    if atom['holder'] != {'holder_type': 'static', 'holder_id': trap_id} or not _same(_point(atom['position']), _point(traps[trap_id]['position'])):
                        raise ValueError('Recorded transport boundary lacks its real declared static holder')
            pose = frame_maps[start][0]['aods'][aod_id]['pose']
            if not _same(wave['source_origin_um'], _point(pose)):
                raise ValueError('Wave source origin differs from actual LOAD device pose')
            route = [_point(pose)] + [_point(o['target_pose']) for o in selected if o['operation_type'] == 'aod_move' and
                observed[(plan['id'], o['id'])]['start'] >= observed[(plan['id'], load['id'])]['end']]
            if len(route) != len(wave['loaded_route_um']) or any(not _same(a, b) for a, b in zip(route, wave['loaded_route_um'])):
                raise ValueError('Logged loaded route differs from executed rigid primitives')
            if not _same(wave['target_origin_um'], route[-1]):
                raise ValueError('Wave target origin differs from actual OFFLOAD pose')
            first, last = observed[(plan['id'], selected[0]['id'])], observed[(plan['id'], selected[-1]['id'])]
            if not _same([wave['start_us'], wave['end_us']], [first['start'] - plan['initial_time_us'], last['end'] - plan['initial_time_us']]):
                raise ValueError('Wave timing metadata differs from committed primitives')
            wave_ids.extend(wave['operation_ids'])
            wave_sources[direction].extend(qs)
            wave_targets[direction].extend(destinations)
    for direction in ('collect', 'return'):
        if Counter(wave_sources[direction]) != Counter(atoms):
            raise ValueError('Collection/return waves omit or duplicate original carriers')
    expected_order = [oid for w in evidence['collection_waves'] for oid in w['operation_ids']]
    expected_order += [o['id'] for o in pulse_ops]
    expected_order += [oid for w in evidence['return_waves'] for oid in w['operation_ids']]
    if expected_order != [o['id'] for o in operations]:
        raise ValueError('All collection must finish before common pulse and all return must follow it')
    if evidence['transport_wave_count'] != len(evidence['collection_waves']) + len(evidence['return_waves']):
        raise ValueError('Transport-wave count differs from actual LOAD/OFFLOADs')
    if len(evidence['service_pulses']) != len(pulse_ops):
        raise ValueError('Service-pulse evidence differs from actual native operations')
    for op, metadata in zip(pulse_ops, evidence['service_pulses']):
        record = observed[(plan['id'], op['id'])]
        hardware_duration = initial['hardware']['measurement_duration_us' if op['operation_type'] == 'measurement' else 'reset_duration_us']
        if not _same([op['duration_us']], [hardware_duration]):
            raise ValueError('Common service changed original hardware duration')
        if (metadata['operation_id'] != op['id'] or metadata['kind'] != op['operation_type'] or
            metadata['gate_ids'] != _ids(op) or metadata['atom_ids'] != [gates[g]['qubit_ids'][0] for g in _ids(op)] or
            not _same([metadata['start_us'], metadata['end_us']],
                      [record['start'] - plan['initial_time_us'], record['end'] - plan['initial_time_us']])):
            raise ValueError('Service metadata differs from committed common pulse')
        for boundary in (starts, ends):
            version = boundary[(plan['id'], op['id'])]['state_version']
            frame, slm = frame_maps[version]
            if frame.get('transfers') or frame.get('transfer') or any(a['is_moving'] for a in frame['aods'].values()):
                raise ValueError('Common service overlaps an unfinished handoff or moving AOD')
            for q in atoms:
                atom, target = atom_frames[version][q], targets[q]
                if (atom['holder'] != {'holder_type': 'static', 'holder_id': target} or
                    not slm.get(target) or not _same(_point(atom['position']), _point(traps[target]['position'])) or
                    not _inside(atom['position'], zones)):
                    raise ValueError('Entire cohort must have actual enabled stationary MZ SLM support')
        if op['operation_type'] == 'measurement':
            committed = ends[(plan['id'], op['id'])].get('measurement_results', {})
            if set(committed) != set(ids) or record['measurement_results'] != committed:
                raise ValueError('Common measurement did not commit all original reports at END')
            completed_version = ends[(plan['id'], op['id'])]['state_version']
            if any(not atom_frames[completed_version][q]['measured'] for q in atoms):
                raise ValueError('Measurement END did not mark every addressed carrier measured')
    if len(pulse_ops) == 2 and observed[(plan['id'], pulse_ops[1]['id'])]['start'] < observed[(plan['id'], pulse_ops[0]['id'])]['end']:
        raise ValueError('All MEASURE reports must finish before any successor RESET')
    last_version = ends[(plan['id'], operations[-1]['id'])]['state_version']
    final_frame, _ = frame_maps[last_version]
    if any(atom_frames[last_version][q]['holder'] != homes[q] for q in atoms) or final_frame.get('transfers'):
        raise ValueError('Actual return did not restore every original home holder')
    if any(a['is_moving'] for a in final_frame['aods'].values()) or any(
        atom['holder']['holder_type'] == 'mobile' for atom in atom_frames[last_version].values()):
        raise ValueError('Collective return left loaded or moving AODs')
    if any(atom_frames[last_version][q]['measured'] for q in atoms):
        raise ValueError('Original successor RESET did not release every measured carrier')
    return {'kind': decision['kind'], 'cohort_size': len(atoms), 'plan_id': plan['id'],
        'collection_wave_sizes': [len(w['atom_ids']) for w in evidence['collection_waves']],
        'return_wave_sizes': [len(w['atom_ids']) for w in evidence['return_waves']],
        'native_pulse_sizes': [len(_ids(o)) for o in pulse_ops],
        'all_holders_mz_before_pulse': True, 'reports_at_measurement_end': True,
        'all_measure_before_reset': True, 'actual_return_to_original_holders': True}


def audit(directory, *, expected_initial_reset_size=None, expected_measurement_size=None):
    directory = Path(directory)
    initial, final, recording, decisions, plans = (read(directory / name) for name in
        ('initial.json', 'checkpoint-final.json', 'recording.json', 'decisions.json', 'plans.json'))
    if final['active_plan'] or final['event_queue']['pending'] or any(
        n['status'] != 'completed' for n in final['dag'].values()):
        raise ValueError('Saved physical prefix is not complete')
    if final['world'] != initial['world'] or final['hardware'] != initial['hardware'] or final['circuit'] != initial['circuit']:
        raise ValueError('World, hardware or native circuit changed during physical execution')
    if recording['scene']['zones'] != initial['world']['zones']:
        raise ValueError('Observer replaced original physical zones')
    if recording['scene']['traps'] != [t for _, t in sorted(initial['world']['traps'].items())]:
        raise ValueError('Observer replaced original finite support inventory')
    by_id, original, source = _source_checks(directory, initial)
    rows, starts, ends, observed, _, projections = _trace_checks(directory, initial, final, plans, recording['operations'], by_id)
    frame_maps = _frame_checks(initial, final, recording, rows)
    collective = [d for d in decisions if 'collective_mz_evidence' in d]
    collective_ids = {d['plan_id'] for d in collective}
    service_plans = [p for p in plans if p['planner_id'] == 'collective-mz-slm-rigid-prefix-v1']
    if not collective or len(collective_ids) != len(collective) or collective_ids != {p['id'] for p in service_plans}:
        raise ValueError('Collective metadata must cover every actual collective plan once')
    needed = {r['state_version'] for key, r in starts.items() if key[0] in collective_ids}
    needed.update(r['state_version'] for key, r in ends.items() if key[0] in collective_ids)
    atoms = _boundary_atoms(recording, needed)
    records = [_validate_service_plan(p, next(d for d in collective if d['plan_id'] == p['id']),
        initial, starts, ends, observed, frame_maps, atoms) for p in service_plans]
    readout_ids = {gid for gid, gate in by_id.items() if gate['gate_type'] in {'RESET', 'MEASURE', 'MZ'}}
    covered = Counter(gid for d in collective for gid in d['gate_ids'] + d.get('included_reset_gate_ids', []))
    if covered != Counter(readout_ids):
        raise ValueError('Collective services must cover every authored projection once')
    if expected_initial_reset_size is not None:
        resets = [r for r in records if r['kind'] == 'RESET']
        ready = {g for g, n in initial['dag'].items() if n['status'] == 'ready' and by_id[g]['gate_type'] == 'RESET'}
        if len(resets) != 1 or resets[0]['native_pulse_sizes'] != [expected_initial_reset_size] or set(collective[0]['gate_ids']) != ready:
            raise ValueError('All initial RESET targets must share one complete original service')
    if expected_measurement_size is not None:
        measured = [r for r in records if r['kind'] == 'MEASURE']
        if len(measured) != 1 or measured[0]['native_pulse_sizes'] != [expected_measurement_size] * 2:
            raise ValueError('All final syndrome MEASURE/RESET targets must share one M then one R')
    helper = _reference_helpers()
    helper.check_dependency_times(list(by_id.values()), list(observed.values()))
    helper.check_effect_kinds([o for o in observed.values() if _ids(o)], by_id)
    import stim
    ids = initial['quantum_state']['qubit_ids']
    if final['quantum_state']['qubit_ids'] != ids or set(ids) != set(initial['atoms']) or len(set(ids)) != len(ids):
        raise ValueError('Quantum reference changed physical carriers')
    final_generators = final['quantum_state']['generators']
    try:
        stim.Tableau.from_stabilizers([stim.PauliString(text) for text in _generator_texts(final['quantum_state'], helper, len(ids))])
    except ValueError as error:
        raise ValueError('Final quantum state requires a complete independent generator set') from error
    simulator = stim.TableauSimulator()
    tableau = stim.Tableau.from_stabilizers([stim.PauliString(text) for text in
        _generator_texts(initial['quantum_state'], helper, len(ids))])
    simulator.set_inverse_tableau(tableau.inverse())
    indices, bits = {q: i for i, q in enumerate(ids)}, {}
    for effect in sorted((o for o in observed.values() if _ids(o)), key=lambda o: (o['end'], o['index'])):
        for gid in _ids(effect):
            bit = helper.apply_stim(simulator, by_id[gid], indices)
            if bit is not None:
                bits[gid] = bit
    if bits != projections or final['measurement_results'] != {g: bits[g] for g, v in by_id.items() if v['gate_type'] in {'MEASURE', 'MZ'}}:
        raise ValueError('Committed projection differs from independent native Stim reference')
    if source:
        original_projections = source['original_native_projections']
        if Counter(p['native_gate_id'] for p in original_projections) != Counter(bits.keys()):
            raise ValueError('Original source projection identities are incomplete or duplicated')
        if any(type(p['outcome']) is not int or p['outcome'] not in (0, 1) or
               bits[p['native_gate_id']] != p['outcome'] for p in original_projections):
            raise ValueError('Collective reorder changed an original source projection')
    for generator in final_generators:
        if simulator.peek_observable_expectation(stim.PauliString(helper.pauli_text(generator, len(ids)))) != 1:
            raise ValueError('Final quantum sector differs from independent native execution')
    names = ['initial.json', 'checkpoint-final.json', 'plans.json', 'trace.jsonl', 'recording.json', 'decisions.json']
    names.extend(name for name in ('source-prefix.json', 'prefix-circuit.json') if (directory / name).exists())
    return {'schema': 'independent-collective-mz-audit/1', 'passed': True,
        'native_gate_count': len(by_id), 'native_counts': dict(Counter(g['gate_type'] for g in original)),
        'original_native_source_span_checked': source is not None, 'native_effects_once': len(by_id),
        'original_projection_count': len(bits), 'service_count': len(records), 'services': records,
        'continuous_collision_validation_scope': 'separate Executor and complete original-initial replay',
        'full_enola_kernel_claimed': False, 'full_physical_shor': False, 'fault_tolerance_claimed': False,
        'artifact_sha256': {name: _sha(directory / name) for name in names}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--expected-initial-reset-size', type=int)
    parser.add_argument('--expected-measurement-size', type=int)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = audit(args.directory, expected_initial_reset_size=args.expected_initial_reset_size,
                   expected_measurement_size=args.expected_measurement_size)
    output = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if args.output:
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(output)
    print(output)


if __name__ == '__main__':
    main()
