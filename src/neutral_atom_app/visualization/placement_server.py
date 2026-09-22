"""Loopback-only manual compilation workbench for free initial placement."""
from concurrent.futures import ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit
from uuid import uuid4
import json
from neutral_atom_app.placement_workbench import build_problem,default_input,compare
from neutral_atom_env.visualization.viewer import write_bundle


def serve(output,port=0):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True);write_bundle(output)
    jobs={};lock=Lock();pool=ThreadPoolExecutor(max_workers=1)
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self,*args,**kwargs):super().__init__(*args,directory=str(output),**kwargs)
        def reply(self,value,status=200):
            body=json.dumps(value,ensure_ascii=False).encode('utf-8');self.send_response(status)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
        def do_GET(self):
            path=urlsplit(self.path).path
            if path in ('/','/placement.js'):
                target=Path(__file__).with_name('placement.html' if path=='/' else 'placement.js')
                body=target.read_bytes();self.send_response(200)
                self.send_header('Content-Type',('text/html' if path=='/' else 'application/javascript')+'; charset=utf-8')
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            elif path=='/api/info':
                self.reply(dict(defaults=default_input(),available=[p.parent.name for p in output.glob('*/comparison.json')]))
            elif path.startswith('/api/jobs/'):
                with lock:
                    job=jobs.get(path.rsplit('/',1)[-1]);self.reply(dict(job) if job else dict(error='Unknown job'),200 if job else 404)
            else:super().do_GET()
        def do_POST(self):
            if urlsplit(self.path).path!='/api/compile':return self.reply(dict(error='Unknown endpoint'),404)
            origin=self.headers.get('Origin')
            if origin and origin!='http://'+self.headers.get('Host',''):return self.reply(dict(error='Origin mismatch'),403)
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=262144:raise ValueError('Invalid input size')
                raw=json.loads(self.rfile.read(length));build_problem(raw)
                with lock:
                    if any(j['status']=='running' for j in jobs.values()):return self.reply(dict(error='已有对照正在编译，请等待完成。'),409)
                    key=uuid4().hex;jobs[key]=dict(id=key,status='running',progress='编译顺序基线…')
                def progress(p):
                    with lock:jobs[key]['progress']=p
                def work():
                    try:
                        r=compare(raw,output/key,progress)
                        with lock:jobs[key].update(status=r['status'],progress='完成',error=None if r['status']=='completed' else json.dumps(r['trials'],ensure_ascii=False))
                    except Exception as e:
                        folder=output/key;folder.mkdir(parents=True,exist_ok=True)
                        (folder/'failure.json').write_text(json.dumps(dict(error=str(e)),ensure_ascii=False),encoding='utf-8')
                        with lock:jobs[key].update(status='failed',error=str(e))
                pool.submit(work);self.reply(dict(id=key),202)
            except (ValueError,TypeError,KeyError) as e:self.reply(dict(error=str(e)),400)
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    url=f'http://127.0.0.1:{server.server_port}/'
    (output/'server.json').write_text(json.dumps(dict(url=url,port=server.server_port)),encoding='utf-8')
    print(url,flush=True)
    try:server.serve_forever()
    finally:server.server_close();pool.shutdown(wait=False)
