"""Extract the historical 12-pair failure with its complete spectator world."""
from pathlib import Path
import gzip
import hashlib
import json

ROOT = Path(__file__).resolve().parents[1]


def main():
    source = ROOT / 'artifacts/demos/joint-factory-accepted-20261008/protocols/T/e0-initialize.json.gz'
    plan = json.loads(gzip.decompress(source.read_bytes()))['physical_plan']
    module = plan['module_composition']['dependency_graph']['modules'][6]
    ids = set(module['source_ids'])
    pulses = [a for a in plan['atom_program']['actions'] if a['payload'].get('name') == 'CZ'
              and any(s['physical_op_id'] in ids for s in a['payload']['pair_sources'])]
    assert len(ids) == 12 and [len(a['payload']['pairs']) for a in pulses] == [11, 1]
    fixture = {
        'schema_version': 'CommittedBatchRegression/0.1',
        'provenance': {
            'source_file': source.relative_to(ROOT).as_posix(),
            'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'module_id': module['id'],
            'old_pulse_pairs': [len(a['payload']['pairs']) for a in pulses],
            'old_pulse_start_us': [a['t_start_us'] for a in pulses],
            'scope': 'selected source leaf and complete initial geometry; no cached runtime results',
        },
        'dag': module['dag'],
        'world': plan['atom_program']['initial_state'],
        'device': json.loads((source.parent / 'device.json').read_bytes()),
    }
    target = ROOT / 'tests/fixtures/joint_batch_12_pairs.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((json.dumps(fixture, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    print(json.dumps({'fixture': str(target), 'atoms': len(fixture['world']['atoms']), 'pairs': len(ids)}))


if __name__ == '__main__':
    main()
