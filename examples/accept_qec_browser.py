"""Real Edge QEC edit -> physical compile -> actual result and 32x playback."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time

from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]


def main(args):
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    def write(name,value):
        (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    def hashes():
        return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted((ROOT/'src').rglob('*')) if p.suffix in {'.py','.js','.html'}}
    before=hashes();write('source-at-start.json',before)
    errors=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
        page=browser.new_page(viewport={'width':1700,'height':1200})
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.add_init_script("""let library;Object.defineProperty(window,'NeutralAtomViewer',{
          configurable:true,get(){return library},set(lib){library=lib;const mount=lib.mount;
          lib.mount=function(...args){const v=mount.apply(this,args);window.acceptanceViewer=v;return v;}}});""")
        if args.job_id:
            job_id=args.job_id
            page.goto(args.base+'/?job='+job_id)
        else:
            page.goto(args.base+'/?example=surface-qec-ghz2')
            page.wait_for_function("document.getElementById('qec-enabled').checked&&!document.getElementById('compile').disabled")
            assert not page.locator('#auto').is_checked()
            assert page.locator('#atom-count').input_value()=='34'
            assert page.locator('[data-tool="MEASURE"]').count()==1
            assert page.locator('[data-tool="RESET"]').count()==1
            assert page.locator('[data-tool="T"]').count()==0
            assert page.locator('.wire-label').filter(has_text='ancilla').count()==16
            page.locator('#seed').fill('7');page.locator('#seed').dispatch_event('change')
            page.locator('#qec-fault-target').select_option('Q000')
            page.locator('#qec-fault').select_option('Y')
            page.locator('#column-jump').fill('201');page.locator('#column-jump').dispatch_event('change')
            page.locator('[data-tool="H"]').click();page.locator('[data-q="0"][data-column="200"]').click()
            page.locator('#undo').click()
            page.locator('#column-jump').fill('1');page.locator('#column-jump').dispatch_event('change')
            page.screenshot(path=str(output/'edited-input.png'),full_page=True)
            with page.expect_response(lambda r:r.url.endswith('/api/compile') and r.request.method=='POST') as response:
                page.locator('#compile').click()
            job_id=response.value.json()['id'];submitted=response.value.request.post_data_json
            write('submitted-input.json',submitted)
            assert submitted['seed']==7
            assert submitted['qec_fault']=={'pauli':'Y','qubit_id':'Q000'}
            fault=next(g for g in submitted['gates'] if g['id']=='QEC_FAULT')
            assert fault['gate_type']=='Y' and fault['qubit_ids']==['Q000']
            assert not any(g['column']==200 for g in submitted['gates'])
            write('job.json',{'job_id':job_id,'url':args.base+'/?job='+job_id})
            print('JOB '+job_id,flush=True)
        stamp=time.monotonic();last=None
        while time.monotonic()-stamp<3700:
            status=page.request.get(args.base+'/api/jobs/'+job_id).json()
            done=status.get('progress',{}).get('completed_gates',0)
            if done!=last:print(json.dumps(status),flush=True);last=done
            if status['status']!='compiling':break
            page.wait_for_timeout(1000)
        write('job-final-status.json',status)
        assert status['status']=='completed',status
        result=page.request.get(args.base+'/api/jobs/'+job_id+'/result').json()
        for source in (Path(args.server_output)/job_id).iterdir():
            if source.is_file():shutil.copy2(source,output/source.name)
        qec=result['qec_result'];recording=result['recording'];gates=result['input']['gates']
        assert qec['verified_logical_ghz2'] and qec['measurement_protocol_complete'],qec
        assert qec['logical_xx']==qec['logical_zz']==1 and len(qec['syndrome_bits'])==32
        assert qec['corrections']
        events=[json.loads(line) for line in (output/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
        effects=[gid for e in events if e.get('effect_completed') for gid in (e.get('effect_gate_ids') or e.get('gate_ids') or [e['gate_id']])]
        assert len(effects)==len(gates) and set(effects)=={g['id'] for g in gates}
        page.wait_for_function("!document.getElementById('export-replay').disabled",timeout=120000)
        assert 'PASS' in page.locator('#qec-result-status').inner_text()
        assert '完整' in page.locator('#qec-result-status').inner_text()
        assert len(page.locator('#qec-syndromes .tag').all())==32
        page.locator('#qec-result').screenshot(path=str(output/'qec-result.png'))
        page.locator('#viewer #mode').select_option('physical')
        measurements=[o for o in recording['operations'] if o['kind']=='measurement']
        resets=[o for o in recording['operations'] if o['kind']=='reset']
        skipped=[o for o in recording['operations'] if o.get('applied') is False]
        assert measurements and resets and skipped
        def seek(t):
            page.locator('#viewer #slider').evaluate("(el,t)=>{el.value=t;el.dispatchEvent(new Event('input',{bubbles:true}))}",t)
        first=measurements[0];seek((first['start']+first['end'])/2)
        live=page.evaluate('acceptanceViewer.debug.current.f.measurement_results')
        assert not set(first['gate_ids'])&set(live)
        assert '测量' in page.locator('#viewer #operation-caption').inner_text()
        page.locator('#viewer').screenshot(path=str(output/'measurement-running.png'))
        seek(first['end'])
        live=page.evaluate('acceptanceViewer.debug.current.f.measurement_results')
        assert all(live[g]==qec['syndrome_bits'][g] for g in first['gate_ids'])
        false=skipped[0];seek((false['start']+false['end'])/2)
        assert '未施加激光' in page.locator('#viewer #operation-caption').inner_text()
        assert false['category']=='control'
        page.locator('#viewer').screenshot(path=str(output/'condition-not-fired.png'))
        playback=[]
        for mode in ('physical','keyframe'):
            page.locator('#viewer #mode').select_option(mode)
            page.locator('#viewer #speed').select_option('32')
            page.locator('#viewer #reset').click();page.locator('#viewer #play').click()
            start=time.monotonic();previous=0;count=0
            while time.monotonic()-start<300:
                page.wait_for_timeout(1000);current=page.evaluate('acceptanceViewer.getStatus()')
                assert current['time_us']>=previous
                if current['playing']:assert current['time_us']>previous,'playback stalled'
                previous=current['time_us'];count+=1
                if not current['playing']:break
            assert not current['playing'] and abs(current['time_us']-recording['duration'])<1e-7
            atoms=page.evaluate('acceptanceViewer.debug.current.atoms')
            assert len(atoms)==34 and all(a['holder']['holder_type']=='static' for a in atoms)
            page.locator('#viewer').screenshot(path=str(output/f'terminal-{mode}.png'))
            playback.append({'mode':mode,'speed':32,'wall_seconds':time.monotonic()-start,'samples':count,'finished':True})
            print(json.dumps(playback[-1]),flush=True)
        assert not errors,errors
        browser.close()
    write('source-stability.json',{'changed_during_run':before!=hashes()})
    report={'status':'passed','browser':'real headless Microsoft Edge via Playwright','job_id':job_id,
      'resumed_viewer_only':bool(args.job_id),'real_edit_and_compile':not args.job_id,'gates':len(gates),
      'seed':7,'fault':{'pauli':'Y','qubit_id':'Q000'},'measurement_bits':32,
      'corrections_applied':len(qec['corrections']),'logical_xx':1,'logical_zz':1,
      'measurement_protocol_complete':True,'effect_count_exactly_once':len(effects),
      'readout_hidden_until_commit':True,'conditional_false_has_no_light':True,
      'duration_us':recording['duration'],'playback':playback,'page_errors':errors}
    write('browser-acceptance.json',report);print(json.dumps(report),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base',default='http://127.0.0.1:8781')
    p.add_argument('--output',default='artifacts/surface-qec-ghz2/browser')
    p.add_argument('--server-output',default='artifacts/workbench-surface-qec')
    p.add_argument('--job-id');main(p.parse_args())
