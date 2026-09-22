"""Bounded native-only IDS benchmark; no claim of local physical validation.

Run with the main Python (requires psutil); the compiler uses its pinned venv.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import re
import subprocess
import sys
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--qubits', type=int, default=5000)
    parser.add_argument('--family', choices=['graphstate', 'ghz-chain'], default='graphstate')
    parser.add_argument('--timeout', type=float, default=900)
    parser.add_argument('--memory-gib', type=float, default=3)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    # Preserve the exact platform even when search times out before worker output.
    architecture_text = (ROOT / 'third_party/qmap/square_architecture.json').read_text(encoding='utf-8')
    (output / 'architecture.json').write_text(architecture_text, encoding='utf-8')
    if args.family == 'graphstate':
        request = dict(benchmark='graphstate', atom_count=args.qubits, routing='strict')
    else:
        gates = [dict(type='H', qubits=[0])]
        for target in range(1, args.qubits):
            gates.extend([dict(type='H', qubits=[target]),
                          dict(type='CZ', qubits=[target-1, target]),
                          dict(type='H', qubits=[target])])
        request = dict(name='ghz-chain', atom_count=args.qubits, routing='strict', gates=gates)
    (output / 'request.json').write_text(json.dumps(request, indent=2), encoding='utf-8')
    worker = ROOT / 'src/neutral_atom_strategies/qmap_native/worker.py'
    interpreter = ROOT / 'artifacts/qmap-native/venv/Scripts/python.exe'
    summary = dict(status='running', started_utc=datetime.now(timezone.utc).isoformat(),
                   request={k:v for k,v in request.items() if k != 'gates'}, timeout_seconds=args.timeout,
                   memory_limit_gib=args.memory_gib, platform=platform.platform(),
                   architecture_sha256=hashlib.sha256(architecture_text.encode()).hexdigest(),
                   cpu=platform.processor(), logical_cpus=psutil.cpu_count(),
                   physical_validation='not_run',
                   worker_sha256=hashlib.sha256(worker.read_bytes()).hexdigest())
    start = time.perf_counter()
    peak_rss = peak_private = 0
    previous_stage = None
    low_memory_samples = 0
    with (output / 'worker.log').open('w', encoding='utf-8') as log:
        proc = subprocess.Popen([str(interpreter), '-u', str(worker),
                                 str(output / 'request.json'), str(output / 'native.json')],
                                stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
        monitored = psutil.Process(proc.pid)
        print(json.dumps(dict(pid=proc.pid, output=str(output))), flush=True)
        with (output / 'resource-samples.jsonl').open('w', encoding='utf-8') as samples:
            while proc.poll() is None:
                elapsed = time.perf_counter() - start
                try:
                    # Windows venv python.exe may be a redirector: include its worker.
                    memories = [p.memory_info() for p in [monitored] + monitored.children(recursive=True)]
                    rss = sum(m.rss for m in memories)
                    private = sum(getattr(m, 'private', 0) for m in memories)
                    peak_rss = max(peak_rss, sum(max(m.rss, getattr(m, 'peak_wset', 0)) for m in memories))
                    peak_private = max(peak_private, private)
                    available = psutil.virtual_memory().available
                    stage = ('output_evaluation' if (output / 'program.naviz').exists() else
                             'native_compile' if (output / 'input.qasm').exists() else
                             'imports_and_input_preparation')
                    sample = dict(elapsed_seconds=round(elapsed, 3), rss_bytes=rss,
                                  available_bytes=available, stage=stage)
                    samples.write(json.dumps(sample) + '\n')
                    samples.flush()
                    low_memory_samples = low_memory_samples + 1 if available < 750 * 2**20 else 0
                    if stage != previous_stage:
                        print(json.dumps(sample), flush=True)
                        previous_stage = stage
                    reason = ('timeout' if elapsed > args.timeout else
                              'process_memory_limit' if max(rss, private) > args.memory_gib * 2**30 else
                              'system_memory_pressure' if low_memory_samples >= 3 else None)
                    if reason:
                        summary.update(status='failed', failure_reason=reason)
                        for child in monitored.children(recursive=True):
                            child.kill()
                        proc.kill()
                        break
                except psutil.NoSuchProcess:
                    break
                time.sleep(1)
        summary['returncode'] = proc.wait()
    summary.update(process_wall_seconds=time.perf_counter() - start,
                   peak_working_set_bytes=peak_rss, peak_sampled_private_bytes=peak_private)
    if summary['returncode'] == 0 and (output / 'native.json').exists():
        native = json.loads((output / 'native.json').read_text(encoding='utf-8'))
        summary.update(status='compiled', stats=native['stats'],
                       native_compile_seconds=native['stats']['totalTime'] / 1e6,
                       native_call_seconds=native['native_call_seconds'],
                       preparation_seconds=native['preparation_seconds'],
                       author_metrics=native['author_metrics'], versions=native['versions'])
        counts = Counter()
        for line in (output / 'input.qasm').read_text(encoding='utf-8').splitlines():
            match = re.match(r'^([a-z][a-z0-9_]*)\s*(?:\([^;]*?\))?\s+q\[', line)
            if match:
                counts[match[1]] += 1
        summary['input_gate_counts'] = dict(counts)
        summary['input_gate_total'] = sum(counts.values())
        summary['input_sha256'] = native['input_sha256']
        summary['naviz_sha256'] = native['naviz_sha256']
    elif summary['status'] == 'running':
        summary.update(status='failed', failure_reason='worker_failed',
                       error_tail=(output / 'worker.log').read_text(encoding='utf-8')[-4000:])
    (output / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2), flush=True)
    return 0 if summary['status'] == 'compiled' else 1


if __name__ == '__main__':
    raise SystemExit(main())
