"""Local workbench, cancellable subprocess compilation and bounded result retention."""
import argparse
from collections import OrderedDict
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import multiprocessing as mp
from math import isfinite
from pathlib import Path
import threading
import time
from urllib.parse import urlsplit
import uuid
from .workbench import validate_input, preview, compile_input, MAX_COMPILE_TIMEOUT_S
from .viewer import javascript, write_html
from neutral_atom_env.replay.serializer import canonical_json


def _worker(value, output, connection):
    try:
        result,state = compile_input(value, lambda p: connection.send(('progress', p)))
        directory=Path(output); directory.mkdir(parents=True,exist_ok=True)
        (directory/'input.json').write_text(canonical_json(result['input']),encoding='utf-8')
        (directory/'recording.json').write_text(canonical_json(result['recording']),encoding='utf-8')
        from neutral_atom_env.statistics import write_atom_statistics
        write_atom_statistics(result['recording']['atom_statistics'],directory)
        write_html(result['recording'],directory/'index.html')
        (directory/'checkpoint.json').write_text(state.snapshot(),encoding='utf-8')
        (directory/'diagnostics.json').write_text(canonical_json(result['diagnostics']),encoding='utf-8')
        (directory/'candidate_rejections.json').write_text(canonical_json(result.get('candidate_rejections',[])),encoding='utf-8')
        (directory/'decisions.json').write_text(canonical_json(result.get('decision_log',[])),encoding='utf-8')
        (directory/'run_options.json').write_text(canonical_json(result.get('run_options',{})),encoding='utf-8')
        (directory/'failure_report.json').write_text(canonical_json(result.get('failure_report')),encoding='utf-8')
        if result.get('qec_result') is not None:
            (directory/'qec_result.json').write_text(canonical_json(result['qec_result']),encoding='utf-8')
        (directory/'result.json').write_text(canonical_json({'status':result['status'],'metrics':state.metrics(),
            'compile_seconds':result.get('compile_seconds'),'run_options':result.get('run_options',{}),
            **({'qec_result':result['qec_result']} if 'qec_result' in result else {})}),encoding='utf-8')
        (directory/'trace.jsonl').write_text('\n'.join(state.trace.records)+'\n',encoding='utf-8')
        connection.send(('result',result))
    except Exception as error:
        connection.send(('error',{'code':type(error).__name__, 'message':str(error)}))
    finally:
        connection.close()


