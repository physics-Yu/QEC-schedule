"""Editable parking experiment, independent from circuit/QEC demo factories."""
from dataclasses import replace
from math import isfinite
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.circuit import PhysicalCircuit, DynamicGateDAG
from neutral_atom_env.domain.models import Atom, GridCoord, HolderRef, HolderType as H, Position2D as P, Rectangle, StaticTrap, Zone, ZoneType
from neutral_atom_env.domain.operations import HardwareConfig
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.world import WorldState, PlacementState, AODRuntimeState
from neutral_atom_env.visualization.recording import VisualRecorder
from neutral_atom_env.replay.serializer import primitive
from neutral_atom_strategies.motion.parking import ParkingConfig, PlanningFailure, plan_pickup, plan_collective_transport
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_env.program.builder import ProgramBuilder


def default_input():
    return dict(rows=2,columns=3,cells=[[2,2,1],[1,2,2]],aod_rows=2,aod_columns=3,
                spacing_um=10,epsilon_x_um=2.5,epsilon_y_um=2.5,shift_x_um=60,shift_y_um=30,strategy='naive_rowwise',obstacles=[])


def large_input():
    """Deterministic 10x10 mixed occupancy; targets span all ten rows/columns."""
    cells=[[2 if (3*r+2*c)%7<3 else (0 if (r+c)%4==0 else 1)
            for c in range(10)] for r in range(10)]
    return default_input() | dict(rows=10,columns=10,cells=cells,
        aod_rows=10,aod_columns=10,shift_x_um=140,shift_y_um=40)


def compatible_input():
    """Nine target rows but two compatible groups; final all-fixed row stays off."""
    cells=[[1 if r==9 else (1 if c>=5 else 2 if c==r%4 else 0) if r<5
            else (1 if c<5 else 2 if c==5+(r-5)%4 else 0) for c in range(10)] for r in range(10)]
    return large_input() | dict(cells=cells,strategy='pattern_optimal')


def make_state(spec):
    if not isinstance(spec,dict):raise ValueError('Parking input must be a JSON object')
    for key in ('rows','columns','aod_rows','aod_columns'):
        if type(spec.get(key)) is not int or not 1<=spec[key]<=16:raise ValueError(key+' must be an integer in 1..16')
    if spec['aod_rows']*spec['aod_columns']>128:raise ValueError('AOD capacity must not exceed 128 intersections')
    cells=spec.get('cells')
    if not isinstance(cells,list) or len(cells)!=spec['rows'] or any(not isinstance(r,list) or len(r)!=spec['columns'] or any(type(v) is not int or v not in (0,1,2) for v in r) for r in cells):
        raise ValueError('cells must be a rectangular empty/protected/target mask (0/1/2)')
    for key in ('spacing_um','epsilon_x_um','epsilon_y_um','shift_x_um','shift_y_um'):
        if type(spec.get(key)) not in (int,float) or not isfinite(spec[key]):raise ValueError(key+' must be finite')
    if spec['spacing_um'] not in (5,10,15,20):raise ValueError('spacing_um must be 5, 10, 15 or 20 um on the physical SLM grid')
    if not 0<spec['epsilon_x_um']<20 or not 0<spec['epsilon_y_um']<20:raise ValueError('Parking offsets must be positive and below 20 um')
    d=spec['spacing_um'];width=(spec['columns']-1)*d;height=(spec['rows']-1)*d
    if not width+10<=spec['shift_x_um']<=500 or not 0<=spec['shift_y_um']<=300:
        raise ValueError('Collective +X shift must clear the source patch by at least 10 um and be <=500 um; +Y must be 0..300 um')
    obstacles=spec.get('obstacles',[])
    if not isinstance(obstacles,list) or len(obstacles)>16 or any(not isinstance(x,list) or len(x)!=2 or any(type(v) not in (int,float) or not isfinite(v) or not -10<=v<=350 for v in x) for x in obstacles):
        raise ValueError('obstacles must contain at most 16 finite [x,y] points in -10..350 um')
    capacity=max(spec['aod_rows'],spec['aod_columns'])*d
    bounds=Rectangle(P(-20,-20),P(width+capacity+spec['shift_x_um']+40,height+capacity+spec['shift_y_um']+40))
    traps={};atoms={};holders={};targets=[]
    for r,row in enumerate(cells):
        for c,kind in enumerate(row):
            site=f'S{r}_{c}';traps[site]=StaticTrap(site,GridCoord(c,r),P(c*d,r*d))
            if kind:
                q=f'Q{r*spec["columns"]+c:03d}';atoms[q]=Atom(q);holders[q]=HolderRef(H.STATIC,site)
                if kind==2:targets.append(q)
    known={(t.position.x_um,t.position.y_um) for t in traps.values()}
    for i,(x,y) in enumerate(obstacles):
        if (x,y) in known:raise ValueError('External obstacle overlaps a source SLM site')
        if not bounds.contains(P(x,y)):raise ValueError('External obstacle outside world bounds')
        known.add((x,y));site=f'E{i}';q=f'E{i:03d}'
        traps[site]=StaticTrap(site,GridCoord(100+i,100),P(x,y));atoms[q]=Atom(q);holders[q]=HolderRef(H.STATIC,site)
    world=WorldState(bounds,traps,(Zone('STORAGE',ZoneType.STORAGE,bounds),),grid_spacing_um=5)
    aod=AODRuntimeState(pose=P(0,0),rows=spec['aod_rows'],columns=spec['aod_columns'],spacing_um=d,
                        enabled_rows=(False,)*spec['aod_rows'],enabled_columns=(False,)*spec['aod_columns'])
    state=SimulationState(world,PlacementState(holders),atoms,aod,DynamicGateDAG(PhysicalCircuit(())),hardware=HardwareConfig(backend='row_column_orthogonal',selective_transfer_enabled=True))
    config=ParkingConfig(rows=spec['rows'],columns=spec['columns'],spacing_x_um=d,spacing_y_um=d,
                         epsilon_x_um=spec['epsilon_x_um'],epsilon_y_um=spec['epsilon_y_um'])
    return state,targets,config


