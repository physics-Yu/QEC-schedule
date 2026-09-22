"""Bounded Figure-2-style native Enola / QMAP scaling on identical public graphs.

Runs methods sequentially, preserves failures, and never invokes local Env.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import traceback

import psutil

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from score_qmap_scaling import score


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_case(case, method, folder, source, timeout, memory_gib):
    folder.mkdir(parents=True, exist_ok=False)
    case_path = folder.parent / 'case.json'
    if method == 'qmap':
        request = dict(name=case['id'], atom_count=case['n'], routing='strict',
                       gates=[dict(type='CZ', qubits=pair) for pair in case['gates']])
        dump(folder / 'request.json', request)
        shutil.copyfile(ROOT / 'third_party/qmap/square_architecture.json', folder / 'architecture.json')
        cmd = [str(ROOT / 'artifacts/qmap-native/venv/Scripts/python.exe'), '-u',
               str(ROOT / 'src/neutral_atom_strategies/qmap_native/worker.py'),
               str(folder / 'request.json'), str(folder / 'native.json')]
    else:
        cmd = [str(source / '.venv-research/Scripts/python.exe'), '-u',
               str(ROOT / 'tools/enola_scaling_worker.py'), str(case_path), str(folder), '--source', str(source)]
    result = dict(status='running', n=case['n'], graph_id=case['graph_id'], method=method,
                  id=case['id'], timeout_seconds=timeout, memory_limit_gib=memory_gib,
                  input_sha256=sha(case_path), started_utc=datetime.now(timezone.utc).isoformat(),
                  validation_scope='native instruction accounting; no local Env or continuous path validation')
    dump(folder / 'progress.json', result)
    print(json.dumps(dict(event='start', **result)), flush=True)
    start = time.perf_counter()
    peak = peak_private = 0
    reason = None
    with (folder / 'worker.log').open('w', encoding='utf-8') as log, (folder / 'resources.jsonl').open('w') as samples:
        proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
        monitor = psutil.Process(proc.pid)
        low = 0
        while proc.poll() is None:
            elapsed = time.perf_counter() - start
            memories = []
            try:
                for child in [monitor] + monitor.children(recursive=True):
                    try:
                        memories.append(child.memory_info())
                    except psutil.NoSuchProcess:
                        pass
            except psutil.NoSuchProcess:
                break
            rss = sum(m.rss for m in memories)
            private = sum(getattr(m, 'private', m.rss) for m in memories)
            peak = max(peak, sum(max(m.rss, getattr(m, 'peak_wset', 0)) for m in memories))
            peak_private = max(peak_private, private)
            available = psutil.virtual_memory().available
            low = low+1 if available < 600*2**20 else 0
            samples.write(json.dumps(dict(seconds=elapsed, rss_bytes=rss, private_bytes=private, available_bytes=available))+'\n')
            samples.flush()
            reason = ('timeout' if elapsed > timeout else 'memory_limit' if max(rss, private) > memory_gib*2**30
                      else 'system_memory_pressure' if low >= 3 else None)
            if reason:
                for child in monitor.children(recursive=True):
                    try:
                        child.kill()
                    except psutil.NoSuchProcess:
                        pass
                proc.kill()
                break
            time.sleep(.5)
        code = proc.wait()
    worker_wall = time.perf_counter()-start
    if reason:
        result.update(status=reason, failure_reason=reason)
    elif code:
        # Preserve a worker's structured exception before writing the wrapper
        # result. A short console summary must not replace its traceback.
        if (folder / 'result.json').exists():
            shutil.copyfile(folder / 'result.json', folder / 'worker-result.json')
            try:
                result.update(json.loads((folder / 'worker-result.json').read_text(encoding='utf-8')))
            except json.JSONDecodeError:
                pass  # The original bytes remain available for diagnostics.
        result.update(status='failed', failure_reason='worker_failed',
                      error_tail=(folder / 'worker.log').read_text(encoding='utf-8')[-3000:])
    else:
        try:
            if method == 'qmap':
                native = json.loads((folder / 'native.json').read_text())
                result.update(status='completed', native_compile_seconds=native['stats']['totalTime']/1e6,
                              native_call_seconds=native['native_call_seconds'], stats=native['stats'],
                              versions=native['versions'], **score(folder))
            else:
                result.update(json.loads((folder / 'result.json').read_text(encoding='utf-8')))
                if 'native_compile_seconds' not in result and 'compile_seconds' in result:
                    result['native_compile_seconds'] = result['compile_seconds']
        except Exception as exc:
            result.update(status='failed', failure_reason='post_compile_audit_failed', error=str(exc), traceback=traceback.format_exc())
    result.update(process_wall_seconds=worker_wall, total_wall_seconds=time.perf_counter()-start,
                  peak_working_set_bytes=peak, peak_sampled_private_bytes=peak_private, returncode=code)
    dump(folder / 'result.json', result)
    print(json.dumps(dict(event='end', case=case['id'], method=method, status=result['status'],
                         native_seconds=result.get('native_compile_seconds'), wall_seconds=worker_wall)), flush=True)
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, default=Path('C:/Users/86136/Documents/ChatGPT/项目/research/Enola'))
    p.add_argument('--output', type=Path, default=ROOT/'artifacts/enola-scaling-20260922')
    p.add_argument('--sizes', nargs='+', type=int, default=[30,100,300,1000,2000,5000])
    p.add_argument('--graph-ids', nargs='+', type=int, default=[0])
    p.add_argument('--methods', nargs='+', choices=['enola','qmap'], default=['enola','qmap'])
    p.add_argument('--timeout', type=float, default=300)
    p.add_argument('--memory-gib', type=float, default=3)
    a = p.parse_args()
    a.output = a.output.resolve()
    a.source = a.source.resolve()
    a.output.mkdir(parents=True, exist_ok=True)
    graphs_path = a.source/'graphs.json'
    graphs = json.loads(graphs_path.read_text())
    manifest_path = a.output/'manifest.json'
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        if manifest['graphs_sha256'] != sha(graphs_path):
            raise ValueError('Public graphs changed')
    else:
        manifest = dict(schema='native-figure2-scaling/v1', created_utc=datetime.now(timezone.utc).isoformat(),
                        graphs_sha256=sha(graphs_path), source=str(a.source), source_commit=subprocess.check_output(
                            ['git','-c','safe.directory='+a.source.as_posix(),'-C',str(a.source),'rev-parse','HEAD'],text=True).strip(),
                        machine=platform.platform(), cpu=platform.processor(), logical_cpus=psutil.cpu_count(),
                        memory_bytes=psutil.virtual_memory().total, runs=[],
                        scope='Native software stacks on their own hardware/time models. Not same-hardware algorithm ranking; no local physical replay.',
                        model_parameters=dict(f2=.995,fexc=.9975,ftrans=.999,t2_us=1500000),
                        enola_settings=dict(dynamic_sa=True,window_is=1000,reverse_to_initial=False,full_code=False),
                        qmap_settings=dict(version='3.5.0',routing='strict',trials=4,queue_capacity=100,
                            use_window=True,architecture_sha256=sha(ROOT/'third_party/qmap/square_architecture.json')))
        sources = a.output/'sources'
        sources.mkdir(exist_ok=True)
        for src,name in [(graphs_path,'graphs.json'),(ROOT/'third_party/qmap/square_architecture.json','qmap-architecture.json')]:
            shutil.copyfile(src,sources/name)
        manifest['source_sha256'] = {}
        files = [ROOT/'examples/benchmark_enola_scaling.py',ROOT/'tools/score_qmap_scaling.py',
                 ROOT/'tools/enola_scaling_worker.py',ROOT/'tools/audit_qmap_hcz.py',
                 ROOT/'src/neutral_atom_strategies/qmap_native/worker.py',
                 ROOT/'src/neutral_atom_strategies/qmap_native/naviz.py',ROOT/'third_party/qmap/eval_ids_relaxed_routing.py']
        for f in files:
            if f.exists():
                rel = f.relative_to(ROOT)
                target = sources/'qec'/rel
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(f,target)
                manifest['source_sha256'][str(rel)] = sha(f)
        for f in list((a.source/'enola').rglob('*.py'))+[a.source/'simulator.py',a.source/'LICENSE']:
            if f.exists():
                target = sources/'Enola'/f.relative_to(a.source)
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(f,target)
                manifest['source_sha256']['Enola/'+f.relative_to(a.source).as_posix()] = sha(f)
    for name, expected in manifest.get('source_sha256', {}).items():
        path = a.source / name[6:] if name.startswith('Enola/') else ROOT / name
        if sha(path) != expected:
            raise ValueError(f'Execution source changed since first run: {path}; use a new output directory')
    manifest['runs'].append(dict(sizes=a.sizes,graph_ids=a.graph_ids,methods=a.methods,timeout=a.timeout,memory_gib=a.memory_gib))
    dump(manifest_path,manifest)
    for n in a.sizes:
        for gid in a.graph_ids:
            gates = graphs[str(n)][gid]
            degree = Counter(q for pair in gates for q in pair)
            if len(gates)!=3*n//2 or degree!=Counter({q:3 for q in range(n)}) or len({tuple(sorted(p)) for p in gates})!=len(gates):
                raise ValueError('Not the expected simple 3-regular graph')
            case = dict(id=f'n{n}_g{gid}',n=n,graph_id=gid,gates=gates)
            case_dir=a.output/case['id']
            case_dir.mkdir(exist_ok=True)
            dump(case_dir/'case.json',case)
            for method in a.methods:
                folder=case_dir/method
                if folder.exists():
                    print(json.dumps(dict(event='preserved_existing',case=case['id'],method=method)),flush=True)
                    continue
                run_case(case,method,folder,a.source,a.timeout,a.memory_gib)
    manifest['source_unchanged_at_end'] = all(sha(a.source/name[6:] if name.startswith('Enola/') else ROOT/name)==expected
        for name,expected in manifest.get('source_sha256',{}).items())
    manifest['finished_utc']=datetime.now(timezone.utc).isoformat()
    dump(manifest_path,manifest)


if __name__ == '__main__':
    main()
