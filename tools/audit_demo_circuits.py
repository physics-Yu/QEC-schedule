"""Audit saved demo circuits and native transversal CNOTs without transport search."""
import argparse
from collections import Counter, defaultdict
from itertools import combinations
import json
from pathlib import Path
import re

from neutral_atom_experiments import surface_ghz as ghz
from neutral_atom_experiments import surface_qec as qec
from neutral_atom_experiments import surface_qec_temporal as temporal
from neutral_atom_experiments import surface_qec_temporal_four as four

ROOT = Path(__file__).resolve().parents[1]


def normalized(g):
    return {k: g.get(k, default) for k, default in (
        ('id', None), ('gate_type', None), ('qubit_ids', []), ('parameters', []),
        ('column', None), ('condition', []), ('depends_on', []), ('readout_flip', False))}


def ordered(gates):
    return [normalized(g) for g in sorted(gates, key=lambda g: (g['column'], g['id']))]


def infer_fault(gates, temporal_mode):
    flips = [g for g in gates if g.get('readout_flip')]
    faults = [g for g in gates if g['id'] in {qec.FAULT_GATE_ID, temporal.FAULT_GATE_ID, four.FAULT_GATE_ID}]
    assert len(flips) + len(faults) <= 1
    if flips:
        match = re.fullmatch(r'round(\d+)_([XZ])(\d+)_(\d+)', flips[0]['id'])
        assert match and temporal_mode
        r, kind, patch, check = match.groups()
        return dict(kind='readout', round=int(r), patch=int(patch), check_type=kind, check_index=int(check))
    assert not faults, 'Extend audit explicitly before accepting a new injected-data demo'
    return None


def assert_cnot(gates, pairs):
    """Compare full signed Pauli-generator action, not only the final GHZ state."""
    qubits = sorted({q for pair in pairs for q in pair})
    for q in qubits:
        for initial in ((1 << q, 0, 0), (0, 1 << q, 0)):
            actual = expected = initial
            for gate in sorted(gates, key=lambda g: (g['column'], g['id'])):
                assert not gate.get('condition')
                actual = ghz.conjugate(actual, gate['gate_type'], tuple(int(x[1:]) for x in gate['qubit_ids']))
            for pair in pairs:
                expected = ghz.conjugate(expected, 'CX', pair)
            assert actual == expected, (q, initial, actual, expected)


def hh_proof(raw, optimized):
    """Every removed operation must belong to an adjacent-wire HH identity."""
    retained = {g['id'] for g in optimized}
    removed = {g['id'] for g in raw} - retained
    stacks = defaultdict(list)
    cancelled = set()
    pairs = []
    by_id = {g['id']: g for g in raw}
    for g in raw:
        qs = g['qubit_ids']
        if len(qs) == 1 and g['gate_type'] == 'H' and not g.get('condition'):
            wire = stacks[qs[0]]
            if wire and wire[-1]['gate_type'] == 'H' and not wire[-1].get('condition'):
                previous = wire[-1]
                if previous['id'] in removed and g['id'] in removed:
                    wire.pop(); cancelled.update((previous['id'], g['id']))
                    pairs.append([previous['id'], g['id']]); continue
        for q in qs:
            stacks[q].append(g)
    assert cancelled == removed, removed - cancelled
    for g in optimized:
        before = normalized(by_id[g['id']]); after = normalized(g)
        before.pop('depends_on'); after.pop('depends_on')
        assert before == after
    return pairs


