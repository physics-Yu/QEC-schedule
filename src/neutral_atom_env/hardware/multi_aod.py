"""Independent AOD lanes on one state, restricted to separated fixed envelopes.

All atoms, SLM supports, CZ spectators and quantum state remain in the same
state. Device envelopes prove cross-lane swept separation even for unequal
durations; this backend does not support overlapping workspaces/AOD transfers.
"""
from dataclasses import replace
from itertools import combinations
from math import hypot
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import HolderRef, HolderType as H, MobileCellIndex, Position2D
from neutral_atom_env.domain.operations import TrapState, TransferRuntime, OperationType as K
from neutral_atom_env.hardware.rigid_aod import distance, segment_clearance
from neutral_atom_env.world import PlacementState


def device(state, aod_id='AOD_0'):
    if aod_id not in state.aods:
        raise ValidationError('UNKNOWN_AOD', 'Operation references an unknown AOD', holder_id=aod_id)
    return state.aods[aod_id]


def needs_device_origin(state):
    return len(state.aods)>1 or any(a.envelope is not None for a in state.aods.values())


def with_aod(state, aod_id, value, **changes):
    device(state, aod_id)
    if value.aod_id != aod_id:
        raise ValidationError('INVALID_AOD_ID', 'Device identity cannot change during an operation')
    devices = dict(state.aods); devices[aod_id] = value
    return replace(state, aod=devices['AOD_0'], aods=devices, **changes)


def with_transfer(state, aod_id, value, **changes):
    transfers = dict(state.transfers)
    if value is None: transfers.pop(aod_id, None)
    else: transfers[aod_id] = value
    return replace(state, transfer=transfers.get('AOD_0'), transfers=transfers, **changes)


def occupancy(state, aod_id):
    return {cell:q for cell,q in state.placement.mobile_occupancy.items() if cell.aod_id == aod_id}


def supports(state, aod_id):
    aod = device(state, aod_id)
    return TrapState(aod.enabled_rows, aod.enabled_columns, tuple(sorted(state.slm_enabled.items())))


def with_supports(state, aod_id, traps, **changes):
    aod = device(state, aod_id)
    return with_aod(state, aod_id, replace(aod, enabled_rows=traps.rows, enabled_columns=traps.columns),
                    slm_enabled=dict(traps.slm), **changes)


def validate_envelopes(state):
    devices = tuple(state.aods.values())
    for aod in devices:
        bound = aod.envelope
        if bound is None or not state.world.bounds.contains(bound.lower) or not state.world.bounds.contains(bound.upper):
            raise ValidationError('AOD_ENVELOPE_REQUIRED', 'Multiple AODs require fixed in-world work envelopes')
        axes = aod.configuration()
        if any(not bound.contains(Position2D(x,y)) for x in (axes.x_um[0],axes.x_um[-1]) for y in (axes.y_um[0],axes.y_um[-1])):
            raise ValidationError('AOD_ENVELOPE_EXCEEDED', 'AOD axes leave its declared work envelope', holder_id=aod.aod_id)
    for left, right in combinations(devices, 2):
        a,b = left.envelope,right.envelope
        dx=max(0.,a.lower.x_um-b.upper.x_um,b.lower.x_um-a.upper.x_um)
        dy=max(0.,a.lower.y_um-b.upper.y_um,b.lower.y_um-a.upper.y_um)
        if hypot(dx,dy) + 1e-9 < max(state.hardware.minimum_clearance_um,state.hardware.slm_clearance_um):
            raise ValidationError('AOD_ENVELOPES_OVERLAP', 'Independent device envelopes must have swept safety separation')


def validate_support(state):
    from neutral_atom_env.hardware.dynamic_traps import TRANSFERS, LOADS
    for q,h in state.placement.atom_to_holder.items():
        enabled=(state.slm_enabled.get(h.holder_id,False) if h.holder_type==H.STATIC else
                 device(state,h.holder_id.aod_id).is_enabled(h.holder_id) if h.holder_type==H.MOBILE else True)
        if not enabled:
            raise ValidationError('HOLDER_SUPPORT_DISABLED','A committed holder must remain enabled',atom_ids=(q,))
    for key,t in state.transfers.items():
        aod=device(state,key)
        if not isinstance(t,TransferRuntime) or t.kind not in TRANSFERS or t.stage!='target_supported' or aod.is_moving or not t.bindings:
            raise ValidationError('INVALID_TRANSFER_STATE','Invalid supported device handoff')
        for b in t.bindings:
            expected=HolderRef(H.STATIC,b.static_trap_id) if t.kind in LOADS else HolderRef(H.MOBILE,b.cell)
            trap=state.world.traps.get(b.static_trap_id)
            if (b.cell.aod_id!=key or state.placement.atom_to_holder.get(b.atom_id)!=expected or trap is None
                or not state.slm_enabled[trap.id] or not aod.is_enabled(b.cell)
                or distance(aod.position(b.cell),trap.position)>state.hardware.alignment_tolerance_um):
                raise ValidationError('TRANSFER_SUPPORT_LOST','Handoff must retain both aligned supports',atom_ids=(b.atom_id,))


