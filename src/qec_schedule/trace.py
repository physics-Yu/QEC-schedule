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
    spans = {s['owner']: s for s in trace['resource_spans']}
    if len(spans) != len(trace['resource_spans']):
        raise ValueError('Duplicate resource owner')
    for a in actions:
        span = spans.get(a['batch_id'])
        if span is None or span['start_time'] > a['start_time'] + 1e-8 or span['end_time'] < a['end_time'] - 1e-8:
            raise ValueError('Action is missing resource custody')
        if any(span['resources'].get(r['resource'], 0) < r['units'] for r in a['required_resources']):
            raise ValueError('Action resources are not covered')
    for lease in trace['reservations']:
        span = spans.get(lease['id'])
        expected = {r['resource']: r['units'] for r in lease['required_resources']}
        release = max((by_id[k]['end_time'] for k in lease['release_after']), default=trace['duration'])
        if (span is None or span['resources'] != expected
                or span['start_time'] > min(by_id[k]['start_time'] for k in lease['acquire_before']) + 1e-8
                or span['end_time'] < release - 1e-8):
            raise ValueError('Persistent reservation lifetime violation')
    # Independently recheck the physical batch rules recorded by the scheduler.
    from .hardware.aod import AODController, Translation
    from .hardware.geometry import Bounds, Position
    controller_data = trace['aod']
    controller = AODController(**{**controller_data, 'allowed_region': Bounds(*controller_data['allowed_region'])})
    batch_actions = defaultdict(list)
    for a in actions:
        batch_actions[a['batch_id']].append(a)
    for batch in batch_actions.values():
        moves = [a for a in batch if a['type'] == 'MOVE']
        if moves:
            translations = [Translation(a['atoms'][0], Position(*a['sources'][0]['position']),
                                         Position(*a['targets'][0]['position'])) for a in moves]
            if not controller.compatible(translations):
                raise ValueError('Incompatible AOD batch')
        for kind in ('MOVE', 'ENTANGLE', 'MEASURE'):
            group = [a for a in batch if a['type'] == kind]
            if group and any(not math.isclose(a['start_time'], group[0]['start_time'], abs_tol=1e-8)
                             or not math.isclose(a['end_time'], group[0]['end_time'], abs_tol=1e-8) for a in group):
                raise ValueError('Unsynchronized batch')
            if kind != 'MOVE' and len({a['source_zone'] for a in group}) > 1:
                raise ValueError('Laser batch spans multiple zones')
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
    sizes = {kind: Counter(a['batch_id'] for a in trace['actions'] if a['type'] == kind)
             for kind in ('MOVE', 'ENTANGLE', 'MEASURE')}
    action_ids = {a['id']: a for a in trace['actions']}
    gate_actions = defaultdict(list)
    for a in trace['actions']:
        gate_actions[a['gate_id']].append(a)
    gate_start = {k: min(a['start_time'] for a in group) for k, group in gate_actions.items()}
    gate_end = {k: max(action_ids[a]['end_time'] for a in terminals) for k, terminals in trace['gate_completion'].items()}
    gate_parents = {k: {action_ids[d]['gate_id'] for a in group for d in a['dependencies']
                        if action_ids[d]['gate_id'] != k} for k, group in gate_actions.items()}
    parallelism = []
    for time in sorted({d['time'] for d in trace['decisions']}):
        ready = [k for k, start in gate_start.items() if start >= time - 1e-8
                 and all(gate_end[p] <= time + 1e-8 for p in gate_parents[k])]
        executed = sum(math.isclose(gate_start[k], time, rel_tol=0, abs_tol=1e-8) for k in ready)
        parallelism.append({'time': time, 'N_ready': len(ready), 'N_executed': executed,
                            'P': executed / len(ready) if ready else None})
    # Integral of ready-but-not-dispatched tasks, not a quantum-gate parallelism ratio.
    blocked_area = sum(d['blocked_tasks'] * (trace['decisions'][i + 1]['time'] - d['time'])
                       for i, d in enumerate(trace['decisions'][:-1]))
    return {'total_execution_time_us': duration, 'physical_gate_count': len(trace['gate_completion']),
            'action_count': len(trace['actions']), 'task_count': len(tasks),
            'movement_distance_um': distance, 'movement_epochs': len(batches['MOVE']),
            'mean_transport_distance_um': distance / max(1, sum(sizes['MOVE'].values())),
            'mean_atoms_per_epoch': sum(sizes['MOVE'].values()) / max(1, len(sizes['MOVE'])),
            'max_atoms_per_epoch': max(sizes['MOVE'].values(), default=0),
            'entangling_batches': len(batches['ENTANGLE']), 'measurement_batches': len(batches['MEASURE']),
            'mean_pairs_per_pulse': sum(sizes['ENTANGLE'].values()) / max(1, len(sizes['ENTANGLE'])),
            'max_pairs_per_pulse': max(sizes['ENTANGLE'].values(), default=0),
            'mean_atoms_per_measurement_batch': sum(sizes['MEASURE'].values()) / max(1, len(sizes['MEASURE'])),
            'transport_device_time_us': busy['device/aod'], 'single_qubit_device_time_us': busy['device/local_1q'],
            'entangling_device_time_us': busy['device/rydberg'], 'measurement_device_time_us': busy['device/imaging'],
            'total_ready_wait_us': sum(waits), 'mean_ready_wait_us': sum(waits) / max(1, len(waits)),
            'max_ready_wait_us': max(waits, default=0), 'blocked_task_time_us': blocked_area,
            'mean_blocked_ready_tasks': blocked_area / duration if duration else 0,
            'physical_gate_parallelism': parallelism,
            'resource_utilization': {k: busy[k] / (v * duration) if duration else 0
                                     for k, v in trace['resource_capacities'].items()},
            'definitions': {'waiting': 'Time from dependency readiness to dispatch, summed per task.',
                            'parallelism_loss': 'Integral of resource-blocked ready tasks; task-level, not physical gates.',
                            'physical_gate_parallelism': 'At each dispatch time, unstarted gates with completed parents versus gates starting now; P=null when none are ready.',
                            'category_times': 'Sum of occupied device-unit durations, not a partition of wall-clock makespan.',
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
