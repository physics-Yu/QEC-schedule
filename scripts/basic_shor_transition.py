"""Preserve and stop only our superseded deep-search producer before replacement."""
from pathlib import Path
import json
from server_strategy_job import remote

PROJECT='/home/yyq/na-platform-simulation/R7/T704/20261008T100815766018Z-basic-shor-component-pipeline-v1'

if __name__=='__main__':
    report=remote('''from pathlib import Path
import json,os,signal,hashlib,time
p=Path(PROJECT);status=json.loads((p/'scripts/outputs/T704/job/status.json').read_bytes());pid=status['child_pid']
cmd=Path('/proc')/str(pid)/'cmdline'
command=cmd.read_bytes().replace(bytes([0]),b' ').decode()
if str(p) not in command or 'remote_pipeline_worker.py' not in command:raise ValueError('MANAGED_PROCESS_IDENTITY')
if os.getpgid(pid)!=pid:raise ValueError('MANAGED_PROCESS_GROUP')
b=p/'artifacts/runs/basic-shor-20261008-v1';cp=b/'prepare/checkpoint.json.gz'
r={'reason':'user deferred optimization; replace the accidentally active deep-frontier cold path with explicit feasible source order','time':time.time(),'pid':pid,'command':command,'checkpoint_sha256':hashlib.sha256(cp.read_bytes()).hexdigest(),'outputs_preserved':True,'other_jobs_affected':False}
(p/'basic-scope-transition.json').write_text(json.dumps(r,indent=2))
os.killpg(pid,signal.SIGTERM)
print(json.dumps(r))
'''.replace('PROJECT',repr(PROJECT)))
    path=Path('knowledge/roles/R0/evidence/basic-shor-v1-transition.json')
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
