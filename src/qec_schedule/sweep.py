"""Explicit one-case-at-a-time hardware studies, with reproducible full traces."""
import csv
from dataclasses import replace
import json
from pathlib import Path
import re
import yaml
from .hardware.config import _UniqueKeyLoader, _keys
from .simulation import run_cycle, save_run


def apply_overrides(config, overrides):
    _keys(overrides, (), ('timing', 'aod', 'zone_capacities', 'devices'))
    timing = overrides.get('timing', {})
    _keys(timing, (), config.timing.__dataclass_fields__)
    aod = overrides.get('aod', {})
    _keys(aod, (), ('max_x_tones', 'max_y_tones', 'displacement_tolerance'))
    zones = overrides.get('zone_capacities', {})
    _keys(zones, (), [z.id for z in config.zones])
    devices = overrides.get('devices', {})
    _keys(devices, (), config.device_capacities)
    return replace(config, timing=replace(config.timing, **timing), aod=replace(config.aod, **aod),
                   zones=tuple(replace(z, capacity=zones.get(z.id, z.capacity)) for z in config.zones),
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
        trace, result = run_cycle(hardware, code=code, rounds=rounds, primitive=primitive)
        save_run(trace, result, output_dir / case['id'])
        row = {'case': case['id'], **{k: v for k, v in result.items() if isinstance(v, (int, float))},
               **{k + '_utilization': v for k, v in result['resource_utilization'].items() if k.startswith('device/')}}
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
