"""Read-only projection of the qualified F0 production path, no compilation."""
from pathlib import Path
import gzip,json,hashlib,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from run_processor_injection_demo import read,SOURCE_RUN
OUT=ROOT/'artifacts/qualification/compact-modmul-20261009'

def main():
    OUT.mkdir(parents=True,exist_ok=True);target=OUT/'producer-template.json.gz'
    if target.exists():
        print('existing frozen producer projection retained');return
    stages=[];hashes={}
    keep=('name','pairs','trajectories','reads','writes','operation','params','state','basis')
    for wi in range(25):
        path=SOURCE_RUN/f'windows/window-{wi:04d}.json.gz';raw=path.read_bytes();hashes[str(path.relative_to(ROOT))]=hashlib.sha256(raw).hexdigest();w=json.loads(gzip.decompress(raw))
        work=next((x for x in w['fleet_work'] if x['factory_id']=='F0'),None)
        if not work:continue
        leaves=[];by={}
        for a in w['atom_program']['actions']:by.setdefault(a['id'].split('/action:')[0],[]).append(a)
        for m in w['physical_plan']['module_composition']['instances']:
            if not m['source_ids'] or not all(s.startswith('F0-e0-') for s in m['source_ids']):continue
            actions=[]
            for a in by[m['instance_id']]:
                ids=[x for x in a['atoms'] if x.startswith('atom:F0:')]
                if a['payload'].get('name')=='CZ':ids=list(dict.fromkeys(x for pair in a['payload']['pairs'] for x in pair))
                assert all(x.startswith('atom:F0:') for x in ids)
                actions.append(dict(id=a['id'],kind=a['kind'],atoms=ids,start=a['t_start_us'],end=a['t_end_us'],
                    condition=a['condition'],source_ids=a['payload'].get('physical_op_ids',a['source_ids'][:1]),
                    payload={k:v for k,v in a['payload'].items() if k in keep}))
            leaves.append(dict(module_hash=m['module_hash'],kind=m['kind'],actions=actions))
        stages.append(dict(stage=work['stage_id'],leaves=leaves,source_dag_hash=hashlib.sha256(json.dumps(work['physical_dag'],sort_keys=True,separators=(',',':')).encode()).hexdigest()))
        print(wi,work['stage_id'],sum(len(m['actions']) for m in leaves),flush=True)
        del w,by
    assert stages[0]['stage']=='initialize' and stages[-1]['stage']=='convert_output'
    assert len(stages)==25
    value=dict(schema_version='FrozenProducerPath/1',scenario='all_raw_readouts_and_syndromes_zero',stages=stages,source_byte_sha256=hashes,
        copies_live_state=False,requires_new_results_and_tokens=True)
    target.write_bytes(gzip.compress(json.dumps(value,separators=(',',':')).encode(),compresslevel=1,mtime=0))
    print('saved',len(stages),sum(len(m['actions']) for s in stages for m in s['leaves']),flush=True)

if __name__=='__main__':main()
