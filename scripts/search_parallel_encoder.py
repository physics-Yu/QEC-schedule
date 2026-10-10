"""Reproducible algebraic candidates; device qualification is a separate job."""
from pathlib import Path
from random import Random
import json, sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from na_pipeline.qec.factory_primitives import reference_css_encoder
from na_pipeline.validation.raw_encoder import certify_encoder


def depth(gates):
    last=[0]*9;layers=[]
    for c,t in gates:
        n=max(last[c],last[t])+1;last[c]=last[t]=n;layers.append(n)
    return max(last,default=0),layers


def search(budget=100000, seed=81044):
    rng=Random(seed);base=reference_css_encoder()['columns'];best={}
    for index in range(budget):
        cols=list(base)
        # Change the + stabilizer basis and the logical-X coset, preserving
        # the two-dimensional isometry; independent signed checks below.
        for _ in range(rng.randrange(8)):
            a,b=rng.sample(range(1,5),2);cols[a]^=cols[b]
        mask=rng.randrange(16)
        for j in range(4):
            if mask>>j&1:cols[0]^=cols[j+1]
        order=list(range(9));rng.shuffle(order);cols=[cols[i] for i in order]
        rows=[sum(((c>>i)&1)<<j for j,c in enumerate(cols)) for i in range(9)]
        reduction=[];pivots=list(range(9));rng.shuffle(pivots);done=set()
        for col in pivots:
            if not rows[col]&(1<<col):
                j=min((j for j in range(9) if j not in done and rows[j]&(1<<col)),
                      key=lambda j:((rows[col]^rows[j]).bit_count(),abs(j%3-col%3)+abs(j//3-col//3)))
                rows[col]^=rows[j];reduction.append([j,col])
            for j in range(9):
                if j!=col and rows[j]&(1<<col):rows[j]^=rows[col];reduction.append([col,j])
            done.add(col)
        gates=list(reversed(reduction));d,_=depth(gates)
        score=(d,len(gates),sum(abs(c%3-t%3)+abs(c//3-t//3) for c,t in gates))
        if len(best)>=10 and score>=max(best):continue
        recipe={'columns':cols,'seed':'d'+str(order.index(0)),
                'plus_inputs':['d'+str(i) for i,j in enumerate(order) if 1<=j<=4],
                'zero_inputs':['d'+str(i) for i,j in enumerate(order) if j>4], 'cx':gates}
        best[score]=recipe
        if len(best)>10:del best[max(best)]
    rows=[]
    for score,recipe in sorted(best.items()):
        proof=certify_encoder(recipe)
        if not proof['passed']:raise ValueError(proof)
        rows.append({'score':list(score),'recipe':recipe,'signed_proof':proof})
    return {'schema_version':'ParallelEncoderSynthesis/0.1','budget':budget,'seed':seed,'candidates':rows,
            'ranking':'dependency_depth_then_CX_count_then_Manhattan','global_optimality_claimed':False,'device_qualified':False}

if __name__=='__main__':
    out=ROOT/'knowledge/roles/R0/evidence/joint-frontier/encoder-expanded-search.json'
    result=search();out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print([(c['score'],c['recipe']['seed']) for c in result['candidates']])
