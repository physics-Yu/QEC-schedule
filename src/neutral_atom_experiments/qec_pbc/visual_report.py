"""Run six independently checked component experiments and render their evidence.

This viewer does not execute quantum hardware or synthesize atom trajectories.
"""
from collections import Counter
from hashlib import sha256
import csv
import json
from pathlib import Path

import numpy as np

from .shor_frontend import ArithmeticProgram, compile_arithmetic, expand_clifford_t, import_gidney_modexp, resource_report
from .visual_quantum_experiments import quantum_experiment_data, _unitary
from .visual_backend_experiments import backend_experiment_data
from .visual_noise_experiments import noise_experiment_data


def shor_experiment_data(qasm_path):
    arithmetic = import_gidney_modexp(qasm_path)
    truth = []
    for exponent in range(1024):
        value = exponent << 5
        for kind, qs in arithmetic.gates:
            if kind != 'H' and all(value >> q & 1 for q in qs[:-1]):
                value ^= 1 << qs[-1]
        expected = pow(2, exponent, 21)
        passed = value >> 5 == exponent and value & 31 == expected
        if not passed:
            raise AssertionError(f'Modular exponentiation oracle failed at {exponent}')
        truth.append({'exponent': exponent, 'output': value & 31, 'expected': expected,
                      'exponent_restored': value >> 5 == exponent, 'passed': passed})
    pauli = compile_arithmetic(arithmetic)
    small = ArithmeticProgram(('a', 'b', 't'), (('CCX', (0, 1, 2)),), 'independent Toffoli reference')
    small_gates = expand_clifford_t(small)
    small_u = _unitary(small_gates, small.wires)
    expected_u = np.eye(8, dtype=complex)
    expected_u[:, [6, 7]] = expected_u[:, [7, 6]]
    error = float(np.max(np.abs(small_u - expected_u)))
    if error > 1e-12:
        raise AssertionError('Phase-sensitive Toffoli oracle failed')
    weights = Counter(len(r.observable.factors) for r in pauli.rotations)
    return {'id': 'E6', 'title': 'N=21 preparation and modular exponentiation',
        'scope': 'logical arithmetic and exact Pauli compilation; no QFT, factory or atom execution',
        'resources': resource_report(arithmetic), 'compiled_program': pauli.to_dict(),
        'input_gates': [{'name': kind, 'wires': [arithmetic.wires[q] for q in qs]} for kind, qs in arithmetic.gates],
        'wire_order': list(arithmetic.wires), 'truth_table': truth,
        'rotation_support_histogram': [{'weight': w, 'count': count} for w, count in sorted(weights.items())],
        'toffoli': {'input_gates': [{'name': 'CCX', 'wires': list(small.wires)}],
            'expanded_gates': [{'name': g.name, 'wires': list(g.wires)} for g in small_gates],
            'wires': list(small.wires), 'unitary_max_abs_error': error,
            'truth_table': [{'input': format(i, '03b'), 'output': format(i ^ (1 if i >= 6 else 0), '03b')} for i in range(8)]}}


def build_experiment_data(qasm_path, *, shots=20000, seed=17):
    quantum = quantum_experiment_data()
    backend = backend_experiment_data()
    data = {e['id']: e for e in quantum['experiments']}
    data.update(E2=backend['E2'], E3=backend['E3'],
                E5=noise_experiment_data(shots=shots, seed=seed), E6=shor_experiment_data(qasm_path))
    source_dir = Path(__file__).parent
    hashes = {p.name: sha256(p.read_bytes()).hexdigest() for p in source_dir.glob('*')
              if p.suffix in {'.py', '.html', '.js'}}
    return {'schema': 'qec-component-visual-delivery/1', 'experiments': data,
            'source_sha256': hashes, 'seed': seed, 'shots_per_noise_point': shots,
            'noise_scan_shots': shots * 30,
            'scope': 'component reference experiments; hardware execution only at separately linked Stage A reference',
            'delivery_status': 'User rejected physical PBC/T-injection delivery; reference experiments only',
            'implementation_status': {
                'exact_ppr_unitary': True, 'ideal_injection_reference': True,
                'adaptive_pbc_measurement_circuit': False,
                'encoded_magic_state_preparation': False,
                'magic_injection_physical_circuit': False,
                'magic_injection_executor_run': False},
            'validation': {'ppr_unitary_error': data['E1']['unitary_max_abs_error'],
                'injection_cases': len(data['E4']['cases']),
                'stabilizers_preserved': data['E3']['all_stabilizers_preserved'],
                'modexp_truth_cases': len(data['E6']['truth_table']),
                'toffoli_unitary_error': data['E6']['toffoli']['unitary_max_abs_error']}}


