"""Trace-only validation, replay and resource estimation."""
from collections import Counter, defaultdict
import math


def validate_trace(trace):
    if trace.get('schema_version') == 2 and 'epochs' in trace:
        return validate_epoch_trace(trace)
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
    if trace.get('schema_version') == 2 and 'epochs' in trace:
        return epoch_metrics(trace)
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
    if trace.get('schema_version') == 2 and 'epochs' in trace:
        return epoch_frame_at(trace, time)
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


def _number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'Invalid {name}')
    return float(value)


def _position(value, name):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError(f'Invalid {name}')
    return tuple(_number(component, name) for component in value)


def validate_epoch_trace(trace):
    """Validate the epoch-centric schema without invoking a scheduler."""
    if trace.get('schema_version') != 2 or trace.get('kind') != 'execution_trace':
        raise ValueError('Invalid epoch trace header')
    duration = _number(trace.get('duration'), 'trace duration')
    if duration < 0:
        raise ValueError('Trace duration must be nonnegative')
    epochs = trace.get('epochs')
    if not isinstance(epochs, list):
        raise ValueError('Epoch trace needs an epochs list')
    by_id = {}
    for epoch in epochs:
        if not isinstance(epoch, dict) or not isinstance(epoch.get('id'), str) or epoch['id'] in by_id:
            raise ValueError('Duplicate or malformed epoch')
        start, end = _number(epoch.get('start_time'), 'epoch start'), _number(epoch.get('end_time'), 'epoch end')
        if start < 0 or end <= start or not math.isclose(end - start, _number(epoch.get('duration'), 'epoch duration'), abs_tol=1e-8):
            raise ValueError('Invalid epoch timing')
        if end > duration + 1e-8:
            raise ValueError('Epoch exceeds trace duration')
        by_id[epoch['id']] = epoch

    atom_initial = {atom['atom_id']: atom for atom in trace.get('initial_state', {}).get('atoms', [])}
    atom_final = {atom['atom_id']: atom for atom in trace.get('final_state', {}).get('atoms', [])}
    if not atom_initial or atom_initial.keys() != atom_final.keys():
        raise ValueError('Atom inventory changed')
    min_separation = _number(trace.get('initial_state', {}).get('min_atom_separation', 1.0),
                             'minimum atom separation')
    entangling_geometry = next((zone.get('entangling_geometry') for zone in trace.get('initial_state', {}).get('zones', [])
                                if zone.get('entangling_geometry')), None)
    pair_distance = float(entangling_geometry.get('pair_distance', 4.0)) if entangling_geometry else 4.0
    pair_tolerance = float(entangling_geometry.get('pair_distance_tolerance', 0.25)) if entangling_geometry else 0.25
    per_atom = defaultdict(list)
    for epoch in epochs:
        atoms = epoch.get('atoms', [])
        if not isinstance(atoms, list) or len(atoms) != len(set(atoms)) or not set(atoms) <= atom_initial.keys():
            raise ValueError('Invalid epoch atom set')
        sources, targets = epoch.get('source_positions'), epoch.get('target_positions')
        if not isinstance(sources, dict) or not isinstance(targets, dict) or set(sources) != set(atoms) or set(targets) != set(atoms):
            raise ValueError('Epoch positions must cover every epoch atom')
        for atom in atoms:
            _position(sources[atom], 'source position')
            _position(targets[atom], 'target position')
            per_atom[atom].append(epoch)
        dependencies = epoch.get('dependencies', [])
        if len(dependencies) != len(set(dependencies)) or any(parent not in by_id for parent in dependencies):
            raise ValueError('Unknown or duplicate epoch dependency')
        if any(by_id[parent]['end_time'] > epoch['start_time'] + 1e-8 for parent in dependencies):
            raise ValueError('Epoch dependency violation')

        requirements = epoch.get('resource_requirements', [])
        requirement_map = {}
        for requirement in requirements:
            if not isinstance(requirement, dict) or not isinstance(requirement.get('resource'), str):
                raise ValueError('Malformed epoch resource requirement')
            units = requirement.get('units')
            if type(units) is not int or units < 1 or requirement['resource'] in requirement_map:
                raise ValueError('Malformed epoch resource requirement')
            requirement_map[requirement['resource']] = units
        listed_resources = epoch.get('resources', [])
        if set(listed_resources) != set(requirement_map):
            raise ValueError('Epoch resource listing mismatch')

        if epoch.get('type') == 'AOD_MOVEMENT':
            from .hardware.aod import AODController, Translation
            from .hardware.geometry import Bounds, Position
            controller_data = trace.get('aod')
            if not isinstance(controller_data, dict):
                raise ValueError('AOD controller data is missing')
            controller = AODController(**{**controller_data,
                                          'allowed_region': Bounds(*controller_data['allowed_region'])})
            translations = tuple(Translation(atom, Position(*sources[atom]), Position(*targets[atom]))
                                 for atom in atoms if sources[atom] != targets[atom])
            if translations and not controller.compatible(translations):
                raise ValueError('Incompatible AOD epoch')
        elif epoch.get('type') == 'RYDBERG':
            pairs = epoch.get('pairs', [])
            if not isinstance(pairs, list) or len(pairs) != len(epoch.get('request_ids', [])):
                raise ValueError('Rydberg epoch pair count mismatch')
            flattened = [atom for pair in pairs for atom in pair]
            if len(flattened) != len(set(flattened)) or flattened != atoms:
                raise ValueError('Rydberg epoch atoms and pairs mismatch')
            placements = epoch.get('pair_placements', [])
            if len(placements) != len(pairs):
                raise ValueError('Rydberg placement count mismatch')
            for placement in placements:
                left, right = _position(placement['position_a'], 'pair position'), _position(placement['position_b'], 'pair position')
                if not math.isclose(math.dist(left, right), pair_distance, abs_tol=pair_tolerance + 1e-8):
                    raise ValueError('Rydberg pair distance violation')
        elif epoch.get('type') == 'IMAGING':
            if len(epoch.get('measurement_keys', [])) != len(atoms):
                raise ValueError('Imaging measurement-key mismatch')

    # Atom positions are a continuous chain across epoch boundaries.
    replay_positions = {atom: tuple(value['position']) for atom, value in atom_initial.items()}
    for atom, sequence in per_atom.items():
        sequence.sort(key=lambda epoch: (epoch['start_time'], epoch['id']))
        previous_end = 0.0
        for epoch in sequence:
            if epoch['start_time'] < previous_end - 1e-8:
                raise ValueError('Atom epochs overlap')
            source = _position(epoch['source_positions'][atom], 'source position')
            if source != replay_positions[atom]:
                raise ValueError(f'Discontinuous atom trajectory: {atom}')
            target = _position(epoch['target_positions'][atom], 'target position')
            replay_positions[atom] = target
            previous_end = epoch['end_time']
    for atom, record in atom_final.items():
        if _position(record['position'], 'final atom position') != replay_positions[atom]:
            raise ValueError(f'Final position mismatch: {atom}')

    # Endpoint minimum separation is the state-level physical invariant.
    for positions in (replay_positions,):
        values = list(positions.values())
        if any(math.dist(left, right) < min_separation - 1e-8
               for index, left in enumerate(values) for right in values[index + 1:]):
            raise ValueError('Final atom separation violation')

    spans = trace.get('resource_spans', [])
    span_by_owner = {}
    capacities = trace.get('resource_capacities', {})
    if not isinstance(capacities, dict) or any(type(value) is not int or value < 1 for value in capacities.values()):
        raise ValueError('Invalid resource capacities')
    changes = []
    for span in spans:
        owner = span.get('owner')
        if owner in span_by_owner:
            raise ValueError('Duplicate resource span owner')
        span_by_owner[owner] = span
        start, end = _number(span.get('start_time'), 'resource start'), _number(span.get('end_time'), 'resource end')
        resources = span.get('resources')
        if end < start or not isinstance(resources, dict):
            raise ValueError('Invalid resource span')
        if owner in by_id:
            epoch = by_id[owner]
            expected = {item['resource']: item['units'] for item in epoch['resource_requirements']}
            if resources != expected or not math.isclose(start, epoch['start_time'], abs_tol=1e-8) or not math.isclose(end, epoch['end_time'], abs_tol=1e-8):
                raise ValueError('Epoch resource custody mismatch')
        for resource, units in resources.items():
            if resource not in capacities or type(units) is not int or units < 1:
                raise ValueError('Invalid resource requirement')
            changes.extend(((start, 1, resource, units), (end, 0, resource, -units)))
    used = Counter()
    for _, sign, resource, units in sorted(changes, key=lambda item: (item[0], item[1])):
        used[resource] += units
        if used[resource] < 0 or used[resource] > capacities[resource]:
            raise ValueError(f'Resource capacity violation: {resource}')

    gate_completion = trace.get('gate_completion', {})
    if not isinstance(gate_completion, dict):
        raise ValueError('Missing gate completion map')
    request_ids = [request_id for terminals in gate_completion.values() for request_id in terminals]
    executed_ids = [request_id for epoch in epochs if epoch.get('type') != 'AOD_MOVEMENT'
                    for request_id in epoch.get('request_ids', [])]
    if len(executed_ids) != len(set(executed_ids)) or set(executed_ids) != set(request_ids):
        raise ValueError('Semantic request coverage mismatch')
    if not math.isclose(duration, max((epoch['end_time'] for epoch in epochs), default=0), abs_tol=1e-8):
        raise ValueError('Trace duration mismatch')
    snapshots = trace.get('state_snapshots', [])
    if snapshots:
        if any(_number(snapshot.get('time'), 'snapshot time') < 0 for snapshot in snapshots):
            raise ValueError('Invalid state snapshot')
        if snapshots[-1].get('state', {}).get('atoms') != trace['final_state']['atoms']:
            raise ValueError('Final state snapshot mismatch')
    return True


