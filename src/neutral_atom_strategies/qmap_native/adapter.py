"""Consume author NAViz decisions using the local checked program/Executor API.

The adapter may split diagonal moves and capacity-limited transport groups;
it preserves gate layers, transfer boundaries and service destination sites.
Intermediate author waypoints are hints: swept-checked shortcuts may omit them.
Any unsupported physical instruction stops with its source line and reason.
"""
from collections import Counter
from dataclasses import replace
from math import isclose
import re
from time import perf_counter

from neutral_atom_env.domain.aod import AODConfiguration
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import MobileCellIndex
from neutral_atom_env.domain.operations import CaptureBinding, OperationType as K
from neutral_atom_env.hardware import get_backend
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_strategies.motion.ordered_primitives import new_builder, finish
from .naviz import parse, transport_blocks, capacity_projection, Instruction


def fill_axis(fixed, count, lower, upper, gap, preferred=None):
    """Interpolate disabled capacity axes between the author's occupied axes."""
    if any(i < 0 or i >= count for i in fixed):
        raise ValidationError('QMAP_AXIS_CAPACITY', 'Author batch exceeds configured AOD axes')
    fixed = dict(fixed)
    if preferred is not None:
        # Empty RF lines have no placement target. Keep their old positions
        # unless an occupied line forces them aside to preserve ordering.
        step = gap + .01
        anchors = [(-1,lower-step),*sorted(fixed.items()),(count,upper+step)]
        result = list(preferred)
        for (li,lv),(ri,rv) in zip(anchors,anchors[1:]):
            if rv-lv < step*(ri-li)-1e-9:
                raise ValidationError('QMAP_AXIS_GEOMETRY','Author axes cannot fit local spacing constraints')
            previous=lv
            for i in range(li+1,ri):
                result[i]=max(previous+step,min(result[i],rv-step*(ri-i)))
                previous=result[i]
            if ri<count:result[ri]=rv
        return tuple(result)
    if not fixed:
        return tuple(lower + (upper-lower)*i/max(1, count-1) for i in range(count))
    first, last = min(fixed), max(fixed)
    step = gap + .01
    fixed.setdefault(0, fixed[first] - step*first)
    fixed.setdefault(count-1, fixed[last] + step*(count-1-last))
    result = [0.]*count
    points = sorted(fixed)
    for index in points:
        result[index] = fixed[index]
    for left, right in zip(points, points[1:]):
        for index in range(left+1, right):
            result[index] = fixed[left] + (fixed[right]-fixed[left])*(index-left)/(right-left)
    if result[0] < lower or result[-1] > upper or any(b-a <= gap for a,b in zip(result,result[1:])):
        raise ValidationError('QMAP_AXIS_GEOMETRY', 'Author axes cannot fit local field/spacing constraints')
    return tuple(result)


