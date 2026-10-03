"""Export the Shor15/PBC/encoded-parity milestone with separate contracts."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from neutral_atom_experiments.qec_pbc.adaptive_pbc import compile_adaptive_pbc, audit_adaptive_pbc
from neutral_atom_experiments.qec_pbc.encoded_ppm import (
    encoded_parity_program, compile_encoded_parity, audit_encoded_parity,
    verify_encoded_parity_instrument)
from neutral_atom_experiments.qec_pbc.encoded_physical import execute_encoded_parity
from neutral_atom_experiments.qec_pbc.physical import fresh_output
from neutral_atom_experiments.qec_pbc.shor15 import build_shor15, arithmetic_prefix, run_shor15
from neutral_atom_experiments.qec_pbc.shor_frontend import compile_arithmetic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--fault-audit', action='store_true', help='Exhaustive declared single-native-fault parity audit')
    parser.add_argument('--physical', action='store_true', help='Full ZZ and XX Executor runs, including independent replay')
    parser.add_argument('--wall-budget', type=float, default=2400)
    args = parser.parse_args()
    output = fresh_output(args.output)
    circuit = build_shor15()
    shor = run_shor15(seed=args.seed)
    source = compile_arithmetic(arithmetic_prefix(circuit))
    adaptive = compile_adaptive_pbc(source, resource_quality='ideal_reference',
        resource_provenance='Explicit ideal logical resources for milestone verification; no physical factory')
    adaptive_audit = audit_adaptive_pbc(source, seed=args.seed)
    for name, value in (('shor15_circuit.json', circuit.to_dict()), ('shor15_report.json', shor),
                        ('arithmetic_pauli.json', source.to_dict()),
                        ('arithmetic_measurement_program.json', adaptive.to_dict()),
                        ('arithmetic_measurement_audit.json', adaptive_audit)):
        (output/name).write_text(json.dumps(value, indent=2), encoding='utf-8')
    parity_reports = {}
    for basis in ('Z', 'X'):
        protocol = encoded_parity_program(basis=basis)
        compiled = compile_encoded_parity(protocol)
        instrument = verify_encoded_parity_instrument(protocol, compiled, seeds=(args.seed,))
        report = {'instrument_audit': instrument, 'physical_requested': args.physical}
        for label, value in (('protocol', protocol.to_dict()), ('compiled', compiled.to_dict()),
                             ('instrument_audit', instrument)):
            (output/f'encoded_{basis.lower()}{basis.lower()}_{label}.json').write_text(
                json.dumps(value, indent=2), encoding='utf-8')
        if args.fault_audit:
            calibration = encoded_parity_program(basis=basis, input_bases=(basis, basis))
            report['native_fault_parity_audit'] = audit_encoded_parity(calibration)
            (output/f'encoded_{basis.lower()}{basis.lower()}_fault_audit.json').write_text(
                json.dumps(report['native_fault_parity_audit'], indent=2), encoding='utf-8')
        if args.physical:
            report['physical'] = execute_encoded_parity(protocol,
                output/f'encoded-{basis.lower()}{basis.lower()}-physical', seed=args.seed,
                wall_budget_s=args.wall_budget,
                progress=lambda row: print(json.dumps(row), flush=True))
        parity_reports[basis] = report
    passed = (shor['success'] and adaptive_audit['passed']
        and all(r['instrument_audit']['passed'] for r in parity_reports.values())
        and all(r.get('native_fault_parity_audit', {}).get('passed', True) for r in parity_reports.values())
        and all(r.get('physical', {}).get('status', 'completed') == 'completed' for r in parity_reports.values()))
    summary = {'schema': 'qec-shor15-stage/1', 'passed': passed,
        'output_directory': str(output.resolve()), 'seed': args.seed,
        'complete_shor_logical_reference': shor['success'],
        'arithmetic_resource_measurement_bridge': adaptive_audit,
        'encoded_parity': parity_reports,
        'full_shor_pbc_compiled': False, 'full_shor_encoded': False,
        'full_shor_physical_executed': False,
        'remaining': ['inverse-QFT CP synthesis and error budget',
                      'encoded mixed/Y Pauli and Clifford feedback',
                      'encoded resource preparation/injection and full algorithm physical execution']}
    (output/'stage_report.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps({'passed': passed, 'factors': shor['factors'],
        'resource_consumptions': len(adaptive.injections), 'output': str(output.resolve()),
        'full_shor_physical_executed': False}, indent=2))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
