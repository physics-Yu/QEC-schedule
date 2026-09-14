"""Constructive single-trap tasks from persistent SLM/loaded states.

Finite routing is audited by the shared backend. The supported family has
separated SLM sites, clear half-grid corridors, spare SLM capacity and EZ sites.
"""
from dataclasses import replace
from neutral_atom_env.domain.models import HolderType as H, HolderRef, MobileCellIndex, Position2D, ZoneType
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget, CaptureBinding, OperationType as K
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_env.program.tasks import idle
from neutral_atom_strategies.motion.single_trap import route, in_zone
from neutral_atom_strategies.motion.planners import HalfGridPlanner


CELL=MobileCellIndex(0,0)


class PersistentTargetCompiler:
    id='persistent-target-v1'

    def __init__(self, planner=None):
        self.planner=planner or HalfGridPlanner()

    def check(self,state):
        idle(state)
        if state.hardware.backend!='rigid' or (state.aod.rows,state.aod.columns)!=(1,1):
            raise ValidationError('SINGLE_TRAP_REQUIRED','Persistent constructor requires one rigid cell')

    def route(self,p,target,**options):
        route(p,target,self.planner,**options)

    def spare(self,state,exclude=(),zone=ZoneType.STORAGE):
        for key,t in sorted(state.world.traps.items()):
            if key not in state.placement.static_occupancy and key not in exclude and in_zone(state,t.position,zone):
                return key
        if zone==ZoneType.STORAGE:
            return self.spare(state,exclude,ZoneType.ENTANGLEMENT)
        raise ValidationError('NO_TERMINAL_CAPACITY','No free legal SLM site in the requested zone')

    def move_atom(self,p,q,site):
        if p.state.placement.atom_to_holder[q]==HolderRef(H.STATIC,site):return
        if site not in p.state.world.traps:
            raise ValidationError('UNKNOWN_TRAP','Unknown terminal site')
        if site in p.state.placement.static_occupancy:
            raise ValidationError('OCCUPIED_TASK_TARGET','Destination is occupied')
        self.load_atom(p,q,exclude=(site,))
        target=CaptureBinding(q,CELL,site)
        self.route(p,p.state.world.traps[site].position,approach=(target,),label='Transport to terminal SLM')
        p.add(K.AOD_OFFLOAD,'Offload at selected SLM',bindings=(target,))

    def load_atom(self,p,q,exclude=()):
        loaded=p.state.placement.mobile_occupancy
        if q in loaded.values():return
        if loaded:
            other=next(iter(loaded.values()))
            self.move_atom(p,other,self.spare(p.state,exclude))
        holder=p.state.placement.atom_to_holder[q]
        if holder.holder_type!=H.STATIC:
            raise ValidationError('UNSUPPORTED_TASK_ORIGIN','Atom must be alive in SLM or the single AOD')
        binding=CaptureBinding(q,CELL,holder.holder_id)
        self.route(p,p.state.world.traps[holder.holder_id].position)
        p.add(K.AOD_LOAD,'Load persistent operand',bindings=(binding,))

    def target(self,p,target):
        desired=dict(target.holders)
        if any(q not in p.state.atoms for q in desired):
            raise ValidationError('UNKNOWN_QUBIT','Unknown terminal atom')
        if len([h for h in desired.values() if h.holder_type==H.MOBILE])>1:
            raise ValidationError('TERMINAL_CAPACITY','Single trap cannot hold two atoms')
        static={q:h.holder_id for q,h in desired.items() if h.holder_type==H.STATIC}
        if len(set(static.values()))!=len(static):
            raise ValidationError('TERMINAL_CAPACITY','Duplicate terminal SLM site')
        if any(h.holder_type not in {H.STATIC,H.MOBILE} for h in desired.values()):
            raise ValidationError('UNSUPPORTED_TASK_TARGET','Cannot assign LOST as a transport target')
        for q in tuple(p.state.placement.mobile_occupancy.values()):
            if q in static and static[q] not in p.state.placement.static_occupancy:
                self.move_atom(p,q,static[q])
        # Clear occupied destinations using an explicitly timed spare, including permutations.
        for q,site in sorted(static.items()):
            if p.state.placement.atom_to_holder[q]==HolderRef(H.STATIC,site):continue
            blocker=p.state.placement.static_occupancy.get(site)
            if blocker is not None and blocker!=q:
                # A free future destination is valid temporary parking. Excluding
                # every final site can falsely exhaust capacity when both EZ
                # sites are resident. Already finalized sites are occupied and
                # cannot be chosen by spare(); later entries repair their targets.
                self.move_atom(p,blocker,self.spare(p.state,exclude=(site,)))
            self.move_atom(p,q,site)
        for q,h in sorted(desired.items()):
            if h.holder_type==H.MOBILE:
                if h.holder_id!=CELL:raise ValidationError('TERMINAL_CAPACITY','Unknown mobile cell')
                self.load_atom(p,q)
        if target.aod_configuration is not None:
            axes=target.aod_configuration
            if len(axes.x_um)!=1 or len(axes.y_um)!=1:
                raise ValidationError('TERMINAL_CAPACITY','Single-cell target axes required')
            self.route(p,Position2D(axes.x_um[0],axes.y_um[0]))
        if target.traps is not None and trap_state(p.state)!=target.traps:
            p.add(K.TRAP_SWITCH,'Apply terminal supports',switch_state=target.traps)

    def compile(self,intent,state):
        self.check(state)
        p=ProgramBuilder(state,intent)
        self.target(p,intent.target)
        if intent.effect_gate_id:
            gate=state.dag.nodes[intent.effect_gate_id].gate
            p.add(K.ENTANGLING_PULSE if gate.gate_type=='CZ' else K.RAMAN_ROTATION,'Requested gate effect')
        if not p.operations:raise ValidationError('TASK_ALREADY_SATISFIED','Terminal state already satisfied')
        return p.finish(self.id)


