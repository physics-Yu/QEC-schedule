"""HTTP smoke test for the gallery and three demo services; no browser simulation."""
from pathlib import Path
from uuid import uuid4
import hashlib
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

root=Path(__file__).resolve().parents[1]
output=root/'artifacts/demo-http'/uuid4().hex;output.mkdir(parents=True,exist_ok=True)
checks=[]
with (output/'launcher.log').open('w',encoding='utf-8') as log:
    child=subprocess.Popen([sys.executable,'demo/launch.py','--port','0','--no-browser','--output',str(output/'runs')],cwd=root,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        session=output/'runs/session.json'
        until=time.monotonic()+30
        while not session.exists():
            if child.poll() is not None:raise RuntimeError('Launcher exited: '+(output/'launcher.log').read_text(encoding='utf-8'))
            if time.monotonic()>until:raise TimeoutError('launcher startup')
            time.sleep(.2)
        links=json.loads(session.read_text(encoding='utf-8'))
        def fetch(url):
            with urllib.request.urlopen(url,timeout=20) as response:
                assert response.status==200
                return response.read()
        for key in ('gallery','workbench','smt','qec'):
            assert b'<!doctype html' in fetch(links[key]).lower()
            checks.append(key+' homepage')
        js=fetch(links['gallery']+'launch-links.js').decode()
        assert links['qec'] in js
        checks.append('dynamic QEC link')
        assert links['parking'] == 'parking/index.html'
        parking = fetch(links['gallery'] + links['parking'])
        assert parking == (root/'demo/parking/index.html').read_bytes()
        assert b'ParkingTemplate' in parking and b'__ENGINE__' not in parking
        checks.append('standalone Parking Lab served unchanged, no parking compiler service')
        catalog=json.loads(fetch(links['qec']+'api/catalog'))
        spec=catalog['demos']['qec_ghz2']
        assert len(spec['gates'])==483 and spec['readout_policy']=={'mode':'adaptive','candidate_budget':16,'top_k':3}
        checks.append('QEC catalog, 483 slots, external readout defaults')
        assert hashlib.sha256(fetch(links['qec']+'assets/qec_editor.js')).digest()==hashlib.sha256((root/'src/neutral_atom_app/visualization/qec_editor.js').read_bytes()).digest()
        checks.append('editor asset')
        for strategy in ('ordered_greedy','smt_ordered'):
            path='qec/reference/'+strategy+'/animation.html'
            assert hashlib.sha256(fetch(links['gallery']+path)).digest()==hashlib.sha256((root/'demo'/path).read_bytes()).digest()
            checks.append(strategy+' complete animation HTTP/hash')
        request=urllib.request.Request(links['qec']+'api/compile',data=b'{"gates":[]}',headers={'Content-Type':'application/json'},method='POST')
        try:
            urllib.request.urlopen(request,timeout=20)
            raise AssertionError('invalid input accepted')
        except urllib.error.HTTPError as error:
            assert error.code==400 and json.loads(error.read())['error']
        checks.append('invalid circuit returns structured 400')
        (output/'acceptance.json').write_text(json.dumps({'status':'passed','checks':checks,'real_browser_test':False},indent=2),encoding='utf-8')
        print(json.dumps({'http_smoke':'passed','checks':checks}))
    finally:
        child.terminate()
        child.wait(timeout=15)
