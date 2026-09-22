"""Compile a custom circuit's initial layout, without rendering or executing it."""
import argparse
import json
from pathlib import Path

from neutral_atom_app.placement import compile_layout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error('Input and output must be different files')
    try:
        report = compile_layout(json.loads(args.input.read_text(encoding='utf-8')))
    except Exception as error:
        report = dict(schema='initial-placement-result/1', status='failed',
                      error=dict(type=type(error).__name__, message=str(error)))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(dict(status=report['status'], output=str(args.output)), ensure_ascii=False))
    return int(report['status'] == 'failed')


if __name__ == '__main__':
    raise SystemExit(main())
