"""Export an explicitly native-instruction inspector, not an Env recording."""
import argparse
from collections import defaultdict, deque
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_view_parser', ROOT/'src/neutral_atom_strategies/qmap_native/naviz.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def export(directory):
    summary = json.loads((directory/'summary.json').read_text())
    audit = json.loads((directory/'audit.json').read_text())
    code = (directory/'program.naviz').read_text()
    if summary['request'].get('name') != 'ghz-chain' or summary['request']['atom_count'] != 5000:
        raise ValueError('This presentation is specifically the audited 5000-qubit GHZ-chain benchmark')
    assert audit['status'] == 'passed' and summary['status'] == 'compiled'
    assert hashlib.sha256(code.encode()).hexdigest() == summary['naviz_sha256']
    assert hashlib.sha256((directory/'input.qasm').read_bytes()).hexdigest() == summary['input_sha256']
    initial, commands = module.parse(code)
    layers = {layer['source_line']: layer['pairs'] for layer in json.loads((directory/'cz-layers.json').read_text())}
    gates, queues = [], defaultdict(deque)
    for line in (directory/'input.qasm').read_text().splitlines():
        if match := re.fullmatch(r'(h|cz) q\[(\d+)\](?:, q\[(\d+)\])?;', line):
            kind = match[1].upper()
            qubits = list(map(int, filter(None, match.groups()[1:])))
            queues[(kind, *sorted(qubits))].append(len(gates))
            gates.append([kind, qubits, None])
    ops = []
    for index, op in enumerate(commands):
        kind = {'load':0, 'move':1, 'store':2, 'cz':3, 'u':4}[op.kind]
        ids = [int(q[4:]) for q in op.atoms]
        effects = []
        if kind == 1:
            values = [[int(q[4:]), *point] for q, point in op.moves]
        elif kind == 3:
            values = [q for pair in layers[op.line] for q in pair]
            effects = [('CZ', *sorted(pair)) for pair in layers[op.line]]
        else:
            values = ids
            if kind == 4:
                effects = [('H', q) for q in ids]
        gate_ids = []
        for effect in effects:
            gate_id = queues[effect].popleft()
            gates[gate_id][2] = index
            gate_ids.append(gate_id)
        ops.append([kind, op.line, values, gate_ids])
    assert len(gates) == summary['input_gate_total'] and all(not q for q in queues.values())
    data = dict(schema=1, origin='native_naviz_not_env', summary=summary, audit=audit,
                architecture=json.loads((directory/'architecture.json').read_text()),
                initial=[initial[f'atom{i}'] for i in range(len(initial))], ops=ops, gates=gates)
    failure = directory.parent/'graphstate5000/summary.json'
    data['comparison'] = json.loads(failure.read_text()) if failure.exists() else None
    source = ROOT/'src/neutral_atom_app/visualization'
    html = (source/'qmap_native_inspector.html').read_text(encoding='utf-8')
    html = html.replace('__NATIVE_DATA__', json.dumps(data, separators=(',', ':')).replace('</', '<\\/'))
    html = html.replace('__NATIVE_JS__', (source/'qmap_native_inspector.js').read_text(encoding='utf-8'))
    destination = directory/'native-inspector.html'
    destination.write_text(html, encoding='utf-8')
    (directory/'native-view-data.json').write_text(json.dumps(data, separators=(',', ':')), encoding='utf-8')
    print(json.dumps(dict(output=str(destination), atoms=len(initial), gates=len(gates), instructions=len(ops), bytes=destination.stat().st_size)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    export(parser.parse_args().directory.resolve())
