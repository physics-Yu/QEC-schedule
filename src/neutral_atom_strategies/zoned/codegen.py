"""Physical lowering. Cheap routes first; bounded portal routes only on failure.

All attempts use private ProgramBuilders and the unchanged physical backend.
Empty intersections, transfer exemptions and continuous sweeps are still checked.
"""
from dataclasses import dataclass, field
from itertools import product
from math import hypot
from time import perf_counter
from neutral_atom_env.domain.aod import AODConfiguration
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import GateStatus, HolderRef, HolderType, ZoneType
from neutral_atom_env.domain.operations import CaptureBinding, OperationType as K
from neutral_atom_env.hardware import get_backend
from neutral_atom_env.hardware.ez_neighbors import validate_ez_neighbors
from neutral_atom_env.program.binding import fingerprint
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_strategies.motion.ordered_primitives import AxisBatch, build_batch, empty_reconfigure, corridor_routes
from neutral_atom_strategies.motion.axis_hold_routes import transfer_annotation
from neutral_atom_strategies.motion.ordered_routes import OccupiedSLMGrid, merge_straight_runs
from .routing import compatible_groups
from .landing import landing_candidates
from .reuse import future_partners
from neutral_atom_strategies.motion.single_trap import in_zone


@dataclass(frozen=True)
class PreparedInteraction:
    """State-bound physical receipt, not a gate effect or a placement request.

    Captured operands have reached a checked interaction configuration. The
    gate remains READY until ``execute_interaction`` explicitly adds its pulse.
    Origin and prefix binding also prevent using the saved return route with a
    different builder history that happens to have the same endpoint geometry.
    """
    batch: AxisBatch
    path: tuple[AODConfiguration, ...]
    state_version: int
    state_fingerprint: str
    origin_fingerprint: str
    operation_count: int
    _operation_prefix: tuple = field(repr=False)

    @property
    def gate_ids(self):
        return self.batch.gate_ids


def fork(p):
    other = ProgramBuilder(p.origin, p.intent)
    other.state = p.state
    other.operations = list(p.operations)
    other.bindings = dict(p.bindings)
    other.distance = p.distance
    return other


def adopt(p, other):
    p.state, p.operations, p.bindings, p.distance = other.state, other.operations, other.bindings, other.distance


def short_routes(start, target):
    """A small constructive family, lazily enumerated before expensive fallback."""
    yield merge_straight_runs((start, AODConfiguration(target.x_um,start.y_um), target))
    yield merge_straight_runs((start, AODConfiguration(start.x_um,target.y_um), target))
    for axis, sign1, sign2 in product((0,1), (-1,1), (-1,1)):
        def shift(c, amount):
            return (AODConfiguration(tuple(v+amount for v in c.x_um),c.y_um) if axis == 0
                    else AODConfiguration(c.x_um,tuple(v+amount for v in c.y_um)))
        left, right = shift(start, sign1*2.5), shift(target, sign2*2.5)
        corner = (AODConfiguration(left.x_um,right.y_um) if axis == 0
                  else AODConfiguration(right.x_um,left.y_um))
        yield merge_straight_runs((start,left,corner,right,target))


