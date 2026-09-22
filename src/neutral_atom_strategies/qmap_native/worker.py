"""Run exclusively in the isolated QMAP 3.5.0 / Bench 2.1.0 environment."""
from hashlib import sha256
from importlib.metadata import version
import importlib.util
import json
from pathlib import Path
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[3]


def author_module():
    path = ROOT/'third_party/qmap/eval_ids_relaxed_routing.py'
    spec = importlib.util.spec_from_file_location('qmap_author_eval', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def compile_request(request, directory):
    from mqt.core import load
    from mqt.qmap.na.zoned import (PlacementMethod, RoutingAwareCompiler,
                                 RoutingMethod, ZonedNeutralAtomArchitecture)
    from qiskit import QuantumCircuit
    versions = {name: version(name) for name in ('mqt.qmap', 'mqt.bench', 'mqt.core', 'qiskit')}
    if versions['mqt.qmap'] != '3.5.0' or versions['mqt.bench'] != '2.1.0':
        raise RuntimeError(f'Paper dependency mismatch: {versions}')
    upstream = author_module()
    prep = perf_counter()
    if 'benchmark' in request:
        from mqt.bench import BenchmarkLevel, get_benchmark
        name = request['benchmark']
        qc = get_benchmark(name, BenchmarkLevel.INDEP, request['atom_count'])
        qc = upstream.transpile_benchmark(name, qc)
    else:
        name = request.get('name', 'editable-circuit')
        qc = QuantumCircuit(request['atom_count'])
        for gate in request['gates']:
            kind = gate['type'].lower()
            operands = gate['qubits']
            if kind not in {'h', 'x', 'y', 'z', 't', 'cz'}:
                raise ValueError(f'Native unitary frontend does not support {kind}; nothing is stripped')
            getattr(qc, kind)(*operands)
    circuit = load(qc)
    circuit.qasm3(str(directory/'input.qasm'))
    architecture = request.get('architecture')
    if architecture is None:
        architecture = json.loads((ROOT/'third_party/qmap/square_architecture.json').read_text())
    arch = ZonedNeutralAtomArchitecture.from_json_string(json.dumps(architecture))
    config = dict(log_level='error', max_filling_factor=.9, use_window=True,
        window_min_width=16, window_ratio=1.0, window_share=.8,
        placement_method=PlacementMethod.ids, deepening_factor=.01, deepening_value=0.,
        lookahead_factor=.4, reuse_level=5., trials=4, queue_capacity=100,
        warn_unsupported_gates=False)
    routing = request.get('routing', 'strict')
    if routing not in {'strict', 'relaxed'}:
        raise ValueError('routing must be strict or relaxed')
    config['routing_method'] = getattr(RoutingMethod, routing)
    if routing == 'relaxed':
        config['prefer_split'] = 1.
    compiler = RoutingAwareCompiler(arch, **config)
    preparation_seconds = perf_counter() - prep
    start = perf_counter()
    code = compiler.compile(circuit)
    native_call_seconds = perf_counter() - start
    stats = dict(compiler.stats())
    (directory/'program.naviz').write_text(code, encoding='utf-8')
    (directory/'architecture.json').write_text(json.dumps(architecture, indent=2), encoding='utf-8')
    # Apply exactly the author's timing metric without altering executable output.
    metric_code = '\n'.join(line for line in code.splitlines() if not line.startswith('@+ u'))
    evaluator = upstream.Evaluator(architecture, str(directory/'author-metrics.csv'))
    evaluator.evaluate(name, circuit, routing, metric_code, stats)
    evaluator.print_header()
    evaluator.print_data()
    return dict(schema=1, status='compiled', engine='mqt.qmap.native.C++', versions=versions,
        input_sha256=sha256((directory/'input.qasm').read_bytes()).hexdigest(),
        naviz_sha256=sha256(code.encode()).hexdigest(), architecture=architecture,
        routing=routing, preparation_seconds=preparation_seconds,
        native_call_seconds=native_call_seconds, stats=stats,
        author_metrics=dict(cz_count=evaluator.two_qubit_gates,
            cz_layers=evaluator.two_qubit_gate_layer, max_parallel_cz=evaluator.max_two_qubit_gates,
            rearrangement_us=evaluator.rearrangement_duration),
        code=code, physical_validation='pending')


if __name__ == '__main__':
    source, output = map(Path, sys.argv[1:])
    result = compile_request(json.loads(source.read_text(encoding='utf-8')), output.parent)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf-8')
