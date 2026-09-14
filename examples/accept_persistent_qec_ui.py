"""One formal UI subcheck. Unexpected failure is persisted, never retried."""
import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import time

from playwright.sync_api import sync_playwright


def main(args):
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    def write(name,value):
        (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    short=[{'id':f'G{i:03d}','gate_type':kind,'qubit_ids':qs,'parameters':[],'column':i}
           for i,(kind,qs) in enumerate((('H',['Q000']),('CZ',['Q000','Q009']),
                                        ('H',['Q009']),('CZ',['Q000','Q009'])))]
    attempt={'number':1,'formal':True,'started_at':datetime.now(timezone.utc).isoformat(),
             'scope':'step2 UI subcheck: restore real 481-slot execution; one editable short compile',
             'expected_short_gates':short,'expected_short_physical_status':'completed',
             'expected_short_logical_ghz2':False,'expected_short_measurement_protocol_complete':False,
             'unexpected_failure_action':'stop and report; do not modify or retry'}
    write('attempt.json',attempt)
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
            assert restored['input']['compiler']=='qec_persistent'
            assert len(restored['input']['gates'])==481
            assert restored['provenance']['kind']=='saved_execution'
            assert restored['provenance']['compiler_free_replay']=='PASS'
            assert '未发起新编译' in page.locator('#saved-provenance').inner_text()
            assert not any(r['method']=='POST' and r['url'].endswith('/api/compile') for r in requests)
            assert not page.locator('#auto').is_checked()
            page.locator('#saved-provenance').screenshot(path=str(output/'saved-result-provenance.png'))
            page.locator('#qec-result').screenshot(path=str(output/'saved-qec-result.png'))
            # Observe a real H pulse while its addressed atom remains in AOD.
            retained=next(o for o in recording['operations'] if o.get('gate_type')=='H' and o.get('applied') is not False
                          and any(h['holder_type']=='mobile' for h in o.get('target_holders',{}).values()))
            page.locator('#viewer #mode').select_option('physical')
            page.locator('#viewer #slider').evaluate("(el,t)=>{el.value=t;el.dispatchEvent(new Event('input',{bubbles:true}))}",(retained['start']+retained['end'])/2)
            atoms=page.evaluate('acceptanceViewer.debug.current.atoms')
            mobile_targets=[a for a in atoms if a['id'] in retained['qubit_ids'] and a['holder']['holder_type']=='mobile']
            assert mobile_targets and all(a['activity']=='gating' for a in mobile_targets)
            assert page.evaluate('acceptanceViewer.debug.current.f.movement===null')
            for atom in mobile_targets:
                distances=[((atom['position']['x_um']-other['position']['x_um'])**2+
                            (atom['position']['y_um']-other['position']['y_um'])**2)**.5
                           for other in atoms if other['id']!=atom['id']]
                assert min(distances)>=5-1e-7
            assert '静止 AOD' in page.locator('#viewer #operation-caption').inner_text()
            page.locator('#viewer').screenshot(path=str(output/'retained-aod-H.png'))
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
                page.locator('#viewer').screenshot(path=str(output/f'saved-terminal-{mode}.png'))
                playback.append({'mode':mode,'speed':32,'finished':True,'wall_seconds':time.monotonic()-stamp})
                print(json.dumps(playback[-1]),flush=True)
            # The only new physical experiment: actual UI editing of four Clifford gates.
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
            assert submitted['compiler']=='qec_persistent' and submitted['gates']==short
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
            assert len(result['input']['gates'])==4
            events=[json.loads(line) for line in (short_out/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
            effects=[gid for e in events if e.get('effect_completed') for gid in (e.get('effect_gate_ids') or e.get('gate_ids') or [e['gate_id']])]
            assert len(effects)==4 and set(effects)=={g['id'] for g in short}
            page.wait_for_function("acceptanceViewer.debug.data.summary.metrics.completed_gate_count===4",timeout=30000)
            assert page.locator('#saved-provenance').is_hidden()
            assert 'FAIL' in page.locator('#qec-result-status').inner_text()
            page.locator('#viewer #mode').select_option('physical')
            page.locator('#viewer #slider').evaluate("(el,t)=>{el.value=t;el.dispatchEvent(new Event('input',{bubbles:true}))}",result['recording']['duration'])
            final=page.evaluate('acceptanceViewer.debug.current.atoms')
            assert len(final)==34 and all(a['holder']['holder_type']=='static' for a in final)
            page.locator('#viewer').screenshot(path=str(output/'short-actual-terminal.png'))
            assert not errors,errors
            browser.close()
        report={'status':'passed','saved_job_id':args.saved_job,'saved_execution_recompiled':False,
            'saved_actual_strategy':'qec_persistent','saved_duration_us':duration,
            'retained_H_atoms':[a['id'] for a in mobile_targets],'retained_H_gate_ids':retained['gate_ids'],
            'retained_H_minimum_separation_checked':True,'full_playback':playback,
            'short_job_id':job,'short_gates':4,'short_effects_exactly_once':effects,'short_actual_compiler':'qec_persistent',
            'short_expected_non_GHZ':True,'short_physical_status':'completed','short_duration_us':result['recording']['duration'],
            'page_errors':errors,'finished_at':datetime.now(timezone.utc).isoformat()}
        write('browser-acceptance.json',report);print(json.dumps(report),flush=True)
    except Exception as error:
        write('failure.json',{'status':'failed','attempt':1,'phase':'formal_ui_subcheck','type':type(error).__name__,
            'message':str(error),'page_errors':errors,'action':'STOP: await user approval; no repair or retry performed',
            'finished_at':datetime.now(timezone.utc).isoformat()})
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',default='http://127.0.0.1:8783')
    p.add_argument('--saved-job',required=True)
    p.add_argument('--output',default='artifacts/qec-roadmap/step2-attempt1/ui-subcheck')
    p.add_argument('--server-output',default='artifacts/workbench-qec-persistent')
    main(p.parse_args())
