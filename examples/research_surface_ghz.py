"""Emit the independently verified ideal surface-code GHZ input."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from neutral_atom_env.experiments.surface_ghz import input_payload, phase_columns, verify


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path)
    args = parser.parse_args(); report = verify(); report["phase_columns"] = phase_columns()
    print(json.dumps(report, indent=2))
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        raw, stages = input_payload()
        for name, value in [('ideal_verification', report), ('circuit', raw), ('stages', stages)]:
            (args.output / f'{name}.json').write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
