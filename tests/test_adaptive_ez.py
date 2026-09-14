"""Demand-driven EZ behavior through real physical plans and exact terminal."""
from collections import Counter
from dataclasses import replace
import json
import pytest
from neutral_atom_app.visualization.workbench import build_inputs, compile_input, validate_input
from neutral_atom_env.platform import initialize
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from neutral_atom_strategies.scheduling.m4 import run_m4
from neutral_atom_strategies.motion.greedy import GreedyCompiler
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_env.simulation import Executor
from neutral_atom_env.domain.models import StaticTrap, GridCoord, Position2D, Zone, ZoneType, Rectangle
from neutral_atom_app.visualization.workbench import failure_report


def circuit(pairs, layout='row', n=4):
    return {'compiler':'greedy','ez_policy':'adaptive','atom_count':n,'layout':layout,'seed':19,
            'gates':[{'id':f'g{i}','gate_type':'CZ','qubit_ids':[f'Q{q:03d}' for q in pair],
                      'parameters':[],'column':i} for i,pair in enumerate(pairs)]}


def state_for(value):
    _,c,p,h=build_inputs(value)
    return initialize(c,p,h,seed=value['seed'])


def test_demand_selects_different_sites_and_all_dormant_sites_are_available():
    chosen=[]
    for pair in [(0,1),(2,3)]:
        state=state_for(circuit([pair]));before=state.snapshot()
        ez=[k for k in state.world.traps if k.startswith('EZ')]
        assert len(ez)>20 and not any(state.slm_enabled[k] for k in ez)
        candidates,_,cut=GreedyCompiler(adaptive_sites=True).alternatives('g0',state)
        assert cut>0 and state.snapshot()==before
        choice=min(candidates,key=lambda c:c.cost)
        chosen.append(state.world.traps[choice.site].position.x_um)
        assert choice.site not in sorted(ez)[:4] or pair==(0,1)
    assert chosen[1]>chosen[0]


@pytest.mark.parametrize('layout',['row','grid','shuffled'])
def test_partner_changes_switch_supports_and_restore_exact_terminal(layout):
    value=circuit([(0,1),(0,2),(2,3),(1,3),(0,1)],layout)
    state=state_for(value);terminal=initial_terminal(state)
    result=run_m4(state,adaptive_sites=True)
    assert result.status=='completed',result.diagnostics
    validate_target(terminal,state)
    chosen=[e['selected'] for e in result.decision_log if e['selected']!='explicit-terminal']
    assert len(chosen)==5 and len({s.split('/')[-1] for s in chosen})>=2
    changes=[c for d in result.decision_log for c in d['ez_changes']]
    assert any(c['enabled'] for c in changes) and any(not c['enabled'] for c in changes)
    records=[json.loads(r) for r in state.trace.records]
    assert Counter(r['gate_id'] for r in records if r.get('effect_completed'))==Counter({f'g{i}':1 for i in range(5)})


def test_failure_is_real_budget_and_edit_recompile_recovers():
    value=circuit([(0,1),(0,2)])|{'max_decisions':1}
    result,state=compile_input(value)
    report=result['failure_report']
    assert result['status']=='stalled' and report['code']=='DECISION_BUDGET_EXHAUSTED'
    assert report['completed_gates']==1 and report['unfinished_gates']==['g1']
    assert report['search'][0]['attempted']>0 and report['search'][0]['omitted']>0
    assert len(result['recording']['operations'])>0
    recovered,_=compile_input(value|{'max_decisions':10000})
    assert recovered['status']=='completed' and recovered['failure_report'] is None


def test_legacy_input_geometry_and_validation_remain_explicit():
    value=circuit([(0,1)]);value.pop('ez_policy')
    state=state_for(value)
    assert len([k for k in state.world.traps if k.startswith('EZ')])==2
    for extra in ({'ez_policy':'magic'},{'max_decisions':0},{'max_decisions':True}):
        with pytest.raises(ValueError):validate_input(value|extra)


@pytest.mark.parametrize('safe_site',[False,True])
def test_geometry_refusals_expand_search_or_report_actual_causes(safe_site):
    value=circuit([(0,1)]);_,c,p,h=build_inputs(value)
    traps={k:t for k,t in p.world.traps.items() if not k.startswith('EZ')}
    # Tiny EZ islands hold the anchor but exclude every 2 um approach side.
    # A world edge alone is no longer a failure: the other sides are valid.
    zones=[z for z in p.world.zones if z.zone_type!=ZoneType.ENTANGLEMENT]
    for y in (-25,-30,-35,-40):
        key=f'EZ_edge_{-y}'
        traps[key]=StaticTrap(key,GridCoord(-2,y//5),Position2D(-10,y),enabled=False)
        zones.append(Zone(key,ZoneType.ENTANGLEMENT,Rectangle(Position2D(-10,y-.5),Position2D(-9.5,y+.5))))
    if safe_site:
        traps['EZ_safe']=StaticTrap('EZ_safe',GridCoord(8,-8),Position2D(40,-40),enabled=False)
        zones.append(Zone('safe',ZoneType.ENTANGLEMENT,Rectangle(Position2D(35,-43),Position2D(43,-35))))
    p=replace(p,world=replace(p.world,traps=traps,zones=tuple(zones)))
    state=initialize(c,p,h,seed=value['seed'])
    result=run_m4(state,adaptive_sites=True,site_limit=2)
    if safe_site:
        # Initial nearest sites fail; the second bounded search reaches safety.
        assert result.status=='completed',result.diagnostics
        assert result.decision_log[0]['selected'].endswith('/EZ_safe')
        assert any(s['offset']>0 for s in result.decision_log[0]['search'])
    else:
        report=failure_report(result,state,value)
        assert report['code']=='CANDIDATES_EXHAUSTED' and report['completed_gates']==0
        assert report['causes'] and report['search'][-1]['offset']>0
