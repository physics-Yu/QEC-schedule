"""Export d=3 QEC/PBC protocol bundles and ideal semantic evidence.

Requires Python >=3.11. Physical execution is a separate explicit example;
these ideal checks never produce neutral-atom timing or fidelity estimates.
"""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from neutral_atom_experiments.qec_pbc import (
    PauliProduct, decode_ideal_memory, logical_product, lower_to_physical,
    memory_program, stabilizers)
from neutral_atom_experiments.qec_pbc.validation import bell_parity_program, simulate_ideal


def export(directory, *, rounds=3):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    cases = {'memory_z': memory_program(basis='Z', rounds=rounds),
             'memory_x': memory_program(basis='X', rounds=rounds),
             'logical_pbc_bell': bell_parity_program()}
    report = {'status': 'passed', 'scope': 'ideal instrument and encoded semantics only',
              'hardware_time_us': None, 'fidelity': None, 'cases': {}}
    for name, program in cases.items():
        compiled = lower_to_physical(program)
        folder = directory / name
        folder.mkdir(exist_ok=True)
        bundle = compiled.to_dict()
        (folder / 'bundle.json').write_text(json.dumps(bundle, indent=2), encoding='utf-8')
        (folder / 'physical_circuit.json').write_text(json.dumps({'gates': bundle['gates']}, indent=2), encoding='utf-8')
        samples = []
        for seed in (0, 1, 7):
            state, raw = simulate_ideal(compiled, seed=seed)
            outputs = compiled.classical_outputs(raw)
            if program.memory_contract is not None:
                assert not any(outputs['detectors'].values())
                assert decode_ideal_memory(program, compiled.semantic_results(raw)) == 0
            else:
                mapping = dict(compiled.bindings)
                for patch in ('A', 'B'):
                    assert all(state.expectation(dict(check.mapped(mapping).factors)) == 1
                               for check in stabilizers(patch))
                for basis in ('X', 'Z'):
                    word = logical_product(PauliProduct((('A', basis), ('B', basis)))).mapped(mapping)
                    assert state.expectation(dict(word.factors)) == 1
            samples.append({'seed': seed, 'outputs': outputs,
                            'semantic_measurements': compiled.semantic_results(raw)})
        counts = Counter(g.gate_type for g in compiled.circuit.gates)
        case = {'roles': len(program.roles), 'operations': len(program.operations),
                'native_gate_slots': len(compiled.circuit.gates), 'gate_counts': dict(counts),
                'detectors': len(program.detectors), 'samples': samples}
        (folder / 'verification.json').write_text(json.dumps(case, indent=2), encoding='utf-8')
        report['cases'][name] = {k: v for k, v in case.items() if k != 'samples'}
    modules = ROOT / 'src' / 'neutral_atom_experiments' / 'qec_pbc'
    report['source_sha256'] = {path.name: sha256(path.read_bytes()).hexdigest()
                               for path in sorted(modules.glob('*.py'))}
    (directory / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'artifacts' / 'qec-pbc-2026-10-01')
    parser.add_argument('--rounds', type=int, default=3)
    args = parser.parse_args()
    print(json.dumps(export(args.output, rounds=args.rounds), indent=2))
