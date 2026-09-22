"""Local parking workbench. Every request builds an isolated physical experiment."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
import uuid
from neutral_atom_experiments.parking_demo import default_input, large_input, compatible_input, preview, run
from neutral_atom_env.visualization.viewer import javascript, write_html
from neutral_atom_env.replay.serializer import primitive
from neutral_atom_env.domain.errors import ValidationError


def create_server(port=0,output='artifacts/parking-demo'):
    root=Path(output).resolve();root.mkdir(parents=True,exist_ok=True)
    jobs={};lock=threading.Lock();pool=ThreadPoolExecutor(max_workers=1)
    def worker(key,value):
        try:
            result=run(value)
            folder=root/key;folder.mkdir()
            (folder/'input.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
            (folder/'result.json').write_text(json.dumps(primitive(result),ensure_ascii=False),encoding='utf-8')
            if result['status']=='completed':
                write_html(result['recording'],folder/'animation.html')
                for name in ('checkpoint','pickup_checkpoint'):(folder/(name+'.json')).write_text(result[name],encoding='utf-8')
                (folder/'recording.json').write_text(json.dumps(result['recording'],ensure_ascii=False),encoding='utf-8')
            with lock:jobs[key]=result
        except Exception as e:
            violation=getattr(e,'violation',None)
            result={'status':'failed','input':value,'error':{'code':violation.code if violation else type(e).__name__,'message':str(e),'phase':'worker'}}
            folder=root/key;folder.mkdir(exist_ok=True)
            (folder/'input.json').write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
            (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
            with lock:jobs[key]=result
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,status,value,content='application/json; charset=utf-8'):
            body=(json.dumps(primitive(value),ensure_ascii=False) if content.startswith('application/json') else value).encode('utf-8')
            self.send_response(status);self.send_header('Content-Type',content);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(body)
        def do_GET(self):
            path=self.path.split('?')[0]
            if path=='/':return self.send(200,Path(__file__).with_name('parking.html').read_text(encoding='utf-8'),'text/html; charset=utf-8')
            if path=='/parking.js':return self.send(200,Path(__file__).with_name('parking.js').read_text(encoding='utf-8'),'text/javascript; charset=utf-8')
            if path=='/atom-viewer.js':return self.send(200,javascript(),'text/javascript; charset=utf-8')
            if path=='/api/default':return self.send(200,large_input())
            if path=='/api/examples/small':return self.send(200,default_input())
            if path=='/api/examples/compatible':return self.send(200,compatible_input())
            if path.startswith('/api/jobs/'):
                key=path.rsplit('/',1)[-1]
                with lock:result=jobs.get(key)
                if result is None:
                    file=root/key/'result.json'
                    if len(key)==32 and all(c in '0123456789abcdef' for c in key) and file.is_file():result=json.loads(file.read_text(encoding='utf-8'))
                return self.send(200 if result else 404,result or {'error':'Unknown job'})
            return self.send(404,{'error':'Not found'})
        def do_POST(self):
            try:
                size=int(self.headers.get('Content-Length',0))
                if not 0<size<65536:raise ValueError('Input must be below 64 KiB')
                value=json.loads(self.rfile.read(size))
                if self.path=='/api/preview':return self.send(200,preview(value))
                if self.path=='/api/compile':
                    with lock:
                        if any(r['status']=='compiling' for r in jobs.values()):return self.send(409,{'error':'A parking job is still compiling'})
                        key=uuid.uuid4().hex;jobs[key]={'status':'compiling'}
                    pool.submit(worker,key,value)
                    return self.send(202,{'id':key})
                return self.send(404,{'error':'Not found'})
            except (ValueError,TypeError,KeyError,ValidationError) as e:return self.send(400,{'error':str(e)})
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.parking_pool=pool
    return server


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=0);parser.add_argument('--output',default='artifacts/parking-demo')
    args=parser.parse_args();server=create_server(args.port,args.output)
    print(f'Parking workbench: http://127.0.0.1:{server.server_port}',flush=True)
    try:server.serve_forever()
    finally:server.server_close();server.parking_pool.shutdown(wait=False)
