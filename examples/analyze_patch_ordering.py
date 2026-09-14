"""Offline geometry/DAG estimate of batch fragmentation; emits no executable plan."""
import argparse,json
from pathlib import Path
from dataclasses import replace
from functools import lru_cache
from math import hypot
from time import perf_counter
from collections import Counter

from neutral_atom_env.domain.models import Position2D as P,HolderRef,HolderType
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.world import PlacementState
from neutral_atom_env.visualization.workbench import build_inputs
from neutral_atom_env.simulation.pipeline import initialize
from neutral_atom_env.simulation.patch_greedy import patch_assignment
from neutral_atom_env.simulation.row_greedy import empty_graph_distance
from neutral_atom_env.motion.patch_array import PatchArrayCompiler


def historical_candidate_groups(state,gates,strategy):
    """Frozen original maximum-group + singleton family for the naive control.

    Do not import production candidate_groups here: adding legal subsets to
    production must not silently rewrite the historical fragmentation model.
    """
    d=hypot(state.hardware.interaction_offset.x_um,state.hardware.interaction_offset.y_um)
    groups={}
    for gate in gates:
        a,b=gate.qubit_ids
        for anchor,mobile in ((a,b),(b,a)):
            pa=state.placement.position(anchor,state.world,state.aod)
            pm=state.placement.position(mobile,state.world,state.aod)
            for ox,oy in ((0,d),(d,0),(0,-d),(-d,0)):
                shift=(pa.x_um+ox-pm.x_um,pa.y_um+oy-pm.y_um)
                groups.setdefault(shift,[]).append((gate.id,anchor,mobile))
    choices=[]
    for shift,members in groups.items():
        used=set();accepted=[]
        for item in members:
            if used.intersection(item[1:]):continue
            accepted.append(item);used.update(item[1:])
        choices.append((shift,tuple(accepted)))
    if strategy=='patch_symmetric':
        first=gates[0].id
        choices=[c for c in choices if any(g==first for g,_,_ in c[1])]
        choices.sort(key=lambda c:(-len(c[1]),c[0]))
    else:
        def estimate(item):
            shift,members=item
            points=[state.placement.position(m,state.world,state.aod) for _,_,m in members]
            origin=P(min(p.x_um for p in points),min(p.y_um for p in points))
            distance=abs(origin.x_um-state.aod.pose.x_um)+abs(origin.y_um-state.aod.pose.y_um)
            cost=200.+(distance+2*(abs(shift[0])+abs(shift[1])))/state.hardware.speed_um_per_us
            return cost/len(members),-len(members),shift
        choices.sort(key=estimate)
    seen=set(choices)
    for shift,members in tuple(choices):
        for member in members:
            item=(shift,(member,))
            if item not in seen:choices.append(item);seen.add(item)
    return choices


