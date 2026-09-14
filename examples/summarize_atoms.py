"""Summarize a saved workbench trace without recompilation or quantum replay."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))

from neutral_atom_env.statistics import AtomStatistics, write_atom_statistics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='Saved workbench input.json')
    parser.add_argument('--trace', type=Path, required=True, help='Full committed trace.jsonl')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    value = json.loads(args.input.read_text(encoding='utf-8'))
    stats = AtomStatistics((f'Q{i:03d}' for i in range(value['atom_count'])), value['gates'])
    with args.trace.open(encoding='utf-8') as stream:
        for line in stream:
            if line.strip():
                stats.consume(line)
    report = stats.report()
    paths = write_atom_statistics(report, args.output)
    print(json.dumps({'atoms': len(report['atoms']), 'events': report['processed_records'],
                      'pending_operations': report['pending_operations'],
                      'outputs': [str(p) for p in paths]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
