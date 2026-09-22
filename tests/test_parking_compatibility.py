import json
from pathlib import Path
import random
import subprocess
from functools import lru_cache

from neutral_atom_strategies.motion.parking_groups import analyze, compatible_groups
from neutral_atom_strategies.motion.parking import plan_pickup, PlanningFailure
from neutral_atom_experiments.parking_demo import default_input, make_state, run, compatible_input
from neutral_atom_env import NeutralAtomEnv


def oracle(cells):
    lines=[r for r in cells if 2 in r]
    def valid(mask):
        return all(not ({lines[i][c] for i in range(len(lines)) if mask>>i&1} >= {1,2}) for c in range(len(cells[0])))
    @lru_cache(None)
    def solve(mask):
        if not mask:return 0
        if valid(mask):return 1
        best=mask.bit_count();sub=mask;pivot=mask&-mask
        while sub:
            if sub&pivot and valid(sub):best=min(best,1+solve(mask^sub))
            sub=(sub-1)&mask
        return best
    return solve((1<<len(lines))-1)


def test_exact_partition_and_javascript_agree_with_independent_set_partition_oracle():
    rng=random.Random(73)
    cases=[[[rng.randrange(3) for _ in range(5)] for _ in range(5)] for _ in range(80)]
    cases += [[[2,1,0],[0,0,2],[1,2,0]], [[2,0],[0,2]], [[0,0],[1,1]]]
    expected=[]
    for cells in cases:
        a=analyze(cells)
        assert a['row']['batches']==oracle(cells)
        assert a['column']['batches']==oracle(list(map(list,zip(*cells))))
        expected.append(a)
    root=Path(__file__).resolve().parents[1]
    script="const E=require('./src/neutral_atom_strategies/motion/parking_template.js');let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>console.log(JSON.stringify(JSON.parse(s).map(E.analyze))));"
    output=subprocess.run(['node','-e',script],cwd=root,input=json.dumps(cases),text=True,capture_output=True,check=True)
    assert json.loads(output.stdout)==expected


def test_wildcard_is_not_transitive_and_empty_rows_do_not_activate():
    assert compatible_groups([[2,1,0],[0,0,2],[1,2,0]])['batches']==2
    assert compatible_groups([[2,0],[0,2]])['batches']==1
    v=default_input()|dict(rows=3,cells=[[2,0,1],[0,2,1],[1,1,1]],aod_rows=3,strategy='pattern_optimal')
    r=run(v);assert r['status']=='completed',r.get('error')
    assert r['pickup']['transfer_events']==1
    assert r['pickup']['analysis']['row']['skipped']==[2]
    assert r['pickup']['steps'][0]['groups']==[0,1]
    assert [o['kind'] for o in r['recording']['operations']].count('aod_load')==1
    final=NeutralAtomEnv.restore(r['checkpoint']).state
    assert final.aod.enabled_rows==(True,True,False)
    assert set(final.placement.mobile_occupancy.values())=={'Q000','Q004'}


def test_column_orientation_can_win_and_empty_input_has_no_actions():
    # Three required row configurations, but only two column configurations.
    cells=[[2,1],[1,2],[2,2],[2,0]]
    a=analyze(cells);assert a['column']['batches']<a['row']['batches'];assert a['selected_axis']=='column'
    v=default_input()|dict(rows=4,columns=2,cells=cells,aod_rows=4,aod_columns=2,strategy='pattern_optimal')
    r=run(v);assert r['status']=='completed',r.get('error');assert r['pickup']['transfer_events']==2
    s,t,c=make_state(v|dict(cells=[[1,0]]*4));p=plan_pickup(s,t,c,'pattern_optimal')
    assert not p.operations and p.analysis['row']['batches']==0


def test_repeated_row_retains_columns_and_grouping_reduces_captures():
    v=default_input()|dict(cells=[[2,2,1],[2,2,1]])
    s,t,c=make_state(v)
    naive=plan_pickup(s,t,c);opt=plan_pickup(s,t,c,'pattern_optimal')
    assert not isinstance(naive,PlanningFailure) and not isinstance(opt,PlanningFailure)
    assert naive.transfer_events==2 and opt.transfer_events==1
    assert opt.duration_us<naive.duration_us
    # No X back-and-forth before the final common terminal normalization.
    assert not any(o.label=='仅调整不匹配的列' for o in naive.operations)
    assert naive.final_aod_state.configuration()==opt.final_aod_state.configuration()


def test_showcase_really_uses_empty_wildcards():
    v=compatible_input();a=analyze(v['cells'])
    assert len([r for r in v['cells'] if 2 in r])==9
    assert a['row']['batches']==2 and a['row']['skipped']==[9]
