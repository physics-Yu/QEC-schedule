"""Local experimental comparison UI; each algorithm runs in a fresh process."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import argparse
import json
import mimetypes
import subprocess
import sys
import threading
from time import perf_counter
from urllib.parse import urlsplit, unquote
from uuid import uuid4

ROOT=Path(__file__).resolve().parents[2]


def isolated_comparison(spec, directory, progress=print):
    from neutral_atom_experiments.smt_comparison import STRATEGIES, validate_spec
    validate_spec(spec)
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    source=directory/'input.json';source.write_text(json.dumps(spec,ensure_ascii=False),encoding='utf-8')
    results=[]
    for strategy in STRATEGIES:
        target=directory/strategy;target.mkdir(exist_ok=True)
        progress({'strategy':strategy,'status':'compiling'})
        tick=perf_counter()
        with (target/'worker.log').open('w',encoding='utf-8') as log:
            try:
                child=subprocess.run([sys.executable,str(ROOT/'examples/run_smt_experiment.py'),'--one',strategy,'--input',str(source),
                    '--output',str(target)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
                    timeout=spec.get('timeout_s',60)+30,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                if child.returncode:raise RuntimeError(f'worker exited {child.returncode}; see worker.log')
                result=json.loads((target/'result.json').read_text(encoding='utf-8'))
            except (subprocess.TimeoutExpired,RuntimeError) as e:
                result={'strategy':strategy,'status':'failed','error':{'code':'WORKER_FAILURE','message':str(e)},
                        'compile_seconds':None,'metrics':{},'cz_batch_sizes':[],'max_cz_batch':0}
                (target/'result.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
        result['process_wall_seconds']=perf_counter()-tick
        results.append(result);progress({'strategy':strategy,'status':result['status'],'compile_seconds':result['compile_seconds']})
    hashes={r.get('initial_sha256') for r in results}
    report={'input':spec,'results':results,'same_initial_state':len(hashes)==1 and None not in hashes,
        'fresh_process_per_strategy':True,'status':'completed' if all(r['status']=='completed' for r in results) else 'failed'}
    (directory/'comparison.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


def create_server(output,port=8793,reference=None,ui_file=None):
    from neutral_atom_experiments.smt_comparison import demos, make_state
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    reference=Path(reference).resolve() if reference else None
    jobs={};lock=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def send(self,data,status=200,kind='application/json; charset=utf-8'):
            if not isinstance(data,bytes):data=json.dumps(data,ensure_ascii=False).encode()
            self.send_response(status);self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store')
            self.end_headers();self.wfile.write(data)
        def do_GET(self):
            path=unquote(urlsplit(self.path).path)
            if path=='/':
                page=Path(ui_file) if ui_file else Path(__file__).with_name('visualization').joinpath('smt_experiment.html')
                return self.send(page.read_bytes(),kind='text/html; charset=utf-8')
            if path=='/api/catalog':return self.send({'demos':demos(),'suite':'/data/attempt2/suite.json'})
            if path.startswith('/api/jobs/'):
                with lock:data=dict(jobs.get(path.split('/')[-1],{}))
                return self.send(data,200 if data else 404)
            if path.startswith('/data/'):
                base=reference if reference and path.startswith('/data/attempt2/') else output
                relative=path[len('/data/attempt2/'):] if base==reference else path[6:]
                target=(base/relative).resolve()
                if not target.is_relative_to(base) or not target.is_file():return self.send({'error':'not found'},404)
                return self.send(target.read_bytes(),kind=(mimetypes.guess_type(str(target))[0] or 'application/octet-stream')+'; charset=utf-8')
            return self.send({'error':'not found'},404)
        def do_POST(self):
            if self.path!='/api/compile':return self.send({'error':'not found'},404)
            origin=self.headers.get('Origin')
            if origin and origin!=f'http://127.0.0.1:{self.server.server_port}':return self.send({'error':'origin rejected'},403)
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=65536:raise ValueError('invalid body size')
                spec=json.loads(self.rfile.read(size));make_state(spec)
            except Exception as e:
                return self.send({'error':{'code':type(e).__name__,'message':str(e)}},400)
            with lock:
                if any(j['status']=='compiling' for j in jobs.values()):return self.send({'error':{'message':'已有实验正在编译，请等待完成'}},409)
                key=uuid4().hex;directory=output/'interactive'/key
                jobs[key]={'id':key,'status':'compiling','progress':{},'base':f'/data/interactive/{key}'}
            def work():
                try:
                    def progress(p):
                        with lock:jobs[key]['progress']=p
                    report=isolated_comparison(spec,directory,progress)
                    with lock:jobs[key].update(status=report['status'],report=report)
                except Exception as e:
                    with lock:jobs[key].update(status='failed',error={'code':type(e).__name__,'message':str(e)})
            threading.Thread(target=work,daemon=True).start()
            return self.send({'id':key},202)
        def log_message(self,*args):pass
    return ThreadingHTTPServer(('127.0.0.1',port),Handler)


def serve(output,port=8793):
    server=create_server(output,port)
    print(f'SMT experiment: http://127.0.0.1:{server.server_port}/',flush=True)
    try: server.serve_forever()
    finally: server.server_close()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8793)
    parser.add_argument('--output',default='artifacts/smt-batch');args=parser.parse_args()
    serve(args.output,args.port)


if __name__=='__main__':main()
