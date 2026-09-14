"""Re-render saved physical recordings with the current viewer; never recompile."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_env.visualization.viewer import write_html


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--source',type=Path,default=Path('artifacts/workbench'))
    parser.add_argument('--output',type=Path,default=Path('artifacts/m4-debug-current'))
    parser.add_argument('--count',type=int,default=6)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True);manifest=[]
    cases=sorted((p for p in args.source.iterdir() if (p/'recording.json').exists()),key=lambda p:p.stat().st_mtime,reverse=True)
    for p in cases[:args.count]:
        raw=(p/'recording.json').read_bytes();data=json.loads(raw)
        write_html(data,args.output/(p.name+'.html'))
        points=sorted(set([data.get('start_time',0),data['duration']]+[t for o in data['operations'] for t in (o['start'],o['end'])]))
        manifest.append({'job':p.name,'source_sha256':hashlib.sha256(raw).hexdigest(),
                         'operations':len(data['operations']),'duration_us':data['duration'],
                         'tiny_gaps':[(a,b,b-a) for a,b in zip(points,points[1:]) if b-a<1e-8]})
        assert (p/'recording.json').read_bytes()==raw
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps(manifest))


if __name__=='__main__':main()
