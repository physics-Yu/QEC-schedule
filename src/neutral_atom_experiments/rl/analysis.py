"""Report all held-out outcomes without selecting the best training seed."""
from statistics import mean


def aggregate(report):
    rows=report['test_results']
    baseline={(r['training_seed'],r['name']):r for r in rows if r['policy']=='local_cost'}
    summaries=[]
    for policy in ('untrained','imitation','ppo_last','ppo','local_cost','random'):
        group=[r for r in rows if r['policy']==policy]
        if not group:continue
        ratios=[r['elapsed_us']/baseline[(r['training_seed'],r['name'])]['elapsed_us']
                for r in group if r['status']=='completed' and baseline[(r['training_seed'],r['name'])]['status']=='completed']
        per_seed={}
        for seed in report['training_seeds']:
            paired=[r['elapsed_us']/baseline[(seed,r['name'])]['elapsed_us'] for r in group
                    if r['training_seed']==seed and r['status']=='completed'
                    and baseline[(seed,r['name'])]['status']=='completed']
            if paired:per_seed[str(seed)]=mean(paired)
        summaries.append({'policy':policy,'successes':sum(r['status']=='completed' for r in group),
            'cases':len(group),'mean_ratio_to_local_cost_on_success':mean(ratios) if ratios else None,
            'paired_success_count':len(ratios),'per_training_seed_mean_ratio':per_seed,
            'mean_negative_normalized_return':mean(-r['return'] for r in group),
            'all_replays_equal':all(r['replay_equal'] for r in group),'all_effects_once':all(r['effects_once'] for r in group)})
    return {'summaries':summaries,'trap':[r for r in rows if r['name']=='test-greedy-trap'],
            'selected_updates':{str(seed):sorted({r['selected_update'] for r in rows
                if r['training_seed']==seed and r['policy']=='ppo'}) for seed in report['training_seeds']},
            'uncertainty':'Two training seeds and nine test circuits are a pilot; no statistical superiority claim.'}
