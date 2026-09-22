"""Headless, shape-preserving initial placement on the full two-patch QEC GHZ.

The source site pool is fixed for all trials. Only prepared initial holders and
their switches differ; MZ/EZ, AOD, circuit, decoder and terminal stay common.
"""
from dataclasses import asdict, replace
import json
from pathlib import Path

from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.models import StaticTrap, GridCoord, Position2D, HolderRef, HolderType, ZoneType
from neutral_atom_env.world import WorldState, PlacementState
from neutral_atom_env.replay.serializer import primitive
from neutral_atom_strategies.placement import (Site,PlacementProblem,SearchConfig,
    PhysicalEvaluation,optimize_initial,select_physically)
from neutral_atom_strategies.scheduling.m3 import initial_terminal
from .qec_ordered_comparison import demos,make_state,run_one


def prepare_experiment():
    spec=demos()['qec_ghz2']
    state=make_state(spec)
    original=state.placement
    traps=dict(state.world.traps)
    sz=next(z for z in state.world.zones if z.zone_type==ZoneType.STORAGE)
    by_position={(t.position.x_um,t.position.y_um):key for key,t in traps.items() if sz.bounds.contains(t.position)}
    # Discrete source candidates stay inside the existing SZ and preserve the
    # FULL relative geometry, not just data/data adjacency. No new routing area.
    for dy in (-5,0,5,10):
        for q,h in original.atom_to_holder.items():
            p=state.world.traps[h.holder_id].position
            point=Position2D(p.x_um,p.y_um+dy)
            if not sz.bounds.contains(point):raise ValueError('Candidate leaves fixed SZ')
            xy=(point.x_um,point.y_um)
            if xy not in by_position:
                key=f'INIT_{point.x_um:g}_{point.y_um:g}'
                traps[key]=StaticTrap(key,GridCoord(round(point.x_um/5),round(point.y_um/5)),point,enabled=False)
                by_position[xy]=key
    world=WorldState(state.world.bounds,traps,state.world.zones,state.world.grid_spacing_um,state.world.grid_origin)
    switches={key:state.slm_enabled.get(key,False) for key in traps}
    state=replace(state,world=world,slm_enabled=switches)
    storage=tuple(Site(key,t.position.x_um,t.position.y_um) for key,t in traps.items() if sz.bounds.contains(t.position))
    ez=next(z for z in state.world.zones if z.zone_type==ZoneType.ENTANGLEMENT)
    interaction=tuple(Site(key,t.position.x_um,t.position.y_um) for key,t in traps.items() if ez.bounds.contains(t.position))
    mapping=tuple((q,h.holder_id) for q,h in state.placement.atom_to_holder.items())
    problem=PlacementProblem(state.dag.circuit,tuple(state.atoms),storage,interaction,mapping,
        aod_rows=state.aod.rows,aod_columns=state.aod.columns,hardware=state.hardware)
    # Existing optimizer's translation seeding, with atom/row permutations
    # explicitly disabled. This is the exact finite translation family only.
    config=SearchConfig(iterations=0,top_k=1,lookahead_layers=64,seed=7)
    result=optimize_initial(problem,config)
    return spec,state,problem,config,result


def candidate_state(base,candidate):
    mapping=dict(candidate.mapping)
    holders={q:HolderRef(HolderType.STATIC,s) for q,s in mapping.items()}
    switches=dict(base.slm_enabled)
    for h in base.placement.atom_to_holder.values():switches[h.holder_id]=False
    for s in mapping.values():switches[s]=True
    return replace(base,placement=PlacementState(holders),slm_enabled=switches)


def shape_translation(base,state):
    shifts=set()
    for q in base.atoms:
        p=base.placement.position(q,base.world,base.aod)
        t=state.placement.position(q,state.world,state.aod)
        shifts.add((t.x_um-p.x_um,t.y_um-p.y_um))
    if len(shifts)!=1:raise AssertionError('Patch relative geometry changed')
    return next(iter(shifts))


def run_experiment(directory):
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    spec,base,problem,config,search=prepare_experiment()
    terminal=initial_terminal(base)
    for name,value in [('input.json',spec),('search.json',asdict(search)),('problem.json',asdict(problem)),('config.json',asdict(config))]:
        (directory/name).write_text(json.dumps(value,indent=2,default=str),encoding='utf-8')
    counter=0;reports=[]
    def evaluate(candidate):
        nonlocal counter
        name='baseline' if candidate.mapping==search.baseline.mapping else f'candidate-{counter}'
        counter+=1
        state=candidate_state(base,candidate)
        shift=shape_translation(base,state)
        print(json.dumps(dict(case=name,translation_um=shift,proxy_us=candidate.cost.score_us)),flush=True)
        result=run_one(spec,'ordered_greedy',directory/name,initial_state=state,terminal_target=terminal,render=False)
        quantum=result['quantum']
        passed=(result['status']=='completed' and result['replay_equal'] and result['effects_once']
                and result['terminal_verified'] and quantum['verified_logical_ghz2']
                and quantum['measurement_protocol_complete'])
        reports.append(dict(name=name,shift_um=shift,passed=passed,physical_us=result['metrics']['simulation_time_us'],
            proxy_us=candidate.cost.score_us,load_batches=result['metrics']['aod_load_count'],
            atom_distance_um=result['metrics']['total_atom_distance_um'],quantum=quantum,
            compile_seconds=result['compile_seconds'],replay_seconds=result['replay_seconds']))
        return PhysicalEvaluation(passed,result['metrics']['simulation_time_us'] if passed else None,
            failure=None if passed else json.dumps(result.get('error') or quantum),evidence=str(directory/name/'result.json'))
    selected,records=select_physically(search,evaluate)
    baseline=next((e for c,e in records if c.mapping==search.baseline.mapping),None)
    chosen=next((e for c,e in records if selected and c.mapping==selected.mapping),None)
    # Independently compare final common geometry, quantum circuit and holder
    # state; quantum measurement outcomes need not match under arbitrary schedules.
    states=[NeutralAtomEnv.restore((directory/r['name']/'checkpoint.json').read_text(encoding='utf-8')).state for r in reports if r['passed']]
    same=all(s.world==base.world and s.hardware==base.hardware and s.dag.circuit==base.dag.circuit
             and s.placement==base.placement and s.slm_enabled==base.slm_enabled
             and s.aod.configuration()==base.aod.configuration() for s in states)
    report=dict(status='passed' if selected and baseline and baseline.valid and same else 'failed',
        atom_count=len(base.atoms),gate_count=len(base.dag.circuit.gates),
        gate_counts={k:sum(g.gate_type==k for g in base.dag.circuit.gates) for k in ('CZ','H','X','Y','Z','MEASURE','RESET')},
        contract='full two logical d=3 GHZ with one data Y fault; rigid whole-footprint translations; prepared initial mapping; common terminal',
        baseline_us=baseline.total_time_us if baseline else None,selected_us=chosen.total_time_us if chosen else None,
        improvement_percent=100*(baseline.total_time_us-chosen.total_time_us)/baseline.total_time_us if chosen and baseline and baseline.valid else None,
        same_world_hardware_circuit_terminal=same,results=reports,
        failures=[asdict(e) for c,e in records if not e.valid],
        scope='not temporal multi-round or four-logical GHZ; no patch-internal permutations; no initial assembly cost',
        gui='not_requested_not_run')
    (directory/'comparison.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report
