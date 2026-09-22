"""Fixed-slot parking pickup. Pure planner; no circuit scheduling or live mutations."""
from dataclasses import dataclass, replace
from math import isfinite, hypot
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.aod import AODConfiguration as Axes
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderType as H, MobileCellIndex
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget, CaptureBinding, OperationType as K
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_env.hardware.trap_spacing import minimum_trap_spacing
from neutral_atom_env.program.builder import ProgramBuilder
from .parking_groups import analyze


@dataclass(frozen=True)
class ParkingConfig:
    rows: int = 2
    columns: int = 3
    origin_x_um: float = 0
    origin_y_um: float = 0
    spacing_x_um: float = 10
    spacing_y_um: float = 10
    epsilon_x_um: float = 2.5
    epsilon_y_um: float = 2.5


@dataclass(frozen=True)
class PlanningFailure:
    code: str
    message: str
    phase: str
    details: object = None


@dataclass(frozen=True)
class PickupPlan:
    plan: object
    final_aod_state: object
    atom_to_tone_mapping: dict
    duration_us: float
    transfer_events: int
    parking_sweeps: int
    movement_distance_um: float
    steps: tuple
    validation: str = 'complete_plan_audited'
    analysis: object = None

    @property
    def operations(self):
        return self.plan.operations if self.plan else ()


