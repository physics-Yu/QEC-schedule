"""Explicit one-case-at-a-time hardware studies, with reproducible full traces."""
import csv
from dataclasses import replace
import json
from pathlib import Path
import re
import yaml
from .hardware.config import _UniqueKeyLoader, _keys
from .hardware.geometry import Bounds
from .hardware.zones import ZoneKind
from .simulation import run_cycle, save_run


def _override_bounds(value, name):
    if isinstance(value, Bounds):
        return value
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ValueError(f'{name} must be [xmin, ymin, xmax, ymax]')
    return Bounds(*value)


def _normalize_geometry_overrides(value, name, optional):
    _keys(value, (), optional)
    result = dict(value)
    if 'interaction_lanes' in result:
        lanes = result['interaction_lanes']
        if lanes is not None and not isinstance(lanes, (list, tuple)):
            raise ValueError(f'{name}.interaction_lanes must be a list, tuple or null')
        result['interaction_lanes'] = None if lanes is None else tuple(lanes)
    for key in ('imaging_bounds', 'field_of_view'):
        if key in result and result[key] is not None:
            result[key] = _override_bounds(result[key], f'{name}.{key}')
    return result


def _configuration_summary(config, overrides, rydberg_parallel_pairs):
    return {
        'overrides': overrides,
        'timing': config.timing.to_dict(),
        'aod': config.aod.to_dict(),
        'zones': [zone.to_dict() for zone in config.zones],
        'device_capacities': dict(config.device_capacities),
        'rydberg_parallel_pairs': rydberg_parallel_pairs,
    }


def _row_hardware_parameters(config, rydberg_parallel_pairs):
    entangling = next((zone.entangling_geometry for zone in config.zones
                       if zone.kind == ZoneKind.ENTANGLING), None)
    measurement = next((zone.measurement_geometry for zone in config.zones
                        if zone.kind == ZoneKind.MEASUREMENT), None)
    return {
        'max_x_tones': config.aod.max_x_tones,
        'max_y_tones': config.aod.max_y_tones,
        'aod_speed_x': config.aod.max_speed_x,
        'aod_speed_y': config.aod.max_speed_y,
        'axis_execution': config.aod.axis_execution,
        'entanglement_max_atoms': entangling.max_atoms if entangling else None,
        'entanglement_max_parallel_pairs': entangling.max_parallel_pairs if entangling else None,
        'inter_pair_guard_distance': entangling.inter_pair_guard_distance if entangling else None,
        'measurement_max_parallel_atoms': measurement.max_parallel_atoms if measurement else None,
        'measurement_fov': measurement.field_of_view.to_list() if measurement else None,
        'rydberg_parallel_pairs': rydberg_parallel_pairs,
    }


def apply_overrides(config, overrides):
    _keys(overrides, (), ('timing', 'aod', 'zone_capacities', 'devices',
                          'entanglement', 'measurement', 'rydberg_parallel_pairs'))
    timing = overrides.get('timing', {})
    _keys(timing, (), config.timing.__dataclass_fields__)
    aod = overrides.get('aod', {})
    _keys(aod, (), ('max_x_tones', 'max_y_tones', 'displacement_tolerance',
                    'axis_execution', 'min_tone_spacing', 'max_speed_x',
                    'max_speed_y', 'ordering_rule'))
    entanglement = _normalize_geometry_overrides(
        overrides.get('entanglement', {}), 'entanglement',
        ('interaction_lanes', 'preferred_axis', 'pair_distance',
         'pair_distance_tolerance', 'inter_pair_guard_distance',
         'min_atom_spacing', 'max_parallel_pairs', 'max_atoms'))
    measurement = _normalize_geometry_overrides(
        overrides.get('measurement', {}), 'measurement',
        ('imaging_bounds', 'min_atom_spacing', 'max_parallel_atoms',
         'field_of_view'))
    zones = overrides.get('zone_capacities', {})
    _keys(zones, (), [z.id for z in config.zones])
    devices = overrides.get('devices', {})
    _keys(devices, (), config.device_capacities)
    rydberg_parallel_pairs = overrides.get('rydberg_parallel_pairs')
    if (rydberg_parallel_pairs is not None
            and (type(rydberg_parallel_pairs) is not int or rydberg_parallel_pairs <= 0)):
        raise ValueError('rydberg_parallel_pairs must be a positive integer or None')
    updated_timing = replace(config.timing, **timing)
    updated_aod = replace(config.aod, **aod)
    if 'move_speed' in timing and not ({'max_speed_x', 'max_speed_y'} & set(aod)):
        updated_aod = replace(updated_aod, max_speed_x=timing['move_speed'],
                              max_speed_y=timing['move_speed'])
    updated_zones = []
    entanglement_applied = measurement_applied = False
    for zone in config.zones:
        values = {'capacity': zones.get(zone.id, zone.capacity)}
        if zone.kind == ZoneKind.ENTANGLING and entanglement:
            values['entangling_geometry'] = replace(zone.entangling_geometry, **entanglement)
            entanglement_applied = True
        if zone.kind == ZoneKind.MEASUREMENT and measurement:
            values['measurement_geometry'] = replace(zone.measurement_geometry, **measurement)
            measurement_applied = True
        updated_zones.append(replace(zone, **values))
    if entanglement and not entanglement_applied:
        raise ValueError('No entangling zone is available for entanglement overrides')
    if measurement and not measurement_applied:
        raise ValueError('No measurement zone is available for measurement overrides')
    return replace(config, timing=updated_timing, aod=updated_aod,
                   zones=tuple(updated_zones),
                   device_capacities={**config.device_capacities, **devices})


