"""Re-render ZAC views from saved execution records without recompiling physics."""
from pathlib import Path
import argparse
import json
import sys
from hashlib import sha256
import shutil
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_experiments.zac_reuse_report import write_replay,write_comparison
from neutral_atom_env.visualization.viewer import write_html

def render(root):
    root=Path(root)
    if (root/'benchmark.json').exists():
        manifest=json.loads((root/'benchmark.json').read_text(encoding='utf-8'))
        if manifest.get('schema')=='zac-initial-benchmark/1':
            from neutral_atom_experiments.zac_initial_report import write_report
            write_report(manifest,root)
            for case in manifest['cases']:
                for mode,run in case['variants'].items():
                    if 'result' not in run: continue
                    folder=root/case['id']/mode
                    placement=json.loads((folder/'upstream/placement.json').read_text(encoding='utf-8'))
                    payload=json.loads((folder/'recording.json').read_text(encoding='utf-8'))
                    write_html(payload,folder/'physical.html')
                    write_replay(placement['spec'],placement,run['result'],payload,folder/'index.html')
            repo=Path(__file__).resolve().parents[1]
            sources=['src/neutral_atom_experiments/zac_initial_report.py',
                     'src/neutral_atom_experiments/zac_reuse_report.py',
                     'src/neutral_atom_env/visualization/viewer.js',
                     'src/neutral_atom_env/visualization/viewer-shell.html']
            hashes={}
            for rel in sources:
                p=repo/rel;hashes[rel]=sha256(p.read_bytes()).hexdigest()
                target=root/'source-snapshot/presentation'/rel
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
            (root/'render.json').write_text(json.dumps(dict(scope='Presentation only; saved physics unchanged',sources=hashes),indent=2),encoding='utf-8')
            return
        from neutral_atom_experiments.zac_benchmark_report import write_dashboard
        write_dashboard(json.loads((root/'benchmark.json').read_text(encoding='utf-8')),root)
    for path in root.glob('*/comparison.json'):
        report=json.loads(path.read_text(encoding='utf-8'))
        for name,result in report['results'].items():
            folder=path.parent/name
            placement=json.loads((folder/'upstream/placement.json').read_text(encoding='utf-8'))
            payload=json.loads((folder/'recording.json').read_text(encoding='utf-8'))
            write_html(payload,folder/'physical.html')
            write_replay(report['spec'],placement,result,payload,folder/'index.html')
        write_comparison(report,path.with_name('index.html'))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path('artifacts/zac-reuse'))
    render(parser.parse_args().root)
