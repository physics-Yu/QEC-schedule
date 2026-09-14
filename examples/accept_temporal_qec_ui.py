"""Temporal UI acceptance; persist evidence before classifying any failure."""
import argparse
import hashlib
import traceback
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
                                        ('H',['Q009']),('CZ',['Q000','Q009']),
                                        ('MEASURE',['Q018']),('RESET',['Q018'])))]
    short[4]['readout_flip']=True
    attempt={'number':args.attempt,'formal':True,'started_at':datetime.now(timezone.utc).isoformat(),
             'scope':'step4B UI subcheck: restore real temporal execution; one editable short measurement compile',
             'expected_short_gates':short,'expected_short_physical_status':'completed',
             'expected_short_logical_ghz2':False,'expected_short_measurement_protocol_complete':False,
             'expected_short_true_bit':0,'expected_short_reported_bit':1,'expected_reset_Z':1,
             'unexpected_failure_action':'persist evidence; UI/test faults may be fixed; report physical uncertainty or framework changes'}
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
            assert restored['input']['compiler']=='qec_temporal'
            assert len(restored['input']['gates'])==recording['summary']['metrics']['completed_gate_count']
            assert len(restored['qec_result']['reported_measurement_results'])==80
            assert len(restored['qec_result']['true_measurement_results'])==80
            assert restored['qec_result']['history_complete'] is True and restored['qec_result']['history_supported'] is True
            assert restored['qec_result']['verified_logical_ghz2'] is True
            assert restored['qec_result']['measurement_protocol_complete'] is True
            assert restored['provenance']['kind']=='saved_execution'
            assert restored['provenance']['compiler_free_replay']=='PASS'
            assert '未发起新编译' in page.locator('#saved-provenance').inner_text()
            assert not any(r['method']=='POST' and r['url'].endswith('/api/compile') for r in requests)
            assert not page.locator('#auto').is_checked()
            page.locator('#saved-provenance').screenshot(path=str(output/'saved-result-provenance.png'))
            page.locator('#qec-result').screenshot(path=str(output/'saved-qec-result.png'))
            page.locator('#viewer #mode').select_option('physical')
            noisy=next(o for o in recording['operations'] if any(o.get('readout_flips',{}).values()))
            flipped=[g for g,value in noisy['readout_flips'].items() if value]
            assert len(flipped)==1
            flip_id=flipped[0]
            assert noisy['measurement_results'][flip_id]!=noisy['measurement_true_results'][flip_id]
            def seek(t):
                page.locator('#viewer #slider').evaluate("(el,t)=>{el.value=t;el.dispatchEvent(new Event('input',{bubbles:true}))}",t)
            seek((noisy['start']+noisy['end'])/2)
            assert flip_id not in page.evaluate('acceptanceViewer.debug.current.f.measurement_results')
            assert flip_id+': 投影' not in page.locator('#viewer #measurement-readout').inner_text()
            page.locator('#viewer').screenshot(path=str(output/'measurement-before-commit.png'))
            seek(noisy['end'])
            assert page.evaluate('acceptanceViewer.debug.current.f.measurement_results')[flip_id]==noisy['measurement_results'][flip_id]
            assert flip_id+': 投影' in page.locator('#viewer #measurement-readout').inner_text()
            assert '（报告翻转）' in page.locator('#viewer #measurement-readout').inner_text()
            page.locator('#viewer').screenshot(path=str(output/'measurement-after-commit.png'))
            assert '80 位报告' in page.locator('#qec-syndromes').inner_text()
            assert '真实投影位' in page.locator('#qec-syndromes').inner_text()
            assert page.locator('#qec-fault').is_disabled()
            playback=[]
            for mode in ('physical','keyframe'):
                page.locator('#viewer #mode').select_option(mode)
                page.locator('#viewer #speed').select_option('32')
                page.locator('#viewer #reset').click();page.locator('#viewer #play').click()
                stamp=time.monotonic();previous=0
                while time.monotonic()-stamp<300:
                    page.wait_for_timeout(1000);state=page.evaluate('acceptanceViewer.getStatus()')
                    assert state['time_us']>=previous
                    if state['playing']:assert state['time_us']>previous,'playback stalled'
                    previous=state['time_us']
                    if not state['playing']:break
                assert not state['playing'] and abs(state['time_us']-duration)<1e-7
                final_atoms=page.evaluate('acceptanceViewer.debug.current.atoms')
                initial_atoms=recording['frames'][0]['atom_updates']
                assert len(final_atoms)==34
                assert {a['id']:(a['holder'],a['position']) for a in final_atoms}=={a['id']:(a['holder'],a['position']) for a in initial_atoms}
                page.locator('#viewer').screenshot(path=str(output/f'saved-terminal-{mode}.png'))
                playback.append({'mode':mode,'speed':32,'finished':True,'wall_seconds':time.monotonic()-stamp})
                print(json.dumps(playback[-1]),flush=True)
            # The only new physical experiment: actual UI editing of six Clifford/readout gates.
            page.locator('#clear').click()
            for gate in short:
                page.locator('[data-tool="'+gate['gate_type']+'"]').click()
                for q in gate['qubit_ids']:
                    page.locator(f'[data-q="{int(q[1:])}"][data-column="{gate["column"]}"]').click()
            page.locator('[data-q="18"][data-column="4"]').click()
            page.locator('#edit-readout-flip').check();page.locator('#apply-gate').click()
            page.screenshot(path=str(output/'short-edited-input.png'),full_page=True)
            with page.expect_response(lambda r:r.url.endswith('/api/compile') and r.request.method=='POST') as response:
                page.locator('#compile').click()
            job=response.value.json()['id'];submitted=response.value.request.post_data_json
            write('short-submitted-input.json',submitted);write('short-job.json',{'job_id':job,'url':args.base+'/?job='+job})
            assert submitted['compiler']=='qec_temporal' and submitted['gates']==short
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
            short_measure=next(o for o in result['recording']['operations'] if o['kind']=='measurement')
            assert short_measure['measurement_true_results']['G004']==0
            assert short_measure['measurement_results']['G004']==1
            assert short_measure['readout_flips']['G004'] is True
            from neutral_atom_env.simulation.state import SimulationState
            short_final=SimulationState.restore((short_out/'checkpoint.json').read_text(encoding='utf-8'))
            assert short_final.quantum_state.expectation({'Q018':'Z'})==1
            assert not short_final.atoms['Q018'].measured
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
            assert {a['id']:(a['holder'],a['position']) for a in final}=={a['id']:(a['holder'],a['position']) for a in result['recording']['frames'][0]['atom_updates']}
            page.locator('#viewer').screenshot(path=str(output/'short-actual-terminal.png'))
            assert not errors,errors
            browser.close()
        report={'status':'passed','saved_job_id':args.saved_job,'saved_execution_recompiled':False,
            'saved_actual_strategy':'qec_temporal','saved_duration_us':duration,
            'reported_count':80,'true_count':80,'flipped_measurement':flip_id,'no_precommit_readout':True,
            'history_supported':True,'full_playback':playback,'short_true_bit':0,'short_reported_bit':1,'short_reset_Z':1,
            'short_job_id':job,'short_gates':6,'short_effects_exactly_once':effects,'short_actual_compiler':'qec_temporal',
            'short_expected_non_GHZ':True,'short_physical_status':'completed','short_duration_us':result['recording']['duration'],
            'page_errors':errors,'finished_at':datetime.now(timezone.utc).isoformat()}
        source_after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_files}
        write('source-stability.json',{'changed_during_run':source_before!=source_after,'files':source_before})
        assert source_before==source_after,'Source changed during formal UI subcheck'
        write('browser-acceptance.json',report);print(json.dumps(report),flush=True)
    except Exception as error:
        write('failure.json',{'status':'failed','attempt':args.attempt,'phase':'formal_ui_subcheck','type':type(error).__name__,
            'message':str(error),'traceback':traceback.format_exc(),'page_errors':errors,'action':'Classify ordinary UI/test faults versus physical/framework uncertainty before follow-up',
            'finished_at':datetime.now(timezone.utc).isoformat()})
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',default='http://127.0.0.1:8786')
    p.add_argument('--saved-job',required=True)
    p.add_argument('--attempt',type=int,default=1)
    p.add_argument('--output',default='artifacts/qec-roadmap/step4b-ui-attempt1')
    p.add_argument('--server-output',default='artifacts/workbench-qec-temporal')
    main(p.parse_args())
