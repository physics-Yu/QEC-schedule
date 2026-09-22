"""Original ZAC SA initial placement crossed with reuse, on a common terminal."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from time import perf_counter
import json
import os
import subprocess
import sys

from neutral_atom_env.replay.serializer import canonical_json
from neutral_atom_experiments.zac_benchmark import fingerprint, workload, write_json
from neutral_atom_experiments.zac_reuse import ROOT, DEFAULT_SOURCE, normalize_spec, frontend, run_one
from neutral_atom_experiments.zac_reuse_report import write_replay

MODES = ('fixed_no_reuse', 'fixed_reuse', 'sa_no_reuse', 'sa_reuse')


def worker(directory, mode, source):
    directory = Path(directory)
    output = directory / mode
    output.mkdir(parents=True, exist_ok=True)
    spec = json.loads((directory/'input.json').read_text(encoding='utf-8'))
    spec['initial_placement'] = 'sa' if mode.startswith('sa_') else 'fixed'
    start = perf_counter()
    phase = 'author_frontend'
    try:
        placement = frontend(spec, source, output/'upstream', mode in ('fixed_reuse', 'sa_reuse'))
        phase = 'physical_execution_and_replay'
        result, payload = run_one(spec, placement, output)
        phase = 'render'
        write_replay(spec, placement, result, payload, output/'index.html')
        record = dict(status=result['status'], result=result, phase='finished', replay_url=f'{mode}/index.html')
    except Exception as exc:
        record = dict(status='failed', phase=phase, error=dict(type=type(exc).__name__, message=str(exc)))
    record['process_elapsed_seconds'] = perf_counter()-start
    write_json(output/'worker.json', record)
    return record


def comparisons(case):
    """Only full, validated, matched runs may yield a physical-time percentage."""
    variants = case['variants']
    pairs = [('fixed_reuse_effect', 'fixed_no_reuse', 'fixed_reuse'),
             ('sa_reuse_effect', 'sa_no_reuse', 'sa_reuse'),
             ('sa_effect_without_reuse', 'fixed_no_reuse', 'sa_no_reuse'),
             ('sa_effect_with_reuse', 'fixed_reuse', 'sa_reuse'),
             ('combined_effect', 'fixed_no_reuse', 'sa_reuse')]
    values = {}
    for name, baseline, candidate in pairs:
        runs = [variants[m] for m in (baseline,candidate)]
        results = [v.get('result', {}) for v in runs]
        valid = all(v['status']=='completed' and all(r.get(k) for k in
            ('replay_equal','effects_once','terminal_verified')) for v,r in zip(runs,results))
        valid = valid and bool(results[0].get('terminal_target_sha256')) and results[0].get('terminal_target_sha256') == results[1].get('terminal_target_sha256')
        if name in ('fixed_reuse_effect','sa_reuse_effect'):
            valid = valid and results[0].get('initial_sha256') == results[1].get('initial_sha256')
        values[name] = dict(baseline=baseline,candidate=candidate,comparable=bool(valid),
            change_percent=100*(results[1]['metrics']['episode_wall_time_us']/results[0]['metrics']['episode_wall_time_us']-1)
                if valid else None)
    return values


def run_suite(output, *, inputs=None, sizes=(16,32), families=('butterfly','random'), depth=8,
              seed=20260921, timeout_s=600, hard_timeout_s=1500, workers=2,
              source=DEFAULT_SOURCE, resume=False, progress=None):
    from neutral_atom_experiments.zac_initial_report import write_report
    if type(workers) is not int or not 1 <= workers <= 4:
        raise ValueError('workers must be 1–4')
    if inputs is None:
        cases = [workload(n,depth,family,seed,timeout_s,True) for n in sizes for family in families]
    else:
        cases = [dict(id=f'custom-{i+1}',family='custom',seed=None,depth=None,spec=normalize_spec(raw))
                 for i,raw in enumerate(inputs)]
    if not cases or len({c['id'] for c in cases}) != len(cases):
        raise ValueError('Specify distinct, nonempty cases')
    for case in cases:
        case['spec']['initial_placement'] = 'compare'
    hard_timeout_s = max(hard_timeout_s, 2*max(c['spec']['timeout_s'] for c in cases)+180)
    output, source = Path(output).resolve(), Path(source).resolve()
    contract = dict(cases=cases, modes=MODES, source=str(source), fingerprints=fingerprint(source),
        workers=workers, hard_timeout_s=hard_timeout_s, author_frontend_timeout_s=120,
        initial='Author unmodified SAPlacer with seed=0 and default parameters; prepared offline',
        terminal='Same canonical row-major holders, SLM masks, AOD axes and masks in all four arms',
        preparation='Initial atom loading/rearrangement into the chosen layout is outside physical episode time')
    for name in ('zac_initial.py','zac_initial_report.py'):
        p=Path(__file__).with_name(name)
        contract['fingerprints']['local'][str(p.relative_to(ROOT))]=sha256(p.read_bytes()).hexdigest()
    digest=sha256(canonical_json(contract).encode()).hexdigest()
    manifest_path=output/'benchmark.json'
    previous={}
    if manifest_path.exists():
        previous=json.loads(manifest_path.read_text(encoding='utf-8'))
        if not resume or previous['contract_sha256'] != digest:
            raise ValueError('Output exists; use a new directory or identical --resume')
    output.mkdir(parents=True,exist_ok=True)
    manifest=dict(schema='zac-initial-benchmark/1',status='running',contract=contract,contract_sha256=digest,
        created_utc=previous.get('created_utc',datetime.now(timezone.utc).isoformat()),cases=[])
    for c in cases:
        (output/c['id']).mkdir(exist_ok=True)
        write_json(output/c['id']/'input.json',c['spec'])
        manifest['cases'].append(dict(**c,variants={m:dict(status='queued') for m in MODES}))

    def save():
        for c in manifest['cases']:
            c['comparisons']=comparisons(c)
        write_json(manifest_path,manifest)
        write_report(manifest,output)

    def launch(case,mode):
        directory=output/case['id']/mode
        directory.mkdir(exist_ok=True)
        record_path=directory/'worker.json'
        if resume and record_path.exists():
            return json.loads(record_path.read_text(encoding='utf-8'))
        env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),PYTHONHASHSEED='0',OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1')
        start=perf_counter()
        with (directory/'worker.log').open('w',encoding='utf-8') as log:
            process=subprocess.Popen([sys.executable,'-m','neutral_atom_experiments.zac_initial',
                str(directory.parent),mode,str(source)],env=env,stdout=log,stderr=subprocess.STDOUT)
            try:
                code=process.wait(timeout=hard_timeout_s)
                if record_path.exists():
                    return json.loads(record_path.read_text(encoding='utf-8'))
                record=dict(status='failed',phase='worker_process',error=dict(type='WorkerExit',message=f'Exit {code}; see worker.log'))
            except subprocess.TimeoutExpired:
                import psutil
                try:
                    parent=psutil.Process(process.pid)
                    for child in parent.children(recursive=True):
                        try: child.kill()
                        except psutil.NoSuchProcess: pass
                    parent.kill()
                except psutil.NoSuchProcess: pass
                process.wait()
                record=dict(status='timeout',phase='worker_process',error=dict(type='TimeoutExpired',message=f'Hard budget {hard_timeout_s}s'))
        record['process_elapsed_seconds']=perf_counter()-start
        write_json(record_path,record)
        return record

    save()
    start=perf_counter()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(launch,c,m):(c,m) for c in manifest['cases'] for m in MODES}
        for future in as_completed(futures):
            case,mode=futures[future]
            record=future.result()
            case['variants'][mode]=record
            message=f"{case['id']} / {mode}: {record['status']} ({record['process_elapsed_seconds']:.1f}s)"
            print(message,flush=True)
            if progress: progress(message)
            save()
    manifest.update(status='finished',invocation_elapsed_seconds=perf_counter()-start,
        finished_utc=datetime.now(timezone.utc).isoformat())
    save()
    return manifest


if __name__=='__main__':
    worker(Path(sys.argv[1]),sys.argv[2],Path(sys.argv[3]))
