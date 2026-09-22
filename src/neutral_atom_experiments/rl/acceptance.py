"""Separate a successful training run from an unproven performance claim."""
import argparse
import json
from pathlib import Path
from statistics import mean
from neutral_atom_env.replay.serializer import canonical_json
from .analysis import aggregate
from .train import render_report


def write_acceptance(directory):
    directory=Path(directory)
    report=json.loads((directory/'report.json').read_text(encoding='utf-8'))
    diagnosis=json.loads((directory/'diagnosis.json').read_text(encoding='utf-8'))
    results=report['test_results'];seed_scores={}
    for seed in report['training_seeds']:
        seed_scores[str(seed)]={policy:mean(-r['return'] for r in results if r['training_seed']==seed and r['policy']==policy)
                               for policy in ('ppo','local_cost')}
    oracle=next(r['elapsed_us'] for r in diagnosis['cases'] if r['name']=='test-greedy-trap' and r['policy']=='oracle')
    trap=[r for r in diagnosis['cases'] if r['name']=='test-greedy-trap' and r['policy']=='selected']
    acceptance={'execution_passed':all(r['status']=='completed' and r['replay_equal'] and r['terminal_verified'] and r['effects_once'] for r in results),
        'test_runs':len(results),'training_failures':report['training_failures'],
        'better_than_baseline_in_every_seed':all(s['ppo']<s['local_cost']-1e-8 for s in seed_scores.values()),
        'nonlocal_counterexample_solved':all(r['elapsed_us']<=oracle+1e-8 for r in trap),
        'per_seed_objective':seed_scores,'performance_status':'NOT_ESTABLISHED',
        'known_gap':'Both selected policies take 7 us on a physically replayed 6 us counterexample.',
        'next_step':'Use fresh training/validation counterexamples and controlled exploration/GAE ablations; freeze new test cases before any tuning.'}
    (directory/'acceptance.json').write_text(canonical_json(acceptance),encoding='utf-8')
    (directory/'analysis.json').write_text(canonical_json(aggregate(report)),encoding='utf-8')
    render_report(directory,report)
    print(json.dumps(acceptance,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('directory');args=parser.parse_args();write_acceptance(args.directory)