class CompileJobs:
    """One active compile for this local workspace. Replacing it kills old computation."""
    def __init__(self, output, timeout=90):
        if type(timeout) not in (int,float) or not isfinite(timeout) or not 0<timeout<=MAX_COMPILE_TIMEOUT_S:
            raise ValueError(f'Compile timeout must be positive and at most {MAX_COMPILE_TIMEOUT_S} seconds')
        self.output=Path(output).resolve(); self.timeout=timeout
        self.lock=threading.RLock(); self.jobs=OrderedDict(); self.active=None

    def restore(self,directory):
        """Expose an existing execution without compiling or editing its artifacts."""
        source=Path(directory).resolve()
        def read(name,default=None):
            path=source/name
            return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default
        saved=read('result.json');original=read('input.json');recording=read('recording.json')
        strategy=read('strategy.json',{})
        if not all(isinstance(v,dict) for v in (saved,original,recording)):
            raise ValueError('Saved execution needs result.json, input.json and recording.json')
        actual=strategy.get('actual_strategy',saved.get('actual_strategy',original.get('compiler')))
        if actual is None and 'compilation' in original:
            actual=validate_input(original)['compiler']
        if actual not in {'qec_ghz2','qec_persistent','qec_joint','qec_temporal','qec_temporal_four'}:
            raise ValueError('Saved execution restoration currently supports explicit QEC strategies only')
        if saved.get('actual_strategy',actual)!=actual:
            raise ValueError('Saved result and strategy disagree')
        metrics=saved.get('metrics',{})
        if saved.get('error') or metrics.get('completed_gate_count')!=len(original.get('gates',())):
            raise ValueError('Saved execution has not completed its actual circuit')
        if saved.get('status') not in {'completed','passed','checks_passed_replay_pending','verified'}:
            raise ValueError('Saved result does not declare a completed physical execution')
        if (recording.get('duration')!=metrics.get('simulation_time_us') or
                recording.get('summary',{}).get('metrics',{}).get('completed_gate_count')!=len(original['gates'])):
            raise ValueError('Saved recording and result metrics disagree')
        # A restored recording belongs to the actually executed strategy. Its
        # saved editor configuration may predate a strategy override; do not
        # let a stale nested recommendation relabel that historical execution.
        execution_input={k:v for k,v in original.items()
                         if k not in {'compilation','compilation_backend','circuit_profile'}}
        value=validate_input(execution_input|{'compiler':actual})
        provenance={'kind':'saved_execution','source_dir':str(source),'source_input_compiler':original.get('compiler'),
            'actual_strategy':actual,'acceptance_status':saved['status'],
            'compiler_free_replay':read('verification.json',{}).get('compiler_free_replay','尚未记录'),
            'note':'保存的真实执行结果；仅恢复展示，未发起新编译。实际策略来自 strategy.json。'}
        timing_scope=saved.get('compile_timing_scope')
        if timing_scope=='suffix_only':
            resumed=read('resume-provenance.json',{})
            provenance['resume']={name:resumed.get(name) for name in (
                'parent_output','selected_checkpoint','classification','prefix_completed_gates',
                'prefix_plans','prefix_time_us','prefix_trace_sha256','prefix_trace_records')}
            provenance['resume']['parent_observed_elapsed_seconds']=(resumed.get('parent_progress') or {}).get('elapsed_seconds')
            provenance['resume']['decision_log_scope']='suffix_only'
            provenance['resume']['recording_scope']='full_prefix_and_suffix'
        key=hashlib.sha256((str(source)+canonical_json(strategy)).encode('utf-8')).hexdigest()[:32]
        result={'input':value,'status':'completed','recording':recording,'compile_seconds':saved.get('compile_seconds'),
            'diagnostics':read('diagnostics.json',[]),'candidate_rejections':read('candidate_rejections.json',[]),
            'decision_log':read('decisions.json',[]),'run_options':read('run_options.json',{}),
            'qec_result':read('qec_result.json',saved.get('qec_result')),'failure_report':None,'provenance':provenance}
        if timing_scope is not None:result['compile_timing_scope']=timing_scope
        with self.lock:
            self.jobs[key]={'id':key,'status':'completed','progress':{'completed_gates':metrics['completed_gate_count'],
                'total_gates':len(value['gates']),'simulation_time_us':recording['duration']},
                'started':time.monotonic(),'input':value,'result':result,'timeout_seconds':value.get('compile_timeout_s',self.timeout)}
        return key

    def start(self,value):
        value=validate_input(value)
        with self.lock:
            if self.active:
                self.cancel(self.active)
            key=uuid.uuid4().hex
            directory=self.output/key; directory.mkdir(parents=True,exist_ok=True)
            (directory/'input.json').write_text(canonical_json(value),encoding='utf-8')
            parent,child=mp.get_context('spawn').Pipe(duplex=False)
            process=mp.get_context('spawn').Process(target=_worker,args=(value,str(self.output/key),child),daemon=True)
            job={'id':key,'status':'compiling','progress':{'completed_gates':0,'total_gates':len(value['gates'])},
                 'started':time.monotonic(),'process':process,'input':value,
                 'timeout_seconds':value.get('compile_timeout_s',self.timeout)}
            self.jobs[key]=job; self.active=key
            while len(self.jobs)>8:
                self.jobs.popitem(last=False)
            process.start(); child.close()
            threading.Thread(target=self._monitor,args=(job,parent),daemon=True).start()
            return key

    def _monitor(self,job,connection):
        try:
            while job['status']=='compiling':
                if time.monotonic()-job['started']>job['timeout_seconds']:
                    with self.lock:
                        if job['status']=='compiling':
                            job.update(status='failed',error={'code':'COMPILE_TIMEOUT','message':f"Compilation exceeded {job['timeout_seconds']:g} seconds; edit the circuit, layout, search budget or explicit timeout and recompile."})
                    break
                if connection.poll(.1):
                    kind,data=connection.recv()
                    with self.lock:
                        if job['status']!='compiling': break
                        if kind=='progress': job['progress']=data
                        elif kind=='result': job.update(status=data['status'],result=data)
                        else: job.update(status='failed',error=data)
                elif not job['process'].is_alive():
                    with self.lock:
                        if job['status']=='compiling':
                            job.update(status='failed',error={'code':'WORKER_EXIT','message':'Compiler process exited without a result'})
        except (EOFError,OSError):
            with self.lock:
                if job['status']=='compiling': job.update(status='failed',error={'code':'WORKER_EXIT','message':'Compiler connection closed'})
        finally:
            connection.close()
            if job['process'].is_alive(): job['process'].terminate()
            job['process'].join(timeout=2)
            if job['status']=='failed':
                report={'status':'failed','phase':'worker','input':job['input'],
                        'error':job.get('error'),'progress':job['progress'],'timeout_seconds':job['timeout_seconds'],
                        'note':'工作进程异常或超时；进度只是最后一次报告，不保证有最终 checkpoint。'}
                (self.output/job['id']/'failure_report.json').write_text(canonical_json(report),encoding='utf-8')

    def cancel(self,key):
        with self.lock:
            job=self.jobs.get(key)
            if job and job['status']=='compiling':
                job['status']='cancelled'
                if job['process'].is_alive(): job['process'].terminate()

    def get(self,key,result=False):
        with self.lock:
            job=self.jobs.get(key)
            if job is None: return None
            if result: return job.get('result')
            return {k:job[k] for k in ('id','status','progress','error','timeout_seconds') if k in job} | {'elapsed_seconds':round(time.monotonic()-job['started'],2)}

    def close(self):
        for key in list(self.jobs): self.cancel(key)