def _interval_union_length(intervals):
    total = 0.0
    current = None
    for start, end in sorted(intervals):
        if current is None:
            current = [start, end]
        elif start <= current[1] + 1e-12:
            current[1] = max(current[1], end)
        else:
            total += current[1] - current[0]
            current = [start, end]
    if current is not None:
        total += current[1] - current[0]
    return total


def epoch_metrics(trace):
    validate_epoch_trace(trace)
    epochs = trace['epochs']
    duration = trace['duration']
    by_type = defaultdict(list)
    for epoch in epochs:
        by_type[epoch['type']].append(epoch)
    movement = by_type['AOD_MOVEMENT']
    rydberg = by_type['RYDBERG']
    imaging = by_type['IMAGING']
    local = by_type['LOCAL_1Q']
    preparation = by_type['PREPARE'] + by_type['RESET']
    spans = trace['resource_spans']
    busy = Counter()
    for span in spans:
        for resource, units in span['resources'].items():
            busy[resource] += units * (span['end_time'] - span['start_time'])
    capacities = trace['resource_capacities']
    aod_sizes = [len(epoch['atoms']) for epoch in movement]
    pair_sizes = [epoch.get('pair_count', len(epoch.get('pairs', []))) for epoch in rydberg]
    imaging_sizes = [epoch.get('measurement_batch_size', len(epoch['atoms'])) for epoch in imaging]
    movement_distance = sum(math.dist(_position(epoch['source_positions'][atom], 'source position'),
                                      _position(epoch['target_positions'][atom], 'target position'))
                            for epoch in movement for atom in epoch['atoms'])
    occupied_wall = _interval_union_length([(epoch['start_time'], epoch['end_time']) for epoch in epochs])
    tone_x = [epoch.get('aod', {}).get('x_tones_used', 0) for epoch in movement]
    tone_y = [epoch.get('aod', {}).get('y_tones_used', 0) for epoch in movement]
    zone_atom_time = Counter()
    for epoch in movement:
        for zone in epoch.get('target_zones', {}).values():
            zone_atom_time[zone] += epoch['duration']
    for epoch in rydberg:
        zone_atom_time['entangling'] += len(epoch['atoms']) * epoch['duration']
    for epoch in imaging:
        zone_atom_time['measurement'] += len(epoch['atoms']) * epoch['duration']
    diagnostic_counts = Counter(item.get('reason') for item in trace.get('diagnostics', [])
                                if item.get('reason'))
    utilization = {resource: busy[resource] / (capacity * duration) if duration else 0
                   for resource, capacity in capacities.items()}
    result = {
        'schema_version': 2,
        'total_execution_time_us': duration,
        'physical_gate_count': len(trace['gate_completion']),
        'epoch_count': len(epochs),
        'movement_epoch_count': len(movement),
        'rydberg_epoch_count': len(rydberg),
        'imaging_epoch_count': len(imaging),
        'total_movement_time_us': sum(epoch['duration'] for epoch in movement),
        'total_rydberg_time_us': sum(epoch['duration'] for epoch in rydberg),
        'total_imaging_time_us': sum(epoch['duration'] for epoch in imaging),
        'total_local_1q_time_us': sum(epoch['duration'] for epoch in local),
        'total_preparation_reset_time_us': sum(epoch['duration'] for epoch in preparation),
        'total_idle_time_us': max(0.0, duration - occupied_wall),
        'movement_distance_um': movement_distance,
        'mean_atoms_per_aod_epoch': sum(aod_sizes) / max(1, len(aod_sizes)),
        'max_atoms_per_aod_epoch': max(aod_sizes, default=0),
        'mean_cz_pairs_per_rydberg_epoch': sum(pair_sizes) / max(1, len(pair_sizes)),
        'max_cz_pairs_per_rydberg_epoch': max(pair_sizes, default=0),
        'mean_measurement_batch_size': sum(imaging_sizes) / max(1, len(imaging_sizes)),
        'max_measurement_batch_size': max(imaging_sizes, default=0),
        'aod_x_tones_max': max(tone_x, default=0),
        'aod_y_tones_max': max(tone_y, default=0),
        'resource_utilization': utilization,
        'aod_utilization': utilization.get('device/aod', 0),
        'rydberg_utilization': utilization.get('device/rydberg', 0),
        'imaging_utilization': utilization.get('device/imaging', 0),
        'zone_atom_time_us': dict(zone_atom_time),
        'diagnostic_counts': dict(diagnostic_counts),
        'definitions': {
            'total_idle_time_us': 'Wall-clock intervals with no active physical epoch.',
            'device_utilization': 'Epoch resource capacity-time divided by available capacity-time.',
            'concurrency': 'Batch sizes are read directly from the epoch trace.',
        },
    }
    # Migration aliases keep small existing scripts readable while the public
    # metrics are now explicitly epoch-centric.
    result.update({
        'action_count': len(epochs),
        'movement_epochs': len(movement),
        'entangling_batches': len(rydberg),
        'measurement_batches': len(imaging),
    })
    return result


