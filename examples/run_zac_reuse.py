"""Run original ZAC reuse on/off targets in our physical environment."""
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'src'))
from neutral_atom_experiments.zac_reuse import compare, demos, DEFAULT_SOURCE

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--demo', choices=demos(), default='cross')
    parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path, default=Path('artifacts/zac-reuse/cross'))
    parser.add_argument('--source', type=Path, default=DEFAULT_SOURCE)
    args = parser.parse_args()
    raw = json.loads(args.input.read_text(encoding='utf-8')) if args.input else demos()[args.demo]
    report = compare(raw, args.output, args.source, progress=lambda s: print(s, flush=True))
    print(json.dumps({k:dict(status=v['status'], metrics=v['metrics'], error=v['error'])
                      for k,v in report['results'].items()}, ensure_ascii=False, indent=2))
    raise SystemExit(report['status'] != 'completed')
