"""One rigid AOD with configurable 1xN capacity: joint preparation and cleanup.

Jointly stage needed atoms at EZ SLM sites, then use the existing single
active-cell gate service. No independent trap trajectories or batch CZ claim.
"""
from dataclasses import replace
from neutral_atom_env.domain.aod import AODConfiguration
from neutral_atom_env.domain.models import HolderType as H, MobileCellIndex, Position2D, ZoneType
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget, CaptureBinding, OperationType as K
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_env.replay.serializer import primitive
from .greedy import GreedyCompiler, GateCandidate
from .planners import OrthogonalHalfGridPlanner
from .astar import AStarHalfGridPlanner
from .program import ProgramBuilder
from .tasks import idle
from .single_trap import in_zone


class RigidArrayOrthogonalPlanner:
    id='rigid-array-orthogonal-half-grid-v1'
    orthogonal=True

    def candidates(self,request):
        a,b=request.start,request.target
        if a.translated(b.x_um[0]-a.x_um[0],b.y_um[0]-a.y_um[0])!=b:
            return
        single=replace(request,start=AODConfiguration((a.x_um[0],),(a.y_um[0],)),
                       target=AODConfiguration((b.x_um[0],),(b.y_um[0],)))
        for route in OrthogonalHalfGridPlanner().candidates(single):
            yield tuple(a.translated(p.x_um[0]-a.x_um[0],p.y_um[0]-a.y_um[0]) for p in route)