def audit_one(identifier, value, seeds):
    gates = value['gates']
    report = dict(id=identifier, slots=len(gates), conditional_slots=sum(bool(g.get('condition')) for g in gates),
                  gate_counts=dict(Counter(g['gate_type'] for g in gates)))
    if identifier == 'parallel-h':
        assert [(g['gate_type'], g['qubit_ids'], g['column']) for g in gates] == [('H', [f'Q{i:03d}'], 0) for i in range(4)]
        assert not report['conditional_slots']
        return dict(report, status='passed', logical_cnot_blocks=[])
    module = {'surface-qec-ghz2': qec, 'surface-qec-temporal': temporal, 'surface-qec-temporal-four': four}.get(identifier)
    if module:
        fault = infer_fault(gates, module != qec)
        original = module.protocol(fault, optimize=False, reduce_edges=False)
        generated = module.protocol(fault)
        stages = {s['gate_id']: s['stage'] for s in original['stages']}
        assert ordered(gates) == ordered(generated['gates'])
        assert value['qec_protocol']['stages'] == generated['stages']
        raw = original['gates']; cancellations = hh_proof(raw, gates)
        report['hh_pairs_removed'] = len(cancellations)
    else:
        assert identifier == 'surface-ghz'
        original, annotations = ghz.input_payload()
        raw = original['gates']; stages = {s['gate_id']: s['stage'] for s in annotations}
        assert ordered(gates) == ordered(raw)
        cancellations = []
        assert ghz.verify_gate_sequence(sorted(gates, key=lambda g: (g['column'], g['id'])))
    logical = []
    for stage in dict.fromkeys(s for s in stages.values() if s.startswith('logical')):
        raw_stage = [g for g in raw if stages[g['id']] == stage]
        if stage == 'logical-cnot' or stage == 'logical-tree-AB': blocks = [(0, 1)]
        elif stage == 'logical-tree-AC-BD': blocks = [(0, 2), (1, 3)]
        else: blocks = [tuple(map(int, stage.removeprefix('logical-cx-').split('-')))]
        pairs = [(9*a+q, 9*b+q) for a,b in blocks for q in range(9)]
        assert_cnot(raw_stage, pairs)
        bad = list(raw_stage); bad.remove(next(g for g in bad if g['gate_type'] == 'CZ'))
        try: assert_cnot(bad, pairs)
        except AssertionError: pass
        else: raise AssertionError('Missing-CZ negative control was not rejected')
        kept = [g for g in gates if stages[g['id']] == stage]
        removed_ids = {g['id'] for g in raw_stage} - {g['id'] for g in kept}
        logical.append(dict(stage=stage, pairs=[[f'Q{a:03d}', f'Q{b:03d}'] for a,b in pairs],
            native_slots_before=len(raw_stage), native_slots_after=len(kept),
            displayed_columns={kind: sorted({g['column']+1 for g in kept if g['gate_type'] == kind}) for kind in ('H','CZ')},
            cross_stage_hh=[p for p in cancellations if removed_ids.intersection(p)],
            pauli_action_verified=True, missing_cz_negative_control='rejected'))
    report['logical_cnot_blocks'] = logical
    # Same-stage, same-wire, same-Pauli branch alternatives must contradict a reported bit.
    branches = defaultdict(list)
    for g in gates:
        if g.get('condition'):
            assert g['gate_type'] in {'X', 'Z'} and len(g['qubit_ids']) == 1
            branches[stages[g['id']], g['qubit_ids'][0], g['gate_type']].append(g)
    for group in branches.values():
        for a,b in combinations(group, 2):
            left, right = dict(a['condition']), dict(b['condition'])
            assert any(left[k] != right[k] for k in left.keys() & right.keys()), (a['id'], b['id'])
    report['conditional_alternatives_mutually_exclusive'] = True
    if module:
        runs = []
        for seed in seeds:
            state, result = module.simulate_ideal(gates, seed=seed)
            raw_state, raw_result = module.simulate_ideal(raw, seed=seed)
            key = 'verified_logical_ghz4' if module == four else 'verified_logical_ghz2'
            assert result[key] and raw_result[key]
            assert result['measurement_protocol_complete'] and raw_result['measurement_protocol_complete']
            assert result['syndrome_bits'] == raw_result['syndrome_bits']
            assert state == raw_state
            runs.append(dict(seed=seed, ghz_verified=True, raw_optimized_quantum_state_identical=True,
                conditional_paulis_applied=len(result['corrections']), conditional_slots_skipped=report['conditional_slots']-len(result['corrections'])))
        report['ideal_runs'] = runs
    return dict(report, status='passed', saved_gates_equal_generator=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--seeds',type=int,nargs='+',default=[0,7,29])
    args=parser.parse_args()
    config=json.loads((ROOT/'configs/studio/workbench.json').read_text(encoding='utf-8'))
    reports=[]
    for demo in config['demos']:
        value=json.loads((ROOT/'configs/studio'/demo['input_file']).read_text(encoding='utf-8'))
        report=audit_one(demo['id'],value,args.seeds);reports.append(report)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(reports,indent=2),encoding='utf-8')
        print(demo['id'],report['status'],report['slots'],'slots',flush=True)


if __name__ == '__main__': main()