class ResidentCompiler(PersistentTargetCompiler):
    """Retain EZ anchor and loaded partner; later calls reuse their actual state."""
    id='resident-circuit-v1'

    def prepare_gate(self,p,gate):
        if gate.u_parameters is not None:
            q=gate.qubit_ids[0]
            if p.state.placement.atom_to_holder[q].holder_type==H.MOBILE:
                self.move_atom(p,q,self.spare(p.state))
            return K.RAMAN_ROTATION
        if gate.gate_type!='CZ':raise ValidationError('UNSUPPORTED_GATE','M3 supports CZ and U/aliases')
        a,b=gate.qubit_ids
        # Prefer the already resident static operand, then a non-loaded operand.
        for q,other in ((a,b),(b,a)):
            h=p.state.placement.atom_to_holder[q]
            if h.holder_type==H.STATIC and in_zone(p.state,p.state.world.traps[h.holder_id].position,ZoneType.ENTANGLEMENT):
                a,b=q,other;break
        else:
            if p.state.placement.atom_to_holder[a].holder_type==H.MOBILE:a,b=b,a
            try:site=self.spare(p.state,zone=ZoneType.ENTANGLEMENT)
            except ValidationError:
                occupied=[(h.holder_id,q) for q,h in p.state.placement.atom_to_holder.items() if h.holder_type==H.STATIC
                          and in_zone(p.state,p.state.world.traps[h.holder_id].position,ZoneType.ENTANGLEMENT)]
                if not occupied:raise
                site,q=sorted(occupied)[0]
                self.move_atom(p,q,self.spare(p.state,exclude=(site,)))
            self.move_atom(p,a,site)
        anchor=p.state.world.traps[p.state.placement.atom_to_holder[a].holder_id].position
        self.load_atom(p,b)
        offset=p.state.hardware.interaction_offset
        self.route(p,Position2D(anchor.x_um+offset.x_um,anchor.y_um+offset.y_um),label='Persistent partner to CZ')
        return K.ENTANGLING_PULSE

    def compile_gate(self,gate_id,state):
        self.check(state)
        node=state.dag.nodes.get(gate_id)
        if node is None or node.status.value!='ready':raise ValidationError('GATE_NOT_READY','READY gate required')
        intent=TaskIntent(f'{self.id}/{gate_id}/{state.version}',TaskTarget(),frozenset(node.gate.qubit_ids),gate_id,'effect',gate_id)
        p=ProgramBuilder(state,intent)
        kind=self.prepare_gate(p,node.gate)
        p.add(kind,'Resident gate effect')
        p.intent=replace(intent,target=TaskTarget(tuple(sorted(p.state.placement.atom_to_holder.items())),
                                                p.state.aod.configuration(),trap_state(p.state)))
        return p.finish(self.id)


class ReturningCompiler(ResidentCompiler):
    """Construct a complete return cycle each gate, preserving explicit origin."""
    id='returning-circuit-v1'

    def compile_gate(self,gate_id,state):
        self.check(state)
        node=state.dag.nodes.get(gate_id)
        if node is None or node.status.value!='ready':raise ValidationError('GATE_NOT_READY','READY gate required')
        origin=TaskTarget(tuple(sorted(state.placement.atom_to_holder.items())),state.aod.configuration(),trap_state(state))
        intent=TaskIntent(f'{self.id}/{gate_id}/{state.version}',origin,frozenset(node.gate.qubit_ids),gate_id,'effect',gate_id)
        p=ProgramBuilder(state,intent)
        kind=self.prepare_gate(p,node.gate)
        p.add(kind,'Returning gate effect')
        self.target(p,origin)
        return p.finish(self.id)
