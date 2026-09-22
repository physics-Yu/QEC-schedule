"""Loopback editor for author-ZAC / local-Executor reuse experiments."""
from concurrent.futures import ThreadPoolExecutor
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit
from uuid import uuid4
import json

from neutral_atom_experiments.zac_reuse import compare, demos, normalize_spec, DEFAULT_SOURCE


def serve(*, output, source=DEFAULT_SOURCE, port=0):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    jobs = {}
    lock = Lock()
    pool = ThreadPoolExecutor(max_workers=1)

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(output), **kwargs)

        def reply(self, data, status=200):
            body = json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            route = urlsplit(self.path).path
            if route == '/':
                body = Path(__file__).with_name('zac_reuse.html').read_bytes()
                self.send_response(200)
                self.send_header('Content-Type','text/html; charset=utf-8')
                self.send_header('Content-Length',str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif route == '/api/demos':
                self.reply(dict(demos=demos(), available=[p.parent.name for p in output.glob('*/comparison.json')],
                                benchmarks=[p.parent.name for p in output.glob('*/benchmark.json')]))
            elif route.startswith('/api/jobs/'):
                with lock:
                    job = jobs.get(route.rsplit('/',1)[-1])
                    self.reply(dict(job) if job else dict(error='Unknown job'), 200 if job else 404)
            else:
                super().do_GET()

        def do_POST(self):
            if urlsplit(self.path).path != '/api/compile':
                return self.reply(dict(error='Unknown endpoint'),404)
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + self.headers.get('Host',''):
                return self.reply(dict(error='Origin mismatch'),403)
            try:
                length = int(self.headers.get('Content-Length','0'))
                if not 0 < length <= 65536:
                    raise ValueError('Invalid input length')
                raw = json.loads(self.rfile.read(length))
                normalize_spec(raw)
                with lock:
                    if any(j['status']=='running' for j in jobs.values()):
                        return self.reply(dict(error='已有实验运行中，请等待完成'),409)
                    key = uuid4().hex
                    jobs[key] = dict(status='running', progress='开始编译', id=key)
                def progress(message):
                    with lock:
                        jobs[key]['progress'] = message
                def work():
                    try:
                        report = compare(raw, output/key, source, progress)
                        status = report['status']
                        if report.get('schema') == 'zac-initial-benchmark/1':
                            runs = [v for c in report['cases'] for v in c['variants'].values()]
                            status = 'completed' if all(v['status']=='completed' for v in runs) else 'failed'
                        with lock:
                            jobs[key].update(status=status, url=f'/{key}/index.html', progress='已收集所有结果；完整性以逐组审计为准')
                    except Exception as exc:
                        (output/key).mkdir(parents=True,exist_ok=True)
                        (output/key/'failure.json').write_text(json.dumps(dict(error=str(exc)),ensure_ascii=False),encoding='utf-8')
                        with lock:
                            jobs[key].update(status='failed', error=str(exc))
                pool.submit(work)
                self.reply(dict(id=key),202)
            except (ValueError,TypeError,KeyError) as exc:
                self.reply(dict(error=str(exc)),400)

    server = ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print(f'ZAC reuse workbench: http://127.0.0.1:{server.server_port}/',flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
        pool.shutdown(wait=False)
