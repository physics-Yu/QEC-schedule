"""Free occupied shape on the full hardware SLM domain, before initialization.

Physical grid/world are hardware constraints, not the user's old atom footprint.
Constructive circuit embeddings seed the same compiler-feedback optimizer;
they do not bound it to a rectangle, a translation, or a circuit family.
"""
from collections import Counter
from dataclasses import replace
from random import Random
from .verified import CompilerSearchConfig, optimize_with_compiler


def embedding_seeds(problem, *, seed=7, limit=64):
    rng=Random(seed);locked=dict(problem.locked);points={s.id:(s.x_um,s.y_um) for s in problem.storage}
    weights=Counter(tuple(sorted(g.qubit_ids)) for g in problem.circuit.gates if g.is_two_qubit)
    def w(a,b):return weights[tuple(sorted((a,b)))] if a!=b else 0
    degree={q:sum(w(q,b) for b in problem.qubits) for q in problem.qubits}
    free=[q for q in problem.qubits if q not in locked]
    if not free:return ()
    anchors=list(points);rng.shuffle(anchors)
    seeds=[];seen=set()
    for attempt in range(limit*2):
        anchor=anchors[attempt%len(anchors)];axis=attempt%2
        mapping=dict(locked);available=set(points)-set(mapping.values())
        first=sorted(free,key=lambda q:(-degree[q],q))[attempt//max(1,len(anchors))%len(free)]
        order=[first]+[q for q in free if q!=first]
        while order:
            q=max(order,key=lambda q:(sum(w(q,b) for b in mapping),degree[q],-order.index(q)))
            ax,ay=points[anchor]
            def cost(s):
                x,y=points[s]
                interaction=sum(w(q,b)*(abs(x-points[t][0])+abs(y-points[t][1])) for b,t in mapping.items())
                # Small anchor tie-break gives spatially compact seeds without
                # treating that heuristic as physical time or a hard restriction.
                return (interaction,.01*(abs(x-ax)+abs(y-ay)),points[s][axis],points[s][1-axis],s)
            site=min(available,key=cost);mapping[q]=site;available.remove(site);order.remove(q)
        key=problem.validate_mapping(mapping)
        if key not in seen:seeds.append(key);seen.add(key)
        if len(seeds)>=limit:break
    return tuple(seeds)


def optimize_free_placement(problem,evaluator,*,contract,config=None,on_trial=None,evaluate_batch=None):
    config=config or CompilerSearchConfig(allow_vacancies=True)
    if not config.allow_vacancies:
        raise ValueError('Free placement requires allow_vacancies=True; use the permutation API explicitly otherwise')
    seeds=embedding_seeds(problem,seed=config.seed,limit=config.proposal_pool)
    result=optimize_with_compiler(problem,evaluator,contract=contract,config=config,
                                  on_trial=on_trial,seed_mappings=seeds,evaluate_batch=evaluate_batch)
    def shape(mapping):
        pts=[next((s.x_um,s.y_um) for s in problem.storage if s.id==site) for _,site in mapping]
        x0=min(x for x,y in pts);y0=min(y for x,y in pts)
        return tuple(sorted((x-x0,y-y0) for x,y in pts))
    original={s for _,s in result.baseline.mapping};initial_shape=shape(result.baseline.mapping)
    details=dict(result.diagnostics,free_placement=True,allowed_site_count=len(problem.storage),
        originally_occupied_site_count=len(problem.qubits),constructive_seeds=len(seeds),
        evaluated_changed_occupancy=sum({s for _,s in t.mapping}!=original for t in result.trials),
        evaluated_changed_shape=sum(shape(t.mapping)!=initial_shape for t in result.trials),
        selected_changed_occupancy=bool(result.selected and {s for _,s in result.selected.mapping}!=original),
        selected_changed_shape=bool(result.selected and shape(result.selected.mapping)!=initial_shape),
        geometry_scope='all configured eligible SLM sites; no fixed occupied shape; no continuous trap synthesis')
    return replace(result,diagnostics=details)