def epoch_frame_at(trace, time):
    """Replay an epoch trace at a time, including active pair links."""
    validate_epoch_trace(trace)
    time = max(0.0, min(float(time), trace['duration']))
    atoms = {atom['atom_id']: {**atom, 'position': list(atom['position'])}
             for atom in trace['initial_state']['atoms']}
    zone_kind = {zone['id']: zone['kind'] for zone in trace['initial_state'].get('zones', [])}
    active = []
    active_pairs = []
    for epoch in sorted(trace['epochs'], key=lambda item: (item['start_time'], item['id'])):
        if time < epoch['start_time']:
            break
        is_active = time < epoch['end_time']
        for atom in epoch['atoms']:
            source = _position(epoch['source_positions'][atom], 'source position')
            target = _position(epoch['target_positions'][atom], 'target position')
            if is_active:
                atoms[atom]['state'] = epoch['type']
                if epoch['type'] == 'AOD_MOVEMENT':
                    fraction = (time - epoch['start_time']) / epoch['duration']
                    atoms[atom]['position'] = [source[index] + fraction * (target[index] - source[index])
                                               for index in (0, 1)]
                    atoms[atom]['zone'], atoms[atom]['site_id'] = None, None
            else:
                atoms[atom]['position'] = list(target)
                if epoch['type'] == 'AOD_MOVEMENT':
                    atoms[atom]['zone'] = epoch.get('target_zones', {}).get(atom)
                    atoms[atom]['site_id'] = epoch.get('target_sites', {}).get(atom)
                    if zone_kind.get(atoms[atom]['zone']) == 'ENTANGLING':
                        atoms[atom]['state'] = 'IN_ENTANGLING_REGION'
                    elif zone_kind.get(atoms[atom]['zone']) == 'MEASUREMENT':
                        atoms[atom]['state'] = 'IN_MEASUREMENT_REGION'
                    else:
                        atoms[atom]['state'] = 'IDLE'
                elif epoch['type'] == 'RYDBERG':
                    atoms[atom]['state'] = 'IN_ENTANGLING_REGION'
                elif epoch['type'] == 'IMAGING':
                    atoms[atom]['state'] = 'MEASURED'
                elif epoch['type'] in ('LOCAL_1Q', 'PREPARE', 'RESET'):
                    if zone_kind.get(atoms[atom].get('zone')) == 'ENTANGLING':
                        atoms[atom]['state'] = 'IN_ENTANGLING_REGION'
                    elif zone_kind.get(atoms[atom].get('zone')) == 'MEASUREMENT':
                        atoms[atom]['state'] = 'IN_MEASUREMENT_REGION'
                    else:
                        atoms[atom]['state'] = 'IDLE'
        if is_active:
            active.append(epoch)
            if epoch['type'] == 'RYDBERG':
                active_pairs.extend(epoch.get('pairs', []))
    return {'time': time, 'atoms': list(atoms.values()), 'active_epochs': active,
            'active_actions': active, 'active_pairs': active_pairs}
