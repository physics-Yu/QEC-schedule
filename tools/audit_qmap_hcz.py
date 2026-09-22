"""Independent H/CZ gate/holder/endpoint audit, NOT a swept-path audit.

CZ gates may commute within each qubit's uninterrupted CZ block. H boundaries
must be respected. This covers both graph-state and H-CZ-H GHZ-chain inputs.
"""
import argparse
from collections import Counter, deque
import importlib.util
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('qmap_naviz_audit_parser',
    ROOT / 'src/neutral_atom_strategies/qmap_native/naviz.py')
parser_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = parser_module
spec.loader.exec_module(parser_module)


def audit(directory):
    qasm = (directory / 'input.qasm').read_text(encoding='utf-8')
    n = int(re.search(r'qubit\[(\d+)\]', qasm)[1])
    expected = Counter()
    expected_h = Counter()
    sequences = {q: [] for q in range(n)}
    for line in qasm.splitlines():
        if match := re.fullmatch(r'cz q\[(\d+)\], q\[(\d+)\];', line):
            a, b = sorted(map(int, match.groups()))
            expected[(a, b)] += 1
            for q, partner in ((a, b), (b, a)):
                if not sequences[q] or sequences[q][-1] == 'H':
                    sequences[q].append(Counter())
                sequences[q][-1][partner] += 1
        elif match := re.fullmatch(r'h q\[(\d+)\];', line):
            expected_h[int(match[1])] += 1
            sequences[int(match[1])].append('H')
        elif not (line.startswith(('//', 'OPENQASM', 'include', 'qubit', 'bit')) or not line.strip()):
            raise ValueError(f'Not the supported H/CZ input: {line}')
    pending = {q: deque(items) for q, items in sequences.items()}

    def consume(q, partner=None):
        assert pending[q], f'Extra gate on qubit {q}'
        if partner is None:
            assert pending[q][0] == 'H', f'H crossed an input CZ dependency on {q}'
            pending[q].popleft()
        else:
            block = pending[q][0]
            assert isinstance(block, Counter) and block[partner] > 0, f'Unexpected CZ dependency {q}, {partner}'
            block[partner] -= 1
            if not any(block.values()):
                pending[q].popleft()
    positions, instructions = parser_module.parse((directory / 'program.naviz').read_text())
    assert set(positions) == {f'atom{i}' for i in range(n)}
    architecture = json.loads((directory / 'architecture.json').read_text())
    pair_sites = []
    storage = set()
    for zone in architecture['storage_zones']:
        for slm in zone['slms']:
            storage.update((slm['location'][0] + c * slm['site_separation'][0],
                            slm['location'][1] + r * slm['site_separation'][1])
                           for r in range(slm['r']) for c in range(slm['c']))
    for zone in architecture['entanglement_zones']:
        a, b = zone['slms']
        for r in range(a['r']):
            for c in range(a['c']):
                pair_sites.append(tuple((s['location'][0] + c * s['site_separation'][0],
                                         s['location'][1] + r * s['site_separation'][1])
                                        for s in (a, b)))
    ez_sites = {p for pair in pair_sites for p in pair}
    actual, actual_h, kinds = Counter(), Counter(), Counter()
    loaded = set()
    layers = []
    for op in instructions:
        kinds[op.kind] += 1
        if op.kind == 'load':
            assert not loaded.intersection(op.atoms), f'Double load at {op.line}'
            loaded.update(op.atoms)
        elif op.kind == 'store':
            assert set(op.atoms) <= loaded, f'Store without load at {op.line}'
            loaded.difference_update(op.atoms)
        elif op.kind == 'move':
            assert set(dict(op.moves)) <= loaded, f'Move without support at {op.line}'
            positions.update(op.moves)
        elif op.kind == 'u':
            assert all(abs(x-y) < 1e-5 for x,y in zip(op.parameters, (math.pi/2, 0, math.pi)))
            for atom in op.atoms:
                q = int(atom[4:])
                consume(q)
                actual_h[q] += 1
        elif op.kind == 'cz':
            occupied = {p: q for q, p in positions.items()}
            assert len(occupied) == n, f'Overlapping atom endpoints at CZ {op.line}'
            in_ez = {q for q,p in positions.items() if any(
                lower[0] <= p[0] <= upper[0] and lower[1] <= p[1] <= upper[1]
                for lower, upper in architecture['rydberg_range'])}
            paired = set()
            batch = []
            for left, right in pair_sites:
                a, b = occupied.get(left), occupied.get(right)
                assert bool(a) == bool(b), f'Unpaired EZ atom at {op.line}'
                if a:
                    pair = tuple(sorted((int(a[4:]), int(b[4:]))))
                    consume(pair[0], pair[1])
                    consume(pair[1], pair[0])
                    actual[pair] += 1
                    paired.update((a, b))
                    batch.append(pair)
            assert paired == in_ez
            layers.append(dict(source_line=op.line, pairs=batch))
        else:
            raise ValueError(f'Unsupported H/CZ operation: {op.kind}')
    assert actual == expected, f'CZ mismatch: missing={expected-actual}, extra={actual-expected}'
    assert actual_h == expected_h
    assert all(not remaining for remaining in pending.values())
    assert not loaded, 'Terminal AOD still loaded'
    assert all(p in storage for p in positions.values()), 'Terminal atom outside SZ sites'
    assert len(set(positions.values())) == n
    result = dict(status='passed', qubits=n, h_count=sum(actual_h.values()),
                  cz_count=sum(actual.values()), cz_layers=len(layers),
                  max_parallel_cz=max(map(lambda x: len(x['pairs']), layers)),
                  instruction_counts=dict(kinds), terminal_all_stored_in_sz=True,
                  gate_pairs_exact=True, per_qubit_h_cz_dependencies=True,
                  scope='H/CZ multiplicity and per-qubit order modulo CZ commutation, holder bookkeeping and CZ/terminal endpoints',
                  continuous_path_validation='not_run', local_env_execution='not_run')
    (directory / 'audit.json').write_text(json.dumps(result, indent=2))
    (directory / 'cz-layers.json').write_text(json.dumps(layers, indent=2))
    return result


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('directory', type=Path)
    print(json.dumps(audit(cli.parse_args().directory), indent=2))
