"""Real Edge browser acceptance: edit, compile, replay, failure feedback."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT=Path('artifacts/smt-batch/ui-final');OUT.mkdir(parents=True,exist_ok=True)
report={'checks':[],'errors':[],'requests':[],'browser':'headless Microsoft Edge via Playwright'}
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1050})
    page.add_init_script("""window.__zoneLabels=new Set();const original=CanvasRenderingContext2D.prototype.fillText;
        CanvasRenderingContext2D.prototype.fillText=function(text,...args){if(/STORAGE|ENTANGLEMENT|MEASUREMENT/.test(text))window.__zoneLabels.add(text);return original.call(this,text,...args)}""")
    page.on('pageerror',lambda e:report['errors'].append(str(e)))
    page.on('request',lambda r:report['requests'].append(r.post_data_json) if r.url.endswith('/api/compile') else None)
    def check(name,ok=True):
        assert ok,name
        report['checks'].append(name)
    try:
        page.goto('http://127.0.0.1:8793/')
        page.locator('#metrics tr').first.wait_for()
        check('three strategies with saved results',page.locator('#metrics tr').count()==3)
        check('no auto compile',not report['requests'])
        page.screenshot(path=str(OUT/'editor.png'),full_page=True)
        page.locator('#results').scroll_into_view_if_needed()
        page.screenshot(path=str(OUT/'comparison.png'))
        for strategy in ('greedy','smt_single','smt_multi'):
            page.click(f'[data-strategy="{strategy}"]')
            frame=page.frame_locator('#animation')
            frame.locator('#play').wait_for()
            check(strategy+' canvas uses actual EZ type',frame.locator('canvas').first.evaluate("()=>[...window.__zoneLabels].some(s=>s.includes('ENTANGLEMENT')) && ![...window.__zoneLabels].some(s=>s.includes('STORAGE'))"))
            frame.locator('#speed').select_option('32')
            frame.locator('#reset').click()
            frame.locator('#play').click()
            page.wait_for_timeout(350)
            check(strategy+' animation progresses',float(frame.locator('#slider').input_value())>0)
            from playwright.sync_api import expect
            expect(frame.locator('#playback-status')).to_contain_text('已到终点',timeout=15000)
            check(strategy+' complete playback reaches end at 32x')
            check(strategy+' end button disabled at actual end',frame.locator('#end').is_disabled())
            check(strategy+' terminal reachable',float(frame.locator('#slider').input_value())==float(frame.locator('#slider').get_attribute('max')))
        check('three original animations play at 32x')
        page.select_option('#demo','parallel');page.click('#load')
        page.select_option('#gateType','X');page.fill('#qa','0');page.click('#add')
        check('gate edit accepted',page.locator('#gates button').count()==13)
        check('editing does not compile',not report['requests'])
        page.click('#compile')
        page.wait_for_function("document.getElementById('status').textContent.includes('三策略编译完成')",timeout=180000)
        check('edited circuit compiled through all strategies',page.locator('#metrics .good').count()==3)
        check('submitted edited gate',report['requests'][-1]['gates'][-1]=={'type':'X','qubits':[0]})
        report['edited_job_base']=page.evaluate('currentBase')
        frame=page.frame_locator('#animation');frame.locator('#play').wait_for();frame.locator('#end').click()
        page.locator('#animation').scroll_into_view_if_needed();page.screenshot(path=str(OUT/'edited-replay.png'))
        # Invalid input feedback is exercised without changing physics.
        page.locator('summary').first.click();page.fill('#rows','0');page.click('#compile')
        page.locator('#failure[open]').wait_for()
        check('invalid configuration produces visible failure dialog','AOD' in page.locator('#failureText').inner_text())
        page.screenshot(path=str(OUT/'failure-input.png'));page.click('#closeFailure')
        page.fill('#rows','2')
        # Force an actual solver UNKNOWN by a 1 ms solver budget.
        page.select_option('#demo','dependency');page.click('#load')
        page.fill('#solver','1');page.click('#compile')
        page.locator('#failure[open]').wait_for(timeout=180000)
        check('solver failure shown, not success','SMT_NO_VALIDATED_PROGRAM' in page.locator('#failureText').inner_text())
        report['failure_job_base']=page.evaluate('currentBase')
        report['failure_text']=page.locator('#failureText').inner_text()
        page.screenshot(path=str(OUT/'failure-solver.png'));page.click('#closeFailure')
        page.select_option('#demo','closure');page.click('#load')
        page.set_viewport_size({'width':720,'height':1000})
        check('responsive page has no horizontal overflow',page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
        page.screenshot(path=str(OUT/'mobile.png'),full_page=True)
        check('no browser script errors',not report['errors'])
        report['status']='passed'
    except Exception as e:
        report['status']='failed';report['failure']=str(e)
        page.screenshot(path=str(OUT/'failure-test.png'),full_page=True)
        raise
    finally:
        (OUT/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        browser.close()
print(json.dumps(report,ensure_ascii=False))
