"""Same native bytes, physical input and terminal; compare local path realization."""
import json
from hashlib import sha256
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_experiments.qmap_native import run

root=Path(__file__).resolve().parents[1]
source=root/'artifacts/qmap-native/original-acceptance'
target=Path(sys.argv[1]) if len(sys.argv)>1 else root/'artifacts/qmap-native/motion-v2'

if __name__=='__main__':
    target.mkdir(parents=True,exist_ok=True)
    results={}
    old=json.loads((source/'summary.json').read_text(encoding='utf-8'))
    for name,previous in old.items():
        native=json.loads((source/name/'upstream/native.json').read_text(encoding='utf-8'))
        request=json.loads((source/name/'upstream/request.json').read_text(encoding='utf-8'))
        print('RUN',name,flush=True)
        result=run(request,target/name,native_result=native)
        (target/name/'native-source.json').write_text(json.dumps(dict(path=str(source/name/'upstream/native.json'),
            code_sha256=sha256(native['code'].encode()).hexdigest()),indent=2),encoding='utf-8')
        def motion(directory):
            recording=json.loads((directory/'recording.json').read_text(encoding='utf-8'))
            moves=[o for o in recording['operations'] if o['kind']=='aod_move']
            return dict(segments=len(moves),movement_us=sum(o['end']-o['start'] for o in moves),
                        empty_segments=sum(not o['moving_count'] for o in moves))
        result.update(original_gate_count=previous['original_gate_count'],
            before=dict(metrics=previous['metrics'],motion=motion(source/name)),motion=motion(target/name),
            same_native_code=True,same_physical_initial=(source/name/'initial.json').read_bytes()==(target/name/'initial.json').read_bytes())
        def services(directory):
            plans=json.loads((directory/'plans.json').read_text(encoding='utf-8'))
            return [(o['operation_type'],o['transfer_bindings'],o['gate_ids'],o['gate_id'])
                    for plan in plans for o in plan['operations']
                    if o['transfer_bindings'] or o['gate_ids'] or o['gate_id']]
        result['same_service_operations']=services(source/name)==services(target/name)
        results[name]=result
        (target/'summary.json').write_text(json.dumps(results,indent=2),encoding='utf-8')
        print(name,result['status'],result['failure'],result['before']['motion']['segments'],'->',result['motion']['segments'],
              previous['metrics']['simulation_time_us'],'->',result['metrics']['simulation_time_us'],flush=True)
    if any(r['status']!='completed' or not r['same_physical_initial'] or not r['same_service_operations']
           for r in results.values()):raise SystemExit(1)