class PhysicalCodegen:
    def __init__(self, deadline, route_budget=128, motion_router='axis_hold'):
        self.deadline, self.route_budget, self.motion_router = deadline, route_budget, motion_router
        self.rejections = []
        self.stats = dict(route_attempts=0, grid_rejections=0, fallback_calls=0, transport_groups=0, cz_batches=[], landings=[])

    def check(self):
        if perf_counter() > self.deadline:
            raise TimeoutError('Zoned physical lowering deadline')

    def paths(self, state, target):
        grid = OccupiedSLMGrid(state)
        start = state.aod.configuration()
        seen = set()
        count = 0
        for family in (lambda: short_routes(start,target), lambda: corridor_routes(start,target,self.motion_router)):
            for path in family():
                self.check()
                if path in seen:
                    continue
                seen.add(path)
                if not grid.allows(path):
                    self.stats['grid_rejections'] += 1
                    continue
                if count >= self.route_budget:
                    return
                count += 1
                yield path
            self.stats['fallback_calls'] += 1

    def route(self, p, target, *, source=(), destination=(), label='Zoned transport', after=None):
        # The after callback includes OFFLOAD or CZ+return, so acceptance means
        # the endpoint is usable, not merely reachable by its last segment.
        for path in self.paths(p.state, target):
            trial = fork(p)
            self.stats['route_attempts'] += 1
            try:
                self._append_path(trial,path,source=source,destination=destination,label=label)
                if after:
                    after(trial,path)
                adopt(p,trial)
                return
            except ValidationError as error:
                self.rejections.append({'code':error.violation.code,'message':error.violation.message})
        raise ValidationError('ZONED_ROUTE_EXHAUSTED',f'No legal {label} route; last failures: {self.rejections[-3:]}')

    @staticmethod
    def _append_path(p,path,*,source=(),destination=(),label):
        for i,c in enumerate(path[1:],1):
            phase = 'depart' if i == 1 and source else 'approach' if i == len(path)-1 and destination else None
            bindings = source if phase == 'depart' else destination if phase == 'approach' else ()
            if phase:
                phase,bindings = transfer_annotation(p.state,p.state.aod.configuration(),c,bindings,phase)
            p.add(K.AOD_MOVE,label,configuration=c,phase=phase,bindings=bindings)

    def move_loaded(self,p,target,label='Loaded AOD transport'):
        if p.state.aod.configuration() != target:
            self.route(p,target,label=label)

    def transfer_group(self,p,destinations,label='Zoned placement'):
        destinations = {q:t for q,t in destinations.items() if p.state.placement.atom_to_holder[q].holder_id != t}
        if not destinations:
            return
        holders = dict(p.state.placement.atom_to_holder)
        occupancy = p.state.placement.static_occupancy
        for q,t in destinations.items():
            if t in occupancy and occupancy[t] not in destinations:
                raise ValidationError('ZONED_TARGET_OCCUPIED','Transport target has a stationary atom')
            holders[q] = HolderRef(HolderType.STATIC,t)
        if len(set(holders.values())) != len(holders):
            raise ValidationError('ZONED_TARGET_DUPLICATE','Transport targets must be distinct')
        validate_ez_neighbors(p.state,holders=holders)
        assignments = [(q,q,q,p.state.world.traps[t].position.x_um,p.state.world.traps[t].position.y_um)
                       for q,t in sorted(destinations.items())]
        batch = build_batch(p.state,assignments,check_interactions=False,bounded_spares=True)
        unload = tuple(CaptureBinding(b.atom_id,b.cell,destinations[b.atom_id]) for b in batch.bindings)
        trial = fork(p)
        empty_reconfigure(trial,batch.pickup)
        trial.add(K.AOD_LOAD,label+': load',bindings=batch.bindings)
        self.route(trial,batch.target,source=batch.bindings,destination=unload,label=label,
                   after=lambda work,path:work.add(K.AOD_OFFLOAD,label+': offload',bindings=unload))
        adopt(p,trial)
        self.stats['transport_groups'] += 1

    def transport(self,p,destinations,label='Zoned placement'):
        pending = {q:t for q,t in destinations.items() if p.state.placement.atom_to_holder[q].holder_id != t}
        while pending:
            self.check()
            assignments = [(q,q,q,p.state.world.traps[t].position.x_um,p.state.world.traps[t].position.y_um)
                           for q,t in sorted(pending.items())]
            groups = compatible_groups(p.state,assignments,interactions=False)
            last = None
            for group in groups:
                attempts = [group] + [(a,) for a in group] if len(group)>1 else [group]
                for attempt in attempts:
                    selected = {a[2]:pending[a[2]] for a in attempt}
                    try:
                        self.transfer_group(p,selected,label)
                    except ValidationError as error:
                        last = error
                        continue
                    for q in selected:
                        pending.pop(q)
                    break
                else:
                    continue
                break
            else:
                raise last or ValidationError('ZONED_TRANSPORT_EMPTY','No transport candidates')

    def restore_destinations(self,p,destinations):
        """Restore arbitrary holder permutations, breaking cycles via a vacancy.

        Initial-placement trials can permute even atoms with no CZ. A selective
        compiler must not rely on staging every atom to make original sites free.
        """
        pending={q:t for q,t in destinations.items() if p.state.placement.atom_to_holder[q].holder_id!=t}
        reserved=set(destinations.values())
        while pending:
            self.check()
            occupied=p.state.placement.static_occupancy
            free={q:t for q,t in pending.items() if t not in occupied}
            if free:
                self.transport(p,free,'Return to initial SLM')
                for q in free:pending.pop(q)
                continue
            q=sorted(pending)[0]
            source=p.state.placement.position(q,p.state.world,p.state.aod)
            vacancies=sorted((t for t in p.state.world.traps.values() if t.id not in occupied and t.id not in reserved),
                             key=lambda t:(hypot(t.position.x_um-source.x_um,t.position.y_um-source.y_um),t.id))
            last=None
            for site in vacancies[:32]:
                try:self.transfer_group(p,{q:site.id},'Break terminal holder cycle')
                except ValidationError as error:last=error;continue
                break
            else:
                raise ValidationError('ZONED_TERMINAL_CYCLE','No legal temporary support for terminal permutation: '+str(last))

    @staticmethod
    def _validate_interaction_request(p,assignments):
        ids = tuple(a[0] for a in assignments)
        if not ids or len(set(ids)) != len(ids) or not set(ids) <= p.intent.gate_ids:
            raise ValidationError('INTERACTION_EFFECT_MISMATCH','Interaction gates must be unique authorized program effects')
        for gate_id,anchor,mobile,_,_ in assignments:
            node = p.state.dag.nodes.get(gate_id)
            if node is None or node.gate.gate_type != 'CZ' or set(node.gate.qubit_ids) != {anchor,mobile}:
                raise ValidationError('INTERACTION_EFFECT_MISMATCH','Interaction operands must match their declared CZ gate')
            if node.status != GateStatus.READY:
                raise ValidationError('INTERACTION_NOT_READY','Interaction preparation requires READY CZ gates')

    def _interaction_preparations(self,p,assignments):
        """Yield private motion-only alternatives; callers decide acceptance."""
        assignments = tuple(tuple(a) for a in assignments)
        self._validate_interaction_request(p,assignments)
        origin_digest = fingerprint(p.origin)
        if not p.state.placement.mobile_occupancy and not p.state.aod.is_moving:
            # A declarative move can already be satisfied by a resident static
            # pair. Honour the resolved endpoints as well as its logical pair.
            matched = all(
                hypot(p.state.placement.position(q,p.state.world,p.state.aod).x_um-x,
                      p.state.placement.position(q,p.state.world,p.state.aod).y_um-y) < 1e-7
                for _,_,q,x,y in assignments)
            if matched:
                ids = tuple(a[0] for a in assignments)
                get_backend(p.state.hardware).validate_pulse_batch(p.state,ids)
                config = p.state.aod.configuration()
                batch = AxisBatch(assignments,config,config,())
                yield fork(p),PreparedInteraction(batch,(config,),p.state.version,fingerprint(p.state),
                                                  origin_digest,len(p.operations),tuple(p.operations))
                return
        batch = build_batch(p.state,assignments,bounded_spares=True)
        trial = fork(p)
        empty_reconfigure(trial,batch.pickup)
        trial.add(K.AOD_LOAD,'Capture CZ operands',bindings=batch.bindings)
        for path in self.paths(trial.state,batch.target):
            work = fork(trial)
            self.stats['route_attempts'] += 1
            try:
                self._append_path(work,path,source=batch.bindings,label='CZ approach')
                # Check the actual all-EZ interaction set without predicting a
                # gate effect or changing the DAG/quantum state.
                get_backend(work.state.hardware).validate_pulse_batch(work.state,batch.gate_ids)
            except ValidationError as error:
                self.rejections.append({'code':error.violation.code,'message':error.violation.message})
                continue
            yield work,PreparedInteraction(batch,tuple(path),work.state.version,fingerprint(work.state),
                                           origin_digest,len(work.operations),tuple(work.operations))

    def prepare_interaction(self,p,assignments):
        """Compile capture and approach only; atomically keep the first endpoint.

        No CZ effect is added. Use the returned immutable receipt with
        ``execute_interaction`` on this unchanged builder state. To backtrack
        over approaches when later cleanup fails, use ``cz_group`` instead.
        """
        for work,prepared in self._interaction_preparations(p,assignments):
            adopt(p,work)
            return prepared
        raise ValidationError('ZONED_ROUTE_EXHAUSTED',f'No legal CZ approach route; last failures: {self.rejections[-3:]}')

    def execute_interaction(self,p,prepared):
        """Add the explicit CZ pulse and existing landing policy atomically."""
        if (not isinstance(prepared,PreparedInteraction) or p.state.version != prepared.state_version
                or len(p.operations) != prepared.operation_count
                or tuple(p.operations) != prepared._operation_prefix
                or fingerprint(p.origin) != prepared.origin_fingerprint
                or fingerprint(p.state) != prepared.state_fingerprint):
            raise ValidationError('INTERACTION_STALE','Prepared interaction does not match the current builder state')
        batch,path = prepared.batch,prepared.path
        self._validate_interaction_request(p,batch.assignments)
        work = fork(p)
        work.add(K.ENTANGLING_PULSE,f'Zoned CZ ×{len(batch.assignments)}',gate_ids=batch.gate_ids)
        landing = self._land_interaction(work,batch,path)
        adopt(p,work)
        self.stats['landings'].append(landing)
        self.stats['cz_batches'].append(list(batch.gate_ids))

    def _land_interaction(self,work,batch,path):
        """Existing post-pulse residency policy, deliberately below the IR."""
        if not batch.bindings:
            return {}  # An already-supported static pair needs no capture/return.
        def return_to_working_support(work,path):
            back = tuple(reversed(path[:-1]))
            for i,c in enumerate(back):
                phase, bindings = (transfer_annotation(work.state,work.state.aod.configuration(),c,batch.bindings,'approach')
                                   if i == len(back)-1 else (None,()))
                work.add(K.AOD_MOVE,'Separate CZ operands',configuration=c,phase=phase,bindings=bindings)
            work.add(K.AOD_OFFLOAD,'Stabilize CZ mobile operands',bindings=batch.bindings)
        future=future_partners(work.state)
        current_partners={mobile:anchor for _,anchor,mobile,_,_ in batch.assignments}
        if any(b.atom_id in future and future[b.atom_id]!=current_partners[b.atom_id] for b in batch.bindings) and all(
                in_zone(work.state,work.state.world.traps[b.static_trap_id].position,ZoneType.ENTANGLEMENT)
                for b in batch.bindings):
            # Preserve a valid working placement across repeated syndrome
            # layers. A nearer vacancy can otherwise destroy the next
            # rectangle and incur many extra 100 us captures. Never sends
            # an EZ newcomer back to a remote SZ source just for this rule.
            attempt=fork(work)
            try:
                return_to_working_support(attempt,path)
                adopt(work,attempt)
                return {b.atom_id:b.static_trap_id for b in batch.bindings}
            except ValidationError:
                pass
        # Choose nearby vacant supports after the pulse, including next-CZ
        # reservations. Keep this decision separate from path realization.
        for cost,target,unload in landing_candidates(work.state,batch.bindings):
            attempt=fork(work)
            try:
                self.route(attempt,target,destination=unload,label='CZ landing',
                           after=lambda w,path:w.add(K.AOD_OFFLOAD,'Retain operands in EZ',bindings=unload))
            except ValidationError:
                continue
            adopt(work,attempt)
            return {b.atom_id:b.static_trap_id for b in unload}
        # Explicit, physically checked fallback to source supports.
        return_to_working_support(work,path)
        return {b.atom_id:b.static_trap_id for b in batch.bindings}

    def cz_group(self,p,assignments):
        """Compatibility service: prepare, pulse and land with route backtracking."""
        for work,prepared in self._interaction_preparations(p,assignments):
            try:
                self.execute_interaction(work,prepared)
            except ValidationError as error:
                self.rejections.append({'code':error.violation.code,'message':error.violation.message})
                continue
            adopt(p,work)
            return
        raise ValidationError('ZONED_ROUTE_EXHAUSTED',f'No legal CZ approach and landing; last failures: {self.rejections[-3:]}')

    def layer(self,p,placement):
        self.transport(p,placement.destinations)
        assignments = [c.assignment for c in placement.choices]
        for group in compatible_groups(p.state,assignments):
            try:
                self.cz_group(p,group)
            except ValidationError:
                if len(group) == 1:
                    raise
                for a in group:
                    self.cz_group(p,(a,))
