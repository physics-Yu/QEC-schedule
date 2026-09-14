"""Play the exported animation from beginning to end in a real browser."""
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

OUT=Path('artifacts/deliveries/ghz4-animation')
check={'status':'running','errors':[]}
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
    page=browser.new_page(viewport={'width':1440,'height':1000})
    page.on('pageerror',lambda e:check['errors'].append(str(e)))
    try:
        page.goto('http://127.0.0.1:8789/animation.html',timeout=60000)
        page.locator('#animation #play').wait_for()
        assert page.locator('#animation #speed').input_value()=='32'
        assert not page.locator('#animation #play').is_disabled()
        initial=page.evaluate('deliveryViewer.debug.sample(0).atoms.map(a=>({id:a.id,holder:a.holder,position:a.position}))')
        page.screenshot(path=str(OUT/'ready-to-play.png'),full_page=True)
        page.click('#animation #play');start=time.monotonic();last=-1
        while True:
            page.wait_for_timeout(1000)
            state=page.evaluate('deliveryViewer.getStatus()')
            assert state['time_us']>last,'Animation stopped advancing'
            last=state['time_us']
            elapsed=time.monotonic()-start
            if int(elapsed)%30==0:print(f'Playing: {elapsed:.0f}s, physical {last:.2f} us',flush=True)
            if not state['playing']:break
            assert elapsed<180,'Playback exceeded its expected duration'
        final=page.evaluate('deliveryViewer.debug.current.atoms.map(a=>({id:a.id,holder:a.holder,position:a.position}))')
        assert final==initial and len(final)==68
        duration=page.evaluate('deliveryViewer.debug.data.duration')
        assert last==duration and abs(duration-105285.6)<1e-7
        assert page.evaluate('deliveryViewer.debug.data.summary.metrics.completed_gate_count')==1868
        assert not check['errors']
        page.screenshot(path=str(OUT/'completed-playback.png'),full_page=True)
        # The actual deliverable is also independently openable without its server.
        page.goto((OUT/'animation.html').resolve().as_uri(),timeout=60000)
        page.locator('#animation #play').wait_for()
        assert page.locator('#animation #speed').input_value()=='32'
        assert not check['errors']
        check.update(status='PASS',playback_seconds=elapsed,duration_us=duration,completed_slots=1868,
                     returned_atoms=68,exact_initial_holders_and_positions=True,offline_html_load='PASS')
        print(json.dumps(check),flush=True)
    except Exception as error:
        check.update(status='FAIL',failure=str(error));raise
    finally:
        (OUT/'playback-check.json').write_text(json.dumps(check,ensure_ascii=False,indent=2),encoding='utf8')
        browser.close()