def preview(spec):
    state,targets,config=make_state(spec)
    return {'recording':VisualRecorder(state).payload(),'target_ids':targets}


def execute_pickup_groups(env, pickup):
    """Preserve the audited operation sequence; commit at parked group boundaries.

    The serial executor re-audits its active plan at every event. Small parked
    batches avoid repeatedly replaying the whole experiment. Each batch still
    goes through ProgramBuilder.finish, submit, and all runtime validation.
    The caller uses a private environment and publishes only a complete job.
    """
    plans=[];start=0
    for index,step in enumerate(pickup.steps):
        stop=step['operation_count']
        p=ProgramBuilder(env.state,TaskIntent(f'parking/group/{index}',TaskTarget(),frozenset(pickup.atom_to_tone_mapping)))
        for op in pickup.operations[start:stop]:
            p.add(op.operation_type,op.label,target=op.target_pose,configuration=op.target_configuration,
                  bindings=op.transfer_bindings,phase=op.transfer_phase,switch_state=op.switch_state)
        p.intent=replace(p.intent,target=TaskTarget(tuple(sorted(p.state.placement.atom_to_holder.items())),p.state.aod.configuration(),trap_state(p.state)))
        plan=p.finish('parking/grouped-execution/v1')
        env.submit(plan);env.run();plans.append(plan);start=stop
    assert start==len(pickup.operations)
    return plans


def run(spec):
    state,targets,config=make_state(spec);initial=state.snapshot()
    pickup=plan_pickup(state,targets,config,spec.get('strategy','naive_rowwise'))
    if isinstance(pickup,PlanningFailure):return {'status':'failed','error':primitive(pickup),'input':spec}
    # Validate the complete job first on a private environment, including the
    # continuation from its actual versioned parked checkpoint.
    validation=NeutralAtomEnv.restore(initial);plans=[]
    if pickup.plan:
        plans.extend(execute_pickup_groups(validation,pickup))
    pickup_checkpoint=validation.snapshot()
    try:
        transport=plan_collective_transport(validation.state,spec['shift_x_um'],spec['shift_y_um'])
        if transport:validation.submit(transport);validation.run();plans.append(transport)
    except Exception as e:
        v=getattr(e,'violation',None)
        return {'status':'failed','error':{'code':v.code if v else type(e).__name__,'message':v.message if v else str(e),'phase':'collective_transport'},'input':spec}
    env=NeutralAtomEnv.restore(initial);recorder=VisualRecorder(env.state)
    for plan in plans:env.submit(plan);env.run(on_event=recorder.observe)
    assert env.snapshot()==validation.snapshot(),'Independent replay mismatch'
    for q,h in state.placement.atom_to_holder.items():
        if q not in targets:assert env.state.placement.atom_to_holder[q]==h
    assert set(env.state.placement.mobile_occupancy.values())==set(targets)
    assert state.snapshot()==initial,'Planning mutated input'
    return {'status':'completed','input':spec,'recording':recorder.payload(),
            'pickup':{'duration_us':pickup.duration_us,'transfer_events':pickup.transfer_events,'parking_sweeps':pickup.parking_sweeps,
                      'movement_distance_um':pickup.movement_distance_um,'steps':pickup.steps,'analysis':pickup.analysis,'atom_to_tone_mapping':primitive(pickup.atom_to_tone_mapping),
                      'final_aod_state':primitive(pickup.final_aod_state)},
            'transport_duration_us':transport.estimated_duration_us if transport else 0,
            'execution_batches':len(plans),
            'validation':{'independent_replay':True,'protected_unchanged':True,'targets_loaded':True,'planning_read_only':True},
            'checkpoint':env.snapshot(),'pickup_checkpoint':pickup_checkpoint}
