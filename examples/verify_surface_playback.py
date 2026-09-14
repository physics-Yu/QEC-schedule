"""Full-duration real browser playback of the delivered large recording."""
import json
from pathlib import Path
import time
from playwright.sync_api import sync_playwright

output=Path('artifacts/surface-ghz');errors=[];checks=[]
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1100})
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://127.0.0.1:8780/')
    page.screenshot(path=str(output/'report.png'),full_page=True)
    assert page.locator('img[alt="36物理比特完整194门线路"]').is_visible()
    assert page.locator('a.primary').get_attribute('href').startswith('http://127.0.0.1:8769/?job=')
    page.goto('http://127.0.0.1:8780/row_greedy/index.html')
    for mode in ('keyframe','physical'):
        page.locator('#mode').select_option(mode);page.locator('#speed').select_option('32')
        page.locator('#reset').click();page.locator('#play').click()
        started=time.monotonic();previous=0.;samples=0;last_print=started
        while time.monotonic()-started<100:
            page.wait_for_timeout(1000)
            status=page.evaluate('viewer.getStatus()');now=status['time_us']
            assert now>=previous,'Playback moved backwards'
            if status['playing']:assert now>previous,'Playback stalled between actual frames'
            previous=now;samples+=1
            if time.monotonic()-last_print>10:
                print(json.dumps({'mode':mode,'elapsed_s':round(time.monotonic()-started,2),'time_us':now}),flush=True)
                last_print=time.monotonic()
            if not status['playing']:break
        expected=json.loads((output/'row_greedy'/'recording.json').read_text(encoding='utf-8'))['duration']
        assert not status['playing'] and abs(status['time_us']-expected)<1e-8,status
        checks.append({'mode':mode,'speed':32,'wall_seconds':round(time.monotonic()-started,2),
                       'samples':samples,'final_simulation_us':status['time_us'],'completed_without_stall':True})
    assert not errors,errors
    browser.close()
report={'browser':'real headless Edge','full_recording_playback':checks,'page_errors':errors}
(output/'full-playback-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report),flush=True)
