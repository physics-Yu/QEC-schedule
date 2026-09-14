"""Read-only audit: identity cancellation is not a physical recompilation."""
import json
import sys
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from neutral_atom_experiments.surface_ghz import verify_gate_sequence


def audit():
    directory=ROOT/'artifacts/surface-2d'
    value=json.loads((directory/'patch_greedy/input.json').read_text(encoding='utf-8'))
    gates=sorted(value['gates'],key=lambda g:(g['column'],g['id']))
    stacks={q:[] for g in gates for q in g['qubit_ids']};removed=set();pairs=[]
    for i,g in enumerate(gates):
        qs=g['qubit_ids']
        if g['gate_type']=='H' and stacks[qs[0]] and gates[stacks[qs[0]][-1]]['gate_type']=='H':
            j=stacks[qs[0]].pop();removed.update((j,i))
            pairs.append({'first':gates[j]['id'],'second':g['id'],'qubit':qs[0]})
        else:
            for q in qs:stacks[q].append(i)
    kept=[g for i,g in enumerate(gates) if i not in removed]
    recording=json.loads((directory/'patch_greedy/recording.json').read_text(encoding='utf-8'))
    pulses=[op for op in recording['operations'] if op['kind']=='entangling_pulse']
    result={'scope':'read-only quantum input audit; no physical recompilation or UI change',
        'data_atoms':36,'measurement_ancillas':0,'measurement_operations':0,
        'original_gate_counts':dict(Counter(g['gate_type'] for g in gates)),
        'consecutive_HH_identity_pairs':pairs,'removable_H_count':len(removed),
        'simplified_gate_counts':dict(Counter(g['gate_type'] for g in kept)),
        'simplified_gate_count':len(kept),'original_ideal_GHZ':verify_gate_sequence(gates),
        'simplified_ideal_GHZ':verify_gate_sequence(kept),
        'physical_recompiled_after_simplification':False,
        'actual_CZ_batch_histogram':dict(Counter(op.get('batch_size',1) for op in pulses)),
        'max_disjoint_2q_gates_on_36_atoms':18,
        'note':'Signed stabilizer state verification is not an executed syndrome measurement.'}
    (directory/'circuit-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='consecutive_HH_identity_pairs'},ensure_ascii=False))


if __name__=='__main__':audit()
