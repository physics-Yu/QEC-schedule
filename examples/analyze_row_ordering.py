"""Offline row-order heuristics; geometry estimates, never a physical compiler.

All single-qubit gates are contracted to zero duration. Every CZ restores the
row, so its minimum loaded round trip is intrinsic and paid in every ordering.
Only empty reposition depends on the preceding chosen moving operand. The
analysis uses the original CZ partial order, both operand roles, and includes
the final empty return to the row's left endpoint. No backend audit is skipped
in the production compiler: this script does not emit an executable plan.
"""
import argparse
import json
from pathlib import Path
from time import perf_counter

from neutral_atom_env.domain.models import Position2D as P
from neutral_atom_env.simulation.pipeline import initialize
from neutral_atom_env.simulation.row_greedy import row_assignment, empty_graph_distance
from neutral_atom_env.visualization.workbench import build_inputs


def analyze(value, *, depth=8, width=32):
    _, circuit, placement, hardware = build_inputs(value)
    state = initialize(circuit, placement, hardware)
    assignment = row_assignment(state)
    points = {q:state.world.traps[t].position for q,t in assignment.items()}
    assert len({p.y_um for p in points.values()}) == 1
    gates = [g for g in circuit.gates if g.gate_type == 'CZ']
    prior = {}; dependencies = []; roles = []; intrinsic = []
    speed = state.hardware.speed_um_per_us
    pulse = state.hardware.load_duration_us + state.hardware.offload_duration_us + state.hardware.pulse_duration_us
    x = {q:p.x_um for q,p in points.items()}
    origin = min(x, key=x.get)
    for i,g in enumerate(gates):
        mask=0
        for q in g.qubit_ids:
            if q in prior:mask |= 1 << prior[q]
            prior[q]=i
        dependencies.append(mask)
        roles.append(tuple(g.qubit_ids))
        intrinsic.append(2*(abs(x[g.qubit_ids[0]]-x[g.qubit_ids[1]])+3)/speed+pulse)
    full=(1<<len(gates))-1
    def ready(done):
        return [i for i,mask in enumerate(dependencies) if not done>>i&1 and done&mask==mask]
    def empty(a,b):
        return 0. if a==b else (abs(x[a]-x[b])+5)/speed
    # Verify the analytic row formula against the production obstacle-free
    # graph. These are geometry checks, not legal loaded-atom path witnesses.
    span=state.aod.configuration().x_um[-1]-state.aod.pose.x_um
    checks=[]
    for g in (gates[0], gates[len(gates)//2], gates[-1]):
        for a,b in (g.qubit_ids, tuple(reversed(g.qubit_ids))):
            assert abs(empty_graph_distance(state.world.bounds,span,points[a],points[b])/speed-empty(a,b))<1e-8
            for dy in (-2.,2.):
                target=P(points[b].x_um,points[b].y_um+dy)
                exact=empty_graph_distance(state.world.bounds,span,points[a],target)
                predicted=abs(x[a]-x[b])+3
                assert abs(exact-predicted)<1e-8
                checks.append({'source':a,'anchor':b,'dy':dy,'graph_distance_um':exact})

    def choices(done,current):
        return [(empty(current,q),i,q) for i in ready(done) for q in roles[i]]
    def interval_return_bound(done,current):
        # Every unfinished CZ must eventually load one endpoint. Relax endpoint
        # choice to visiting any point in its interval; a 1-D tour from current
        # to origin must cover all these intervals. Ignoring portal detours
        # keeps this admissible for empty transportation in the abstract family.
        unfinished=[i for i in range(len(gates)) if not done>>i&1]
        if not unfinished:return empty(current,origin)
        low=min(x[current],x[origin],min(max(x[q] for q in roles[i]) for i in unfinished))
        high=max(x[current],x[origin],max(min(x[q] for q in roles[i]) for i in unfinished))
        return min(abs(x[current]-low)+high-low+abs(high-x[origin]),
                   abs(x[current]-high)+high-low+abs(low-x[origin]))/speed
    def select(done,current,method):
        available=choices(done,current)
        if method=='symmetric':
            i=min(ready(done),key=lambda i:gates[i].id)
            return i,roles[i][1]
        if method=='immediate':
            _,i,q=min(available,key=lambda c:(c[0]+intrinsic[c[1]],gates[c[1]].id,c[2]))
            return i,q
        if method=='intrinsic_corrected':
            _,i,q=min(available,key=lambda c:(c[0],gates[c[1]].id,c[2]))
            return i,q
        # Each beam node is an exact abstract DAG+pose state, without physical
        # forks. Subtracting completed intrinsic cost is algebraically equal
        # to g + sum(unfinished intrinsic); it avoids depth bias toward short
        # mandatory CZs. Direct return to origin is an empty-travel lower bound.
        beam=[(0.,done,current,())]
        def bound(node):
            return node[0]+(interval_return_bound(node[1],node[2]) if method=='beam_intervals' else empty(node[2],origin))
        for _ in range(depth):
            deduplicated={}
            for cost,finished,last,path in beam:
                if finished==full:
                    deduplicated[(finished,last)]=(cost,finished,last,path)
                    continue
                for distance,i,q in choices(finished,last):
                    node=(cost+distance,finished|(1<<i),q,path+((i,q),))
                    key=(node[1],q)
                    if key not in deduplicated or (node[0],node[3])<(deduplicated[key][0],deduplicated[key][3]):
                        deduplicated[key]=node
            beam=sorted(deduplicated.values(),key=lambda n:(bound(n),n[3]))[:width]
            if all(n[1]==full for n in beam):break
        winner=min(beam,key=lambda n:(bound(n),n[3]))
        return winner[3][0]

    outputs={}
    for method in ('symmetric','immediate','intrinsic_corrected','beam','beam_intervals'):
        started=perf_counter();done=0;current=origin;travel=0.;sequence=[]
        while done!=full:
            i,q=select(done,current,method)
            assert dependencies[i]&done==dependencies[i]
            reposition=empty(current,q);travel+=reposition
            sequence.append({'gate_id':gates[i].id,'moving_operand':q,'empty_reposition_us':reposition})
            current=q;done|=1<<i
        final=empty(current,origin);travel+=final
        outputs[method]={'cz_count':len(gates),'intrinsic_us':sum(intrinsic),'empty_reposition_including_terminal_us':travel,
            'terminal_empty_us':final,'abstract_total_us':sum(intrinsic)+travel,
            'analysis_seconds':perf_counter()-started,'sequence':sequence}
    return {'model':'restoring row; no obstacles; zero-time contracted 1Q; exact tested half-grid geometry',
        'not_a_physical_execution':True,'excluded':'joint row stage/return cost, switching overhead, Raman schedule, obstacles and pulse audits',
        'beam_depth':depth,'beam_width':width,'geometry_spot_checks':checks,'strategies':outputs}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('input',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--depth',type=int,default=8);parser.add_argument('--width',type=int,default=32)
    args=parser.parse_args();result=analyze(json.loads(args.input.read_text(encoding='utf-8')),depth=args.depth,width=args.width)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:{a:b for a,b in v.items() if a!='sequence'} for k,v in result['strategies'].items()},indent=2))
