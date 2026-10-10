"""Record the frozen SE server result without compiling or changing its actions."""
from pathlib import Path
import difflib
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts/demos/se-parallel-server-20261008'
JOB = ROOT / 'scripts/outputs/T704/server/20261008T020748291058Z-t044-se-five-pulse-reset-aod-v1'
NOTE = ROOT / 'knowledge/roles/R0'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    # Extended paths support the content-addressed leaf library on Windows.
    import os
    path = Path('\\\\?\\' + str(path.resolve())) if os.name == 'nt' else path
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    inventory = read(JOB / 'result/T704/source-inventory.json')
    sources = {p: h for p, h in inventory.items() if p.startswith(('src/', 'tests/'))}
    mismatch = [p for p, h in sources.items() if sha(ROOT / p) != h]
    assert not mismatch, mismatch
    original = read(JOB / 'result/export-manifest.json')['files']
    protected = {v['source_relative']: v['sha256'] for v in original.values()
                 if v['source_relative'].startswith('artifacts/demos/se-parallel-server-20261008/')}
    assert all(sha(ROOT / p) == h for p, h in protected.items())
    worker = read(JOB / 'result/T704/worker-receipt.json')
    assert worker['returncode'] == 0 and worker['source_snapshot_stable'] and worker['input_snapshot_verified']
    rows = []
    for folder in sorted(OUT.iterdir()):
        if not (folder / 'summary.json').exists():
            continue
        summary = read(folder / 'summary.json')
        validation = read(folder / 'validation.json')
        assert summary['status'] == 'passed' and validation['passed']
        assert not validation['failures'] and not validation['unverified']
        program = read(folder / 'atom-program.json')
        actions = program['actions']
        pulses = [a for a in actions if a['kind'] == 'gate' and a['payload'].get('name') == 'CZ']
        transfers = [a for a in actions if a['kind'] in ('pickup', 'drop')]
        assert all(a['t_end_us'] - a['t_start_us'] == 100 for a in transfers)
        resets = [a for a in actions if a['kind'] == 'reset' and
                  set(a['payload'].get('carrier_at_reset', {}).values()) == {'AOD'}]
        rows.append({'id': folder.name, 'duration_us': summary['duration_us'],
                     'actions': len(actions), 'CZ_pulses': len(pulses),
                     'pairs_per_pulse': [len(a['payload']['physical_op_ids']) for a in pulses],
                     'transfer_batches': len(transfers), 'transfer_duration_us': 100,
                     'AOD_reset_actions': len(resets),
                     'AOD_reset_intervals_us': sorted({(a['t_start_us'], a['t_end_us']) for a in resets}),
                     'source_dag_sha256': sha(folder / 'physical-dag.json'),
                     'atom_program_sha256': sha(folder / 'atom-program.json'),
                     'event_trace_sha256': sha(folder / 'event-trace.json')})
    se = next(r for r in rows if r['id'] == 'SE')
    pair = next(r for r in rows if r['id'] == 'SE_PAIR')
    assert se['pairs_per_pulse'] == [6, 3, 6, 3, 6] and se['AOD_reset_actions'] == 8
    assert len(se['AOD_reset_intervals_us']) == 1 and se['transfer_batches'] == 14
    assert pair['pairs_per_pulse'] == [12, 6, 12, 6, 12]
    old = ROOT / 'artifacts/demos/aod-held-cz-20261007/SE'
    assert sha(old / 'physical-dag.json') == se['source_dag_sha256']
    tests = {}
    for suite in ('qec', 'backend', 'device', 'runtime', 'validation'):
        log = (OUT / (suite + '-tests.log')).read_text(encoding='utf-8')
        assert re.search(r'\nOK\s*$', log) and 'skipped=' not in log
        tests[suite] = int(re.search(r'Ran (\d+) tests?', log)[1])
    assert sum(tests.values()) == 382
    functional = read(OUT / 'se-viewer-functional-checks.json')
    paths = read(OUT / 'viewer-path-audit.json')
    assert functional['passed'] and paths['passed']
    before = read(NOTE / 'se-parallel-before-20261008/manifest.json')
    changed = [p for p, h in before.items() if sha(ROOT / p) != h]
    additions = ['src/na_pipeline/backend/se_frontier.py', 'tests/backend/test_se_parallel.py',
                 'scripts/se_parallel_job.py', 'scripts/probe_se_capture_waves.py',
                 'scripts/build_se_parallel_viewer.py', 'scripts/check_se_parallel_viewer.js',
                 'scripts/record_se_parallel_delivery.py']
    changes, patch = [], []
    for p in changed + additions:
        prior = NOTE / 'se-parallel-before-20261008' / p
        old_text = prior.read_text(encoding='utf-8') if p in changed else ''
        new_text = (ROOT / p).read_text(encoding='utf-8')
        patch.extend(difflib.unified_diff(old_text.splitlines(True), new_text.splitlines(True),
                     fromfile='a/' + p if p in changed else '/dev/null', tofile='b/' + p))
        changes.append({'path': p, 'before_sha256': before.get(p), 'after_sha256': sha(ROOT / p)})
    (NOTE / 'se-parallel-changes-20261008.patch').write_text(''.join(patch), encoding='utf-8')
    save(NOTE / 'se-parallel-changes-20261008.json', {'files': changes,
         'note': 'Already present in shared checkout; inspect hashes before applying elsewhere. Do not blindly apply twice.'})
    acceptance = {'schema_version': 'SEParallelDelivery/1', 'engineering_passed': True,
        'user_visual_acceptance': 'pending', 'browser_rendering_verified': False,
        'kb_revision': 'kb-0006', 'plan_revision': 'plan-0008', 'interface_version': 'IF-COMPILED-MODULE-001/0.3.0',
        'target_thread_id': '01a11223-4072-7061-a537-4b86db99ee28',
        'server_job_id': JOB.name, 'server': read(JOB / 'observed-status.json'),
        'source_test_files_match_server': len(sources), 'server_output_files_preserved': len(protected),
        'SE_source_unchanged': True, 'tests': tests, 'test_total': sum(tests.values()),
        'components': rows, 'viewer_functional': functional, 'viewer_paths': paths,
        'comparison': {'old_SE_CZ_pulses': 7, 'new_SE_CZ_pulses': 5,
                       'old_SE_at_200us_transfer_duration_us': 4148,
                       'new_SE_at_200us_transfer_duration_us_tested': 3289,
                       'new_SE_at_100us_transfer_duration_us': 1889},
        'boundaries': ['Five CZ pulses achieved; four not achieved, no global optimality claim.',
                       'Current frozen canonical geometry, selected endpoints and return-home policy.',
                       'SE_PAIR has five shared pulses but two measurement connectors.',
                       'One factory maintenance stage checked; full factory/T/Shor not rebuilt here.',
                       '100us is user supplied engineering assumption, not calibrated hardware.',
                       'Old saved devices and artifacts remain at their recorded timings.',
                       'No general retime API or cross-module held-AOD composition implemented.',
                       'Fake event scenario, no quantum-state/noise/hardware execution.']}
    save(OUT / 'acceptance.json', acceptance)
    print(json.dumps({'engineering_passed': True, 'test_total': sum(tests.values()),
                     'source_test_files': len(sources), 'protected_server_files': len(protected),
                     'changed_files': changed, 'SE': se, 'SE_PAIR': pair}, ensure_ascii=False))


if __name__ == '__main__':
    main()
