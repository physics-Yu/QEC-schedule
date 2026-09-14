"""Real-browser configuration isolation, explicit compilation and saved QEC UI checks."""
import argparse
import json
import time
import traceback
from pathlib import Path
from playwright.sync_api import sync_playwright


def main(args):
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    evidence={'scope':'UI/configuration contracts + small actual physical compiles; saved full QEC is not recompiled',
              'checks':[], 'page_errors':[], 'compile_requests':[]}
    def check(name,condition=True):
        assert condition,name
        evidence['checks'].append(name)
        print('PASS '+name,flush=True)
    def write(name,value):
        (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
            page=browser.new_page(viewport={'width':1440,'height':1000})
            page.on('pageerror',lambda e:evidence['page_errors'].append(str(e)))
            page.on('request',lambda r:evidence['compile_requests'].append(r.post_data_json) if r.url.endswith('/api/compile') else None)
            page.add_init_script("""let library;Object.defineProperty(window,'NeutralAtomViewer',{
              configurable:true,get(){return library},set(lib){library=lib;const mount=lib.mount;
              lib.mount=function(...args){const v=mount.apply(this,args);window.acceptanceViewer=v;return v;}}});""")
            def exported():
                with page.expect_download() as d:page.click('#export-input')
                return json.loads(Path(d.value.path()).read_text(encoding='utf-8'))
            def template(name):
                page.locator('.template-library').evaluate('(e)=>e.open=true')
                page.select_option('#preset',name)
                page.wait_for_timeout(400)
            def import_workspace(value):
                page.locator('#import-file').set_input_files({'name':'edited-circuit.json','mimeType':'application/json','buffer':json.dumps(value).encode()})
                page.wait_for_function("document.getElementById('import-file').value === ''")
                check('workspace import accepted',not page.locator('#toast').inner_text())
            def compile_result():
                with page.expect_response(lambda r:r.url.endswith('/api/compile') and r.request.method=='POST') as response:
                    page.click('#compile')
                started=response.value.json();job=started['id']
                page.wait_for_function("['complete','completed','failed','stalled'].includes(document.getElementById('compile-state').dataset.state)",timeout=180000)
                result=page.request.get(args.base+'/api/jobs/'+job+'/result').json()
                check('explicit physical compile completed',result['status']=='completed')
                return job,result
            page.goto(args.base+'/')
            page.locator('#viewer canvas').wait_for()
            page.wait_for_timeout(900)
            check('automatic compilation removed',page.locator('#auto').count()==0 and not evidence['compile_requests'])
            check('compile action belongs to editor',page.locator('#circuit-editor #compile').count()==1)
            check('AOD capacity has no redundant input',page.locator('#aod-traps').count()==0)
            template('parallel1q');original=exported()
            page.click('#tab-config');page.select_option('#compiler','baseline');page.click('#return-circuit')
            baseline=exported()
            check('strategy changes preserve circuit and initial layout',baseline['gates']==original['gates'] and baseline['layout']==original['layout'] and baseline['circuit_profile']==original['circuit_profile'])
            page.click('#tab-config');page.select_option('#compiler','recommended')
            page.fill('#compile-timeout','120');page.locator('#compile-timeout').press('Tab')
            page.fill('#compilation-name','Reusable search');page.click('#compilation-save')
            page.fill('#aod-rows','2');page.locator('#aod-rows').press('Tab')
            page.fill('#aod-columns','2');page.locator('#aod-columns').press('Tab')
            page.fill('#aod-column-offsets','0, 20');page.locator('#aod-column-offsets').press('Tab')
            page.fill('#platform-name','Two by two');page.click('#platform-save')
            check('capacity derives from shape','2 × 2 = 4' in page.locator('#aod-capacity').inner_text())
            with page.expect_download() as download:page.click('#platform-export')
            platform_json=Path(download.value.path()).read_bytes()
            check('platform file excludes circuit and compiler',set(json.loads(platform_json)['config']) <= {'aod_rows','aod_columns','aod_row_offsets_um','aod_column_offsets_um','ez_neighbor_guard_enabled','ez_policy'})
            page.click('#return-circuit');before_template=exported();template('mixed');after_template=exported()
            check('template load preserves independent compilation',before_template['compilation']==after_template['compilation'])
            page.click('#tab-config');page.select_option('#platform-saved','Two by two');page.click('#platform-load')
            page.wait_for_function("document.getElementById('aod-rows').value==='2'")
            page.click('#return-circuit');after_platform=exported()
            check('platform load preserves edited circuit and compiler',after_platform['gates']==after_template['gates'] and after_platform['compilation']==after_template['compilation'])
            page.click('#tab-config');page.select_option('#compiler','baseline');page.select_option('#compilation-saved','Reusable search');page.click('#compilation-load')
            page.wait_for_function("document.getElementById('compiler').value==='recommended'")
            page.locator('#platform-file').set_input_files({'name':'platform.json','mimeType':'application/json','buffer':platform_json})
            page.wait_for_function("document.getElementById('platform-file').value === ''")
            page.screenshot(path=str(output/'configuration-management.png'),full_page=True)
            page.click('#return-circuit');saved_config=exported()
            check('standalone configuration roundtrip',saved_config['aod_columns']==2 and saved_config['aod_rows']==2 and saved_config['aod_column_offsets_um']==[0,20] and saved_config['compilation']['compile_timeout_s']==120)
            page.wait_for_timeout(900)
            check('all edits and configuration loads remain manual',not evidence['compile_requests'])
            template('parallel1q');ordinary_job,ordinary=compile_result()
            check('same-type four H actually parallel',ordinary['recording']['summary']['metrics']['completed_gate_count']==4 and ordinary['recording']['duration']==1)
            write('ordinary-result-summary.json',{'job':ordinary_job,'input':ordinary['input'],'duration':ordinary['recording']['duration'],'metrics':ordinary['recording']['summary']['metrics']})
            page.screenshot(path=str(output/'ordinary-compiled.png'),full_page=True)
            check('no horizontal overflow on desktop',page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            page.goto(args.base+'/?job='+args.saved_job)
            page.wait_for_function("!document.getElementById('export-replay').disabled",timeout=60000)
            saved=exported()
            check('saved full circuit remains editable',len(saved['gates'])==1868 and saved['atom_count']==68)
            check('saved result did not compile',len(evidence['compile_requests'])==1)
            check('full prefix/suffix timing remains explicit','后缀续编译' in page.locator('#greedy-summary').inner_text())
            page.locator('#qec-result').evaluate('(e)=>e.open=true')
            check('saved quantum results retained','PASS' in page.locator('#qec-result-status').inner_text())
            page.locator('#qec-result').evaluate('(e)=>e.open=false')
            page.screenshot(path=str(output/'saved-full-workspace.png'),full_page=True)
            page.locator('#viewer').screenshot(path=str(output/'saved-full-viewer.png'))
            page.click('#tab-config');check('temporal baseline explicitly unsupported',page.locator('#compiler option[value=baseline]').evaluate('(e)=>e.disabled'))
            page.click('#return-circuit')
            short=[{'id':f'G{i:03d}','gate_type':kind,'qubit_ids':qs,'parameters':[],'column':i,'condition':[],'depends_on':[]}
                   for i,(kind,qs) in enumerate((('H',['Q000']),('CZ',['Q000','Q009']),('H',['Q009']),('CZ',['Q000','Q009']),('MEASURE',['Q036']),('RESET',['Q036'])))]
            short[4]['readout_flip']=True
            saved['gates']=short;saved['compilation']['compile_timeout_s']=120
            import_workspace(saved)
            check('short arbitrary edit preserved',exported()['gates']==short)
            qec_job,qec=compile_result()
            result=qec['qec_result']
            check('short actual QEC executes all six edits',qec['recording']['summary']['metrics']['completed_gate_count']==6 and qec['recording']['duration']==4006.6)
            check('actual measurement/report/reset semantics retained',result['true_measurement_results']['G004']==0 and result['reported_measurement_results']['G004']==1)
            check('short edit is not mislabelled full GHZ',result['verified_logical_ghz4'] is False and result['measurement_protocol_complete'] is False)
            write('short-qec-summary.json',{'job':qec_job,'input':qec['input'],'duration':qec['recording']['duration'],'qec_result':result})
            page.screenshot(path=str(output/'short-edited-compiled.png'),full_page=True)
            page.set_viewport_size({'width':720,'height':900});page.screenshot(path=str(output/'narrow-workspace.png'),full_page=True)
            check('no horizontal overflow at 720px',page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
            check('no browser errors',not evidence['page_errors'])
            # Leave the delivered link pointing at the saved complete execution.
            evidence.update(status='PASS',saved_job=args.saved_job,ordinary_job=ordinary_job,short_qec_job=qec_job)
            browser.close()
    except Exception:
        evidence.update(status='FAIL',failure=traceback.format_exc())
        raise
    finally:
        write('browser-acceptance.json',evidence)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--base',default='http://127.0.0.1:8788')
    parser.add_argument('--saved-job',default='87eef4dc58e467e0e6b423bfda158c43')
    parser.add_argument('--output',default='artifacts/workbench-cleanup/acceptance-attempt1')
    main(parser.parse_args())
