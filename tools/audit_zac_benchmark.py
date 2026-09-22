"""Audit saved large runs against inputs, trace effects, phases and terminal states."""
from collections import Counter
from hashlib import sha256
from pathlib import Path
import argparse
import json
import math
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from neutral_atom_env.replay.serializer import canonical_json


def audit(root):
    root = Path(root)
    read = lambda p: json.loads(p.read_text(encoding='utf-8'))
    manifest = read(root/'benchmark.json')
    assert manifest['status'] == 'finished'
    assert sha256(canonical_json(manifest['contract']).encode()).hexdigest() == manifest['contract_sha256']
    counts = Counter()
    for case in manifest['cases']:
        hashes = []
        for mode, record in case['variants'].items():
            counts[record['status']] += 1
            assert record['status'] in {'completed', 'failed', 'timeout', 'cancelled'}
            directory = root / case['id'] / mode
            assert read(directory/'worker.json') == record
            if 'result' not in record:
                assert record.get('error')
                continue
            result = read(directory/'result.json')
            assert result == record['result']
            initial_text = (directory/'initial.json').read_text(encoding='utf-8')
            hashes.append(sha256(initial_text.encode()).hexdigest())
            assert hashes[-1] == result['initial_sha256']
            initial, final = json.loads(initial_text), read(directory/'checkpoint.json')
            trace = [json.loads(s) for s in (directory/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
            effects = Counter(g for r in trace if r.get('effect_completed') for g in r.get('effect_gate_ids',[]))
            expected = Counter({f'g{i:04d}':1 for i in range(len(case['spec']['pairs']))})
            assert all(effects[g] <= expected[g] for g in effects)
            assert (effects == expected) == result['effects_once']
            assert sum(effects.values()) == result['metrics']['completed_gate_count']
            total = result['metrics']['episode_wall_time_us']
            assert math.isclose(sum(result['phase_time_us'].values()), total, abs_tol=1e-6)
            placement = read(directory/'upstream/placement.json')
            assert Counter(g for layer in placement['gate_layers'] for g in layer) == Counter(range(len(expected)))
            assert len(placement['gate_layers']) == case['depth']
            assert placement['spec'] == case['spec']
            if record['status'] == 'completed':
                assert result['replay_equal'] and result['terminal_verified'] and result['effects_once']
                assert all(r['passed'] for r in result['reuse_audit'])
                assert len(result['reuse_audit']) == sum(map(len,result['selected_reuse'][:-1]))
                # These are serialized hardware/holder fields, not strategy declarations.
                for key in ('placement', 'slm_enabled', 'aod'):
                    assert initial[key] == final[key], (case['id'],mode,key)
            else:
                assert result['error'] or result['replay_error'] or not result['effects_once']
        if len(hashes)==2:
            assert hashes[0] == hashes[1]
    report = dict(status='passed', cases=len(manifest['cases']), variants=dict(counts),
                  checks=['contract hash', 'paired initial state', 'trace exactly once', 'ASAP depth',
                          'phase accounting', 'residency audit coverage', 'full terminal fields'])
    (root/'audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('output',type=Path)
    print(json.dumps(audit(p.parse_args().output),indent=2))
