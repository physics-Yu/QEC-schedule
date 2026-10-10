"""Compact read-only progress for one durable T044 repair job."""
from pathlib import Path
import json
from server_strategy_job import remote

ROOT = Path(__file__).resolve().parents[1]
DISPATCH = ROOT/'scripts/outputs/T704/server/20261008T095105858687Z-t044-joint-factory-committed-batch/dispatch.json'


def main():
    record = json.loads(DISPATCH.read_bytes())
    script = r'''from pathlib import Path
import json,re
root=Path(PROJECT); out=root/OUTPUT
def read(p): return json.loads(p.read_bytes()) if p.is_file() else {}
s=read(out/'status.json'); j=read(root/'scripts/outputs/T704/job/status.json')
result={'job_status':j.get('status'),'elapsed_seconds':j.get('elapsed_seconds'),'peak_tree_rss_bytes':j.get('peak_tree_rss_bytes'),
        'phase':s.get('phase'),'checks':s.get('checks'), 'components':len(s.get('components',[])),
        'last_component':[v.get('component_id') for v in s.get('components',[])[-3:]]}
result['active_components']=[p.parent.name for p in out.glob('*/status.json') if read(p).get('status')=='running']
result['failed_components']=[{'id':v.get('component_id'),'error':v.get('error')} for v in s.get('components',[]) if v.get('status')!='passed']
result['module_files']=sum(not p.name.startswith('frontier-') for p in (out/'compiled-modules').glob('*.json'))
result['frontier_proofs']=sum(1 for p in (out/'compiled-modules').glob('frontier-proof-*.json'))
result['test_counts']={p.name:re.findall(r'Ran (\d+) tests?',p.read_text(errors='replace')) for p in out.glob('*-tests.log')}
result['test_skips']={p.name:re.findall(r'OK \(skipped=(\d+)\)',p.read_text(errors='replace')) for p in out.glob('*-tests.log')}
result['protocols']={p.parent.name:{k:v for k,v in read(p).items() if k in ('status','stage_id','time_us','phase','completed_stages','physical_stage_count','duration_us','error')} for p in (out/'protocols').glob('*/status.json')}
f=read(out/'frame-continuations/status.json');result['frames']={'status':f.get('status'),'completed':[v.get('id') for v in f.get('components',[])]}
x=read(out/'parallel-examples/status.json');result['parallel_examples']={'status':x.get('status'),'completed':[v.get('id') for v in x.get('cases',[])]}
if j.get('status') not in ('running','starting'):
 result['stderr_tail']=(root/'scripts/outputs/T704/job/stderr.log').read_text(errors='replace')[-4000:]
result['strict_audit_exists']=(out/'joint-parallel-acceptance.json').exists()
print(json.dumps(result))
'''.replace('PROJECT', repr(record['project'])).replace('OUTPUT', repr(record['spec']['output_roots'][0]))
    result = remote(script)
    (DISPATCH.parent/'compact-progress.json').write_bytes((json.dumps(result, ensure_ascii=False, indent=2)+'\n').encode('utf-8'))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
