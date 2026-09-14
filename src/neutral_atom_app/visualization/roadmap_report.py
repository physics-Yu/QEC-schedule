"""Read-only persisted stage acceptance report; no experiment execution API."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import urlsplit


STAGE_STATUSES={'pending','running','passed','failed','awaiting_approval'}
ATTEMPT_STATUSES={'running','passed','failed'}


def validate_status(value):
    """Reject unsubstantiated PASS and unapproved retries in the supplied ledger."""
    if not isinstance(value,dict) or value.get('schema_version')!=1:
        raise ValueError('Expected roadmap schema_version 1')
    stages=value.get('stages')
    if not isinstance(stages,list) or len(stages)!=4:
        raise ValueError('Exactly four stages are required')
    ids=set()
    for stage in stages:
        if not isinstance(stage,dict) or not isinstance(stage.get('id'),str) or not stage['id']:
            raise ValueError('Each stage needs an ID')
        if stage['id'] in ids:raise ValueError('Duplicate stage ID')
        ids.add(stage['id'])
        if not isinstance(stage.get('title'),str) or not stage['title']:
            raise ValueError('Each stage needs a title')
        if stage.get('status') not in STAGE_STATUSES:
            raise ValueError('Unknown stage status')
        attempts=stage.get('attempts',[])
        if not isinstance(attempts,list):raise ValueError('attempts must be a list')
        last_number=0;formal=[]
        for attempt in attempts:
            if not isinstance(attempt,dict):raise ValueError('Attempt must be an object')
            number=attempt.get('number')
            if type(number) is not int or number<=last_number:
                raise ValueError('Attempt numbers must be positive and strictly increasing')
            last_number=number
            if type(attempt.get('formal')) is not bool:
                raise ValueError('Attempt formal flag must be explicit')
            if attempt.get('status') not in ATTEMPT_STATUSES:
                raise ValueError('Unknown attempt status')
            evidence=attempt.get('evidence',[])
            if not isinstance(evidence,list) or any(not isinstance(e,dict) or
                    not isinstance(e.get('label'),str) or not isinstance(e.get('path'),str) for e in evidence):
                raise ValueError('Evidence must contain label/path objects')
            if attempt['formal']:
                if formal and formal[-1]['status']=='failed':
                    approval=formal[-1]['failure']['approval']
                    if approval['status']!='approved' or not approval.get('user_message'):
                        raise ValueError('A new formal attempt requires explicit recorded user approval after failure')
                formal.append(attempt)
            if attempt['status']=='failed' and attempt['formal']:
                failure=attempt.get('failure')
                if not isinstance(failure,dict):raise ValueError('Formal failure requires a failure report')
                for key in ('facts','hypotheses','proposed_retry_scope'):
                    if not isinstance(failure.get(key),list) or any(not isinstance(s,str) for s in failure[key]):
                        raise ValueError(f'Failure {key} must be a list of strings')
                if not failure['facts']:raise ValueError('Formal failure must record observed facts')
                approval=failure.get('approval')
                if not isinstance(approval,dict) or approval.get('status') not in {'pending','approved','rejected'}:
                    raise ValueError('Failure requires an explicit approval state')
                if approval['status']=='approved' and (not isinstance(approval.get('user_message'),str) or not approval['user_message'].strip()):
                    raise ValueError('Approval needs the user message; elapsed time is not approval')
        latest=formal[-1] if formal else None
        if stage['status']=='passed' and (not latest or latest['status']!='passed' or not latest.get('evidence')):
            raise ValueError('Passed stage requires a passed formal attempt with evidence')
        if stage['status']=='running' and (not latest or latest['status']!='running'):
            raise ValueError('Running stage requires a running formal attempt')
        if stage['status'] in {'failed','awaiting_approval'} and (not latest or latest['status']!='failed'):
            raise ValueError('Failed stage requires a failed formal attempt')
        if latest and latest['status']=='failed' and stage['status'] not in {'failed','awaiting_approval'}:
            raise ValueError('A formal failure must remain visibly failed or awaiting approval')
    return value


def write_page(directory):
    """Create the view only; never create or change the root-owned status.json."""
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    for name in ('index.html','roadmap.js'):
        source=Path(__file__).with_name('roadmap.html' if name=='index.html' else name)
        (directory/name).write_text(source.read_text(encoding='utf-8'),encoding='utf-8')
    return directory.resolve()


def create_server(directory,port=8782):
    directory=Path(directory).resolve()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def respond(self,code,value,content_type):
            body=value.encode('utf-8')
            self.send_response(code);self.send_header('Content-Type',content_type)
            self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
        def do_GET(self):
            path=urlsplit(self.path).path
            if path=='/status.json':
                try:
                    value=validate_status(json.loads((directory/'status.json').read_text(encoding='utf-8')))
                    return self.respond(200,json.dumps(value,ensure_ascii=False),'application/json; charset=utf-8')
                except (ValueError,OSError) as error:
                    return self.respond(422,json.dumps({'error':str(error)},ensure_ascii=False),'application/json; charset=utf-8')
            files={'/':'index.html','/index.html':'index.html','/roadmap.js':'roadmap.js'}
            if path not in files:return self.respond(404,'Not found','text/plain; charset=utf-8')
            source=Path(__file__).with_name('roadmap.html' if files[path]=='index.html' else 'roadmap.js')
            return self.respond(200,source.read_text(encoding='utf-8'),'text/javascript; charset=utf-8' if path.endswith('.js') else 'text/html; charset=utf-8')
        def do_POST(self):
            return self.respond(405,'Read-only report: no approval, retry or execution endpoint','text/plain; charset=utf-8')
        do_PUT=do_POST
        do_DELETE=do_POST
        do_PATCH=do_POST
    return ThreadingHTTPServer(('127.0.0.1',port),Handler)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',default='artifacts/qec-roadmap')
    parser.add_argument('--port',type=int,default=8782)
    parser.add_argument('--write-only',action='store_true')
    args=parser.parse_args();write_page(args.directory)
    if args.write_only:return
    server=create_server(args.directory,args.port)
    print(f'Read-only QEC roadmap: http://127.0.0.1:{server.server_port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()


if __name__=='__main__':main()
