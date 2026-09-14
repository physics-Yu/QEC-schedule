from dataclasses import replace

import pytest

from neutral_atom_env.domain.operations import TaskIntent, TaskTarget
from neutral_atom_env.domain.models import Position2D
from neutral_atom_strategies.motion.multi_trap import MultiTrapGreedyCompiler
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_env.platform import initialize
from neutral_atom_env.simulation.executor import Executor
from neutral_atom_strategies.scheduling.row_greedy import run_row, row_assignment, gate_service, service_lower_bound
from neutral_atom_app.visualization.workbench import build_inputs
from neutral_atom_env.replay.operation_codec import event_from_dict
import json


def value():
    return {'atom_count':4,'layout':'row','seed':0,'compiler':'greedy','ez_policy':'adaptive','aod_traps':4,
        'gates':[{'id':'A','gate_type':'CZ','qubit_ids':['Q000','Q003'],'column':0},
                 {'id':'B','gate_type':'CZ','qubit_ids':['Q001','Q002'],'column':0},
                 {'id':'C','gate_type':'H','qubit_ids':['Q003'],'column':1},
                 {'id':'D','gate_type':'H','qubit_ids':['Q002'],'column':1}]}


def initial(v=None):
    _,c,p,l=build_inputs(v or value())
    return initialize(c,p,l)


@pytest.mark.parametrize('strategy',['row_symmetric','row_greedy'])
def test_full_row_service_and_compiler_free_replay(strategy):
    state=initial(); result=run_row(state,strategy=strategy)
    assert result.status=='completed',result.diagnostics
    assert state.metrics()['completed_gate_count']==4
    assert all(h.holder_id==f'S{i:03d}' for i,(_,h) in enumerate(sorted(state.placement.atom_to_holder.items())))
    replay=initial()
    for raw in state.trace.records:
        event=event_from_dict(json.loads(raw)['event'])
        if event.event_type.value=='plan_started':
            executor=Executor(replay);executor.submit(event.plan);executor.run()
    assert replay.snapshot()==state.snapshot()
    assert state.metrics()['aod_load_count']==4  # 2 CZ + one collective staging and one return.
    if strategy=='row_greedy':
        assert sum(d.get('bound_pruned',0) for d in result.decision_log)>0


def test_bounds_against_all_legal_orientations_and_lights():
    state=initial(); compiler=MultiTrapGreedyCompiler(adaptive_sites=True)
    p=ProgramBuilder(state,TaskIntent('stage',TaskTarget(),frozenset(state.atoms),phase='prepare'))
    compiler.transfer_group(p,row_assignment(state))
    p.intent=replace(p.intent,target=TaskTarget(tuple(sorted(p.state.placement.atom_to_holder.items()))))
    ex=Executor(state);ex.submit(p.finish('test-stage'));ex.run()
    durations=[]
    for gate in state.dag.ready_gates():
        for anchor in gate.qubit_ids:
            point=state.placement.position(anchor,state.world,state.aod)
            for dx,dy in ((0,2),(0,-2),(-2,0),(2,0)):
                pose=Position2D(point.x_um+dx,point.y_um+dy)
                plan=gate_service(state,compiler,gate,anchor,pose)
                bound=service_lower_bound(state,gate,anchor,pose)
                assert bound<=plan.estimated_duration_us+1e-8
                durations.append(plan.estimated_duration_us)
    probe=initial();result=run_row(probe,strategy='row_greedy')
    first=next(d for d in result.decision_log if d.get('kind')=='cz')
    assert first['duration_us']==pytest.approx(min(durations))
    assert first['local_optimum_certified']


def test_budget_exhaustion_is_visible_and_geometry_rejection_is_atomic(monkeypatch):
    # Deliberately loose, still admissible bounds ensure this tests the budget
    # branch even when the production graph bound exactly proves the winner.
    monkeypatch.setattr('neutral_atom_strategies.scheduling.row_greedy.service_lower_bound',lambda *args:0.)
    state=initial();result=run_row(state,strategy='row_greedy',candidate_budget=1)
    assert result.status=='completed'
    assert any(d.get('budget_omitted',0)>0 and not d['local_optimum_certified'] for d in result.decision_log)
    bad=initial(value()|{'layout':'grid'})
    before=bad.snapshot();result=run_row(bad)
    assert result.status=='stalled' and result.diagnostics[0]['code']=='ROW_ORIGIN'
    assert bad.snapshot()==before


def test_terminal_budget_and_already_satisfied_terminal():
    probe=initial();complete=run_row(probe,strategy='row_symmetric')
    bounded=initial();result=run_row(bounded,strategy='row_symmetric',max_decisions=complete.decisions-1)
    assert result.status=='stalled' and result.diagnostics[0]['code']=='DECISION_BUDGET_EXHAUSTED'
    assert result.decisions==complete.decisions-1
    assert bounded.dag.completed  # The omitted work is explicitly terminal cleanup.
    flexible=initial();result=run_row(flexible,strategy='row_symmetric',terminal=TaskTarget())
    assert result.status=='completed' and result.decision_log[-1]['selected']!='explicit-terminal'
    empty=initial(value()|{'gates':[]});before=empty.snapshot();result=run_row(empty)
    assert result.status=='completed' and result.decisions==0 and empty.snapshot()==before


def test_empty_graph_bound_matches_independent_dijkstra_and_respects_footprint():
    from heapq import heappop,heappush
    from types import SimpleNamespace
    from neutral_atom_env.domain.aod import AODConfiguration
    from neutral_atom_strategies.motion.astar import AStarHalfGridPlanner
    from neutral_atom_strategies.scheduling.row_greedy import empty_graph_distance
    from neutral_atom_env.domain.errors import ValidationError
    state=initial();bounds=state.world.bounds;span=30
    for a,b in [(Position2D(0,0),Position2D(30,-25)),
                (Position2D(10,-25),Position2D(0,-23)),
                (Position2D(10,-25),Position2D(2,-25)),
                (Position2D(0,-25),Position2D(0,-25)),
                (Position2D(2.5,-22.5),Position2D(32.5,-22.5))]:
        axes=lambda p:AODConfiguration((p.x_um,p.x_um+span),(p.y_um,))
        graph,start,end=AStarHalfGridPlanner.graph(SimpleNamespace(start=axes(a),target=axes(b),world=state.world))
        distances={start:0};queue=[(0,start)]
        while queue:
            cost,node=heappop(queue)
            if cost!=distances[node]:continue
            if node==end:break
            for next_node in graph[node]:
                new=cost+abs(node[0]-next_node[0])+abs(node[1]-next_node[1])
                if new<distances.get(next_node,float('inf')):
                    distances[next_node]=new;heappush(queue,(new,next_node))
        assert empty_graph_distance(bounds,span,a,b)==distances[end]
        assert empty_graph_distance(bounds,span,b,a)==distances[end]
    outside=Position2D(bounds.upper.x_um-span+1,0)
    with pytest.raises(ValidationError,match='Full rigid array'):
        empty_graph_distance(bounds,span,Position2D(0,0),outside)