def create_server(port=8766,output='artifacts/workbench',timeout=90,restore_job_dir=None):
    jobs=CompileJobs(output,timeout)
    restored_job=jobs.restore(restore_job_dir) if restore_job_dir else None
    root=Path(__file__).parent
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def respond(self,code,value,content_type='application/json; charset=utf-8'):
            body=(canonical_json(value) if content_type.startswith('application/json') else value).encode('utf-8')
            self.send_response(code); self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff'); self.end_headers()
            try: self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError): pass

        def local_request(self):
            # Bound loopback plus Host/Origin checks; no CORS or arbitrary filesystem routes.
            host=self.headers.get('Host','')
            if host not in {f'localhost:{self.server.server_port}',f'127.0.0.1:{self.server.server_port}'}:
                self.respond(403,{'error':'Invalid local host'}); return False
            origin=self.headers.get('Origin')
            if origin and origin != 'http://'+host:
                self.respond(403,{'error':'Cross-origin requests are not allowed'}); return False
            return True

        def do_GET(self):
            if not self.local_request(): return
            path=urlsplit(self.path).path
            if path=='/': return self.respond(200,(root/'workbench.html').read_text(encoding='utf-8'),'text/html; charset=utf-8')
            if path=='/workbench.js': return self.respond(200,(root/'workbench.js').read_text(encoding='utf-8'),'text/javascript; charset=utf-8')
            if path=='/atom-viewer.js': return self.respond(200,javascript(),'text/javascript; charset=utf-8')
            if path=='/api/examples/surface-ghz':
                try:
                    from neutral_atom_env.experiments.surface_ghz import experiment_input
                    return self.respond(200,validate_input(experiment_input()))
                except Exception as error:
                    return self.respond(422,{'error':str(error)})
            if path=='/api/examples/surface-qec-ghz2':
                try:
                    from neutral_atom_env.experiments.surface_qec import experiment_input
                    return self.respond(200,validate_input(experiment_input()))
                except Exception as error:
                    return self.respond(422,{'error':str(error)})
            if path=='/api/examples/surface-qec-temporal':
                try:
                    from neutral_atom_env.experiments.surface_qec_temporal import experiment_input
                    value=experiment_input({'kind':'readout','round':2,'patch':0,'check_type':'X','check_index':0})
                    value['seed']=7
                    return self.respond(200,validate_input(value))
                except Exception as error:
                    return self.respond(422,{'error':str(error)})
            if path=='/api/examples/surface-qec-temporal-four':
                try:
                    from neutral_atom_env.experiments.surface_qec_temporal_four import experiment_input
                    value=experiment_input({'kind':'readout','round':2,'patch':0,'check_type':'X','check_index':0})
                    value['seed']=7
                    return self.respond(200,validate_input(value))
                except Exception as error:
                    return self.respond(422,{'error':str(error)})
            parts=path.strip('/').split('/')
            if len(parts) in (3,4) and parts[:2]==['api','jobs']:
                result=len(parts)==4 and parts[3]=='result'
                data=jobs.get(parts[2],result)
                if data is not None: return self.respond(200,data)
            self.respond(404,{'error':'Not found or result no longer retained'})

        def do_POST(self):
            if not self.local_request(): return
            try:
                if self.headers.get('Content-Type','').split(';')[0]!='application/json':
                    return self.respond(415,{'error':'Use application/json'})
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=2*1024*1024: return self.respond(413,{'error':'Request must be 1 byte–2 MiB'})
                self.connection.settimeout(10)
                value=json.loads(self.rfile.read(size))
                path=urlsplit(self.path).path
                if path=='/api/preview': return self.respond(200,preview(value))
                if path=='/api/compile': return self.respond(202,{'id':jobs.start(value)})
                parts=path.strip('/').split('/')
                if len(parts)==4 and parts[:2]==['api','jobs'] and parts[3]=='cancel':
                    jobs.cancel(parts[2]); return self.respond(200,{'status':'cancelled'})
                self.respond(404,{'error':'Not found'})
            except (ValueError,TypeError,KeyError,AttributeError) as error:
                self.respond(400,{'error':str(error)})
            except Exception as error:
                self.respond(422,{'error':str(error)})
    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.jobs=jobs
    server.restored_job=restored_job
    return server


def main():
    parser=argparse.ArgumentParser(description='Local editable quantum circuit workbench')
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--output',default='artifacts/workbench')
    parser.add_argument('--timeout',type=float,default=90,help='Default compile timeout in seconds; input compile_timeout_s can override (maximum 86400)')
    parser.add_argument('--restore-job-dir',help='Read an existing QEC execution as a saved job; does not recompile')
    args=parser.parse_args()
    server=create_server(args.port,args.output,args.timeout,args.restore_job_dir)
    print(f'Circuit workbench: http://127.0.0.1:{server.server_port}',flush=True)
    if server.restored_job:
        print(f'Saved execution: http://127.0.0.1:{server.server_port}/?job={server.restored_job}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.jobs.close(); server.server_close()


if __name__=='__main__': main()
