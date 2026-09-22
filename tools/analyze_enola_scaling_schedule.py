"""Diagnose input-order scheduling versus commuting-CZ coloring; no placement.

Run in the pinned Enola interpreter. This does not claim compiled movement or
improved execution time for the reordered circuits.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys


def asap(n, gates, capacity):
    available = [0] * n
    layers = []
    for a, b in gates:
        layer = max(available[a], available[b])
        while layer < len(layers) and len(layers[layer]) >= capacity:
            layer += 1
        if layer == len(layers):
            layers.append([])
        layers[layer].append([a, b])
        available[a] = available[b] = layer + 1
    return layers


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--root', type=Path, required=True)
    cli.add_argument('--source', type=Path, required=True)
    args = cli.parse_args()
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(args.source))
    from enola.scheduler.gate_scheduler import gate_scheduling
    graphs = json.loads((args.root / 'sources/graphs.json').read_text())
    rows = []
    for n in [30,100,300,1000,2000,5000]:
        edges = graphs[str(n)][0]
        schedule = gate_scheduling(n, edges)
        colored = [[edges[i] for i in layer] for layer in schedule]
        for layer in colored:
            assert len({q for pair in layer for q in pair}) == 2*len(layer)
        assert Counter(tuple(sorted(e)) for layer in colored for e in layer) == Counter(tuple(sorted(e)) for e in edges)
        reordered = [edge for layer in colored for edge in layer]
        original_layers = asap(n, edges, 306)
        reordered_layers = asap(n, reordered, 306)
        run = args.root/f'n{n}_g0/qmap/result.json'
        result = json.loads(run.read_text(encoding='utf-8')) if run.exists() else {}
        if result.get('status') == 'completed':
            assert result['score']['pulses'] == len(original_layers)
        rows.append(dict(n=n,graph_id=0,cz_count=len(edges),
                         original_order_asap_layers=len(original_layers),
                         edge_coloring_layers=len(colored),
                         reordered_asap_layers_under_capacity306=len(reordered_layers),
                         actual_native_pulses=result.get('score',{}).get('pulses'),
                         input_cz_multiset_preserved=True,
                         reordered_movement_compile='not_run'))
    out = dict(scope='CZ-only scheduling ablation. No reordered placement, routing or fidelity result.',
               source_sha256=hashlib.sha256((args.source/'enola/scheduler/gate_scheduler.py').read_bytes()).hexdigest(),
               rows=rows)
    (args.root/'scheduling-diagnosis.json').write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps(out,indent=2))


if __name__ == '__main__':
    main()