class MultiTrapGreedyCompiler(GreedyCompiler):
    id='greedy-rigid-multi-trap-v1'

    def __init__(self,**kwargs):
        super().__init__(**kwargs)
        self.planner=AStarHalfGridPlanner()

    def check(self,state):
        idle(state)
        if (state.hardware.backend!='rigid' or state.aod.rows!=1 or state.aod.columns<2
                or state.aod.spacing_um!=10 or state.aod.column_offsets_um is not None
                or state.aod.row_offsets_um is not None):
            raise ValidationError('MULTI_TRAP_PLATFORM','Requires one rigid 1xN AOD, N >= 2, with 10 um spacing')
        # Between services only cell 0 may remain loaded. Batch preparation
        # accounts for every other cell and parks all of them before the gate.
        if any(c!=MobileCellIndex(0,0) for c in state.placement.mobile_occupancy):
            raise ValidationError('MULTI_TRAP_ORIGIN','Nonzero loaded cells require completion of their joint preparation')

    def target(self,p,target):
        axes=target.aod_configuration
        self.bulk_cleanup(p,target)
        # Reuse static target assignment but preserve the complete array axes.
        super().target(p,replace(target,aod_configuration=None,traps=None))
        if axes is not None:
            current=p.state.aod.configuration()
            pose=Position2D(axes.x_um[0],axes.y_um[0])
            if current.translated(pose.x_um-current.x_um[0],pose.y_um-current.y_um[0])!=axes:
                raise ValidationError('MULTI_TRAP_TARGET','Rigid array target must preserve all axes and spacing')
            self.route(p,pose)
        if target.traps is not None and trap_state(p.state)!=target.traps:
            p.add(K.TRAP_SWITCH,'Apply terminal supports',switch_state=target.traps)

    def transfer_group(self,p,destinations,*,label='Joint transfer'):
        """Move a fixed same-row static group to a rigidly translated SLM row.

        General reusable transport primitive, independent of circuit identities.
        Every active cell is explicitly bound; no incidental atoms are omitted.
        """
        if not destinations:return
        if p.state.placement.mobile_occupancy:
            raise ValidationError('JOINT_TRANSFER_BUSY','Joint transfer requires an empty AOD')
        members={}
        for atom,site in sorted(destinations.items()):
            holder=p.state.placement.atom_to_holder.get(atom)
            if holder is None or holder.holder_type!=H.STATIC or site not in p.state.world.traps:
                raise ValidationError('JOINT_TRANSFER_TARGET','Joint operands need real static sources and destinations')
            occupant=p.state.placement.static_occupancy.get(site)
            if occupant is not None and occupant!=atom:
                raise ValidationError('OCCUPIED_TASK_TARGET','Joint destination is occupied by another atom')
            members[atom]=(p.state.world.traps[holder.holder_id],p.state.world.traps[site])
        if all(source.id==destination.id for source,destination in members.values()):return
        origin=Position2D(min(source.position.x_um for source,_ in members.values()),
                          next(iter(members.values()))[0].position.y_um)
        shifts={(round(destination.position.x_um-source.position.x_um,9),
                 round(destination.position.y_um-source.position.y_um,9)) for source,destination in members.values()}
        if len(shifts)!=1:
            raise ValidationError('JOINT_TRANSFER_SHAPE','Joint destinations must preserve the complete group geometry')
        bindings=[];unload=[]
        for atom,(source,destination) in members.items():
            column=(source.position.x_um-origin.x_um)/p.state.aod.spacing_um
            if (source.position.y_um!=origin.y_um or abs(column-round(column))>1e-9
                    or not 0<=round(column)<p.state.aod.columns):
                raise ValidationError('JOINT_TRANSFER_SHAPE','Joint sources must fit one ordered rigid AOD row')
            cell=MobileCellIndex(0,round(column))
            bindings.append(CaptureBinding(atom,cell,source.id))
            unload.append(CaptureBinding(atom,cell,destination.id))
        bindings=tuple(bindings);unload=tuple(unload)
        dx,dy=next(iter(shifts));destination=Position2D(origin.x_um+dx,origin.y_um+dy)
        self.route(p,origin)
        p.add(K.AOD_LOAD,f'{label}: load {len(bindings)} atoms',bindings=bindings)
        self.route(p,destination,depart=bindings,approach=unload,label=f'{label}: transport')
        p.add(K.AOD_OFFLOAD,f'{label}: offload {len(unload)} atoms',bindings=unload)

    def bulk_cleanup(self,p,target):
        """Greedily group compatible terminal assignments without combinations.

        Equal translation vectors and source rows define groups. Each AOD-width
        window is tried at most once; a refused group leaves the builder intact
        and the existing individual target constructor remains the fallback.
        """
        desired=dict(target.holders)
        loaded=p.state.placement.mobile_occupancy
        if loaded:
            atom=next(iter(loaded.values()));holder=desired.get(atom)
            if holder is None or holder.holder_type!=H.STATIC or holder.holder_id in p.state.placement.static_occupancy:return
            self.move_atom(p,atom,holder.holder_id)
        groups={}
        for atom,holder in sorted(desired.items()):
            source=p.state.placement.atom_to_holder.get(atom)
            if holder.holder_type!=H.STATIC or source is None or source.holder_type!=H.STATIC or holder==source:continue
            if holder.holder_id not in p.state.world.traps or holder.holder_id in p.state.placement.static_occupancy:continue
            a=p.state.world.traps[source.holder_id].position;b=p.state.world.traps[holder.holder_id].position
            key=(a.y_um,round(b.x_um-a.x_um,9),round(b.y_um-a.y_um,9),round(a.x_um%10,9))
            groups.setdefault(key,[]).append((a.x_um,atom,holder.holder_id))
        for members in groups.values():
            remaining=sorted(members)
            while remaining:
                left=remaining[0][0];window=[item for item in remaining if item[0]-left<=10*(p.state.aod.columns-1)+1e-9]
                remaining=remaining[len(window):]
                if len(window)<2:continue
                trial=ProgramBuilder(p.origin,p.intent);trial.state=p.state
                try:self.transfer_group(trial,{atom:site for _,atom,site in window},label='Joint terminal return')
                except ValidationError:continue
                self.append(p,trial.operations)

    @staticmethod
    def append(p,operations):
        for op in operations:
            p.add(op.operation_type,op.label,target=op.target_pose,configuration=op.target_configuration,
                  bindings=op.transfer_bindings,phase=op.transfer_phase,switch_state=op.switch_state)

    def alternatives(self,gate_id,state,*,site_limit=4,site_offset=0):
        candidates,rejected,cut=super().alternatives(gate_id,state,site_limit=site_limit,site_offset=site_offset)
        gate=state.dag.nodes[gate_id].gate
        if gate.gate_type!='CZ' or state.placement.mobile_occupancy or not self.adaptive_sites:
            return candidates,rejected,cut
        # Prefetch is allowed for known future CZ operands, including blocked
        # gates. It changes only placement; their logical effects remain blocked.
        needed={q for node in state.dag.nodes.values() if node.gate.gate_type=='CZ'
                and node.status.value!='completed' for q in node.gate.qubit_ids}
        sources={q:state.world.traps[h.holder_id] for q,h in state.placement.atom_to_holder.items()
                 if q in needed and h.holder_type==H.STATIC
                 and in_zone(state,state.world.traps[h.holder_id].position,ZoneType.STORAGE)}
        groups={}
        for q in gate.qubit_ids:
            if q not in sources:continue
            point=sources[q].position
            row=sorted((trap.position.x_um,other,trap) for other,trap in sources.items()
                       if trap.position.y_um==point.y_um and abs((trap.position.x_um-point.x_um)/10-round((trap.position.x_um-point.x_um)/10))<1e-9)
            # Choose the widest demand window containing this operand. Source
            # rows, not gate names or logical-code blocks, determine grouping.
            windows=[]
            for x,_,_ in row:
                if not x<=point.x_um<=x+10*(state.aod.columns-1):continue
                values={other:trap for xx,other,trap in row if x<=xx<=x+10*(state.aod.columns-1)}
                windows.append((-len(values),x,values))
            if not windows:continue
            _,left,members=min(windows,key=lambda item:(item[0],item[1]))
            origin=Position2D(left,point.y_um)
            if len(members)>=2:
                groups[tuple(sorted(members))]=(origin,members)
        for group,(origin,members) in groups.items():
            bindings=tuple(CaptureBinding(q,MobileCellIndex(0,round((t.position.x_um-origin.x_um)/10)),t.id)
                           for q,t in sorted(members.items()))
            by_position={(t.position.x_um,t.position.y_um):t.id for t in state.world.traps.values()
                         if t.id not in state.placement.static_occupancy and in_zone(state,t.position,ZoneType.ENTANGLEMENT)}
            destinations=[]
            for xy,site in by_position.items():
                points=[(xy[0]+b.cell.column*10,xy[1]) for b in bindings]
                if all(p in by_position for p in points):
                    destinations.append((abs(xy[0]-origin.x_um)+abs(xy[1]-origin.y_um),xy))
            destinations.sort()
            cut+=max(0,len(destinations)-site_offset-site_limit)
            for _,xy in destinations[site_offset:site_offset+site_limit]:
                key=f'{gate_id}/joint-{len(group)}/{xy[0]:g},{xy[1]:g}'
                p=ProgramBuilder(state,TaskIntent(f'{self.id}/{state.version}/{key}',TaskTarget(),
                    frozenset(group),gate_id,'effect',gate_id))
                try:
                    self.transfer_group(p,{b.atom_id:by_position[(xy[0]+b.cell.column*10,xy[1])] for b in bindings},label='Joint prefetch to EZ')
                    # Compare the actual remaining gate service, not an estimated teleport.
                    follow,failures,_=super().alternatives(gate_id,p.state,site_limit=site_limit)
                    if not follow:
                        rejected.extend(dict(r,preparation=key) for r in failures)
                        continue
                    best=min(follow,key=lambda c:c.cost)
                    self.append(p,best.plan.operations)
                    p.intent=replace(p.intent,target=TaskTarget(tuple(sorted(p.state.placement.atom_to_holder.items())),
                        p.state.aod.configuration(),trap_state(p.state)))
                    candidates.append(GateCandidate(key+'/'+best.key,gate_id,best.anchor,best.site,p.finish(self.id)))
                except ValidationError as error:
                    rejected.append({'candidate':key,'violation':primitive(error.violation)})
        return candidates,rejected,cut
