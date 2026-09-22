"""Re-run the existing circuit fixtures without changing their AOD capacities."""
import json
from hashlib import sha256
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_experiments.qmap_native import run, compatible_architecture

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'artifacts/qmap-native/original-acceptance'
CASES={
    'grid-16':'configs/placement/grid-16-parallel.json',
    'partners-12':'configs/placement/partners-12-parallel.json',
    'random20-depth4':'configs/workbench/random20_depth4.json',
    'sparse20':'configs/workbench/zoned_sparse20.json',
    'repeated16':'configs/workbench/zoned_repeated16.json',
}
if __name__=='__main__':
    OUT.mkdir(parents=True,exist_ok=True)
    reports={}
    for name,path in CASES.items():
        original=json.loads((ROOT/path).read_text(encoding='utf-8'))
        # Column order belongs to the original editor semantics.
        gates=original['gates']
        if any('column' in g for g in gates):gates=sorted(gates,key=lambda g:(g['column'],g['id']))
        request=dict(atom_count=original['atom_count'],gates=[dict(id=g['id'],type=g['gate_type'],
            qubits=[int(q[1:]) for q in g['qubit_ids']]) for g in gates],
            architecture=compatible_architecture(original['atom_count'],
                rows=original['aod_rows'],columns=original['aod_columns']))
        print('RUN',name,len(gates),'gates',flush=True)
        try:result=run(request,OUT/name)
        except Exception as exc:result=dict(status='failed',failure=dict(type=type(exc).__name__,message=str(exc)))
        result.update(source=path,source_sha256=sha256((ROOT/path).read_bytes()).hexdigest(),
            same_circuit=True,original_gate_count=len(gates),same_aod_capacity=True,
            aod_shape=[original['aod_rows'],original['aod_columns']],same_geometry=False,
            comparison_scope='Same circuit/axis capacity; explicit native paired SLM geometry, no speedup claim against old platform')
        reports[name]=result
        (OUT/'summary.json').write_text(json.dumps(reports,indent=2,ensure_ascii=False),encoding='utf-8')
        print(name,result['status'],result.get('failure'),result.get('metrics',{}).get('simulation_time_us'),flush=True)
    if any(r['status']!='completed' for r in reports.values()):
        raise SystemExit(1)
