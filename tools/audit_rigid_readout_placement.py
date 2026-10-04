"""Read-only geometry/provenance audit of saved automatic rigid MZ decisions.

Recomputes the nearest origin from recorded source positions and original
zones/device axes, without importing the production placement or router.
Executor/replay and continuous collision validation remain separate evidence.
"""
import argparse
from collections import Counter
import hashlib
import json
from math import hypot, isclose
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def audit(directory):
    directory = Path(directory)
    initial, recording, decisions, summary = (read(directory/name) for name in
        ('initial.json', 'recording.json', 'decisions.json', 'summary.json'))
    if summary['status'] != 'completed' or summary.get('readout_placement') != 'nearest_mz':
        raise ValueError('Requires a completed automatic-MZ run')
    if not summary['audit']['independent_plan_replay_equal']:
        raise ValueError('Original-initial-state replay must already be verified')
    gates = {g['id']: g for g in initial['circuit']['gates']}
    registry = initial.get('aods') or {'AOD_0': initial['aod']}
    effects = [o for o in recording['operations'] if o['kind'] in ('reset', 'measurement')]
    original_ids = {g for g, gate in gates.items() if gate['gate_type'] in ('RESET', 'MEASURE', 'MZ')}
    actual_ids = Counter(g for pulse in effects for g in (pulse.get('gate_ids') or [pulse['gate_id']]))
    if actual_ids != Counter({g: 1 for g in original_ids}):
        raise ValueError('Recorded readout pulses omit, duplicate or invent original projections')
    zones = {z['id']: z for z in initial['world']['zones'] if z['zone_type'] == 'measurement'}

    def at(time):
        points, aods = {}, None
        for frame in recording['frames']:
            if frame['time'] > time + 1e-8:
                break
            for atom in frame['atom_updates']:
                points[atom['id']] = atom['position']
            aods = frame['aods']
        return points, aods

    def same(a, b):
        return len(a) == len(b) and all(isclose(x, y, abs_tol=1e-7) for x, y in zip(a, b))

    selections, covered = [], set()
    for decision in decisions:
        rows = decision.get('readout_placement_decisions', [])
        if decision['kind'] in ('RESET', 'MEASURE') and not rows:
            raise ValueError('Every committed readout service needs a placement decision')
        for row in rows:
            source, _ = at(decision['start_us'])
            aod_id, atom_ids = row['aod_id'], row['atom_ids']
            aod = registry[aod_id]
            origin = row['source_origin_um']
            xs = aod['column_offsets_um'] or [i*aod['spacing_um'] for i in range(aod['columns'])]
            ys = aod['row_offsets_um'] or [i*aod['spacing_um'] for i in range(aod['rows'])]
            offsets = {}
            tolerance = initial['hardware']['alignment_tolerance_um']
            for q in atom_ids:
                actual = []
                for key, axis, value in zip(('x_um', 'y_um'), (xs, ys), origin):
                    matches = [offset for offset in axis if abs(source[q][key]-value-offset) <= tolerance]
                    if len(matches) != 1:
                        raise ValueError('Source must embed uniquely in actual device axes at capture origin')
                    actual.append(matches[0])
                offsets[q] = tuple(actual)
            selected = row['selected']
            if not selected or selected['status'] != 'accepted' or row['optimality_claim']:
                raise ValueError('Selection must be a validated bounded service')
            accepted = [c for c in row['candidates'] if c['status'] == 'accepted']
            if len(row['candidates']) > row['candidate_budget'] or len(accepted) > row['top_k']:
                raise ValueError('Placement budget exceeded')
            best = min(accepted, key=lambda c: (c['actual_us'], c['actual_distance_um'],
                c['proxy_distance_um'], *c['target_pose_um'], c['zone_id']))
            if selected != best:
                raise ValueError('Selected target does not minimize actual accepted service cost')
            zone = zones[selected['zone_id']]['bounds']
            world = initial['world']['bounds']
            rectangles = [world] + ([aod['envelope']] if aod['envelope'] else [])
            lo = [max(rect['lower'][key]-min(axis) for rect in rectangles)
                  for key, axis in zip(('x_um', 'y_um'), (xs, ys))]
            hi = [min(rect['upper'][key]-max(axis) for rect in rectangles)
                  for key, axis in zip(('x_um', 'y_um'), (xs, ys))]
            for axis, key in enumerate(('x_um', 'y_um')):
                lo[axis] = max(lo[axis], zone['lower'][key]-min(p[axis] for p in offsets.values()))
                hi[axis] = min(hi[axis], zone['upper'][key]-max(p[axis] for p in offsets.values()))
            if any(low > high for low, high in zip(lo, hi)):
                raise ValueError('Payload cannot fit original MZ and device domain')
            nearest = [max(low, min(high, v)) for v, low, high in zip(origin, lo, hi)]
            if not same(nearest, selected['features']['geometric_nearest_pose_um']):
                raise ValueError('Nearest geometry differs from independent source/axis calculation')
            if not same([lo[0], lo[1], hi[0], hi[1]], selected['features']['feasible_origin_bounds_um']):
                raise ValueError('Feasible domain omits actual carriers or spare axes')
            target = selected['target_pose_um']
            expected_positions = {q: (target[0]+dx, target[1]+dy) for q, (dx, dy) in offsets.items()}
            if set(dict(selected['positions'])) != set(atom_ids):
                raise ValueError('Selection carrier set changed')
            if any(not same(expected_positions[q], p) for q, p in selected['positions']):
                raise ValueError('Selected positions do not preserve source rigid payload offsets')
            gate_ids = row['gate_ids'] + row['included_reset_gate_ids']
            expected_atoms = {gates[g]['qubit_ids'][0] for g in gate_ids}
            if expected_atoms != set(atom_ids) or covered.intersection(gate_ids):
                raise ValueError('Missing, foreign or repeated native readout gate')
            covered.update(gate_ids)
            pulses = [o for o in effects if set(o.get('gate_ids') or [o['gate_id']]).intersection(gate_ids)]
            pulse_ids = Counter(g for o in pulses for g in (o.get('gate_ids') or [o['gate_id']]) if g in gate_ids)
            if pulse_ids != Counter({g: 1 for g in gate_ids}):
                raise ValueError('Placement decision lacks corresponding actual committed projections')
            operations = [o for o in recording['operations'] if o['plan_id'] == decision['plan_id']]
            lane = [o for o in operations if o['kind'] not in ('reset', 'measurement') and o['aod_id'] == aod_id]
            actual_us = sum(o['end']-o['start'] for o in lane + pulses)
            actual_distance = sum(hypot(o['target_axes']['x_um'][0]-o['source_axes']['x_um'][0],
                o['target_axes']['y_um'][0]-o['source_axes']['y_um'][0]) for o in lane if o['kind'] == 'aod_move')
            if not same([actual_us, actual_distance], [selected['actual_us'], selected['actual_distance_um']]):
                raise ValueError('Selected service cost differs from actual committed lane operations')
            if len(rows) == 1 and not same([actual_us], [decision['duration_us']]):
                raise ValueError('Single service cost differs from committed plan duration')
            for pulse in pulses:
                points, aods = at(pulse['start'])
                if not same(target, [aods[aod_id]['pose']['x_um'], aods[aod_id]['pose']['y_um']]):
                    raise ValueError('Committed device measurement pose differs from selected target')
                for q, point in expected_positions.items():
                    if not same(point, [points[q]['x_um'], points[q]['y_um']]):
                        raise ValueError('Committed carrier position differs from selected target')
                    if not all(zone['lower'][key] <= value <= zone['upper'][key]
                               for key, value in zip(('x_um', 'y_um'), point)):
                        raise ValueError('Committed measured carrier outside MZ')
            selections.append({'decision': decision['decision'], 'aod_id': aod_id,
                'carrier_count': len(atom_ids), 'source_origin_um': origin,
                'nearest_geometric_pose_um': nearest, 'selected_pose_um': target,
                'geometric_nearest_distance_um': hypot(nearest[0]-origin[0], nearest[1]-origin[1]),
                'tried': len(row['candidates']), 'accepted': len(accepted),
                'selected_actual_service_us': selected['actual_us'],
                'cost_verified_from_recording': True,
                'shared_service_cost_scope': 'sum of lane operation durations plus shared effect; joint waits separate' if len(rows)>1 else 'complete service',
                'pulse_count_checked': len(pulses)})
    if covered != original_ids:
        raise ValueError('Automatic placement decisions do not cover every original projection')
    return {'schema': 'independent-rigid-readout-placement-audit/1', 'passed': True,
        'selections': selections, 'selection_count': len(selections),
        'original_projection_count': len(covered), 'independent_original_geometry': True,
        'accepted_actual_cost_minimum': True, 'committed_pose_positions_match_selection': True,
        'continuous_collision_proof': 'separate Executor validation and complete original-initial replay',
        'continuous_global_optimum_claimed': False,
        'artifact_sha256': {name: hashlib.sha256((directory/name).read_bytes()).hexdigest() for name in
            ('initial.json', 'recording.json', 'decisions.json', 'summary.json')}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = audit(args.directory)
    text = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
    if args.output:
        args.output.write_text(text, encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
