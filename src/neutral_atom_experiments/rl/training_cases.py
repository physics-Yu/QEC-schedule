"""Explicit disjoint train/validation/test circuit manifests for first learning."""
from functools import lru_cache
from hashlib import sha256
import json
import random
from .instances import make_snapshot


def wire_case(name,strings,split):
    gates=[(kind,[q]) for q,s in enumerate(strings) for kind in s]
    return dict(name=name,split=split,atom_count=len(strings),gates=gates,scale=1.,family='wire_words')


def manifest():
    cases=[];seen=set()
    # Training has length<=3 H/X words. Hold out long words and other gate kinds.
    for split,seed,count in [('train',41,12),('validation',73,3),('test',107,4)]:
        rng=random.Random(seed)
        for i in range(count):
            while True:
                strings=tuple(''.join(rng.choice('HX') for _ in range(rng.randint(1,3))) for _ in range(4))
                key=tuple(sorted(strings))
                if key not in seen:seen.add(key);break
            cases.append(wire_case(f'{split}-words-{i}',strings,split))
    cases.extend([
        wire_case('test-greedy-trap',('HX','HHXX','HX','XHHH'),'test'),
        wire_case('test-unseen-gate-types',('YZ','ZY','Y','ZZ'),'test'),
        wire_case('test-six-wire-size',('HX','XH','HH','XX','H','X'),'test'),
    ])
    for split,n in [('train',4),('validation',6),('test',8)]:
        width=n//2
        gates=[('H',[q]) for q in range(n)]+[('CZ',[q,q+width]) for q in range(width)]
        cases.append(dict(name=f'{split}-cz-{n}',split=split,atom_count=n,gates=gates,scale=1000.,family='parallel_cz'))
    # Novel cross-dependency topology; never present in training/validation.
    cases.append(dict(name='test-cz-crossed',split='test',atom_count=4,
        gates=[('H',[0]),('CZ',[0,3]),('X',[3]),('CZ',[1,2]),('H',[1])],scale=1000.,family='crossed_cz'))
    for case in cases:
        case['fingerprint']=sha256(json.dumps([case['atom_count'],case['gates']],sort_keys=True).encode()).hexdigest()
    assert len({c['fingerprint'] for c in cases})==len(cases)
    return cases


def initial(case):return make_snapshot(case['gates'],case['atom_count'],seed=0)


def wire_optimum(case):
    if any(kind=='CZ' for kind,_ in case['gates']):return None
    words=['']*case['atom_count']
    for kind,qs in case['gates']:words[qs[0]]+=kind
    @lru_cache(None)
    def solve(strings):
        choices={s[0] for s in strings if s}
        return 0 if not choices else 1+min(solve(tuple(s[1:] if s.startswith(k) else s for s in strings)) for k in choices)
    return solve(tuple(words))
