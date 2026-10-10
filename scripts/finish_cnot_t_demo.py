"""One-shot continuation of the active job: audit then export, never reexecute."""
from pathlib import Path
import json
import subprocess
import sys
import time
import hashlib
import argparse

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'src')]
from na_pipeline.runtime.pipeline import save_artifact

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--execution-job',type=Path,required=True)
    args=parser.parse_args()
    base=ROOT/'artifacts/qualification/cnot-t-bottom-20261009'
    run=base/'run-v1'
    out=ROOT/'artifacts/deliveries/cnot-t-bottom-20261009/viewer'
    status=base/'delivery-status.json'
    end=time.monotonic()+21600
    save_artifact(status,dict(status='waiting_for_existing_execution',job=str(args.execution_job)))
    while time.monotonic()<end:
        try:
            job=json.loads((args.execution_job/'status.json').read_bytes())
        except (PermissionError, FileNotFoundError):
            # Windows antivirus/atomic replacement may briefly lock the file.
            time.sleep(.2)
            continue
        if job['status'] in ('starting','running','dispatched_not_completed'):
            time.sleep(5);continue
        if job['status']!='completed':
            save_artifact(status,dict(status='stopped_execution_not_complete',job=job));return 2
        break
    else:
        save_artifact(status,dict(status='postprocessing_wait_budget_exhausted'));return 2
    try:
        save_artifact(status,dict(status='independent_audit_running',run=str(run)))
        from audit_cnot_t_demo import audit_run
        report=audit_run(run)
        if not report['passed']:
            save_artifact(status,dict(status='stopped_audit_failed',report=str(run/'acceptance.json'),failures=report['failures'][:8]));return 2
        save_artifact(status,dict(status='exporting_checked_actions'))
        from export_cnot_t_demo import export
        export(run,out)
        subprocess.run(['node',str(ROOT/'scripts/check_basic_shor_viewer.js'),str(out)],cwd=ROOT,check=True)
        hashes={p.relative_to(out).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file()}
        save_artifact(out.parent/'file-hashes.json',hashes)
        save_artifact(status,dict(status='compiled_demo_and_viewer_checks_passed',viewer=str(out/'animation-library.html'),
                                 browser_render_review='pending',user_visual_acceptance='pending',hardware_executed=False))
        return 0
    except BaseException as e:
        save_artifact(status,dict(status='stopped_postprocessing_error',error=repr(e)));raise

if __name__=='__main__':raise SystemExit(main())
