"""Compare pinned GitHub and AE frontends on identical physical CZ inputs."""
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_experiments.zac_reuse import demos,normalize_spec,frontend,DEFAULT_SOURCE

def main(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    github=next((DEFAULT_SOURCE.parents[1]/'github').glob('ZAC-*'))
    rows=[]
    for name,raw in demos().items():
        spec=normalize_spec(raw)
        for reuse in (False,True):
            variant='reuse' if reuse else 'no_reuse'
            a=json.loads((DEFAULT_SOURCE.parents[2]/name/variant/'upstream/placement.json').read_text(encoding='utf-8'))
            b=frontend(spec,github,output/name/variant,reuse)
            fields=('gate_layers','matching_reuse','selected_reuse','mappings')
            checks={key:a[key]==b[key] for key in fields}
            rows.append(dict(case=name,reuse=reuse,checks=checks,passed=all(checks.values())))
    report=dict(status='passed' if all(r['passed'] for r in rows) else 'failed',cases=rows,
                scope='ASAP layers, matching reuse, selected reuse and complete mapping sequence; physical CZ input bypasses QASM synthesis')
    (output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
    return report['status']=='passed'

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=Path('artifacts/zac-reuse/source-parity'))
    raise SystemExit(not main(parser.parse_args().output))
