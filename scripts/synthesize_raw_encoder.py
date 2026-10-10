"""Reproduce the bounded binary synthesis behind the raw A encoder.

This ranks native-CX decompositions by count then canonical Manhattan distance;
it neither samples a quantum state nor establishes fault-tolerant injection.
"""
from pathlib import Path
from random import Random
import json,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from na_pipeline.qec.factory_primitives import reference_css_encoder,legacy_css_encoder_v2


def synthesize(candidates=3000,seed=704):
    rng=Random(seed);base=reference_css_encoder()['columns'];best=None
    for _ in range(candidates):
        order=list(range(9));rng.shuffle(order);columns=[base[i] for i in order]
        rows=[sum(((c>>i)&1)<<j for j,c in enumerate(columns)) for i in range(9)]
        reduction=[];pivots=list(range(9));rng.shuffle(pivots);done=set()
        for col in pivots:
            if not rows[col]&(1<<col):
                j=min((j for j in range(9) if j not in done and rows[j]&(1<<col)),
                      key=lambda j:((rows[col]^rows[j]).bit_count(),abs(j%3-col%3)+abs(j//3-col//3)))
                rows[col]^=rows[j];reduction.append((j,col))
            for j in range(9):
                if j!=col and rows[j]&(1<<col):rows[j]^=rows[col];reduction.append((col,j))
            done.add(col)
        assert rows==[1<<i for i in range(9)]
        score=(len(reduction),sum(abs(a%3-b%3)+abs(a//3-b//3) for a,b in reduction))
        if best is None or score<best[0]:best=(score,order,list(reversed(reduction)))
    encoder=legacy_css_encoder_v2()
    assert encoder['cx']==[list(p) for p in best[2]]
    return {'schema_version':'RawEncoderSynthesis/0.1','candidate_budget':candidates,'seed':seed,
            'score_CX_count_and_Manhattan_distance':list(best[0]),'column_order':best[1],
            'encoder':encoder,'matches_selected_recipe':True,'global_optimality_claimed':False,
            'quantum_state_simulated':False,'fault_tolerance_claimed':False}


if __name__=='__main__':
    out=ROOT/'knowledge/roles/R0/evidence/modular/raw-encoder-synthesis.json'
    out.write_text(json.dumps(synthesize(),ensure_ascii=False,indent=2),encoding='utf-8')
    print(out)
