"""Verify built-in presets operate on independent compilation configuration."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE='http://127.0.0.1:8788'
OUT=Path('artifacts/workbench-presets');OUT.mkdir(parents=True,exist_ok=True)
report={'checks':[],'errors':[],'compile_requests':[]}
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1000})
    page.on('pageerror',lambda e:report['errors'].append(str(e)))
    page.on('request',lambda r:report['compile_requests'].append(r.post_data_json) if r.url.endswith('/api/compile') else None)
    def check(name,passed):
        assert passed,name
        report['checks'].append(name)
    def exported():
        page.click('#tab-circuit')
        with page.expect_download() as d:page.click('#export-input')
        return json.loads(Path(d.value.path()).read_text(encoding='utf8'))
    def select(preset):
        page.click('#tab-config');page.select_option('#compiler','preset:'+preset)
        value=exported()
        valid=page.request.post(BASE+'/api/preview',data=value)
        assert valid.ok,valid.text()
        check('dispatch '+preset,valid.json()['input']['compiler']==preset)
        return value
    try:
        page.goto(BASE+'/');page.locator('#viewer canvas').wait_for()
        original=exported()
        page.click('#tab-config');page.fill('#compile-timeout','123');page.locator('#compile-timeout').press('Tab')
        for preset in ['greedy','critical_path','lookahead','basic']:
            value=select(preset)
            check(preset+' keeps circuit and initial state',all(value[k]==original[k] for k in ['gates','layout','atom_count','seed','circuit_profile']))
            check(preset+' keeps wall time',value['compilation']['compile_timeout_s']==123)
        value=select('lookahead');check('lookahead defaults',all(value['compilation'][k]==v for k,v in {'lookahead_depth':2,'beam_width':3,'rollout_budget':12}.items()))
        page.click('#tab-config');page.screenshot(path=str(OUT/'physical-presets.png'),full_page=True)
        check('nine visible named strategies',page.locator('#compiler option[value^="preset:"]').count()==9)
        page.click('#tab-circuit');page.locator('.template-library').evaluate('(e)=>e.open=true');page.click('#surface-ghz')
        page.wait_for_function("document.getElementById('atom-count').value==='36'")
        patch=exported()
        for preset in ['patch_greedy','patch_symmetric']:
            value=select(preset);check(preset+' keeps patch circuit',value['gates']==patch['gates'] and value['layout']==patch['layout'])
        page.goto(BASE+'/?example=surface-qec-ghz2');page.wait_for_function("document.getElementById('atom-count').value==='34'")
        qec=exported()
        for preset in ['qec_joint','qec_persistent','qec_ghz2']:
            value=select(preset);check(preset+' keeps QEC semantics',all(value[k]==qec[k] for k in ['gates','qec_protocol','qec_enabled','layout','circuit_profile']))
        page.goto(BASE+'/?example=surface-qec-temporal-four');page.wait_for_function("document.getElementById('atom-count').value==='68'")
        page.click('#tab-config')
        check('temporal cannot bypass guarded compiler',page.locator('#compiler option[value^="preset:"]').evaluate_all('(items)=>items.every(e=>e.disabled)'))
        check('temporal recommendation named', '多轮 QEC 联合优化' in page.locator('#compiler option[value=recommended]').inner_text())
        page.screenshot(path=str(OUT/'temporal-presets.png'),full_page=True)
        check('no automatic compiles',not report['compile_requests'])
        page.goto(BASE+'/');page.locator('#viewer canvas').wait_for()
        page.locator('.template-library').evaluate('(e)=>e.open=true');page.select_option('#preset','parallel1q')
        select('lookahead');page.click('#tab-circuit')
        with page.expect_response(lambda r:r.url.endswith('/api/compile')) as response:page.click('#compile')
        job=response.value.json()['id']
        page.wait_for_function("document.getElementById('compile-state').dataset.state==='completed'",timeout=30000)
        result=page.request.get(BASE+'/api/jobs/'+job+'/result').json()
        check('explicit lookahead physically executes four H',result['run_options']['strategy']=='lookahead' and result['recording']['duration']==1 and result['recording']['summary']['metrics']['completed_gate_count']==4)
        check('browser error free',not report['errors'])
        report.update(status='PASS',job=job)
    except Exception as error:
        report.update(status='FAIL',failure=str(error));raise
    finally:
        (OUT/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        browser.close()