def plan_pickup(snapshot, target_ids, config=ParkingConfig(), strategy='naive_rowwise'):
    """Return PickupPlan or PlanningFailure, leaving the supplied snapshot unchanged.

    snapshot may be a SimulationState or its serialized checkpoint. All geometry,
    obstacles and timing come from it; config defines the source grid/parking slots.
    pattern_optimal minimizes compatible whole-line capture groups in either orientation.
    """
    phase='preflight'
    try:
        if not isinstance(config,ParkingConfig):
            raise ValueError('config must be a ParkingConfig')
        if strategy not in ('naive_rowwise','naive_columnwise','pattern_optimal'):
            raise ValidationError('STRATEGY_NOT_IMPLEMENTED', 'Requested pickup strategy has not been implemented')
        state=NeutralAtomEnv.restore(snapshot).state if isinstance(snapshot,str) else snapshot
        targets=frozenset(target_ids)
        if not targets:return PickupPlan(None,state.aod,{},0,0,0,0,(),analysis=analyze([[0]*config.columns for _ in range(config.rows)]))
        if state.hardware.backend!='row_column_orthogonal':
            raise ValidationError('PARKING_BACKEND', 'Parking v0 requires orthogonal ordered axes')
        if state.placement.mobile_occupancy:
            raise ValidationError('AOD_ENTRY_LOADED','Pickup entry must have no carried atoms')
        if any(state.aod.enabled_rows) or any(state.aod.enabled_columns):
            raise ValidationError('AOD_ENTRY_ACTIVE','Pickup entry requires all rows and columns disabled')
        if type(config.rows) is not int or type(config.columns) is not int or min(config.rows,config.columns)<1:
            raise ValidationError('SOURCE_GRID','Positive integer grid dimensions required')
        numbers=(config.origin_x_um,config.origin_y_um,config.spacing_x_um,config.spacing_y_um,config.epsilon_x_um,config.epsilon_y_um)
        if any(type(v) not in (int,float) or not isfinite(v) for v in numbers):
            raise ValidationError('PARKING_GEOMETRY','Grid and parking coordinates must be finite')
        b=max(state.hardware.minimum_clearance_um,state.hardware.slm_clearance_um,state.hardware.alignment_tolerance_um)
        gap=minimum_trap_spacing(state.hardware)
        for d,e in ((config.spacing_x_um,config.epsilon_x_um),(config.spacing_y_um,config.epsilon_y_um)):
            if not (e>b and d-e>max(b,gap)):
                raise ValidationError('PARKING_GEOMETRY','Fixed +X/+Y parking lacks conservative clearance or axis spacing')
        mapping={}
        for q in sorted(targets):
            h=state.placement.atom_to_holder.get(q)
            if h is None or h.holder_type!=H.STATIC:
                raise ValidationError('TARGET_NOT_SLM','Every target must be a known atom on SLM',atom_ids=(q,))
            pos=state.world.traps[h.holder_id].position
            c=round((pos.x_um-config.origin_x_um)/config.spacing_x_um)
            r=round((pos.y_um-config.origin_y_um)/config.spacing_y_um)
            if (not 0<=r<config.rows or not 0<=c<config.columns or
                abs(pos.x_um-config.origin_x_um-c*config.spacing_x_um)>state.hardware.alignment_tolerance_um or
                abs(pos.y_um-config.origin_y_um-r*config.spacing_y_um)>state.hardware.alignment_tolerance_um):
                raise ValidationError('SOURCE_GRID','Target is not on the declared regular source grid',atom_ids=(q,))
            mapping[q]=(r,c)
        rs=sorted({r for r,c in mapping.values()});cs=sorted({c for r,c in mapping.values()})
        if len(rs)>state.aod.rows or len(cs)>state.aod.columns:
            raise ValidationError('AXIS_CAPACITY','Distinct target rows/columns exceed AOD capacity')
        bindings={q:CaptureBinding(q,MobileCellIndex(rs.index(r),cs.index(c)),state.placement.atom_to_holder[q].holder_id) for q,(r,c) in mapping.items()}
        # Unused axes remain disabled; their positions/order/bounds are still checked.
        def full(values,count,spacing):return tuple(values)+tuple(values[-1]+spacing*i for i in range(1,count-len(values)+1))
        ax=full([config.origin_x_um+c*config.spacing_x_um for c in cs],state.aod.columns,config.spacing_x_um)
        ay=full([config.origin_y_um+r*config.spacing_y_um for r in rs],state.aod.rows,config.spacing_y_um)
        px=tuple(x+config.epsilon_x_um if i<len(cs) else x for i,x in enumerate(ax))
        py=tuple(y+config.epsilon_y_um if i<len(rs) else y for i,y in enumerate(ay))
        p=ProgramBuilder(state,TaskIntent('parking/'+strategy,TaskTarget(),targets))
        steps=[];distance=0.;sweeps=0;loaded=set()
        def move(x,y,label,parking=False):
            nonlocal distance,sweeps,phase
            goal=Axes(tuple(x),tuple(y));old=p.state.aod.configuration()
            if goal==old:return
            phase=label
            before={q:p.state.aod.position(cell) for cell,q in p.state.placement.mobile_occupancy.items()}
            p.add(K.AOD_MOVE,label,configuration=goal)
            for cell,q in p.state.placement.mobile_occupancy.items():
                a=before[q];z=p.state.aod.position(cell);distance+=hypot(z.x_um-a.x_um,z.y_um-a.y_um)
            sweeps+=int(parking)
        cells=[[0]*config.columns for _ in range(config.rows)]
        for q,h in state.placement.atom_to_holder.items():
            if h.holder_type!=H.STATIC:continue
            pos=state.world.traps[h.holder_id].position
            r=round((pos.y_um-config.origin_y_um)/config.spacing_y_um)
            c=round((pos.x_um-config.origin_x_um)/config.spacing_x_um)
            if (0<=r<config.rows and 0<=c<config.columns and
                abs(pos.x_um-config.origin_x_um-c*config.spacing_x_um)<=state.hardware.alignment_tolerance_um and
                abs(pos.y_um-config.origin_y_um-r*config.spacing_y_um)<=state.hardware.alignment_tolerance_um):
                cells[r][c]=2 if q in targets else 1
        analysis=analyze(cells)
        rowwise=analysis['selected_axis']=='row' if strategy=='pattern_optimal' else strategy=='naive_rowwise'
        groups=analysis['row' if rowwise else 'column']['groups'] if strategy=='pattern_optimal' else [[i] for i in (rs if rowwise else cs)]
        initial=Axes(ax,ay)
        phase='empty_configuration'
        move(initial.x_um,p.state.aod.configuration().y_um,'空载配置 X')
        move(initial.x_um,initial.y_um,'空载配置 Y')
        masks=replace(trap_state(p.state),columns=tuple(i<len(cs) for i in range(state.aod.columns)) if rowwise else (False,)*state.aod.columns,
                      rows=(False,)*state.aod.rows if rowwise else tuple(i<len(rs) for i in range(state.aod.rows)))
        p.add(K.TRAP_SWITCH,'只启用列 tones，尚无交点' if rowwise else '只启用行 tones，尚无交点',switch_state=masks)
        for indices in groups:
            qs=sorted(q for q,(r,c) in mapping.items() if (r if rowwise else c) in indices)
            bb=tuple(bindings[q] for q in qs)
            x=list(p.state.aod.configuration().x_um);y=list(p.state.aod.configuration().y_um)
            for i,coordinate in enumerate(cs if rowwise else rs):
                values=[cells[line][coordinate] if rowwise else cells[coordinate][line] for line in indices]
                if 2 in values and 1 in values:raise ValidationError('GROUP_CONFLICT','Capture batch includes a protected intersection')
                if 2 in values:
                    if rowwise:x[i]=ax[i]
                    else:y[i]=ay[i]
                elif 1 in values:
                    if rowwise:x[i]=px[i]
                    else:y[i]=py[i]
            move(x,y,'仅调整不匹配的列' if rowwise else '仅调整不匹配的行')
            phase='capture_closure'
            p.add(K.AOD_RECAPTURE if loaded else K.AOD_LOAD,('兼容行拾取 ' if rowwise else '兼容列拾取 ')+','.join(qs),bindings=bb)
            loaded.update(qs)
            if rowwise:
                y=list(p.state.aod.configuration().y_um)
                for bnd in bb:y[bnd.cell.row]=py[bnd.cell.row]
                move(p.state.aod.configuration().x_um,y,'本批行 Y parking',True)
            else:
                x=list(p.state.aod.configuration().x_um)
                for bnd in bb:x[bnd.cell.column]=px[bnd.cell.column]
                move(x,p.state.aod.configuration().y_um,'本批列 X parking',True)
            if set(p.state.placement.mobile_occupancy.values())!=loaded:
                raise ValidationError('PICKUP_SET','Actual loaded set differs from processed targets')
            if any(p.state.placement.atom_to_holder[q]!=h for q,h in state.placement.atom_to_holder.items() if q not in loaded):
                raise ValidationError('PROTECTED_CHANGED','Unprocessed/protected holders changed')
            axes=p.state.aod.configuration()
            if (rowwise and any(on and axes.y_um[i]!=py[i] for i,on in enumerate(p.state.aod.enabled_rows)) or
                not rowwise and any(on and axes.x_um[i]!=px[i] for i,on in enumerate(p.state.aod.enabled_columns))):
                raise ValidationError('PARKING_INVARIANT','Processed group axes must be in their parking lanes')
            steps.append({'group':indices[0],'groups':indices,'axis':'row' if rowwise else 'column','picked':qs,'loaded':sorted(loaded),
                          'operation_count':len(p.operations),'end_us':sum(o.duration_us for o in p.operations)})
        move(px,p.state.aod.configuration().y_um,'统一最终 X parking')
        move(p.state.aod.configuration().x_um,py,'统一最终 Y parking')
        steps[-1]['operation_count']=len(p.operations)
        steps[-1]['end_us']=sum(o.duration_us for o in p.operations)
        phase='complete_audit'
        p.intent=replace(p.intent,target=TaskTarget(tuple(sorted(p.state.placement.atom_to_holder.items())),p.state.aod.configuration(),trap_state(p.state)))
        plan=p.finish('parking/'+strategy+'/v2')
        return PickupPlan(plan,p.state.aod,{q:b.cell for q,b in bindings.items()},plan.estimated_duration_us,len(steps),sweeps,distance,tuple(steps),analysis=analysis)
    except (ValidationError,ValueError,TypeError) as e:
        v=getattr(e,'violation',None)
        return PlanningFailure(v.code if v else 'INVALID_INPUT',v.message if v else str(e),phase,v)


def plan_collective_transport(state, shift_x_um, shift_y_um):
    """Separate checked continuation from the actual loaded/parked state, X then Y."""
    if not state.placement.mobile_occupancy:return None
    p=ProgramBuilder(state,TaskIntent('parking/collective-transport',TaskTarget(),frozenset(state.placement.mobile_occupancy.values())))
    start=state.aod.configuration()
    goal=Axes(tuple(x+shift_x_um for x in start.x_um),tuple(y+shift_y_um for y in start.y_um))
    for c,label in ((Axes(goal.x_um,start.y_um),'集体运输 X'),(goal,'集体运输 Y')):
        if c!=p.state.aod.configuration():p.add(K.AOD_MOVE,label,configuration=c)
    if not p.operations:return None
    p.intent=replace(p.intent,target=TaskTarget(tuple(sorted(p.state.placement.atom_to_holder.items())),goal,trap_state(p.state)))
    return p.finish('parking/collective-transport/v1')
