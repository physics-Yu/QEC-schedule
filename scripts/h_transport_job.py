"""Frozen, bounded H transport correction and relevant regression evidence."""
from pathlib import Path
import argparse
import json
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'scripts')]
from component_gallery_job import compile_one, save
from na_pipeline.validation import validate_physical_dag_source


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    args = ap.parse_args(); out = ROOT/args.out; out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter(); checks = []
    suites = [('qec','test_physical_dag.py'), ('backend','test*.py'), ('device','test*.py'),
              ('runtime','test*.py'), ('validation','test_validation.py')]
    for folder, pattern in suites:
        result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests/'+folder, '-p', pattern, '-v'],
                                cwd=ROOT, text=True, capture_output=True)
        (out/(folder+'-tests.log')).write_text(result.stdout+result.stderr, encoding='utf-8')
        checks.append({'suite':folder, 'pattern':pattern, 'exit_code':result.returncode})
        print(json.dumps(checks[-1]), flush=True)
    components = []
    for name in ('H','CZ'):
        result = compile_one(name, out, 120)
        components.append(result)
        if result['status']=='passed':
            dag = json.loads((out/name/'physical-dag.json').read_bytes())
            report = validate_physical_dag_source(dag)
            save(out/name/'source-semantics.json', report)
            if not report['passed']: raise ValueError(report)
    passed = all(c['exit_code']==0 for c in checks) and all(c['status']=='passed' for c in components)
    save(out/'status.json', {'status':'passed' if passed else 'incomplete', 'checks':checks,
         'components':components, 'wall_seconds':time.perf_counter()-started,
         'scope':'H transport and inherited CZ-H macros; fake events; no quantum-state or hardware execution; no full Shor restart',
         'user_visual_acceptance':'pending'})
    if not passed: raise SystemExit(1)


if __name__ == '__main__': main()
