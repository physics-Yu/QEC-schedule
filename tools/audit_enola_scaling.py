"""Audit saved scaling inputs, native output counters, and model arithmetic."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('root', type=Path)
    args = cli.parse_args()
    root = args.root
    graphs = json.loads((root/'sources/graphs.json').read_text())
    rows = []
    for path in sorted(root.glob('n*_g*/*/result.json')):
        result = json.loads(path.read_text(encoding='utf-8'))
        case_path = path.parent.parent/'case.json'
        case = json.loads(case_path.read_text(encoding='utf-8'))
        assert case['gates'] == graphs[str(case['n'])][case['graph_id']]
        assert result['input_sha256'] == hashlib.sha256(case_path.read_bytes()).hexdigest()
        assert Counter(q for edge in case['gates'] for q in edge)==Counter({q:3 for q in range(case['n'])})
        row = dict(n=result['n'], method=result['method'], status=result['status'], public_input_exact=True)
        if result['status'] == 'completed':
            score = result['score']
            transfers = spectators = pulses = 0
            pairs = Counter()
            if result['method'] == 'enola':
                program = json.loads((path.parent/'program.json').read_text())
                for op in program:
                    if op['type'] == 'Rydberg' and op['gates']:
                        pulses += 1
                        pairs.update(tuple(sorted((g['q0'],g['q1']))) for g in op['gates'])
                        spectators += case['n'] - 2*len(op['gates'])
                    elif op['type'] in ('Activate','Deactivate'):
                        transfers += len(op['pickup_qs' if op['type']=='Activate' else 'dropoff_qs'])
                assert score['checks']['terminal_aod_empty']
            else:
                events = json.loads((path.parent/'score-events.json').read_text())
                for op in events:
                    if op['kind'] == 'cz':
                        pulses += 1
                        pairs.update(tuple(sorted(pair)) for pair in op['pairs'])
                        spectators += len(op['exposed_atoms']) - 2*len(op['pairs'])
                    elif op['kind'] in ('load','store'):
                        transfers += len(op['atoms'])
                assert result['checks']['terminal_all_stored_in_sz']
                assert result['checks']['author_rearrangement_time_equal']
            assert pairs == Counter(tuple(sorted(pair)) for pair in case['gates'])
            assert (transfers,spectators,pulses)==(score['transfers'],score['spectator_excitations'],score['pulses'])
            assert math.isclose(score['losses']['two_qubit'], -len(case['gates'])*math.log(.995)-spectators*math.log(.9975),rel_tol=1e-10)
            assert math.isclose(score['losses']['transfer'], -transfers*math.log(.999),rel_tol=1e-10)
            valid = all(0 <= idle < 1500000 for idle in score['idle_us'])
            assert score['model_valid'] == valid
            if valid:
                decoherence = -sum(math.log1p(-t/1500000) for t in score['idle_us'])
                assert math.isclose(score['losses']['decoherence'],decoherence,rel_tol=1e-10,abs_tol=1e-8)
                assert math.isclose(score['log_fidelity'], -sum(score['losses'].values()),rel_tol=1e-10)
                assert score['fidelity'] == math.exp(score['log_fidelity'])
            else:
                assert score['fidelity'] is None and score['losses']['decoherence'] is None
            row.update(gates_exact=True, counters_exact=True, score_arithmetic=True, model_valid=valid)
        else:
            row.update(failure_preserved=True, worker_log=(path.parent/'worker.log').exists(),
                       native_program_present=any((path.parent/name).exists() for name in ('program.json','program.naviz')))
        rows.append(row)
    value = dict(status='passed', rows=rows,
                 scope='Public input, raw instruction counts and scoring arithmetic. No new continuous geometry or quantum-state validation.')
    (root/'suite-audit.json').write_text(json.dumps(value,indent=2),encoding='utf-8')
    print(json.dumps(dict(status='passed',results=len(rows)),indent=2))


if __name__ == '__main__':
    main()
