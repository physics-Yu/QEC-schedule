"""One formal UI subcheck. Evidence is persisted separately for each attempt."""
import argparse
import hashlib
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import time
import traceback

from playwright.sync_api import sync_playwright


def main(args):
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    def write(name,value):
        (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    short=[{'id':f'G{i:03d}','gate_type':kind,'qubit_ids':qs,'parameters':[],'column':i}
           for i,(kind,qs) in enumerate((('H',['Q000']),('H',['Q009']),('CZ',['Q000','Q009']),
                                        ('H',['Q009']),('CZ',['Q000','Q009']),('X',['Q001'])))]
    attempt={'number':args.attempt,'formal':True,'started_at':datetime.now(timezone.utc).isoformat(),
             'scope':f'step4A attempt{args.attempt} UI subcheck: restore real 481-slot execution; one editable short compile',
             'expected_patch_origins':[[0,0],[45,5]],'expected_aod_shape':[8,14],
             'expected_short_gates':short,'expected_short_physical_status':'completed',
             'expected_short_logical_ghz2':False,'expected_short_measurement_protocol_complete':False,
             'criteria':['saved staggered481 not recompiled','two origin controls and JSON export match physical input','origin edit and undo preserve gates and AOD','both 32x modes exact original SLM terminal','six edited effects once and original terminal','submitted origin field reaches actual shifted initial coordinates'],
             'unexpected_failure_action':'persist evidence; ordinary UI/test faults may be fixed; stop and report physical uncertainty or framework changes'}
    write('attempt.json',attempt)
    source_files=sorted(p for p in Path('src').rglob('*') if p.suffix in {'.py','.js','.html'})
    source_before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
    errors=[];requests=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
            page=browser.new_page(viewport={'width':1700,'height':1200})
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.on('request',lambda request:requests.append({'method':request.method,'url':request.url}))
            page.add_init_script("""let library;Object.defineProperty(window,'NeutralAtomViewer',{
              configurable:true,get(){return library},set(lib){library=lib;const mount=lib.mount;
              lib.mount=function(...args){const v=mount.apply(this,args);window.acceptanceViewer=v;return v;}}});""")
            page.goto(args.base+'/?job='+args.saved_job)
            page.wait_for_function("!document.getElementById('export-replay').disabled",timeout=30000)
            restored=page.request.get(args.base+'/api/jobs/'+args.saved_job+'/result').json()
            recording=restored['recording'];duration=recording['duration']
            assert restored['input']['compiler']=='qec_joint'
            assert len(restored['input']['gates'])==481
            assert restored['provenance']['kind']=='saved_execution'
            assert restored['provenance']['compiler_free_replay']=='PASS'
            assert '未发起新编译' in page.locator('#saved-provenance').inner_text()
            assert not any(r['method']=='POST' and r['url'].endswith('/api/compile') for r in requests)
            assert not page.locator('#auto').is_checked()
            page.locator('#saved-provenance').screenshot(path=str(output/'saved-result-provenance.png'))
            page.locator('#qec-result').screenshot(path=str(output/'saved-qec-result.png'))
            assert restored['input']['qec_patch_origins']==[[0,0],[45,5]]
            assert (restored['input']['aod_rows'],restored['input']['aod_columns'])==(8,14)
            assert page.locator('#qec-patch-origin-0').input_value()=='0, 0'
            assert page.locator('#qec-patch-origin-1').input_value()=='45, 5'
            def exported(label):
                with page.expect_download() as download:
                    page.locator('#export-input').click()
                path=output/(label+'.json');download.value.save_as(str(path))
                return json.loads(path.read_text(encoding='utf-8'))
            original=exported('full-export-original')
            assert original==restored['input']
            page.wait_for_load_state('networkidle')
            page.locator('#qec-options').screenshot(path=str(output/'origin-controls.png'))
            page.locator('#layout-preview').screenshot(path=str(output/'shifted-initial-preview.png'))
            page.locator('#qec-patch-origin-1').fill('40, 0')
            page.locator('#qec-patch-origin-1').press('Tab')
            edited=exported('full-export-origin-edited')
            assert edited==original|{'qec_patch_origins':[[0,0],[40,0]]}
            page.locator('#undo').click()
            undone=exported('full-export-origin-undone')
            assert undone==original
            assert page.locator('#qec-patch-origin-1').input_value()=='45, 5'
            assert not any(r['method']=='POST' and r['url'].endswith('/api/compile') for r in requests)
            initial={a['id']:a for a in recording['frames'][0]['atom_updates']}
            assert len(initial)==34
            assert initial['Q009']['position']=={'x_um':45,'y_um':5}
            assert initial['Q026']['position']=={'x_um':50,'y_um':10}
            playback=[]
            for mode in ('physical','keyframe'):
                page.locator('#viewer #mode').select_option(mode)
                page.locator('#viewer #speed').select_option('32')
                page.locator('#viewer #reset').click();page.locator('#viewer #play').click()
                stamp=time.monotonic();previous=0
                while time.monotonic()-stamp<180:
                    page.wait_for_timeout(1000);state=page.evaluate('acceptanceViewer.getStatus()')
                    assert state['time_us']>=previous
                    if state['playing']:assert state['time_us']>previous,'playback stalled'
                    previous=state['time_us']
                    if not state['playing']:break
                assert not state['playing'] and abs(state['time_us']-duration)<1e-7
                final_atoms=page.evaluate('acceptanceViewer.debug.current.atoms')
                assert {a['id']:a['holder'] for a in final_atoms}=={a['id']:a['holder'] for a in recording['frames'][0]['atom_updates']}
                assert len(final_atoms)==34 and all(a['holder']['holder_type']=='static' for a in final_atoms)
                assert {a['id']:a['position'] for a in final_atoms}=={q:a['position'] for q,a in initial.items()}
                page.locator('#viewer').screenshot(path=str(output/f'saved-terminal-{mode}.png'))
                playback.append({'mode':mode,'speed':32,'finished':True,'wall_seconds':time.monotonic()-stamp})
                print(json.dumps(playback[-1]),flush=True)
            # The only new physical experiment: actual UI editing of six Clifford gates.
            page.locator('#clear').click()
            for gate in short:
                page.locator('[data-tool="'+gate['gate_type']+'"]').click()
                for q in gate['qubit_ids']:
                    page.locator(f'[data-q="{int(q[1:])}"][data-column="{gate["column"]}"]').click()
            page.screenshot(path=str(output/'short-edited-input.png'),full_page=True)
            with page.expect_response(lambda r:r.url.endswith('/api/compile') and r.request.method=='POST') as response:
                page.locator('#compile').click()
            job=response.value.json()['id'];submitted=response.value.request.post_data_json
            write('short-submitted-input.json',submitted);write('short-job.json',{'job_id':job,'url':args.base+'/?job='+job})
            assert submitted['compiler']=='qec_joint' and submitted['gates']==short
            assert submitted['qec_patch_origins']==[[0,0],[45,5]]
            for key in ('aod_rows','aod_columns','aod_row_offsets_um','aod_column_offsets_um'):
                assert submitted[key]==original[key]
            print('SHORT JOB '+job,flush=True)
            stamp=time.monotonic()
            while time.monotonic()-stamp<120:
                status=page.request.get(args.base+'/api/jobs/'+job).json()
                if status['status']!='compiling':break
                page.wait_for_timeout(1000)
            write('short-job-final-status.json',status)
            assert status['status']=='completed',status
            result=page.request.get(args.base+'/api/jobs/'+job+'/result').json()
            short_out=output/'short-compile';short_out.mkdir(exist_ok=True)
            for source in (Path(args.server_output)/job).iterdir():
                if source.is_file():shutil.copy2(source,short_out/source.name)
            assert result['qec_result']['verified_logical_ghz2'] is False
            assert result['qec_result']['measurement_protocol_complete'] is False
            assert len(result['input']['gates'])==6
            assert result['input']['qec_patch_origins']==submitted['qec_patch_origins']
            short_initial={a['id']:a for a in result['recording']['frames'][0]['atom_updates']}
            assert len(short_initial)==34
            assert short_initial['Q009']['position']=={'x_um':45,'y_um':5}
            assert short_initial['Q026']['position']=={'x_um':50,'y_um':10}
            events=[json.loads(line) for line in (short_out/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
            effects=[gid for e in events if e.get('effect_completed') for gid in (e.get('effect_gate_ids') or e.get('gate_ids') or [e['gate_id']])]
            assert len(effects)==6 and set(effects)=={g['id'] for g in short}
            page.wait_for_function("acceptanceViewer.debug.data.summary.metrics.completed_gate_count===6",timeout=30000)
            assert page.locator('#saved-provenance').is_hidden()
            assert 'FAIL' in page.locator('#qec-result-status').inner_text()
            page.locator('#viewer #mode').select_option('physical')
            page.locator('#viewer #slider').evaluate("(el,t)=>{el.value=t;el.dispatchEvent(new Event('input',{bubbles:true}))}",result['recording']['duration'])
            final=page.evaluate('acceptanceViewer.debug.current.atoms')
            assert len(final)==34 and all(a['holder']['holder_type']=='static' for a in final)
            initial_holders={a['id']:a['holder'] for a in result['recording']['frames'][0]['atom_updates']}
            assert {a['id']:a['holder'] for a in final}==initial_holders
            assert {a['id']:a['position'] for a in final}=={q:a['position'] for q,a in short_initial.items()}
            page.locator('#viewer').screenshot(path=str(output/'short-actual-terminal.png'))
            assert not errors,errors
            browser.close()
        report={'status':'passed','saved_job_id':args.saved_job,'saved_execution_recompiled':False,
            'saved_actual_strategy':'qec_joint','saved_duration_us':duration,
            'patch_origins':[[0,0],[45,5]],'aod_shape':[8,14],'origin_edit_undo_export_preserves_circuit_and_aod':True,
            'short_actual_initial_positions':{q:short_initial[q]['position'] for q in ('Q009','Q026')},'full_playback':playback,
            'short_job_id':job,'short_gates':6,'short_effects_exactly_once':effects,'short_actual_compiler':'qec_joint',
            'short_expected_non_GHZ':True,'short_physical_status':'completed','short_duration_us':result['recording']['duration'],
            'page_errors':errors,'finished_at':datetime.now(timezone.utc).isoformat()}
        source_after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
        write('source-stability.json',{'changed_during_run':source_before!=source_after,'files':source_before})
        assert source_before==source_after,'Source changed during formal subcheck'
        write('browser-acceptance.json',report);print(json.dumps(report),flush=True)
    except Exception as error:
        write('failure.json',{'status':'failed','attempt':args.attempt,'phase':'formal_ui_subcheck','type':type(error).__name__,
            'message':str(error),'traceback':traceback.format_exc(),'page_errors':errors,'action':'Persist failure; classify UI/test versus physical/framework issue before follow-up',
            'finished_at':datetime.now(timezone.utc).isoformat()})
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',default='http://127.0.0.1:8785')
    p.add_argument('--saved-job',required=True)
    p.add_argument('--attempt',type=int,default=3)
    p.add_argument('--output',default='artifacts/qec-roadmap/step4-attempt3-ui')
    p.add_argument('--server-output',default='artifacts/workbench-qec-origins')
    main(p.parse_args())
