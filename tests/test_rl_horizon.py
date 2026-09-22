import pytest
pytest.importorskip('torch')

from neutral_atom_experiments.rl.horizon import fresh_manifest,canonical_words,words_of,local_cost_steps
from neutral_atom_experiments.rl.training_cases import manifest,wire_optimum
from neutral_atom_experiments.rl.instances import make_snapshot
from neutral_atom_strategies.learning import DecisionEnv,EpisodeConfig
from neutral_atom_strategies.learning.policies import LocalCostPolicy


def test_fresh_canonical_splits_and_counterexample_balance():
    cases=fresh_manifest()
    keys=[canonical_words(words_of(c)) for c in cases]
    old={canonical_words(w) for c in manifest() if (w:=words_of(c)) is not None}
    assert len(keys)==48 and len(set(keys))==48 and not set(keys)&old
    for split,size in [('train',24),('validation',8),('test',16)]:
        rows=[c for c in cases if c['split']==split]
        assert len(rows)==size and sum(c['family']=='counterexample' for c in rows)==size//2
        for c in rows:
            assert c['optimum_us']==wire_optimum(c)
            assert c['baseline_us']==local_cost_steps(words_of(c))


def test_declared_baseline_matches_physical_same_kind_pulses():
    for case in fresh_manifest()[:3]:
        env=DecisionEnv(make_snapshot(case['gates']),EpisodeConfig(reward_scale_us=1))
        while env.status=='running':env.collect_fragment(LocalCostPolicy(),4)
        result=env.audit()
        assert result['elapsed_us']==case['baseline_us']
        assert result['replay_equal'] and result['terminal_verified']
