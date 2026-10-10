"""Read-only diagnosis of the original failed window; no certified-prefix reuse."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import hashlib, json, sqlite3, sys, unittest

from basic_shor_audit import read, checked_ref
from na_pipeline.runtime.pipeline import save_artifact
from na_pipeline.validation.dag_core import DAGAudit
from na_pipeline.validation.dag_session import inspect_window_binding
from na_pipeline.validation.stream_session import StreamingSessionValidator


def check(run, out):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tests/validation'))
    suite = unittest.defaultTestLoader.loadTestsFromNames([
        'test_window_duration.WindowDurationTests', 'test_validation.GeometryFixtureTests'])
    with (out/'duration-regressions.log').open('w', encoding='utf-8') as stream:
        tests = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    if not tests.wasSuccessful() or tests.skipped:
        raise ValueError('DURATION_REPAIR_REGRESSIONS_FAILED')
    base = run/'execute'; paths = sorted((base/'window-index').glob('*.json'))
    entry = read(paths[1047]); window_path = checked_ref(entry['window'], base/'windows')
    window = read(window_path); atom = window['atom_program']
    body = read(checked_ref(entry['history'], base/'history'))
    prior = read(checked_ref(read(paths[1046])['history'], base/'history'))
    device = read(run/'world.json.gz')['device']
    db_path = run/'validation-execute-c87b4a2a892d/index.sqlite3'
    # This old index only supplies independent historical witnesses for the
    # bounded diagnosis. Full qualification starts at zero under the new hash.
    db = sqlite3.connect(db_path.as_uri()+'?mode=ro', uri=True)
    try:
        reads = {r for a in atom['actions'] for r in a['payload'].get('reads', [])}
        results = {r:json.loads(db.execute('SELECT body FROM results WHERE id=?',(r,)).fetchone()[0]) for r in reads}
        dependencies = {}
        for dep in {d for a in atom['actions'] for d in a['depends_on']}:
            end, status = db.execute('SELECT end,status FROM actions WHERE id=?',(dep,)).fetchone()
            dependencies[dep] = {'id':dep, 't_end_us':end, 'status':status}
    finally:
        db.close()
    witness = SimpleNamespace(device=device, world=prior['final_state'], illumination=prior['illumination_counts'], sequence=1047)
    audit = DAGAudit('original_window_timing_geometry_trace_diagnostic', {}, fixture=False)
    inspect_window_binding(audit, window['physical_plan'], atom,
                           atom['session_binding']['execution_context'], results, body['run_id'])
    StreamingSessionValidator._physical(witness, audit, body, window, dependencies, results)
    if audit.failures or audit.unverified:
        raise ValueError({'original_window_diagnostic':audit.report()})
    changed = deepcopy(window); changed['atom_program']['stats']['duration_us'] = 1.
    negative = DAGAudit('duration_mutation', {}, fixture=True)
    StreamingSessionValidator._physical(witness, negative, body, changed, dependencies, results)
    if 'PLAN_STATS' not in {f['code'] for f in negative.failures}:
        raise ValueError('DURATION_TAMPER_NOT_REJECTED')
    report = {'scope':'original_window_timing_geometry_trace_diagnostic', 'passed':True,
              'full_program_passed':False, 'regressions_passed':tests.testsRun,
              'window':1047, 'window_byte_sha256':hashlib.sha256(window_path.read_bytes()).hexdigest(),
              'metrics':audit.metrics, 'rejected_mutation':'duration_us=1',
              'external_result_ready_us':{r:v['ready_us'] for r,v in results.items()},
              'feedback_latency_us':device['timings_us']['feedback_latency'],
              'physical_execution_repeated':False, 'original_inputs_modified':False,
              'new_checker_full_audit_starts_from_zero':True}
    save_artifact(out/'duration-repair.json', report)
    print(json.dumps({'duration_repair_diagnostic':'passed','tests':tests.testsRun}), flush=True)