class NativeProgramAdapter:
    id = 'qmap_native'

    def __init__(self, code, *, atom_names=None, simplify_motion=True):
        self.simplify_motion=simplify_motion
        self.initial, self.instructions = parse(code)
        # The local laser contract permits equal 1Q gates on distinct atoms
        # together. Preserve per-qubit order and the author's CZ boundaries.
        merged = []
        for op in self.instructions:
            if (merged and op.kind in {'u','rz'} and merged[-1].kind==op.kind
                    and merged[-1].parameters==op.parameters
                    and not set(merged[-1].atoms).intersection(op.atoms)):
                previous = merged[-1]
                merged[-1] = Instruction(op.kind,previous.atoms+op.atoms,
                    parameters=op.parameters,line=previous.line)
            else:
                merged.append(op)
        self.instructions = tuple(merged)
        self.blocks = transport_blocks(self.initial, self.instructions)
        if atom_names is None:
            if any(re.fullmatch(r'atom\d+',name) is None for name in self.initial):
                raise ValueError('Pinned QMAP atom names must explicitly encode qubit indices')
            atom_names = {name:f'Q{int(name[4:]):03d}' for name in self.initial}
        self.names = atom_names
        self.plans, self.decisions = [], []
        self.failure = None
        self.capacity_adaptations = []

    def configuration(self, state, positions, axes, atoms):
        bounds = state.world.bounds
        vectors = []
        for dim, count, lower, upper in ((0,state.aod.columns,bounds.lower.x_um,bounds.upper.x_um),
                                         (1,state.aod.rows,bounds.lower.y_um,bounds.upper.y_um)):
            fixed = {}
            for name in atoms:
                slot, coordinate = axes[dim][name], positions[name][dim]
                if slot in fixed and not isclose(fixed[slot], coordinate, abs_tol=1e-8):
                    raise ValidationError('QMAP_AXIS_SPLIT', 'Shared author axis has inconsistent coordinates')
                fixed[slot] = coordinate
            preferred=(state.aod.configuration().x_um,state.aod.configuration().y_um)[dim] if self.simplify_motion else None
            vectors.append(fill_axis(fixed,count,lower,upper,state.hardware.minimum_axis_spacing_um,preferred))
        return AODConfiguration(*vectors)

    def run(self, env, *, on_event=None):
        self.instructions,self.capacity_adaptations=capacity_projection(
            self.initial,self.instructions,env.state.aod.rows,env.state.aod.columns)
        self.blocks=transport_blocks(self.initial,self.instructions)
        positions, loaded = dict(self.initial), set()
        sites = {(t.position.x_um,t.position.y_um): t.id for t in env.state.world.traps.values()}
        for name, point in positions.items():
            q = self.names[name]
            actual = env.state.placement.position(q,env.state.world,env.state.aod)
            if (actual.x_um,actual.y_um) != point:
                raise ValidationError('QMAP_INITIAL_MAPPING', 'Native initial placement differs; no teleportation is allowed')
        p = new_builder(env.state, tuple(env.state.dag.nodes))
        def move(target, line, *, direct_only=False, waypoints=()):
            start = p.state.aod.configuration()
            move_start = p.origin.time_us + sum(o.duration_us for o in p.operations)
            if target == start:
                return
            paths = [(target,)]
            if p.state.hardware.backend == 'row_column_orthogonal' and start.x_um != target.x_um and start.y_um != target.y_um:
                paths = [(AODConfiguration(target.x_um,start.y_um),target),
                         (AODConfiguration(start.x_um,target.y_um),target)]
            def elbows(a,b):
                if a.x_um==b.x_um or a.y_um==b.y_um:return [(b,)]
                return [(AODConfiguration(b.x_um,a.y_um),b),(AODConfiguration(a.x_um,b.y_um),b)]
            # A blocked straight/L path can still skip most author waypoints
            # after escaping the source row. These are candidate paths only:
            # every resulting continuous segment is checked below.
            for waypoint in waypoints:
                for head in elbows(start,waypoint):
                    for tail in elbows(waypoint,target):
                        compact=[start]
                        for point in head+tail:
                            if point==compact[-1]:continue
                            if len(compact)>1 and ((compact[-2].x_um==compact[-1].x_um==point.x_um)
                                    or (compact[-2].y_um==compact[-1].y_um==point.y_um)):
                                compact.pop()
                            compact.append(point)
                        paths.append(tuple(compact[1:]))
            reasons = []
            backend = get_backend(p.state.hardware)
            paths.sort(key=lambda path:sum(backend.move_duration(
                p.state.aod.configured(a),b,p.state.hardware)
                for a,b in zip((start,)+tuple(path[:-1]),path)))
            from neutral_atom_strategies.motion.axis_hold_routes import axis_hold_routes
            # Routing in QMAP means movement GROUPING. The local transport
            # backend additionally requires swept, orthogonal trajectories.
            # Service endpoints/groups are fixed; transport waypoints are hints.
            def candidates():
                yield from paths
                if p.state.placement.mobile_occupancy and not direct_only:
                    alternatives = [path[1:] for path in axis_hold_routes(start,target)]
                    backend = get_backend(p.state.hardware)
                    alternatives.sort(key=lambda path:sum(backend.move_duration(
                        p.state.aod.configured(a),b,p.state.hardware)
                        for a,b in zip((start,)+tuple(path[:-1]),path)))
                    yield from alternatives[:128]
            tried = set()
            for path in candidates():
                if path in tried:
                    continue
                tried.add(path)
                probe = new_builder(p.state)
                try:
                    for endpoint in path:
                        if endpoint != probe.state.aod.configuration():
                            probe.add(K.AOD_MOVE,f'QMAP line {line}: ordered movement',configuration=endpoint)
                except ValidationError as exc:
                    reasons.append(exc.violation.code)
                    continue
                for endpoint in path:
                    if endpoint != p.state.aod.configuration():
                        p.add(K.AOD_MOVE,f'QMAP line {line}: ordered movement',configuration=endpoint)
                if path not in paths:
                    self.decisions.append(dict(kind='local_orthogonal_route',line=line,
                        segments=len(path),rejected_direct=reasons[:2],
                        start_us=move_start,duration_us=p.origin.time_us+sum(o.duration_us for o in p.operations)-move_start,
                        reason='Author endpoints/group retained; local swept orthogonal path required'))
                return
            raise ValidationError('QMAP_MOTION_INCOMPATIBLE',
                f'Author line {line} blocked by local physics: {reasons}; endpoints/group not changed')
        start_wall = perf_counter()
        consumed=-1
        for index, op in enumerate(self.instructions):
            if index<=consumed:continue
            try:
                if op.kind in {'load','move','store'}:
                    axes = self.blocks[index]
                    if op.kind == 'load':
                        # Disabling unoccupied SLM lights is an explicit physical operation.
                        masks = trap_state(p.state)
                        occupied = p.state.placement.static_occupancy
                        masks = replace(masks,slm=tuple((t,on and t in occupied) for t,on in masks.slm))
                        if masks != trap_state(p.state):
                            p.add(K.TRAP_SWITCH,'QMAP: close vacant SLM supports',switch_state=masks)
                        move(self.configuration(p.state,positions,axes,loaded|set(op.atoms)),op.line)
                        bindings = tuple(sorted((CaptureBinding(self.names[q],
                            MobileCellIndex(axes[1][q],axes[0][q]),sites[positions[q]]) for q in op.atoms),key=lambda b:b.atom_id))
                        p.add(K.AOD_RECAPTURE if loaded else K.AOD_LOAD,
                            f'QMAP line {op.line}: load {len(bindings)}',bindings=bindings)
                        loaded.update(op.atoms)
                    elif op.kind == 'move':
                        end=index+1
                        if self.simplify_motion:
                            while end<len(self.instructions) and self.instructions[end].kind=='move':end+=1
                        sequence=self.instructions[index:end]
                        goal=dict(positions)
                        for item in sequence:goal.update(item.moves)
                        begin=p.origin.time_us+sum(o.duration_us for o in p.operations)
                        shortened=False
                        if len(sequence)>1:
                            intermediate=[];partial=dict(positions);previous=p.state.aod.configuration()
                            for item in sequence[:-1]:
                                partial.update(item.moves)
                                point=self.configuration(p.state,partial,axes,loaded)
                                intermediate.extend((AODConfiguration(point.x_um,previous.y_um),
                                                     AODConfiguration(previous.x_um,point.y_um),point))
                                previous=point
                            try:
                                move(self.configuration(p.state,goal,axes,loaded),op.line,
                                     direct_only=True,waypoints=intermediate)
                            except ValidationError:
                                pass  # Failed probes never alter the live or builder state.
                            else:
                                positions=goal;shortened=True
                        if not shortened:
                            for item in sequence:
                                positions.update(item.moves)
                                move(self.configuration(p.state,positions,axes,loaded),item.line)
                        else:
                            self.decisions.append(dict(kind='local_path_shortcut',line=op.line,
                                through_line=sequence[-1].line,removed_author_waypoints=len(sequence)-1,
                                start_us=begin,duration_us=p.origin.time_us+sum(o.duration_us for o in p.operations)-begin,
                                reason='Swept-checked shortcut between unchanged load/store/gate boundaries'))
                        consumed=end-1
                    else:
                        bindings = tuple(sorted((CaptureBinding(self.names[q],
                            MobileCellIndex(axes[1][q],axes[0][q]),sites[positions[q]]) for q in op.atoms),key=lambda b:b.atom_id))
                        remaining = loaded-set(op.atoms)
                        p.add(K.AOD_PARK if remaining else K.AOD_OFFLOAD,
                            f'QMAP line {op.line}: store {len(bindings)}',bindings=bindings)
                        loaded = remaining
                        if remaining:
                            # Native NAViz names carried atoms, not lingering
                            # empty RF lines. Close every now-unused line before
                            # repositioning spare axes; Cartesian ghost cells
                            # between STILL used rows/columns remain checked.
                            occupancy=p.state.placement.mobile_occupancy
                            masks=replace(trap_state(p.state),
                                rows=tuple(any(c.row==r for c in occupancy) for r in range(p.state.aod.rows)),
                                columns=tuple(any(c.column==c0 for c in occupancy) for c0 in range(p.state.aod.columns)))
                            if masks!=trap_state(p.state):
                                p.add(K.TRAP_SWITCH,'QMAP: close unused AOD lines after partial store',switch_state=masks)
                elif op.kind == 'cz':
                    pairs = get_backend(p.state.hardware).actual_pairs(p.state)
                    gates = tuple(g.id for g in p.state.dag.ready_gates()
                                  if g.gate_type=='CZ' and tuple(sorted(g.qubit_ids)) in pairs)
                    if len(gates) != len(pairs) or not pairs:
                        raise ValidationError('QMAP_GATE_ALIGNMENT','Native CZ pairs do not match input READY gates')
                    p.add(K.ENTANGLING_PULSE,f'QMAP CZ layer: {len(gates)} gates',gate_ids=gates)
                    self.decisions.append(dict(kind='CZ',line=op.line,gate_ids=gates,
                        start_us=p.origin.time_us+sum(o.duration_us for o in p.operations[:-1]),
                        duration_us=p.operations[-1].duration_us))
                else:
                    parameters = op.parameters if op.kind=='u' else (0.,0.,op.parameters[0])
                    ids = []
                    for name in op.atoms:
                        choices = [g for g in p.state.dag.ready_gates() if g.qubit_ids==(self.names[name],)
                            and g.u_parameters is not None
                            and all(isclose(a,b,abs_tol=1e-5) for a,b in zip(g.u_parameters,parameters))]
                        if len(choices)!=1:
                            raise ValidationError('QMAP_1Q_ALIGNMENT','Native rotation cannot be matched to input gate')
                        ids.append(choices[0].id)
                    # Local laser supports only identical gate types in one pulse.
                    by_kind = {}
                    for gid in ids:
                        by_kind.setdefault(p.state.dag.nodes[gid].gate.gate_type,[]).append(gid)
                    for kind, gates in by_kind.items():
                        self.rotation(p,kind,tuple(gates),op.line)
                # Commit whole transport blocks so the private prediction never
                # becomes a partial live update on a failed routing attempt.
                if not loaded and p.operations:
                    p.intent = replace(p.intent,gate_effects=frozenset(
                        gid for operation in p.operations for gid in operation.effect_gate_ids))
                    plan = finish(p,compiler='qmap-native-3.5.0-adapter')
                    env.submit(plan)
                    self.plans.append(plan)
                    env.run(on_event=on_event)
                    p = new_builder(env.state,tuple(env.state.dag.nodes))
            except Exception as exc:
                self.failure = dict(instruction=index,line=op.line,kind=op.kind,
                    error=str(exc),code=getattr(getattr(exc,'violation',None),'code',type(exc).__name__))
                raise
        self.validate_final(env.state)
        return dict(status='completed',adapter_execute_seconds=perf_counter()-start_wall,
                    cz_layers=sum(x['kind']=='CZ' for x in self.decisions))

    def validate_final(self, state):
        """Require the author's final positions and a fully drained local device."""
        if not state.dag.completed:
            raise ValidationError('QMAP_INCOMPLETE','Native program did not execute every requested gate')
        if (state.active_plan or state.event_queue or state.reservations or state.transfer
                or state.aod.is_moving or state.placement.mobile_occupancy):
            raise ValidationError('QMAP_TERMINAL','Native program left pending work or a loaded AOD')
        expected = dict(self.initial)
        for op in self.instructions:
            expected.update(op.moves)
        for name, point in expected.items():
            p = state.placement.position(self.names[name],state.world,state.aod)
            if not all(isclose(a,b,abs_tol=1e-6) for a,b in zip((p.x_um,p.y_um),point)):
                raise ValidationError('QMAP_TERMINAL',f'{name} differs from the native final position')

    def rotation(self, p, kind, gates, line):
        """Deterministic local 5um addressing compatibility for retained pairs.

        Temporarily separate right partners, pulse, and restore exactly the
        author's holders. No author CZ layer, group or eventual site is changed.
        """
        from neutral_atom_env.hardware.raman import validate_rotation_batch
        from neutral_atom_strategies.motion.ordered_primitives import build_batch, empty_reconfigure
        try:
            validate_rotation_batch(p.state,gates)
        except ValidationError as exc:
            if exc.violation.code != 'RAMAN_NEIGHBOR_TOO_CLOSE':
                raise
        else:
            p.add(K.RAMAN_ROTATION,f'QMAP {kind}',gate_ids=gates)
            return
        state = p.state
        targets = {state.dag.nodes[g].gate.qubit_ids[0] for g in gates}
        positions = {q:state.placement.position(q,state.world,state.aod) for q in state.atoms}
        pairs = get_backend(state.hardware).actual_pairs(state)
        moving = {}
        for a,b in pairs:
            if not targets.intersection((a,b)):
                continue
            left,right = sorted((a,b),key=lambda q:positions[q].x_um)
            l,r = positions[left],positions[right]
            if l.y_um != r.y_um:
                raise ValidationError('QMAP_1Q_ISOLATION','Native paired-SLM addressing requires horizontal pairs')
            moving[right] = (l.x_um+state.hardware.raman_minimum_separation_um,r.y_um)
        if not moving or state.placement.mobile_occupancy:
            raise ValidationError('QMAP_1Q_ISOLATION','Cannot isolate native 1Q targets with the paired-SLM adapter')
        batch = build_batch(state,[(q,q,q,x,y) for q,(x,y) in sorted(moving.items())],
                            check_interactions=False,bounded_spares=True)
        before = sum(o.duration_us for o in p.operations)
        empty_reconfigure(p,batch.pickup)
        p.add(K.AOD_LOAD,'Local addressing: load retained right partners',bindings=batch.bindings)
        p.add(K.AOD_MOVE,'Local addressing: separate to 5 um',configuration=batch.target)
        p.add(K.RAMAN_ROTATION,f'QMAP {kind}; local clearance verified',gate_ids=gates)
        p.add(K.AOD_MOVE,'Local addressing: restore author positions',configuration=batch.pickup)
        p.add(K.AOD_OFFLOAD,'Local addressing: restore author SLM holders',bindings=batch.bindings)
        self.decisions.append(dict(kind='local_1q_clearance',line=line,gate_ids=gates,
            start_us=p.origin.time_us+before,
            moved_atoms=sorted(moving),duration_us=sum(o.duration_us for o in p.operations)-before,
            reason='Local 1Q requires >=5um, author retains CZ partners at 2um'))
