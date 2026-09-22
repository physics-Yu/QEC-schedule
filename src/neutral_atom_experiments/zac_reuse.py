"""Matched reuse on/off experiment: author frontend, local physical execution."""
from collections import Counter
from hashlib import sha256
from pathlib import Path
from time import perf_counter
import json
import math
import os
import subprocess
import sys

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.circuit import PhysicalCircuit, DynamicGateDAG
from neutral_atom_env.domain.models import (Atom, GridCoord, HolderRef, HolderType,
    PhysicalGate, Position2D as P, Rectangle, StaticTrap, Zone, ZoneType)
from neutral_atom_env.domain.operations import HardwareConfig
from neutral_atom_env.replay.serializer import canonical_json, primitive
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.visualization.recording import VisualRecorder
from neutral_atom_env.world import WorldState, PlacementState, AODRuntimeState
from neutral_atom_strategies.scheduling.zac_reuse import ZACPlacementStrategy, site_id
from neutral_atom_strategies.scheduling.m3 import initial_terminal

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SOURCE = ROOT / 'artifacts/zac-reuse/sources/zenodo/ZAC_AE'


def demos():
    return {
        'cross': dict(name='四原子换伙伴', atom_count=4,
                      pairs=[[0,1],[2,3],[0,2],[1,3],[0,3],[1,2]]),
        'repeat': dict(name='同一对连续复用', atom_count=4,
                       pairs=[[0,1],[2,3],[0,1],[2,3],[0,1],[2,3]]),
        'eight': dict(name='八原子三层交叉配对', atom_count=8,
                      pairs=[[0,1],[2,3],[4,5],[6,7],[0,2],[1,3],[4,6],[5,7],
                             [0,4],[1,5],[2,6],[3,7]]),
        'idle': dict(name='闲置原子不驻留 EZ', atom_count=6,
                     pairs=[[0,1],[2,3],[0,2],[2,4],[1,5]]),
        'tradeoff': dict(name='反例：少搬原子但总时间更长', atom_count=4,
                         pairs=[[0,1],[2,3],[0,2]]),
    }