def analyze(value):
    _,c,p,h=build_inputs(value);initial=initialize(c,p,h)
    destinations=patch_assignment(initial)
    positions={q:initial.world.traps[s].position for q,s in destinations.items()}
    origin=P(min(p.x_um for p in positions.values()),min(p.y_um for p in positions.values()))
    state=replace(initial,placement=PlacementState({q:HolderRef(HolderType.STATIC,s) for q,s in destinations.items()}),
        aod=replace(initial.aod,pose=origin),slm_enabled={s:s in set(destinations.values()) for s in initial.world.traps})
    compiler=PatchArrayCompiler();gates=[g for g in c.gates if g.gate_type=='CZ'];index={g.id:i for i,g in enumerate(gates)}
    predecessors=[];last={}
    for i,g in enumerate(gates):
        mask=sum(1<<j for j in {last[q] for q in g.qubit_ids if q in last})
        predecessors.append(mask)
        for q in g.qubit_ids:last[q]=i
    heights=[1]*len(gates)
    for i in range(len(gates)-1,-1,-1):
        for j in range(i):
            if predecessors[i]>>j&1:heights[j]=max(heights[j],heights[i]+1)
    # Infer occupied nearest-neighbor components solely from metric geometry.
    nearest=min(hypot(a.x_um-b.x_um,a.y_um-b.y_um) for q,a in positions.items() for r,b in positions.items() if q<r)
    components={q:q for q in positions}
    def root(q):
        while components[q]!=q:q=components[q]
        return q
    for q,a in positions.items():
        for r,b in positions.items():
            if q<r and abs(hypot(a.x_um-b.x_um,a.y_um-b.y_um)-nearest)<1e-8:
                components[root(q)]=root(r)
    local=[root(g.qubit_ids[0])==root(g.qubit_ids[1]) for g in gates]
    axes=state.aod.configuration();spanx=axes.x_um[-1]-axes.x_um[0];spany=axes.y_um[-1]-axes.y_um[0]
    @lru_cache(None)
    def distance(a,b):return empty_graph_distance(state.world.bounds,spanx,a,b,spany)
    @lru_cache(None)
    def geometry(shift,members):
        try:
            source,bindings=compiler.bindings(state,[m for _,_,m in members])
            selected={b.atom_id for b in bindings};xs={positions[q].x_um for q in selected};ys={positions[q].y_um for q in selected}
            closure={q for q,p in positions.items() if p.x_um in xs and p.y_um in ys}
            if closure!=selected:return None
            end={q:P(p.x_um+shift[0],p.y_um+shift[1]) if q in selected else p for q,p in positions.items()}
            pairs=set()
            for a,pa in end.items():
                for b,pb in end.items():
                    if a>=b:continue
                    d=hypot(pa.x_um-pb.x_um,pa.y_um-pb.y_um)
                    if d<state.hardware.minimum_clearance_um-1e-9:return None
                    if d<=state.hardware.interaction_distance_um+1e-9:pairs.add(tuple(sorted((a,b))))
            if pairs!={tuple(sorted((a,b))) for _,a,b in members}:return None
            target=P(source.x_um+shift[0],source.y_um+shift[1])
            loaded=2*distance(source,target)
            return source,loaded
        except ValidationError:return None
    speed=state.hardware.speed_um_per_us
    fixed=state.hardware.load_duration_us+state.hardware.offload_duration_us+state.hardware.pulse_duration_us
    output={};all_done=(1<<len(gates))-1
    for method in ('symmetric','immediate','locality_first','reverse_cz_depth','locality_closed','balanced_closed'):
        started=perf_counter();done=0;pose=origin;sequence=[];total=0.
        while done!=all_done:
            ready=[i for i,mask in enumerate(predecessors) if not done>>i&1 and done&mask==mask]
            if method in {'locality_first','locality_closed','balanced_closed'} and any(local[i] for i in ready):ready=[i for i in ready if local[i]]
            if method=='balanced_closed' and all(local[i] for i in ready):
                progress=Counter(root(gates[i].qubit_ids[0]) for i in range(len(gates)) if done>>i&1 and local[i])
                minimum=min(progress[root(gates[i].qubit_ids[0])] for i in ready)
                ready=[i for i in ready if progress[root(gates[i].qubit_ids[0])]==minimum]
            if method=='reverse_cz_depth':ready=[i for i in ready if heights[i]==max(heights[j] for j in ready)]
            frontier=sorted((gates[i] for i in ready),key=lambda g:g.id)
            view=replace(state,aod=replace(state.aod,pose=pose))
            choices=historical_candidate_groups(view,frontier,'patch_symmetric' if method=='symmetric' else 'patch_greedy')
            if method.endswith('_closed'):
                seen=set(choices)
                for shift,members in tuple(choices):
                    for axis in ('x_um','y_um'):
                        for coordinate in {getattr(positions[m],axis) for _,_,m in members}:
                            group=tuple(item for item in members if getattr(positions[item[2]],axis)==coordinate)
                            if (shift,group) not in seen:choices.append((shift,group));seen.add((shift,group))
            best=None
            for shift,members in choices:
                geo=geometry(shift,members)
                if geo is None:continue
                source,loaded=geo
                cost=fixed+(distance(pose,source)+loaded)/speed
                key=(cost/len(members),-len(members),distance(pose,source)+loaded,shift)
                if best is None or key<best[0]:best=key,cost,members,source,shift
                if method=='symmetric':break
            if best is None:raise ValueError('Offline geometry model has no allowed group')
            key,cost,members,pose,shift=best
            done |= sum(1<<index[g] for g,_,_ in members);total+=cost
            sequence.append({'gate_ids':[g for g,_,_ in members],'batch_size':len(members),'duration_lower_estimate_us':cost,
                             'shift':shift,'component_local':all(local[index[g]] for g,_,_ in members)})
        terminal=distance(pose,origin)/speed;total+=terminal
        output[method]={'batch_count':len(sequence),'batch_sizes':dict(Counter(s['batch_size'] for s in sequence)),
            'cz_service_and_terminal_empty_estimate_us':total,'terminal_empty_estimate_us':terminal,
            'analysis_seconds':perf_counter()-started,'sequence':sequence}
    return {'model':'CZ DAG contracts 1Q; exact Cartesian capture closure + endpoint pairs + empty routing graph; no swept loaded validation',
        'not_a_physical_execution':True,'excluded':'Raman, joint stage/return, support switching, loaded path detours and full audit',
        'inferred_components':len({root(q) for q in positions}),'nearest_spacing_um':nearest,'strategies':output}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('input',type=Path);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=analyze(json.loads(args.input.read_text(encoding='utf-8')))
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:{x:y for x,y in v.items() if x!='sequence'} for k,v in result['strategies'].items()},indent=2))