def _write_tables(output, data):
    with (output / 'noise-scan.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        fields = ['basis', 'scenario', 'event_probability', 'shots', 'seed', 'failures',
                  'logical_failure_probability', 'wilson_low', 'wilson_high']
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for curve in data['experiments']['E5']['curves']:
            for point in curve['points']:
                writer.writerow({**{k: point[k] for k in fields if k in point},
                    'basis': curve['basis'], 'scenario': curve['scenario'],
                    'wilson_low': point['wilson_95'][0], 'wilson_high': point['wilson_95'][1]})
    with (output / 'modexp-truth.csv').open('w', newline='', encoding='utf-8-sig') as stream:
        rows = data['experiments']['E6']['truth_table']
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def _scientific_plot(output, data):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    labels = {'gate_only': 'Gate noise only', 'readout_only': 'Readout noise only', 'both': 'Gate + readout'}
    figure, axes = plt.subplots(1, 2, figsize=(10, 4.2), sharey=True, constrained_layout=True)
    for axis, basis in zip(axes, ('X', 'Z')):
        for curve in data['experiments']['E5']['curves']:
            if curve['basis'] != basis:
                continue
            x = [p['event_probability']*100 for p in curve['points']]
            y = [p['logical_failure_probability']*100 for p in curve['points']]
            lo = [(p['logical_failure_probability']-p['wilson_95'][0])*100 for p in curve['points']]
            hi = [(p['wilson_95'][1]-p['logical_failure_probability'])*100 for p in curve['points']]
            axis.errorbar(x, y, yerr=[lo, hi], marker='o', capsize=3, label=labels[curve['scenario']])
        axis.set_title(f'{basis} memory, d=3, 3 rounds')
        axis.set_xlabel('Synthetic event probability (%)')
        axis.grid(alpha=0.2)
        axis.legend(fontsize=8)
    axes[0].set_ylabel('Decoded logical failure probability (%)')
    figure.suptitle(f'Native H/CZ reference; {data["shots_per_noise_point"]:,} shots/point; Wilson 95% CI', fontsize=11)
    for extension in ('svg', 'png', 'pdf'):
        figure.savefig(output / f'noise-scan.{extension}', dpi=180)
    plt.close(figure)


def write_visual_report(output, data):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(data, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/')
    (output / 'experiments.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    source_dir = Path(__file__).parent
    page = (source_dir / 'visual_report.html').read_text(encoding='utf-8')
    page = page.replace('__EXPERIMENT_DATA__', encoded)
    for key, filename in [('__QUANTUM_PANELS__', 'visual_quantum_panels.js'),
                          ('__BACKEND_PANELS__', 'visual_backend_panels.js'),
                          ('__NOISE_PANELS__', 'visual_noise_panels.js')]:
        page = page.replace(key, (source_dir / filename).read_text(encoding='utf-8'))
    if any(marker in page for marker in ('__EXPERIMENT_DATA__', '__QUANTUM_PANELS__', '__BACKEND_PANELS__', '__NOISE_PANELS__')):
        raise ValueError('Unresolved report template marker')
    (output / 'index.html').write_text(page, encoding='utf-8')
    _write_tables(output, data)
    _scientific_plot(output, data)
    return output / 'index.html'
