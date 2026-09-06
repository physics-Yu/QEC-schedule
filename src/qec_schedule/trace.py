"""Trace-only validation, replay and resource estimation."""
from collections import Counter, defaultdict
import math


def validate_trace(trace):
    actions = trace['actions']
    by_id = {a['id']: a for a in actions}
    if len(by_id) != len(actions):
        raise ValueError('Duplicate trace action')
    per_atom = defaultdict(list)
    for action in actions:
        start, end = action['start_time'], action['end_time']
        if not all(math.isfinite(v) for v in (start, end)) or start < 0 or end <= start:
            raise ValueError('Invalid action timing')
        if not math.isclose(end - start, action['duration'], abs_tol=1e-8):
            raise ValueError('Action duration mismatch')
        if any(d not in by_id or by_id[d]['end_time'] > start + 1e-8 for d in action['dependencies']):
            raise ValueError('Dependency violation')
        for atom in action['atoms']:
            per_atom[atom].append(action)
    initial = {a['atom_id']: a for a in trace['initial_state']['atoms']}
    final = {a['atom_id']: a for a in trace['final_state']['atoms']}
    if initial.keys() != final.keys():
        raise ValueError('Atom inventory changed')
    for atom, sequence in per_atom.items():
        position, end = initial[atom]['position'], 0
        for action in sorted(sequence, key=lambda a: a['start_time']):
            if action['start_time'] < end - 1e-8:
                raise ValueError('Atom actions overlap')
            index = action['atoms'].index(atom)
            if action['sources'][index]['position'] != position:
                raise ValueError('Discontinuous atom trajectory')
            position, end = action['targets'][index]['position'], action['end_time']
        if final[atom]['position'] != position:
            raise ValueError('Final position mismatch')
    changes = []
    for span in trace['resource_spans']:
        if span['end_time'] < span['start_time']:
            raise ValueError('Invalid resource span')
        for resource, units in span['resources'].items():
            if resource not in trace['resource_capacities'] or type(units) is not int or units < 1:
                raise ValueError('Invalid resource requirement')
            changes.extend([(span['start_time'], 1, resource, units), (span['end_time'], 0, resource, -units)])
    used = Counter()
    for _, _, resource, units in sorted(changes):
        used[resource] += units
        if used[resource] < 0 or used[resource] > trace['resource_capacities'][resource]:
            raise ValueError(f'Resource capacity violation: {resource}')
    # Replay trap occupancy at pickup/dropoff boundaries, independently of leases.
    occupied = {a['site_id']: a['atom_id'] for a in initial.values() if a['site_id']}
    atom_sites = {a['atom_id']: a['site_id'] for a in initial.values()}
    zones = {s['id']: z['id'] for z in trace['initial_state']['zones'] for s in z['sites']}
    caps = {z['id']: z['capacity'] for z in trace['initial_state']['zones']}
    boundaries = []
    for a in actions:
        if a['type'] == 'PICKUP':
            boundaries.append((a['start_time'], 0, a['id'], a))
        elif a['type'] == 'DROPOFF':
            boundaries.append((a['end_time'], 1, a['id'], a))
    for _, _, _, a in sorted(boundaries):
        atom = a['atoms'][0]
        if a['type'] == 'PICKUP':
            site = a['sources'][0]['site']
            if occupied.get(site) != atom:
                raise ValueError('Pickup from unoccupied site')
            del occupied[site]
            atom_sites[atom] = None
        else:
            site = a['targets'][0]['site']
            if site in occupied or atom_sites[atom] is not None:
                raise ValueError('Dropoff occupancy conflict')
            occupied[site], atom_sites[atom] = atom, site
        counts = Counter(zones[s] for s in occupied)
        if any(v > caps[k] for k, v in counts.items()):
            raise ValueError('Physical zone occupancy exceeded')
    if any(atom_sites[k] != a['site_id'] for k, a in final.items()):
        raise ValueError('Final site mismatch')
    if not math.isclose(trace['duration'], max((a['end_time'] for a in actions), default=0), abs_tol=1e-8):
        raise ValueError('Trace duration mismatch')
    return True


def metrics(trace):
    validate_trace(trace)
    duration = trace['duration']
    busy = Counter()
    for span in trace['resource_spans']:
        for resource, units in span['resources'].items():
            busy[resource] += units * (span['end_time'] - span['start_time'])
    batches = defaultdict(set)
    tasks = {}
    distance = 0.0
    for a in trace['actions']:
        batches[a['type']].add(a['batch_id'])
        tasks.setdefault(a['task_id'], a)
        if a['type'] == 'MOVE':
            distance += math.dist(a['sources'][0]['position'], a['targets'][0]['position'])
    waits = [a['start_time'] - a['ready_time'] for a in tasks.values()]
    # Integral of ready-but-not-dispatched tasks, not a quantum-gate parallelism ratio.
    blocked_area = sum(d['blocked_tasks'] * (trace['decisions'][i + 1]['time'] - d['time'])
                       for i, d in enumerate(trace['decisions'][:-1]))
    return {'total_execution_time_us': duration, 'physical_gate_count': len(trace['gate_completion']),
            'action_count': len(trace['actions']), 'task_count': len(tasks),
            'movement_distance_um': distance, 'movement_epochs': len(batches['MOVE']),
            'entangling_batches': len(batches['ENTANGLE']), 'measurement_batches': len(batches['MEASURE']),
            'total_ready_wait_us': sum(waits), 'mean_ready_wait_us': sum(waits) / max(1, len(waits)),
            'max_ready_wait_us': max(waits, default=0), 'blocked_task_time_us': blocked_area,
            'mean_blocked_ready_tasks': blocked_area / duration if duration else 0,
            'resource_utilization': {k: busy[k] / (v * duration) if duration else 0
                                     for k, v in trace['resource_capacities'].items()},
            'definitions': {'waiting': 'Time from dependency readiness to dispatch, summed per task.',
                            'parallelism_loss': 'Integral of resource-blocked ready tasks; task-level, not physical gates.',
                            'utilization': 'Occupied capacity-time / available capacity-time; includes custody leases.'}}


def frame_at(trace, time):
    """Interpolate a frame using trace records alone; time is in microseconds."""
    time = max(0, min(float(time), trace['duration']))
    atoms = {a['atom_id']: {**a, 'position': list(a['position'])} for a in trace['initial_state']['atoms']}
    active = []
    for a in trace['actions']:
        if time < a['start_time']:
            break
        for i, atom in enumerate(a['atoms']):
            target = a['targets'][i]
            if time >= a['end_time']:
                atoms[atom].update(position=target['position'], state='IDLE')
                if a['type'] == 'DROPOFF':
                    atoms[atom].update(zone=target['zone'], site_id=target['site'])
                elif a['type'] == 'PICKUP':
                    atoms[atom].update(zone=None, site_id=None, state='MOVING')
            else:
                atoms[atom]['state'] = a['type']
                if a['type'] in ('PICKUP', 'MOVE', 'DROPOFF'):
                    atoms[atom].update(zone=None, site_id=None)
                if a['type'] == 'MOVE':
                    f = (time - a['start_time']) / a['duration']
                    atoms[atom]['position'] = [x + f * (y - x) for x, y in zip(a['sources'][i]['position'], target['position'])]
        if time < a['end_time']:
            active.append(a)
    return {'time': time, 'atoms': list(atoms.values()), 'active_actions': active}
