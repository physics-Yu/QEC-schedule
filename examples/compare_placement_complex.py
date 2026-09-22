"""Reproducible changing-partner and 2D-interaction placement comparisons.

These are generic physical circuits, not logical surface-code protocols.
No layout or optimized mapping is supplied to the strategy.
"""
import argparse
import json
from pathlib import Path
from neutral_atom_app.placement_workbench import default_input, compare


def cases(evaluations=6):
    def gate(name, kind, *qs):
        return dict(id=name, gate_type=kind, qubit_ids=[f'Q{q:03d}' for q in qs])
    twelve = default_input()
    twelve.update(workers=1,proposal_pool=64,terminal_mode='fixed')
    twelve.update(atom_count=12, source_rows=4, source_columns=8,
                  aod_rows=4, aod_columns=8, evaluations=evaluations, compile_timeout_s=90)
    gates = [gate(f'prepare_{q}', 'H', q) for q in range(12)]
    for layer in range(4):
        gates += [gate(f'pair_{layer}_{i}', 'CZ', i, 6+(i+layer)%6) for i in range(6)]
        gates += [gate(f'mix_{layer}_{q}', 'H' if layer%2==0 else 'T', q) for q in range(12)]
    twelve['gates'] = gates
    grid = default_input()
    grid.update(workers=1,proposal_pool=64,terminal_mode='fixed')
    grid.update(atom_count=16, source_rows=6, source_columns=8,
                aod_rows=4, aod_columns=8, evaluations=evaluations, compile_timeout_s=90)
    gates = [gate(f'prepare_{q}', 'H', q) for q in range(16)]
    edges = [(4*r+c, 4*r+c+1) for parity in range(2) for r in range(4)
             for c in range(parity, 3, 2)]
    edges += [(4*r+c, 4*(r+1)+c) for parity in range(2) for r in range(parity, 3, 2)
              for c in range(4)]
    for layer in range(2):
        gates += [gate(f'grid_{layer}_{i}', 'CZ', a, b) for i,(a,b) in enumerate(edges)]
        gates += [gate(f'mix_{layer}_{q}', 'H' if layer==0 else 'T', q) for q in range(16)]
    grid['gates'] = gates
    return {'partners-12': twelve, 'grid-16': grid}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evaluations', type=int, default=6)
    parser.add_argument('--case', choices=['partners-12','grid-16','all'], default='all')
    parser.add_argument('--output', type=Path, default=Path('artifacts/free-placement'))
    parser.add_argument('--inputs-only', action='store_true')
    args = parser.parse_args()
    for name, value in cases(args.evaluations).items():
        if args.case!='all' and name!=args.case:
            continue
        config = Path('configs/placement') / (name+'.json')
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')
        if args.inputs_only:
            continue
        print(json.dumps(dict(case=name, phase='start', gates=len(value['gates']))), flush=True)
        report = compare(value, args.output/name,
                         lambda p: print(json.dumps(dict(case=name,**p)), flush=True))
        print(json.dumps(dict(case=name, status=report['status'],
                              gain=report['improvement_percent'], wall=report['wall_seconds'])), flush=True)


if __name__=='__main__':
    main()
