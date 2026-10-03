"""Execute the standard d=3 four-layer memory on the native physical platform."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--basis', choices=('X', 'Z'), default='Z')
    parser.add_argument('--rounds', type=int, default=3, help='Total syndrome rounds, including the first round')
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--wall-budget', type=float, default=900)
    parser.add_argument('--initial-placement', choices=('prearranged', 'storage'), default='prearranged',
                        help='Prepared EZ layout (default); storage reproduces historical staging')
    parser.add_argument('--audit-deps', help='Optional isolated directory containing pinned Stim dependency')
    parser.add_argument('--output')
    args = parser.parse_args()
    if args.audit_deps:
        sys.path.insert(0, str(Path(args.audit_deps).resolve()))
    from neutral_atom_env.replay.serializer import canonical_json
    from neutral_atom_experiments.qec_pbc.canonical import canonical_memory_program
    from neutral_atom_experiments.qec_pbc.baseline import canonical_native_inputs, execute_canonical_memory
    from neutral_atom_experiments.qec_pbc.canonical_audit import (
        audit_canonical_memory, native_to_stim, official_reference_stim)
    memory = canonical_memory_program(basis=args.basis, rounds=args.rounds)
    inputs = canonical_native_inputs(memory, seed=args.seed, initial_placement=args.initial_placement)
    fault_audit = audit_canonical_memory(memory, inputs.compiled)
    output = args.output or f'artifacts/qec-baseline-2026-10-03/{args.initial_placement}-memory-{args.basis.lower()}'
    if not fault_audit['passed']:
        from neutral_atom_experiments.qec_pbc.physical import fresh_output
        failed = fresh_output(output)
        (failed / 'fault_audit.json').write_text(canonical_json(fault_audit), encoding='utf-8')
        (failed / 'canonical.json').write_text(canonical_json(memory.to_dict()), encoding='utf-8')
        print(canonical_json({'status': 'fault_audit_failed', 'output_directory': str(failed.resolve())}), flush=True)
        return 1
    result = execute_canonical_memory(memory, output, seed=args.seed, fault_audit=fault_audit,
        wall_budget_s=args.wall_budget, initial_placement=args.initial_placement,
        progress=lambda row: print(canonical_json(row), flush=True))
    run_output = Path(result['output_directory'])
    (run_output / 'native_reference.stim').write_text(str(native_to_stim(inputs.compiled)), encoding='utf-8')
    (run_output / 'official_reference.stim').write_text(str(official_reference_stim(memory)), encoding='utf-8')
    from neutral_atom_experiments.qec_pbc.baseline_report import canonical_memory_report
    canonical_memory_report(result['output_directory'])
    print(canonical_json({key: result[key] for key in ('status', 'error', 'output_directory',
        'native_gate_count', 'gate_counts', 'plans', 'wall_seconds', 'metrics')}), flush=True)
    return 0 if result['status'] == 'completed' and fault_audit['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
