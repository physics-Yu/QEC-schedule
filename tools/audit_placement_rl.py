"""Audit saved independent discrete witnesses and frozen dataset/source manifests."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from neutral_atom_strategies.placement_rl.model import Circuit, Hardware, Scenario, CompilerConfig, CompileResult
from neutral_atom_strategies.placement_rl.compiler import audit_result


def audit(directory):
    manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    summary = json.loads((directory/'summary.json').read_text(encoding='utf-8'))
    errors = []
    digests = [row['digest'] for rows in manifest['splits'].values() for row in rows]
    if len(digests) != len(set(digests)):
        errors.append('Identical circuit data appears across splits')
    for rows in manifest['splits'].values():
        for row in rows:
            actual = sha256(json.dumps(row['circuit'], sort_keys=True).encode()).hexdigest()
            if actual != row['digest']:
                errors.append(f'Circuit digest mismatch: {row["id"]}')
    for name, expected in manifest['source_sha256'].items():
        path = directory/'source-snapshot'/name
        if not path.exists() or sha256(path.read_bytes()).hexdigest() != expected:
            errors.append(f'Missing/mismatched frozen source: {name}')
        if name.replace('\\', '/').endswith(('/placement_rl/model.py', '/placement_rl/compiler.py')):
            if sha256((ROOT/name).read_bytes()).hexdigest() != expected:
                errors.append(f'Current replay model differs from experiment: {name}')
    witnesses = list(directory.glob('*/witnesses/*/*.json'))
    completed = 0
    for path in witnesses:
        raw = json.loads(path.read_text(encoding='utf-8'))
        circuit, hardware = Circuit(**raw['circuit']), Hardware(**raw['hardware'])
        result = CompileResult(**raw['result'])
        check = audit_result(circuit, hardware, tuple(raw['mapping']), result,
                             Scenario(**raw['scenario']), CompilerConfig(**raw['compiler']))
        if result.status == 'completed':
            completed += 1
            if check['status'] != 'passed':
                errors.append(f'{path.relative_to(directory)}: {check}')
    expected_witnesses = len(summary['results']) * sum(len(manifest['splits'][k])
                         for k in ('test', 'size_holdout')) * 3 * len(manifest['scenarios'])
    if len(witnesses) != expected_witnesses:
        errors.append(f'Expected {expected_witnesses} witnesses, found {len(witnesses)}')
    if summary['status'] != 'completed':
        errors.append('Experiment incomplete')
    for variant in summary['results']:
        training = variant['training']
        if not training['actor_changed']:
            errors.append('Actor did not update')
        if training['mode'] == 'adversarial' and not training['adversary_changed']:
            errors.append('Adversary did not update')
        if training['mode'] == 'uniform' and training['adversary_changed']:
            errors.append('Uniform ablation opponent changed')
        best = min(training['validations'], key=lambda v: v['score'])
        if best['step'] != training['selected_step']:
            errors.append('Checkpoint not selected by validation')
    report = dict(status='failed' if errors else 'passed', errors=errors,
                  unique_dataset_circuits=len(digests), witnesses=len(witnesses),
                  completed_witnesses=completed, source_files=len(manifest['source_sha256']),
                  physical_validation='not_run')
    (directory/'audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    report = audit(args.directory)
    print(json.dumps(report, indent=2))
    raise SystemExit(report['status'] != 'passed')
