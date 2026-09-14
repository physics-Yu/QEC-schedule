"""Real Edge acceptance of editable 2D patches, batch CZ and full playback."""
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
from neutral_atom_experiments.surface_ghz import verify_gate_sequence


def main(output,server_output,base,job_id=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    def write(name,value):
        (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    def hashes():
        return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted((ROOT/'src').rglob('*')) if p.suffix in {'.py','.js','.html'}}
    resuming=job_id is not None
    prior_editor_evidence=(resuming and (output/'job.json').exists() and (output/'editor.png').exists()
        and json.loads((output/'job.json').read_text(encoding='utf-8')).get('job_id')==job_id)
    errors=[]
    source_start=json.loads((output/'source-at-start.json').read_text(encoding='utf-8')) if prior_editor_evidence and (output/'source-at-start.json').exists() else hashes()
    write('source-at-start.json',source_start)
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
        page=browser.new_page(viewport={'width':1700,'height':1200})
        page.on('pageerror',lambda error:errors.append(str(error)))
        # Observe the actual mounted viewer; do not replace data or execution.
        page.add_init_script("""let viewerLibrary;
            Object.defineProperty(window,'NeutralAtomViewer',{configurable:true,
              get(){return viewerLibrary},set(lib){viewerLibrary=lib;
                const original=lib.mount;lib.mount=function(...args){
                  const result=original.apply(this,args);window.acceptanceViewer=result;return result;
                };
              }});""")
        if not resuming:
            page.goto(base+'/?example=surface-ghz')
            page.wait_for_function("document.getElementById('circuit-count').textContent.includes('194')")
            assert page.locator('#layout').input_value()=='surface_patches'
            assert page.locator('#compiler').input_value()=='patch_greedy'
            assert page.locator('#atom-count').input_value()=='36'
            assert page.locator('#aod-rows').input_value()==page.locator('#aod-columns').input_value()=='6'
            assert [float(x) for x in page.locator('#aod-column-offsets').input_value().split(',')]==[0,10,20,40,50,60]
            assert [float(x) for x in page.locator('#aod-row-offsets').input_value().split(',')]==[0,10,20,40,50,60]
            assert not page.locator('#ez-neighbor-guard').is_checked()
            assert not page.locator('#auto').is_checked()
            page.locator('#add-column').click()
            page.locator('[data-tool="H"]').click()
            page.locator('[data-q="0"][data-column="17"]').click()
            assert '195' in page.locator('#circuit-count').inner_text()
            page.locator('#undo').click()
            assert '194' in page.locator('#circuit-count').inner_text()
            page.screenshot(path=str(output/'editor.png'),full_page=True)
            with page.expect_response(lambda r:r.url.endswith('/api/compile') and r.request.method=='POST') as started:
                page.locator('#compile').click()
            job_id=started.value.json()['id']
            write('job.json',{'job_id':job_id,'url':base+'/?job='+job_id})
        else:
            page.goto(base+'/?job='+job_id)
        stamp=time.monotonic();last=-1
        while time.monotonic()-stamp<3700:
            response=page.request.get(base+'/api/jobs/'+job_id).json()
            done=response.get('progress',{}).get('completed_gates',0)
            if done!=last:
                print(json.dumps(response,ensure_ascii=False),flush=True);last=done
            if response['status']!='compiling':break
            page.wait_for_timeout(1000)
        write('job-final-status.json',response)
        assert response['status']=='completed',response
        result=page.request.get(base+'/api/jobs/'+job_id+'/result').json()
        source=Path(server_output)/job_id
        for path in source.iterdir():
            if path.is_file():shutil.copy2(path,output/path.name)
        records=[json.loads(s) for s in (source/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
        by_id={g['id']:g for g in result['input']['gates']}
        effects=[gid for r in records if r.get('effect_completed')
                 for gid in (r.get('effect_gate_ids') or r.get('gate_ids') or [r['gate_id']])]
        assert len(effects)==194 and len(set(effects))==194
        assert verify_gate_sequence([by_id[g] for g in effects])
        write('actual-quantum-verification.json',{'status':'verified_ideal_clifford','effect_count':194,
             'gate_order':effects,'batch_events':sum(bool(r.get('effect_gate_ids')) for r in records if r.get('effect_completed'))})
        saved=json.loads((source/'result.json').read_text(encoding='utf-8'))
        result['metrics']=saved['metrics'];result['ideal_logical_GHZ_verified']=True
        write('result.json',{k:v for k,v in result.items() if k!='recording'})
        page.wait_for_function("!document.getElementById('export-replay').disabled",timeout=120000)
        page.locator('#viewer #joint').click()
        page.locator('#viewer').screenshot(path=str(output/'joint-transport.png'))
        page.locator('#viewer #mode').select_option('physical')
        batch_checks=[]
        batch_sizes=sorted({len(o.get('gate_ids',[])) for o in result['recording']['operations'] if len(o.get('gate_ids',[]))>1})
        assert batch_sizes,'The experiment produced no actual parallel CZ batch'
        inspected=sorted(({9,18}&set(batch_sizes))|{max(batch_sizes)})
        for count in inspected:
            operation=next(o for o in result['recording']['operations'] if len(o.get('gate_ids',[]))==count)
            mid=(operation['start']+operation['end'])/2
            page.locator('#viewer #slider').evaluate("(el,t)=>{el.value=t;el.dispatchEvent(new Event('input',{bubbles:true}))}",mid)
            status=page.locator('#viewer #status').inner_text()
            assert f'{count} 门' in status,status
            active=page.evaluate("acceptanceViewer.debug.operationsAt(acceptanceViewer.getStatus().time_us).filter(o=>o.kind==='entangling_pulse')")
            assert sum(len(o.get('gate_ids',[])) for o in active)==count
            assert sum(len(o.get('intended_pairs',[])) for o in active)==count
            page.locator('#viewer').screenshot(path=str(output/f'batch-{count}.png'))
            batch_checks.append({'count':count,'time_us':mid,'gate_ids':operation['gate_ids'],'visible_status':status,'pairs':operation['intended_pairs']})
        playback=[]
        for mode in ('physical','keyframe'):
            page.locator('#viewer #mode').select_option(mode)
            page.locator('#viewer #speed').select_option('32')
            page.locator('#viewer #reset').click();page.locator('#viewer #play').click()
            stamp=time.monotonic();previous=0;count=0
            while time.monotonic()-stamp<150:
                page.wait_for_timeout(1000)
                state=page.evaluate('acceptanceViewer.getStatus()');now=state['time_us']
                assert now>=previous
                if state['playing']:assert now>previous,'Playback stalled'
                previous=now;count+=1
                if not state['playing']:break
            assert not state['playing'] and abs(state['time_us']-result['recording']['duration'])<1e-8,state
            page.locator('#viewer').screenshot(path=str(output/f'terminal-{mode}.png'))
            playback.append({'mode':mode,'speed':32,'wall_seconds':time.monotonic()-stamp,
                'samples':count,'final_simulation_us':state['time_us'],'completed_without_stall':True})
            print(json.dumps(playback[-1]),flush=True)
        page.goto(base+'/?job='+job_id)
        page.wait_for_function("!document.getElementById('export-replay').disabled",timeout=120000)
        assert page.locator('#layout').input_value()=='surface_patches'
        assert not page.locator('#auto').is_checked()
        assert '194' in page.locator('#circuit-count').inner_text()
        assert not errors,errors
        browser.close()
    source_end=hashes();write('source-sha256.json',source_end)
    write('source-stability.json',{'changed_during_run':source_start!=source_end})
    report={'browser':'real headless Microsoft Edge via Playwright','job_id':job_id,'status':'passed',
            'gates':194,'resumed_existing_job':resuming,'actual_batch_sizes':batch_sizes,'physical_layout':'four 3x3 patches in 2x2','aod_shape':[6,6],
            'fixed_nonuniform_axes_um':[0,10,20,40,50,60],'ez_neighbor_guard_enabled':False,
            'edit_add_H_and_undo':not resuming or prior_editor_evidence,
            'real_compile_button':not resuming or prior_editor_evidence,'joint_move_viewed':True,
            'batch_views':batch_checks,'full_recording_playback':playback,'completed_deep_link':True,
            'page_errors':errors,'actual_effect_order_ideal_GHZ':True}
    write('browser-acceptance.json',report);print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',default='artifacts/surface-2d/patch_greedy')
    p.add_argument('--server-output',default='artifacts/workbench-surface-2d')
    p.add_argument('--base',default='http://127.0.0.1:8769')
    p.add_argument('--job-id',help='Inspect a previously browser-compiled job without recompiling')
    args=p.parse_args();main(args.output,args.server_output,args.base,args.job_id)
