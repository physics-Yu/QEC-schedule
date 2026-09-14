"""Real browser editing and recompilation smoke on the final 2D platform."""
import json
from pathlib import Path
import shutil
import sys
import time

from playwright.sync_api import sync_playwright


output = Path('artifacts/surface-2d/edited-smoke')
output.mkdir(parents=True, exist_ok=True)
base = 'http://127.0.0.1:8769'


def write(name, value):
    (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


errors = []
with sync_playwright() as p:
    browser = p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
    page = browser.new_page(viewport={'width':1700, 'height':1200})
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.add_init_script("""let viewerLibrary; Object.defineProperty(window,'NeutralAtomViewer',{
        configurable:true,get(){return viewerLibrary},set(lib){viewerLibrary=lib;
        const original=lib.mount;lib.mount=function(...args){const result=original.apply(this,args);
        window.acceptanceViewer=result;return result;}}});""")
    resuming = '--resume' in sys.argv
    if resuming:
        job_id = json.loads((output / 'job.json').read_text(encoding='utf-8'))['job_id']
        assert (output / 'submitted-input.json').exists() and (output / 'edited-circuit.png').exists()
        page.goto(base + '/?job=' + job_id)
    else:
        page.goto(base + '/?example=surface-ghz')
        page.wait_for_function("document.getElementById('circuit-count').textContent.includes('194')")
        assert not page.locator('#auto').is_checked()
        page.locator('#clear').click()
        for q, gate in enumerate(('H', 'X', 'Y', 'Z', 'T')):
            page.locator('[data-tool="' + gate + '"]').click()
            page.locator(f'[data-q="{q}"][data-column="0"]').click()
        page.locator('[data-tool="CZ"]').click()
        page.locator('[data-q="0"][data-column="1"]').click()
        page.locator('[data-q="9"][data-column="1"]').click()
        assert '6 门' in page.locator('#circuit-count').inner_text()
        page.screenshot(path=str(output / 'edited-circuit.png'), full_page=True)
        with page.expect_response(lambda r: r.url.endswith('/api/compile') and r.request.method == 'POST') as started:
            page.locator('#compile').click()
        job_id = started.value.json()['id']
        submitted = started.value.request.post_data_json
        write('submitted-input.json', submitted)
        write('job.json', {'job_id':job_id, 'url':base + '/?job=' + job_id})
        print('JOB ' + job_id, flush=True)
    stamp = time.monotonic()
    while time.monotonic() - stamp < 300:
        status = page.request.get(base + '/api/jobs/' + job_id).json()
        if status['status'] != 'compiling': break
        page.wait_for_timeout(1000)
    write('job-final-status.json', status)
    assert status['status'] == 'completed', status
    result = page.request.get(base + '/api/jobs/' + job_id + '/result').json()
    for source in (Path('artifacts/workbench-surface-2d') / job_id).iterdir():
        if source.is_file(): shutil.copy2(source, output / source.name)
    gates = result['input']['gates']
    assert len(gates) == 6 and {g['gate_type'] for g in gates} == {'H','X','Y','Z','T','CZ'}
    assert next(g['qubit_ids'] for g in gates if g['gate_type']=='CZ') == ['Q000','Q009']
    records = [json.loads(line) for line in (output / 'trace.jsonl').read_text(encoding='utf-8').splitlines()]
    effects = [gid for event in records if event.get('effect_completed')
               for gid in (event.get('effect_gate_ids') or event.get('gate_ids') or [event['gate_id']])]
    assert len(effects) == 6 and set(effects) == {g['id'] for g in gates}
    page.wait_for_function("!document.getElementById('export-replay').disabled", timeout=60000)
    page.locator('#viewer #reset').click()
    initial = page.evaluate('acceptanceViewer.debug.current.atoms')
    duration = result['recording']['duration']
    page.locator('#viewer #mode').select_option('physical')
    page.locator('#viewer #slider').evaluate("(el,time)=>{el.value=time;el.dispatchEvent(new Event('input',{bubbles:true}))}", duration)
    terminal = page.evaluate('acceptanceViewer.debug.current.atoms')
    assert len(terminal) == 36
    assert {a['id']:a['position'] for a in terminal} == {a['id']:a['position'] for a in initial}
    assert all(a['holder']['holder_type'] == 'static' for a in terminal)
    viewer_data = page.evaluate('acceptanceViewer.debug.data')
    assert viewer_data['duration'] == duration
    assert viewer_data['frames'][-1]['gate_counts']['completed'] == 6
    page.locator('#viewer').screenshot(path=str(output / 'terminal.png'))
    assert not errors, errors
    browser.close()
report = {'status':'passed','browser':'real headless Microsoft Edge via Playwright',
          'job_id':job_id,'real_edit_controls':True,'real_compile_button':True,
          'layout':'surface_patches','atoms':36,'gates':6,'gate_types':['H','X','Y','Z','T','CZ'],
          'cross_patch_CZ':['Q000','Q009'],'effects_exactly_once':effects,
          'all_atoms_restored':True,'viewer_completed_gates':6,'duration_us':duration,
          'resumed_viewer_only':resuming,'old_194_gate_result_replaced':True,'page_errors':errors}
write('browser-acceptance.json',report)
print(json.dumps(report,ensure_ascii=False),flush=True)