def normalize_spec(raw):
    n = raw.get('atom_count')
    pairs = raw.get('pairs')
    if type(n) is not int or not 2 <= n <= 128:
        raise ValueError('当前实验支持 2–128 原子')
    if not isinstance(pairs, list) or not 1 <= len(pairs) <= 4096:
        raise ValueError('请输入 1–4096 个 CZ 对')
    for pair in pairs:
        if (not isinstance(pair, list) or len(pair) != 2 or pair[0] == pair[1]
                or any(type(q) is not int or not 0 <= q < n for q in pair)):
            raise ValueError('CZ 对须包含两个不同且在原子范围内的整数')
    timeout = raw.get('timeout_s', 300)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or not 1 <= timeout <= 7200:
        raise ValueError('timeout_s 须在 1–7200 秒之间')
    bounded_spares = raw.get('bounded_spares', False)
    if type(bounded_spares) is not bool:
        raise ValueError('bounded_spares 须为布尔值')
    initial_placement = raw.get('initial_placement', 'fixed')
    if initial_placement not in ('fixed', 'sa', 'compare'):
        raise ValueError('initial_placement 须为 fixed、sa 或 compare')
    # These are explicit experimental geometry parameters, not author defaults.
    # A 1 um coordinate lattice represents the author's paired 2 um SLM sites;
    # physical clearance, AOD spacing floor, and pulse radius are unchanged.
    cols = max(4, math.ceil(n / 2))
    ez_cols = math.ceil(n / 4)
    width = max(100, 10 * cols + 40, 20 * ez_cols + 40)
    architecture = dict(name='QEC-scheduler ZAC reuse experiment',
        operation_duration=dict(rydberg=.3, atom_transfer=100, **{'1qGate':1}),
        storage_zones=[dict(zone_id=0, slms=[dict(id=0, site_seperation=[10,10],
            r=3, c=cols, location=[0,0])])],
        entanglement_zones=[dict(zone_id=0, slms=[
            dict(id=1, site_seperation=[20,20], r=2, c=ez_cols, location=[0,50]),
            dict(id=2, site_seperation=[20,20], r=2, c=ez_cols, location=[2,50])])],
        aods=[dict(id=0, site_seperation=2, r=2, c=cols)],
        arch_range=[[-20,-20],[width,110]], rydberg_range=[[[-20,40],[width,90]]])
    return dict(name=str(raw.get('name', '自定义 CZ'))[:120], atom_count=n, pairs=pairs,
                initial_mapping=[[0,q // cols,q % cols] for q in range(n)],
                architecture=architecture, timeout_s=timeout, bounded_spares=bounded_spares,
                initial_placement=initial_placement)


def make_state(spec):
    arch = spec['architecture']
    bounds = Rectangle(*(P(*v) for v in arch['arch_range']))
    width = bounds.upper.x_um
    storage_bounds = spec.get('storage_bounds', [[-20,-20], [width,30]])
    entanglement_bounds = spec.get('entanglement_bounds', [[-20,40], [width,90]])
    zones = (Zone('SZ', ZoneType.STORAGE, Rectangle(*(P(*v) for v in storage_bounds))),
             Zone('EZ', ZoneType.ENTANGLEMENT, Rectangle(*(P(*v) for v in entanglement_bounds))))
    traps = {}
    occupied = {site_id(s) for s in spec['initial_mapping']}
    for zone in arch['storage_zones'] + arch['entanglement_zones']:
        for slm in zone['slms']:
            for r in range(slm['r']):
                for c in range(slm['c']):
                    x = slm['location'][0] + c * slm['site_seperation'][0]
                    y = slm['location'][1] + r * slm['site_seperation'][1]
                    key = site_id((slm['id'], r, c))
                    traps[key] = StaticTrap(key, GridCoord(x,y), P(x,y), enabled=key in occupied)
    for i in range(2):
        x, y = width - 10, i * 10
        key = f'BUFFER{i}'
        traps[key] = StaticTrap(key, GridCoord(x,y), P(x,y), enabled=False)
    world = WorldState(bounds, traps, zones, grid_spacing_um=1)
    atoms = {f'Q{q:03d}': Atom(f'Q{q:03d}') for q in range(spec['atom_count'])}
    placement = PlacementState({f'Q{q:03d}': HolderRef(HolderType.STATIC, site_id(s))
                                for q,s in enumerate(spec['initial_mapping'])})
    gates = tuple(PhysicalGate(f'g{i:04d}', 'CZ', tuple(f'Q{q:03d}' for q in pair))
                  for i,pair in enumerate(spec['pairs']))
    aod_spec = arch['aods'][0]
    aod = AODRuntimeState(pose=P(-10,-10), rows=aod_spec['r'], columns=aod_spec['c'], spacing_um=10)
    return SimulationState(world, placement, atoms, aod, DynamicGateDAG(PhysicalCircuit(gates)),
                           hardware=HardwareConfig(backend='row_column_orthogonal'))


def frontend(spec, source, directory, reuse):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / 'input.json'
    path.write_text(canonical_json(spec), encoding='utf-8')
    if not (Path(source) / 'zac/zac.py').is_file():
        raise FileNotFoundError('Run python tools/fetch_zac_sources.py first')
    cmd = [sys.executable, '-m', 'neutral_atom_experiments.zac_frontend', '--source', str(Path(source).resolve()),
           '--input', str(path.resolve()), '--output', str(directory.resolve())]
    if not reuse:
        cmd.append('--no-reuse')
    child_env = dict(os.environ, PYTHONPATH=str(ROOT/'src'), PYTHONHASHSEED='0')
    completed = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8',
                               errors='replace', timeout=120, env=child_env)
    (directory/'process.log').write_text(completed.stdout + completed.stderr, encoding='utf-8')
    if completed.returncode:
        raise RuntimeError(f'Author frontend failed: {completed.stderr[-1800:]}')
    return json.loads((directory/'placement.json').read_text(encoding='utf-8'))


def run_one(spec, placement, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # SA chooses the prepared initial state, never teleports a live environment.
    # All initial-placement variants restore the SAME canonical absolute target.
    actual_spec = dict(spec, initial_mapping=placement['mappings'][0])
    terminal = initial_terminal(make_state(spec))
    env = NeutralAtomEnv(make_state(actual_spec))
    initial = env.snapshot()
    recorder = VisualRecorder(env.state)
    strategy = ZACPlacementStrategy(placement, timeout_s=spec['timeout_s'],
                                    terminal_target=terminal,
                                    bounded_spares=spec.get('bounded_spares', False))
    start = perf_counter()
    error = None
    try:
        strategy.run(env, on_event=lambda s,e: recorder.observe(s))
    except Exception as exc:
        error = dict(type=type(exc).__name__, message=str(exc),
                     code=getattr(getattr(exc, 'violation', None), 'code', None))
    execute_seconds = perf_counter() - start
    replay_start = perf_counter()
    replay = NeutralAtomEnv.restore(initial)
    replay_error = None
    try:
        for plan in strategy.plans:
            replay.submit(plan)
            replay.run()
    except Exception as exc:
        replay_error = dict(type=type(exc).__name__, message=str(exc))
    replay_equal = replay_error is None and replay.snapshot() == env.snapshot()
    replay_seconds = perf_counter() - replay_start
    effects = Counter(g for record in env.state.trace.records
        for g in (json.loads(record).get('effect_gate_ids', [])
                  if json.loads(record).get('effect_completed') else []))
    exactly_once = effects == Counter({g.id:1 for g in env.state.dag.circuit.gates})
    payload = recorder.payload()
    transfers = Counter()
    for op in payload['operations']:
        if op['kind'] in ('aod_load', 'aod_offload'):
            transfers[op['kind']] += len(op.get('captured', []))
    pulses = [op for op in payload['operations'] if op['kind'] == 'entangling_pulse']
    reuse_audit = []
    for stage, qs in enumerate(placement['selected_reuse'][:-1]):
        if stage + 1 >= len(pulses):
            break
        lo, hi = pulses[stage]['end'], pulses[stage+1]['start']
        for q in qs:
            atom = f'Q{q:03d}'
            # Inspect actual accepted transfer decisions throughout BOTH return
            # and preparation, not only positions at stage endpoints.
            touched = [d for d in strategy.decisions if d.get('kind') == 'transfer'
                       and d['start_us'] >= lo-1e-8 and d['end_us'] <= hi+1e-8
                       and atom in d.get('destinations', {})]
            stable = (placement['mappings'][2*stage+1][q] == placement['mappings'][2*stage+2][q]
                      == placement['mappings'][2*stage+3][q])
            reuse_audit.append(dict(stage=stage, atom=atom, start_us=lo, end_us=hi,
                                   holder=site_id(placement['mappings'][2*stage+1][q]),
                                   passed=stable and not touched))
    success = error is None and replay_equal and exactly_once and all(x['passed'] for x in reuse_audit)
    phases = Counter()
    for decision in strategy.decisions:
        phase = decision.get('phase', decision['kind'])
        phases[phase] += decision['end_us'] - decision['start_us']
    result = dict(status='completed' if success else 'failed', error=error,
        reuse_enabled=placement['reuse_enabled'], metrics=env.state.metrics(),
        initial_sha256=sha256(initial.encode()).hexdigest(), effects_once=exactly_once,
        terminal_target_sha256=sha256(canonical_json(primitive(terminal)).encode()).hexdigest(),
        initial_placement=placement.get('initial_placement', dict(method='fixed')),
        replay_equal=replay_equal, replay_error=replay_error, terminal_verified=error is None,
        realize_execute_record_seconds=execute_seconds, independent_replay_seconds=replay_seconds,
        phase_time_us=dict(phases), selected_reuse=placement['selected_reuse'],
        matching_reuse=placement['matching_reuse'], gate_layers=placement['gate_layers'],
        reuse_audit=reuse_audit, atom_transfers=dict(transfers),
        decisions=strategy.decisions, boundaries=strategy.boundaries,
        author_frontend_seconds=placement['frontend_seconds'],
        author_compile_verify_seconds=placement['author_compile_verify_seconds'],
        scope='Author ASAP/reuse/dynamic placement; local ordered transport and timing; explicit initial-state cleanup; CZ-only')
    for name,data in [('result.json',result),('plans.json',primitive(strategy.plans)),
                       ('recording.json',payload),('rejections.json',strategy.rejections)]:
        (directory/name).write_text(canonical_json(data), encoding='utf-8')
    (directory/'initial.json').write_text(initial, encoding='utf-8')
    (directory/'terminal-target.json').write_text(canonical_json(primitive(terminal)), encoding='utf-8')
    (directory/'checkpoint.json').write_text(env.snapshot(), encoding='utf-8')
    env.state.trace.write(directory/'trace.jsonl')
    recorder.write(directory/'physical.html')
    return result, payload


def compare(raw, directory, source=DEFAULT_SOURCE, progress=None):
    spec = normalize_spec(raw)
    if spec['initial_placement'] == 'compare':
        from neutral_atom_experiments.zac_initial import run_suite
        return run_suite(directory, inputs=[spec], source=source, workers=2, progress=progress)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory/'input.json').write_text(canonical_json(spec), encoding='utf-8')
    results = {}
    for reuse, name in ((False, 'no_reuse'), (True, 'reuse')):
        if progress:
            progress(f'{name}: author scheduling / reuse / placement / ZAIR')
        placement = frontend(spec, source, directory/name/'upstream', reuse)
        if progress:
            progress(f'{name}: physical realization / Executor / independent replay')
        result, payload = run_one(spec, placement, directory/name)
        results[name] = result
        # Import kept here so the experiment core has no app dependency.
        from neutral_atom_experiments.zac_reuse_report import write_replay
        write_replay(spec, placement, result, payload, directory/name/'index.html')
    equal = results['reuse']['initial_sha256'] == results['no_reuse']['initial_sha256']
    report = dict(status='completed' if equal and all(r['status']=='completed' for r in results.values()) else 'failed',
                  same_initial_state=equal, spec=spec, results=results)
    (directory/'comparison.json').write_text(canonical_json(report), encoding='utf-8')
    from neutral_atom_experiments.zac_reuse_report import write_comparison
    write_comparison(report, directory/'index.html')
    return report
