"""Isolated adapter to unmodified ZAC scheduling, reuse, placement and router.

Run this module in a subprocess: importing one source tree must never pollute
the application's module cache when comparing GitHub with the AE archive.
The input is a physical CZ circuit; no synthesis or QASM resynthesis occurs.
"""
from contextlib import redirect_stdout
from hashlib import sha256
from pathlib import Path
from time import perf_counter
import argparse
import importlib.metadata
import json
import sys


def compile_frontend(spec, source, output, reuse=True):
    source = Path(source).resolve()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(source))
    from zac.ds.architecture import Architecture
    from zac.zac import ZAC
    with (output / 'upstream.log').open('w', encoding='utf-8') as log, redirect_stdout(log):
        architecture = Architecture(spec['architecture'])
        architecture.preprocessing()
        compiler = ZAC()
        compiler.parse_setting(dict(name=spec['name'], dependency=True, scheduling='asap',
            trivial_placement=spec.get('initial_placement', 'fixed') != 'sa', dynamic_placement=True, reuse=reuse, resyn=False,
            routing_strategy='maximalis_sort', use_window=True, window_size=1000, use_verifier=True))
        compiler.set_architecture(architecture)
        compiler.n_q = spec['atom_count']
        compiler.g_q = [sorted(pair) for pair in spec['pairs']]
        compiler.n_g = len(compiler.g_q)
        compiler.g_s = tuple('CRZ' for _ in compiler.g_q)
        compiler.dict_g_1q_parent = {-1: []}
        initial_mode = spec.get('initial_placement', 'fixed')
        if initial_mode not in ('fixed', 'sa'):
            raise ValueError('Frontend initial_placement must be fixed or sa')
        if initial_mode == 'fixed':
            compiler.set_initial_mapping([tuple(s) for s in spec['initial_mapping']])
        compiler.qubit_mapping = []
        start = perf_counter()
        compiler.scheduling()
        if reuse:
            compiler.collect_reuse_qubit()
        else:
            compiler.reuse_qubit = [set() for _ in compiler.gate_scheduling]
        proposed = [sorted(qs) for qs in compiler.reuse_qubit]
        compiler.place_qubit_initial()
        initial_mapping = [list(s) for s in compiler.qubit_mapping[0]]
        # Evaluate both mappings with the author's exact cost implementation.
        # Save/restore RNG state: observing the score must not affect compilation.
        import random
        from zac.placer.saplacer import SAPlacer
        rng_state = random.getstate()
        scorer = SAPlacer(compiler.l2)
        scorer.n_qubit, scorer.architecture = compiler.n_q, architecture
        scorer.list_gate = compiler.gate_scheduling
        scorer.preprocessing()
        scorer.current_mapping = spec['initial_mapping']
        baseline_cost = scorer.get_cost()
        scorer.current_mapping = initial_mapping
        selected_cost = scorer.get_cost()
        random.setstate(rng_state)
        initial_info = dict(method=initial_mode, seed=0 if initial_mode == 'sa' else None,
            seconds=compiler.runtime_analysis['initial placement'], baseline_cost=baseline_cost,
            selected_cost=selected_cost, mapping=initial_mapping,
            changed_atoms=sum(a != b for a,b in zip(initial_mapping,spec['initial_mapping'])),
            objective='Author SAPlacer.get_cost; layer weights 1,0.9,0.8,0.7,0.6 then 0.6; l2=False; proxy, not physical us')
        compiler.place_qubit_intermedeiate()
        frontend_s = perf_counter() - start
        # Full author router and verifier run as separate reference evidence.
        # Their ZAIR timings are not used as this project's execution times.
        compiler.route_qubit()
        compiler.verify_scheduling(compiler.gate_scheduling_idx)
        compiler.verify_qubit_mapping(0)
        author_s = perf_counter() - start
    files = ['zac/zac.py', 'zac/scheduler/scheduler.py', 'zac/placer/placer.py',
             'zac/placer/vmplacer.py', 'zac/placer/saplacer.py', 'zac/router/router.py', 'zac/ds/architecture.py']
    result = dict(schema='zac-placement/1', source_path=str(source), reuse_enabled=reuse,
        source_hashes={f: sha256((source / f).read_bytes()).hexdigest() for f in files},
        dependencies={x: importlib.metadata.version(x) for x in ('numpy', 'scipy', 'qiskit', 'rustworkx')},
        spec=spec, initial_placement=initial_info, gate_layers=compiler.gate_scheduling_idx,
        matching_reuse=proposed, selected_reuse=[sorted(qs) for qs in compiler.reuse_qubit],
        mappings=compiler.qubit_mapping, frontend_seconds=frontend_s,
        author_compile_verify_seconds=author_s, author_verifier_executed=True)
    (output / 'placement.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    (output / 'author-zair.json').write_text(json.dumps(compiler.result_json, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--no-reuse', action='store_true')
    args = parser.parse_args()
    result = compile_frontend(json.loads(args.input.read_text(encoding='utf-8')), args.source,
                              args.output, not args.no_reuse)
    print(json.dumps(dict(layers=result['gate_layers'], reuse=result['selected_reuse'])))
