from dataclasses import replace
from time import perf_counter

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.aod import AODConfiguration as C
from neutral_atom_env.domain.operations import OperationType as K
from neutral_atom_env.domain.models import Position2D
from neutral_atom_env.hardware import get_backend
from neutral_atom_experiments.ordered_axis_comparison import demos,make_state
from neutral_atom_strategies.motion.ordered_routes import merge_straight_runs,discrete_corridor_routes,OccupiedSLMGrid
from neutral_atom_strategies.scheduling.ordered_greedy import new_builder,empty_reconfigure,build_batch,realize_batch


def test_straight_runs_merge_but_turns_and_reversals_stop():
    a,b,c,d=(C((x,),(y,)) for x,y in ((0,0),(2.5,0),(10,0),(10,10)))
    assert merge_straight_runs((a,b,c,d))==(a,c,d)
    assert merge_straight_runs((a,c,b))==(a,c,b)
    # Independent columns can make different amounts of progress, while all
    # traps still move monotonically along their own horizontal straight lines.
    a,b,c=C((0,10),(0,)),C((2.5,15),(0,)),C((10,20),(0,))
    assert merge_straight_runs((a,b,c))==(a,c)
    backend=get_backend(make_state(demos()['stretch']).hardware)
    state=make_state(demos()['stretch']);a,b,c=C((0,),(0,)),C((2.5,),(0,)),C((10,),(0,))
    aod=replace(state.aod,rows=1,columns=1,enabled_rows=(False,),enabled_columns=(False,),pose=Position2D(0,0))
    assert backend.move_duration(aod,c,state.hardware)<backend.move_duration(aod,b,state.hardware)+backend.move_duration(aod.configured(b),c,state.hardware)


def test_new_grid_includes_original_slm_aligned_lines_and_no_redundant_stop():
    routes=discrete_corridor_routes(C((0,),(0,)),C((0,),(28,)))
    assert (C((0,),(0,)),C((0,),(28,))) in routes
    for r in routes:
        assert merge_straight_runs(r)==r
        assert all(a.x_um==b.x_um or a.y_um==b.y_um for a,b in zip(r,r[1:]))


def test_grid_marks_static_atoms_not_the_loaded_source_and_checks_mid_segment():
    state=make_state(demos()['stretch']);initial=state.snapshot()
    assignments=tuple((f'g{i:03}',f'Q{i+3:03}',f'Q{i:03}',x,30) for i,x in enumerate((-2,18,38)))
    batch=build_batch(state,assignments)
    p=new_builder(state,batch.gate_ids);empty_reconfigure(p,batch.pickup)
    p.add(K.AOD_LOAD,'load',bindings=batch.bindings)
    grid=OccupiedSLMGrid(p.state)
    assert (0,0) not in grid.blocked and (0,12) in grid.blocked
    assert not grid.allows((C((0,10,20),(25,)),C((0,10,20),(35,))))
    assert grid.allows((C((2.5,12.5,22.5),(25,)),C((2.5,12.5,22.5),(35,))))
    assert state.snapshot()==initial
    assert all(p.state.slm_enabled[state.placement.atom_to_holder[f'Q{i:03}'].holder_id] for i in (3,4,5))


def test_schedule_uses_last_interval_exactly_and_replays_after_float_sum_difference():
    spec=demos()['stretch'];state=make_state(spec);initial=state.snapshot()
    batch=build_batch(state,(('g000','Q003','Q000',0,28),))
    plan=realize_batch(state,batch,perf_counter()+20,128,[])
    assert plan.estimated_duration_us==max(i.end_us for i in plan.operation_intervals)
    env=NeutralAtomEnv(state);env.submit(plan);env.run()
    replay=NeutralAtomEnv.restore(initial);replay.submit(plan);replay.run()
    assert env.snapshot()==replay.snapshot()
