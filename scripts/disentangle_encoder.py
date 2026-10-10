"""Bounded CSS isometry disentangling, with independent signed certificate."""
from pathlib import Path
import json,sys,time
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from na_pipeline.qec.surface17 import CHECKS,LOGICAL_X,LOGICAL_Z
from na_pipeline.validation.raw_encoder import certify_encoder
from search_parallel_encoder import depth


def basis(rows):
    rows=list(rows);k=0
    for bit in range(9):
        found=next((j for j in range(k,len(rows)) if rows[j]>>bit&1),None)
        if found is None:continue
        rows[k],rows[found]=rows[found],rows[k]
        for j in range(len(rows)):
            if j!=k and rows[j]>>bit&1:rows[j]^=rows[k]
        k+=1
    return tuple(rows)


def vectors(gs):
    span=[0]
    for g in gs:span += [p^g for p in list(span)]
    return span


def search(width=256,max_depth=14):
    mask=lambda s:sum(1<<i for i in s)
    initial=tuple(basis(mask(s) for _,b,s,_ in CHECKS if b==a) for a in ('X','Z'))
    beam=[(initial,[])];seen={initial};solutions=[];visited=0
    for step in range(max_depth):
        pool={}
        for (xs,zs),path in beam:
            for c in range(9):
                for t in range(9):
                    if c==t:continue
                    nx=basis(x^((1<<t) if x>>c&1 else 0) for x in xs)
                    nz=basis(z^((1<<c) if z>>t&1 else 0) for z in zs);state=(nx,nz)
                    visited+=1
                    if state in seen or state in pool:continue
                    new=path+[[c,t]];xv=vectors(nx);zv=vectors(nz)
                    plus=[i for i in range(9) if 1<<i in xv];zero=[i for i in range(9) if 1<<i in zv]
                    if len(plus)+len(zero)==8:
                        seed=next(i for i in range(9) if i not in plus+zero)
                        gates=list(reversed(new))
                        recipe={'seed':f'd{seed}','plus_inputs':[f'd{i}' for i in plus],'zero_inputs':[f'd{i}' for i in zero],'cx':gates}
                        proof=certify_encoder(recipe)
                        if proof['passed']:
                            solutions.append({'recipe':recipe,'score':[depth(gates)[0],len(gates),sum(abs(c%3-t%3)+abs(c//3-t//3) for c,t in gates)],'signed_proof':proof})
                            if len(solutions)>=16:return solutions,visited,step+1
                    small=sum(sorted(v.bit_count() for v in xv[1:])[:4])+sum(sorted(v.bit_count() for v in zv[1:])[:4])
                    score=(8-len(plus)-len(zero),small,depth(new)[0],sum(abs(c%3-t%3)+abs(c//3-t//3) for c,t in new))
                    pool[state]=(score,new)
        chosen=sorted(pool.items(),key=lambda v:v[1][0])[:width]
        beam=[(state,p) for state,(_,p) in chosen];seen.update(state for state,_ in beam)
        print('depth',step+1,'states',len(pool),'score',chosen[0][1][0] if chosen else None,flush=True)
        if not beam:break
    return solutions,visited,step+1

if __name__=='__main__':
    started=time.perf_counter();sol,n,d=search()
    out=ROOT/'knowledge/roles/R0/evidence/joint-frontier/encoder-disentangle-search.json'
    out.write_text(json.dumps({'schema_version':'ParallelEncoderSynthesis/0.1','method':'CSS_disentangling_beam','width':256,'depth_limit':14,'visited':n,'reached_depth':d,'wall_seconds':time.perf_counter()-started,'candidates':sorted(sol,key=lambda s:s['score']),'global_optimality_claimed':False},indent=2)+'\n')
    print('solutions',len(sol),'seconds',time.perf_counter()-started)
