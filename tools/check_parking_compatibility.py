"""Reproducible current Python execution references and browser-template comparison."""
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from neutral_atom_experiments.parking_demo import default_input, compatible_input, run
from neutral_atom_env.replay.serializer import primitive


def main():
    folder=ROOT/'artifacts/parking-compatible-v2'
    folder.mkdir(parents=True,exist_ok=True)
    cases={
        'retained-columns':default_input()|dict(cells=[[2,2,1],[2,2,1]]),
        'batch-identical':default_input()|dict(cells=[[2,2,1],[2,2,1]],strategy='pattern_optimal'),
        'column-wins':default_input()|dict(rows=4,columns=2,cells=[[2,1],[1,2],[2,2],[2,0]],aod_rows=4,aod_columns=2,strategy='pattern_optimal'),
        'wildcard-10x10':compatible_input(),
    }
    reports=[];paths=[]
    for name,spec in cases.items():
        start=time.perf_counter();result=run(spec);out=folder/name;out.mkdir(exist_ok=True)
        (out/'input.json').write_text(json.dumps(spec),encoding='utf-8')
        (out/'result.json').write_text(json.dumps(primitive(result)),encoding='utf-8')
        assert result['status']=='completed',(name,result.get('error'))
        (out/'recording.json').write_text(json.dumps(result['recording']),encoding='utf-8')
        report={'name':name,'captures':result['pickup']['transfer_events'],'analysis':result['pickup']['analysis'],
                'duration_us':result['recording']['duration'],'full_audit_seconds':time.perf_counter()-start,'validation':result['validation']}
        reports.append(report);paths.append(str(out));print(json.dumps(report),flush=True)
    verified=subprocess.run(['node','tests/parking_template.cjs',*paths],cwd=ROOT,capture_output=True,text=True,check=True)
    (folder/'browser-equivalence.json').write_text(verified.stdout,encoding='utf-8')
    (folder/'summary.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
    print(verified.stdout)


if __name__=='__main__':main()
