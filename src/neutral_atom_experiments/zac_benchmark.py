"""Reproducible larger CZ workloads and isolated, resumable physical comparisons."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from time import perf_counter
import json
import os
import platform
import random
import subprocess
import sys

from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_experiments.zac_reuse import ROOT, DEFAULT_SOURCE, normalize_spec, frontend, run_one
from neutral_atom_experiments.zac_reuse_report import write_replay, write_comparison


FAMILIES = ('repeat', 'butterfly', 'random')


def workload(n, depth, family, seed=20260921, timeout_s=600, bounded_spares=False):
    """All qubits participate once per layer; retain repeated physical CZ gates."""
    if type(n) is not int or n < 2 or n > 128 or n & (n - 1):
        raise ValueError('Benchmark sizes must be powers of two from 2 through 128')
    if type(depth) is not int or depth < 1 or n * depth // 2 > 4096:
        raise ValueError('Depth must be positive and yield at most 4096 CZ gates')
    if family not in FAMILIES:
        raise ValueError(f'Unknown family: {family}')
    rng = random.Random(seed)
    pairs = []
    for layer in range(depth):
        if family == 'random':
            order = list(range(n))
            rng.shuffle(order)
            pairs.extend([order[i:i + 2] for i in range(0, n, 2)])
        else:
            mask = 1 if family == 'repeat' else 1 << (layer % (n.bit_length() - 1))
            pairs.extend([[q, q ^ mask] for q in range(n) if q < (q ^ mask)])
    key = f'{family}-n{n}-d{depth}' + (f'-s{seed}' if family == 'random' else '')
    label = {'repeat': '重复配对', 'butterfly': '蝶形换伙伴', 'random': '随机配对'}[family]
    spec = normalize_spec(dict(name=f'{n} 原子 / {depth} 层 · {label}', atom_count=n,
                               pairs=pairs, timeout_s=timeout_s, bounded_spares=bounded_spares))
    return dict(id=key, family=family, seed=seed if family == 'random' else None,
                depth=depth, spec=spec)


def fingerprint(source):
    files = sorted((ROOT / 'src/neutral_atom_env').rglob('*.py'))
    files += sorted((ROOT / 'src/neutral_atom_strategies').rglob('*.py'))
    files += [Path(__file__), ROOT / 'src/neutral_atom_experiments/zac_reuse.py',
              ROOT / 'src/neutral_atom_experiments/zac_frontend.py']
    local = {str(p.relative_to(ROOT)): sha256(p.read_bytes()).hexdigest() for p in files}
    upstream = {str(p.relative_to(source)): sha256(p.read_bytes()).hexdigest()
                for p in sorted(Path(source).rglob('*.py'))}
    return dict(local=local, upstream=upstream)


def write_json(path, data):
    """Atomic replacement keeps the live dashboard readable during a run."""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(canonical_json(data), encoding='utf-8')
    tmp.replace(path)


def worker(case_path, mode, source):
    directory = Path(case_path)
    spec = json.loads((directory / 'input.json').read_text(encoding='utf-8'))
    output = directory / mode
    output.mkdir(parents=True, exist_ok=True)
    started = perf_counter()
    phase = 'author_frontend'
    try:
        placement = frontend(spec, source, output / 'upstream', mode == 'reuse')
        phase = 'physical_execution_and_replay'
        result, payload = run_one(spec, placement, output)
        phase = 'render'
        write_replay(spec, placement, result, payload, output / 'index.html')
        record = dict(status=result['status'], result=result, phase='finished', replay_url=f'{mode}/index.html')
    except Exception as exc:
        record = dict(status='failed', phase=phase,
                      error=dict(type=type(exc).__name__, message=str(exc)))
    record['process_elapsed_seconds'] = perf_counter() - started
    write_json(output / 'worker.json', record)
    return record


def run_suite(output, *, sizes=(16, 32, 64, 128), depth=8, families=FAMILIES,
              seeds=(20260921,), timeout_s=600, hard_timeout_s=1200, workers=2,
              source=DEFAULT_SOURCE, resume=False, bounded_spares=False):
    if not 1 <= workers <= 4:
        raise ValueError('Use 1–4 independent worker processes')
    if hard_timeout_s <= timeout_s + 120:
        raise ValueError('Hard timeout must leave time for author subprocess and independent replay')
    output = Path(output).resolve()
    source = Path(source).resolve()
    cases = [workload(n, depth, family, seed, timeout_s, bounded_spares)
             for n in sizes for family in families
             for seed in (seeds if family == 'random' else (seeds[0],))]
    if not cases or len({c['id'] for c in cases}) != len(cases):
        raise ValueError('Specify a nonempty suite without duplicate cases')
    contract = dict(cases=cases, source=str(source), fingerprints=fingerprint(source),
                    timeout_s=timeout_s, hard_timeout_s=hard_timeout_s, workers=workers,
                    terminal='fixed initial holders, masks and AOD axes', recording=True,
                    seed_policy='Python random.Random per case; PYTHONHASHSEED=0 in workers')
    contract_hash = sha256(canonical_json(contract).encode()).hexdigest()
    manifest_path = output / 'benchmark.json'
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding='utf-8'))
        if not resume or previous['contract_sha256'] != contract_hash:
            raise ValueError('Output exists; use a new output or --resume with the identical contract/code')
    else:
        previous = {}
    output.mkdir(parents=True, exist_ok=True)
    manifest = dict(schema='zac-benchmark/1', created_utc=previous.get('created_utc', datetime.now(timezone.utc).isoformat()),
                    contract=contract, contract_sha256=contract_hash, status='running',
                    host=dict(python=sys.version, platform=platform.platform(), cpu_count=os.cpu_count()),
                    cases=[])
    for case in cases:
        directory = output / case['id']
        directory.mkdir(parents=True, exist_ok=True)
        write_json(directory / 'input.json', case['spec'])
        manifest['cases'].append(dict(**case, variants={m:dict(status='queued') for m in ('no_reuse', 'reuse')}))

    from neutral_atom_experiments.zac_benchmark_report import write_dashboard

    def save():
        write_json(manifest_path, manifest)
        write_dashboard(manifest, output)

    def run_variant(case, mode):
        directory = output / case['id'] / mode
        directory.mkdir(parents=True, exist_ok=True)
        record_path = directory / 'worker.json'
        # Finished failures are evidence too; resume never silently retries them.
        if resume and record_path.exists():
            return json.loads(record_path.read_text(encoding='utf-8'))
        started = perf_counter()
        cmd = [sys.executable, '-m', 'neutral_atom_experiments.zac_benchmark',
               str(directory.parent), mode, str(source)]
        child_env = dict(os.environ, PYTHONPATH=str(ROOT / 'src'), PYTHONHASHSEED='0',
                         OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1')
        with (directory / 'worker.log').open('w', encoding='utf-8') as log:
            try:
                process = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT,
                                         env=child_env, timeout=hard_timeout_s)
                if record_path.exists():
                    return json.loads(record_path.read_text(encoding='utf-8'))
                record = dict(status='failed', phase='worker_process',
                              error=dict(type='WorkerExit', message=f'Exit code {process.returncode}; see worker.log'))
            except subprocess.TimeoutExpired:
                record = dict(status='timeout', phase='worker_process',
                              error=dict(type='TimeoutExpired', message=f'Hard process budget {hard_timeout_s}s; incomplete, not a timing result'))
        record['process_elapsed_seconds'] = perf_counter() - started
        write_json(record_path, record)
        return record

    save()
    start = perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_variant, case, mode):(case, mode)
                   for case in manifest['cases'] for mode in ('no_reuse', 'reuse')}
        for future in as_completed(futures):
            case, mode = futures[future]
            record = future.result()
            case['variants'][mode] = record
            elapsed = record.get('process_elapsed_seconds')
            elapsed_label = 'elapsed unavailable' if elapsed is None else f'{elapsed:.1f}s'
            print(f"{case['id']} / {mode}: {record['status']} ({elapsed_label})", flush=True)
            a, b = (case['variants'][m] for m in ('no_reuse', 'reuse'))
            if 'result' in a and 'result' in b:
                same = a['result']['initial_sha256'] == b['result']['initial_sha256']
                report = dict(status='completed' if same and all(v['status'] == 'completed' for v in (a, b)) else 'failed',
                              same_initial_state=same, spec=case['spec'],
                              results={m:case['variants'][m]['result'] for m in ('no_reuse', 'reuse')})
                write_json(output / case['id'] / 'comparison.json', report)
                write_comparison(report, output / case['id'] / 'index.html')
            save()
    manifest.update(status='finished', invocation_elapsed_seconds=perf_counter() - start,
                    finished_utc=datetime.now(timezone.utc).isoformat())
    save()
    return manifest


if __name__ == '__main__':
    worker(Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3]))