class DeviceBackend:
    """Pure device-selected operations; never remove or rename foreign atoms."""
    def __init__(self, hardware, aod_id):
        from neutral_atom_env.hardware import get_backend
        self.base=get_backend(hardware); self.aod_id=aod_id
        self.name=self.base.name; self.motion_profile=self.base.motion_profile
    def target_aod(self,aod,target): return self.base.target_aod(aod,target)
    def move_duration(self,aod,target,hardware): return self.base.move_duration(aod,target,hardware)
    def move_distance(self,aod,target): return self.base.move_distance(aod,target)
    def atom_distance(self,state,target):
        start=device(state,self.aod_id);end=self.target_aod(start,target)
        return sum(distance(start.position(c),end.position(c)) for c in occupancy(state,self.aod_id))
    def validate_pose(self,state,target):
        end=self.target_aod(device(state,self.aod_id),target)
        from neutral_atom_env.hardware.trap_spacing import validate_trap_spacing
        validate_trap_spacing(end,state.hardware)
        validate_envelopes(with_aod(state,self.aod_id,end))
    def capture_closure(self,state,pose,*,active_only=False,allow_loaded=False):
        aod=device(state,self.aod_id)
        if aod.is_moving or (occupancy(state,self.aod_id) and not allow_loaded):
            raise ValidationError('AOD_BUSY','Capture needs this device empty and stationary')
        self.validate_pose(state,pose); aod=self.target_aod(aod,pose)
        cells=(aod.active_cells if active_only else tuple(MobileCellIndex(r,c,self.aod_id) for r in range(aod.rows) for c in range(aod.columns)))
        result=[]
        from neutral_atom_env.domain.operations import CaptureBinding
        for q,h in sorted(state.placement.atom_to_holder.items()):
            if h.holder_type!=H.STATIC: continue
            p=state.world.traps[h.holder_id].position
            aligned=[c for c in cells if distance(aod.position(c),p)<=state.hardware.alignment_tolerance_um]
            if len(aligned)>1: raise ValidationError('AMBIGUOUS_CAPTURE','Multiple traps align to one atom')
            if aligned: result.append(CaptureBinding(q,aligned[0],h.holder_id))
        return tuple(result)
    def validate_active_sweep(self,state,end,*,allowed=(),cells=None):
        aod=device(state,self.aod_id); exemptions={(b.cell,b.atom_id) for b in allowed}
        own=occupancy(state,self.aod_id)
        for cell in aod.active_cells if cells is None else cells:
            start,finish=aod.position(cell),end.position(cell)
            for q,atom in state.atoms.items():
                if not atom.alive or own.get(cell)==q: continue
                h=state.placement.atom_to_holder[q]
                if h.holder_type==H.LOST: continue
                p=state.placement.position(q,state.world,state.aods)
                if (cell,q) in exemptions and start==finish and distance(start,p)<=state.hardware.alignment_tolerance_um: continue
                if h.holder_type==H.MOBILE and h.holder_id.aod_id==self.aod_id:
                    other_end=end.position(h.holder_id)
                    relative_start=Position2D(start.x_um-p.x_um,start.y_um-p.y_um)
                    relative_end=Position2D(finish.x_um-other_end.x_um,finish.y_um-other_end.y_um)
                    d,closest=segment_clearance(Position2D(0,0),relative_start,relative_end)
                else:
                    d,closest=segment_clearance(p,start,finish)
                if d+1e-9<state.hardware.minimum_clearance_um:
                    raise ValidationError('ACTIVE_TRAP_SWEEP','Active trap sweeps a live atom, including other devices',atom_ids=(q,),position=closest)
    def validate_geometry_move(self,state,target):
        aod=device(state,self.aod_id); self.validate_pose(state,aod.configuration() if self.name!='rigid' else aod.pose)
        self.validate_pose(state,target);end=self.target_aod(aod,target)
        if self.name=='row_column_orthogonal' and aod.configuration().x_um!=end.configuration().x_um and aod.configuration().y_um!=end.configuration().y_um:
            raise ValidationError('ORTHOGONAL_MOVE_REQUIRED','One primitive may change only one axis')
        moving=occupancy(state,self.aod_id)
        starts={q:aod.position(c) for c,q in moving.items()};ends={q:end.position(c) for c,q in moving.items()}
        limit=state.hardware.minimum_clearance_um
        for a,b in combinations(starts,2):
            r0=Position2D(starts[a].x_um-starts[b].x_um,starts[a].y_um-starts[b].y_um)
            r1=Position2D(ends[a].x_um-ends[b].x_um,ends[a].y_um-ends[b].y_um)
            if segment_clearance(Position2D(0,0),r0,r1)[0]+1e-9<limit:
                raise ValidationError('MOBILE_CLEARANCE','Loaded atoms violate swept clearance',atom_ids=(a,b))
        for q,start in starts.items():
            for other,atom in state.atoms.items():
                if other in starts or not atom.alive or state.placement.atom_to_holder[other].holder_type==H.LOST: continue
                p=state.placement.position(other,state.world,state.aods)
                d,closest=segment_clearance(p,start,ends[q])
                if d+1e-9<limit: raise ValidationError('PATH_BLOCKED','Swept atom clearance violated',atom_ids=(q,other),position=closest)
    def validate_move(self,state,target,*,transfer=None,bindings=()):
        if self.aod_id in state.transfers: raise ValidationError('TRANSFER_BUSY','Motion cannot interrupt this device handoff')
        self.validate_geometry_move(state,target)
        start=device(state,self.aod_id);end=self.target_aod(start,target)
        self.validate_active_sweep(state,end)
        if transfer not in {None,'depart','approach'}: raise ValidationError('INVALID_TRANSFER_PHASE','Unknown transfer phase')
        bound={b.atom_id:b for b in bindings};radius=state.hardware.slm_clearance_um;tol=state.hardware.alignment_tolerance_um
        for cell,q in occupancy(state,self.aod_id).items():
            a,b=start.position(cell),end.position(cell);binding=bound.get(q)
            for trap in state.world.traps.values():
                if not state.slm_enabled[trap.id] and not (transfer and binding and trap.id==binding.static_trap_id): continue
                if transfer and binding and trap.id==binding.static_trap_id:
                    near,far=(a,b) if transfer=='depart' else (b,a)
                    dx,dy=far.x_um-near.x_um,far.y_um-near.y_um
                    outward=(near.x_um-trap.position.x_um)*dx+(near.y_um-trap.position.y_um)*dy
                    if binding.cell!=cell or distance(near,trap.position)>tol or distance(far,trap.position)+1e-9<radius or outward < -tol*max(1.,hypot(dx,dy)):
                        raise ValidationError('INVALID_TRANSFER_PATH','Transfer must monotonically leave/approach its actual trap')
                elif segment_clearance(trap.position,a,b)[0]+1e-9<radius:
                    raise ValidationError('SLM_PATH_BLOCKED','Move intersects an enabled SLM exclusion region',atom_ids=(q,),holder_id=trap.id)
        from neutral_atom_env.hardware.ez_neighbors import validate_ez_neighbors
        validate_ez_neighbors(with_aod(state,self.aod_id,end))
    def move(self,state,target,*,transfer=None,bindings=()):
        self.validate_move(state,target,transfer=transfer,bindings=bindings)
        return with_aod(state,self.aod_id,self.target_aod(device(state,self.aod_id),target))
    def begin_transfer(self,state,bindings,kind):
        from neutral_atom_env.hardware.dynamic_traps import LOADS,TRANSFERS
        bindings=tuple(bindings);aod=device(state,self.aod_id);own=occupancy(state,self.aod_id)
        if kind not in TRANSFERS or self.aod_id in state.transfers or aod.is_moving:
            raise ValidationError('TRANSFER_BUSY','Device handoff must be idle and stationary')
        if not bindings or any(b.cell.aod_id!=self.aod_id for b in bindings) or any(len({getattr(b,k) for b in bindings})!=len(bindings) for k in ('atom_id','cell','static_trap_id')):
            raise ValidationError('INVALID_TRANSFER_SET','Bindings must be unique and belong to the selected device')
        if kind in {K.AOD_PARK,K.AOD_RECAPTURE} and not state.hardware.selective_transfer_enabled:
            raise ValidationError('SELECTIVE_TRANSFER_UNSUPPORTED','Partial transfer requires an explicit capability')
        loading=kind in LOADS
        if kind==K.AOD_LOAD and own: raise ValidationError('AOD_BUSY','LOAD requires this AOD empty')
        if kind==K.AOD_OFFLOAD and set(own.values())!={b.atom_id for b in bindings}: raise ValidationError('OFFLOAD_SET_MISMATCH','OFFLOAD must account for this device entire load')
        before=supports(state,self.aod_id);rows,cols,slm=list(before.rows),list(before.columns),dict(before.slm)
        for b in bindings:
            trap=state.world.traps.get(b.static_trap_id)
            expected=HolderRef(H.STATIC,b.static_trap_id) if loading else HolderRef(H.MOBILE,b.cell)
            if trap is None or state.placement.atom_to_holder.get(b.atom_id)!=expected: raise ValidationError('TRANSFER_SOURCE_MISMATCH','Actual source does not own this atom')
            occupied=own.get(b.cell) if loading else state.placement.static_occupancy.get(trap.id)
            if occupied is not None: raise ValidationError('TRANSFER_DESTINATION_OCCUPIED','Destination is already occupied')
            if distance(aod.position(b.cell),trap.position)>state.hardware.alignment_tolerance_um: raise ValidationError('TRANSFER_MISALIGNMENT','Handoff must align at its actual SLM site')
            if loading: rows[b.cell.row]=cols[b.cell.column]=True
            else: slm[trap.id]=True
        overlap=TrapState(tuple(rows),tuple(cols),tuple(sorted(slm.items())))
        if loading:
            candidate=with_supports(state,self.aod_id,overlap)
            actual=tuple(b for b in self.capture_closure(candidate,aod.configuration() if self.name!='rigid' else aod.pose,active_only=True,allow_loaded=kind==K.AOD_RECAPTURE))
            if actual!=bindings: raise ValidationError('CAPTURE_CHANGED','Transfer must cover the full active Cartesian capture closure')
            for b in bindings: slm[b.static_trap_id]=False
        else:
            remaining=set(own)-{b.cell for b in bindings}
            for b in bindings:
                if not any(c.row==b.cell.row for c in remaining): rows[b.cell.row]=False
                elif not any(c.column==b.cell.column for c in remaining): cols[b.cell.column]=False
                else: raise ValidationError('SHARED_AXIS_SUPPORT','Closing axes would drop another atom')
            if not remaining: rows=[False]*aod.rows;cols=[False]*aod.columns
        target=TrapState(tuple(rows),tuple(cols),tuple(sorted(slm.items())))
        transfer=TransferRuntime(kind,bindings,before,target)
        result=with_transfer(with_supports(state,self.aod_id,overlap),self.aod_id,transfer)
        self.validate_active_sweep(result,device(result,self.aod_id),allowed=bindings if loading else ())
        self.finish_transfer(result,bindings,kind)
        return result
    def finish_transfer(self,state,bindings,kind):
        from neutral_atom_env.hardware.dynamic_traps import LOADS
        t=state.transfers.get(self.aod_id)
        if t is None or t.bindings!=tuple(bindings) or t.kind!=kind: raise ValidationError('TRANSFER_STATE_MISMATCH','No matching device handoff')
        validate_support(state);holders=dict(state.placement.atom_to_holder)
        for b in bindings: holders[b.atom_id]=HolderRef(H.MOBILE,b.cell) if kind in LOADS else HolderRef(H.STATIC,b.static_trap_id)
        # Apply only this lane's SLM deltas; another simultaneous handoff may
        # have committed unrelated supports since this lane began.
        slm=dict(state.slm_enabled);before=dict(t.source_traps.slm);target=dict(t.target_traps.slm)
        for key in before:
            if before[key]!=target[key]: slm[key]=target[key]
        traps=replace(t.target_traps,slm=tuple(sorted(slm.items())))
        result=with_transfer(state,self.aod_id,None,placement=PlacementState(holders))
        result=with_supports(result,self.aod_id,traps)
        self.validate_geometry_move(result,device(result,self.aod_id).configuration() if self.name!='rigid' else device(result,self.aod_id).pose)
        self.validate_active_sweep(result,device(result,self.aod_id))
        return result
    def _transfer(self,state,bindings,kind): return self.finish_transfer(self.begin_transfer(state,bindings,kind),bindings,kind)
    def load(self,state,bindings): return self._transfer(state,bindings,K.AOD_LOAD)
    def offload(self,state,bindings): return self._transfer(state,bindings,K.AOD_OFFLOAD)
    def park(self,state,bindings): return self._transfer(state,bindings,K.AOD_PARK)
    def recapture(self,state,bindings): return self._transfer(state,bindings,K.AOD_RECAPTURE)
    def switch_traps(self,state,target):
        aod=device(state,self.aod_id)
        if state.transfers or any(value.is_moving for value in state.aods.values()):
            raise ValidationError('TRAP_SWITCH_BUSY','Global SLM-mask switch requires every device outside motion/handoff')
        result=with_supports(state,self.aod_id,target)
        self.validate_pose(result,aod.configuration() if self.name!='rigid' else aod.pose)
        self.validate_active_sweep(result,device(result,self.aod_id))
        for key,enabled in result.slm_enabled.items():
            if enabled and not state.slm_enabled[key]:
                for cell,q in state.placement.mobile_occupancy.items():
                    if distance(device(state,cell.aod_id).position(cell),state.world.traps[key].position)<state.hardware.slm_clearance_um:
                        raise ValidationError('SLM_ENABLE_OVERLAP','SLM enabling beneath any device needs a bound handoff',atom_ids=(q,))
        return result
    def actual_pairs(self,state):
        from neutral_atom_env.domain.models import ZoneType
        points=[]
        for q,atom in state.atoms.items():
            if atom.alive and state.placement.atom_to_holder[q].holder_type!=H.LOST:
                p=state.placement.position(q,state.world,state.aods)
                if any(z.zone_type==ZoneType.ENTANGLEMENT and z.bounds.contains(p) for z in state.world.zones): points.append((q,p))
        return frozenset(tuple(sorted((a,b))) for (a,p),(b,q) in combinations(points,2) if distance(p,q)<=state.hardware.interaction_distance_um+1e-9)
    def validate_pulse_batch(self,state,gate_ids):
        ids=tuple(gate_ids)
        if not ids or len(set(ids))!=len(ids) or any(g not in state.dag.nodes for g in ids): raise ValidationError('INVALID_CZ_BATCH','Known unique CZ IDs required')
        gates=tuple(state.dag.nodes[g].gate for g in ids);qs=tuple(q for g in gates for q in g.qubit_ids)
        if any(g.gate_type!='CZ' for g in gates): raise ValidationError('UNSUPPORTED_GATE','CZ pulse requires CZ gates')
        if len(set(qs))!=len(qs): raise ValidationError('OVERLAPPING_CZ_BATCH','CZ targets must be disjoint')
        if any(not state.atoms[q].alive or state.atoms[q].measured for q in qs): raise ValidationError('CZ_TARGET_UNAVAILABLE','Targets must be alive/unmeasured')
        if state.transfers or any(a.is_moving for a in state.aods.values()): raise ValidationError('AOD_MOVING','Global CZ illumination needs every device stationary and stable')
        if len(ids)>1 and (len({state.dag.nodes[g].status.value for g in ids})!=1 or state.dag.nodes[ids[0]].status.value not in {'ready','reserved','running'}): raise ValidationError('CZ_BATCH_NOT_READY','CZ batch must share ready phase')
        for key in state.aods:
            backend=DeviceBackend(state.hardware,key);aod=device(state,key)
            backend.validate_move(state,aod.configuration() if backend.name!='rigid' else aod.pose)
        actual=self.actual_pairs(state);expected=frozenset(tuple(sorted(g.qubit_ids)) for g in gates)
        if actual!=expected: raise ValidationError('UNINTENDED_PAIR',f'Global actual pairs {sorted(actual)} != intended {sorted(expected)}')
        return actual
    def validate_pulse(self,state,gate_id): return self.validate_pulse_batch(state,(gate_id,))


def backend_for(state,aod_id='AOD_0'):
    device(state,aod_id)
    if len(state.aods)>1: return DeviceBackend(state.hardware,aod_id)
    from neutral_atom_env.hardware import get_backend
    return get_backend(state.hardware)