def load_sweep(path):
    try:
        raw = yaml.load(Path(path).read_text(encoding='utf-8'), Loader=_UniqueKeyLoader)
        _keys(raw, ('schema_version', 'cases'))
        if type(raw['schema_version']) is not int or raw['schema_version'] != 1 or not isinstance(raw['cases'], list) or not raw['cases']:
            raise ValueError('Expected nonempty sweep schema_version 1')
        seen = set()
        for case in raw['cases']:
            _keys(case, ('id', 'overrides'))
            if not isinstance(case['id'], str) or not re.fullmatch(r'[a-zA-Z0-9_-]+', case['id']) or case['id'] in seen:
                raise ValueError('Case IDs must be unique safe directory names')
            seen.add(case['id'])
        return raw['cases']
    except yaml.YAMLError as exc:
        raise ValueError(f'Malformed sweep: {exc}') from exc


def run_sweep(config, cases, output_dir, *, code=None, rounds=1, primitive='CZ'):
    # Validate all configurations before starting any simulation or writing output.
    ids = [c['id'] for c in cases]
    if not ids or len(set(ids)) != len(ids) or any(not re.fullmatch(r'[a-zA-Z0-9_-]+', k) for k in ids):
        raise ValueError('Invalid sweep IDs')
    configs = [apply_overrides(config, case['overrides']) for case in cases]
    output_dir = Path(output_dir)
    rows = []
    for case, hardware in zip(cases, configs):
        rydberg_parallel_pairs = case['overrides'].get('rydberg_parallel_pairs')
        trace, result = run_cycle(hardware, code=code, rounds=rounds, primitive=primitive,
                                  rydberg_parallel_pairs=rydberg_parallel_pairs)
        save_run(trace, result, output_dir / case['id'])
        row = {
            'case': case['id'],
            'configuration': _configuration_summary(hardware, case['overrides'],
                                                    rydberg_parallel_pairs),
            **_row_hardware_parameters(hardware, rydberg_parallel_pairs),
            **{k: v for k, v in result.items() if isinstance(v, (int, float))},
            **{k + '_utilization': v for k, v in result['resource_utilization'].items()
               if k.startswith('device/')},
            'diagnostic_counts': result.get('diagnostic_counts', {}),
            'decision_count': len(trace.get('decisions', [])),
            'infeasibility_diagnostics': trace.get('diagnostics', []),
        }
        rows.append(row)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / 'sweep.json').write_text(json.dumps({'schema_version': 1, 'cases': cases, 'results': rows}, indent=2), encoding='utf-8')
    with (output_dir / 'sweep.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return rows


def save_sweep_plot(rows, path):
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    fig = Figure(figsize=(11, 6), layout='constrained')
    FigureCanvasAgg(fig)
    ax = fig.subplots()
    bars = ax.barh([r['case'] for r in rows], [r['total_execution_time_us'] for r in rows], color='#377e91')
    ax.invert_yaxis()
    ax.bar_label(bars, fmt='%.1f μs', padding=5, fontsize=9)
    ax.set_xlim(0, max(r['total_execution_time_us'] for r in rows) * 1.18)
    ax.set_xlabel('Complete syndrome-cycle execution time (μs)')
    ax.set_title('Hardware parameter sweep', loc='left', fontsize=17, pad=15)
    ax.spines[['top', 'right']].set_visible(False)
    ax.grid(axis='x', alpha=.15)
    ax.set_axisbelow(True)
    fig.savefig(path, dpi=160)
