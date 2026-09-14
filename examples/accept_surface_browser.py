"""Real headless Edge acceptance: edit GHZ, undo, compile, inspect full replay."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from playwright.sync_api import sync_playwright
from neutral_atom_env.experiments.surface_ghz import verify_gate_sequence


def main(output,server_output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    def hashes():
        return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'src').rglob('*.py'))}
    source_start=hashes();errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
        page=browser.new_page(viewport={'width':1600,'height':1100})
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto('http://127.0.0.1:8769/?example=surface-ghz')
        page.wait_for_function("document.getElementById('circuit-count').textContent.includes('194')")
        assert page.locator('#atom-count').input_value()=='36'
        assert page.locator('#aod-traps').input_value()=='36'
        assert not page.locator('#auto').is_checked()
        # Edit the real input then undo; compilation must receive the exact GHZ.
        page.locator('#add-column').click()
        page.locator('[data-tool="H"]').click()
        page.locator('[data-q="0"][data-column="17"]').click()
        assert '195' in page.locator('#circuit-count').inner_text()
        page.locator('#undo').click()
        assert '194' in page.locator('#circuit-count').inner_text()
        page.screenshot(path=str(output/'editor.png'),full_page=True)
        with page.expect_response(lambda r:r.url.endswith('/api/compile') and r.request.method=='POST') as started:
            page.locator('#compile').click()
        job_id=started.value.json()['id'];last=-1
        (output/'job.json').write_text(json.dumps({'job_id':job_id,'url':f'http://127.0.0.1:8769/?job={job_id}'}),encoding='utf-8')
        stamp=time.monotonic()
        while time.monotonic()-stamp<3700:
            response=page.request.get(f'http://127.0.0.1:8769/api/jobs/{job_id}').json()
            done=response.get('progress',{}).get('completed_gates',0)
            if done!=last:
                print(json.dumps(response,ensure_ascii=False),flush=True);last=done
            if response['status']!='compiling':break
            page.wait_for_timeout(1000)
        assert response['status']=='completed',response
        result=page.request.get(f'http://127.0.0.1:8769/api/jobs/{job_id}/result').json()
        source=Path(server_output)/job_id
        for path in source.iterdir():
            if path.is_file():shutil.copy2(path,output/path.name)
        # Trace format is read independently from the worker's physical output.
        records=[json.loads(s) for s in (source/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
        by_id={g['id']:g for g in result['input']['gates']}
        effects=[r['gate_id'] for r in records if r.get('effect_completed')]
        assert len(effects)==194 and verify_gate_sequence([by_id[g] for g in effects])
        saved=json.loads((source/'result.json').read_text(encoding='utf-8'))
        result['metrics']=saved['metrics'];result['ideal_logical_GHZ_verified']=True
        (output/'result.json').write_text(json.dumps({k:v for k,v in result.items() if k!='recording'},ensure_ascii=False),encoding='utf-8')
        page.wait_for_function("!document.getElementById('export-replay').disabled",timeout=120000)
        # Inspect a real joint move and verify actual playback controls.
        page.locator('#viewer #joint').click()
        page.locator('#viewer').screenshot(path=str(output/'joint-transport.png'))
        for mode in ('physical','keyframe'):
            page.locator('#viewer #mode').select_option(mode)
            page.locator('#viewer #speed').select_option('32')
            page.locator('#viewer #reset').click()
            page.locator('#viewer #play').click()
            page.wait_for_timeout(600)
            assert float(page.locator('#viewer #slider').input_value())>0
            page.locator('#viewer #play').click()
        page.locator('#viewer #slider').evaluate("el=>{el.value=el.max;el.dispatchEvent(new Event('input',{bubbles:true}))}")
        page.locator('#viewer').screenshot(path=str(output/'terminal.png'))
        # Loading the completed job deep link must restore editable input and replay.
        page.goto(f'http://127.0.0.1:8769/?job={job_id}')
        page.wait_for_function("!document.getElementById('export-replay').disabled",timeout=120000)
        assert '194' in page.locator('#circuit-count').inner_text()
        assert not page.locator('#auto').is_checked()
        assert not errors,errors
        browser.close()
    source_end=hashes()
    (output/'source-at-start.json').write_text(json.dumps(source_start),encoding='utf-8')
    (output/'source-sha256.json').write_text(json.dumps(source_end),encoding='utf-8')
    (output/'source-stability.json').write_text(json.dumps({'changed_during_run':source_start!=source_end}),encoding='utf-8')
    report={'browser':'headless Microsoft Edge via Playwright','job_id':job_id,'status':'passed','gates':194,
            'edit_add_H_and_undo':True,'real_compile_button':True,'joint_move_viewed':True,
            'two_modes_at_32x_advance':True,'completed_deep_link':True,'page_errors':errors,
            'actual_effect_order_ideal_GHZ':True}
    (output/'browser-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',default='artifacts/surface-ghz/row_greedy')
    p.add_argument('--server-output',default='artifacts/workbench-surface-ghz')
    a=p.parse_args();main(a.output,a.server_output)
