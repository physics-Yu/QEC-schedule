"""Replaceable serial CZ compilation: shuttle one atom at a time with one trap."""
from dataclasses import dataclass
from itertools import islice
from neutral_atom_env.domain.models import Position2D, HolderType, ZoneType, GateStatus, MobileCellIndex
from neutral_atom_env.domain.operations import CaptureBinding, OperationType as K, EndDisposition
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware import get_backend
from .planners import HalfGridPlanner, RouteRequest
from .program import ProgramBuilder


def in_zone(state, position, kind):
    return any(z.zone_type == kind and z.bounds.contains(position) for z in state.world.zones)


def route(builder, target, planner, *, depart=(), approach=(), label='Transport atom'):
    """Try bounded routes using backend checks, preserving transfer boundary stops."""
    state = builder.state
    backend = get_backend(state.hardware)
    if state.aod.pose == target:
        return
    if not state.placement.mobile_occupancy:
        if state.aod.active_cells:
            from neutral_atom_env.hardware.dynamic_traps import trap_state
            from dataclasses import replace
            masks=replace(trap_state(state),rows=(False,)*state.aod.rows,columns=(False,)*state.aod.columns)
            builder.add(K.TRAP_SWITCH, 'Disable empty AOD before reposition', switch_state=masks)
        if not getattr(planner,'orthogonal',False):
            builder.add(K.AOD_MOVE, 'Empty reposition', target=target)
            return
        state=builder.state
        label='Empty reposition'
    request = RouteRequest(state.aod.configuration(), backend.target_aod(state.aod, target).configuration(),
                           state.world.grid_spacing_um, state.world.grid_origin.x_um, tuple(depart), state.world, state.hardware,
                           state=state, depart=tuple(depart), approach=tuple(approach))
    errors = []
    for candidate in islice(planner.candidates(request), 64):
        trial = ProgramBuilder(builder.origin, builder.intent)
        trial.state = state
        try:
            points = []
            for c in candidate:
                if not points or points[-1] != c:
                    points.append(c)
            if len(points) < 2 or points[0] != request.start or points[-1] != request.target:
                raise ValidationError('INVALID_ROUTE', 'Route must include start and target')
            if depart and approach and len(points) < 3:
                raise ValidationError('INVALID_ROUTE', 'Two transfer boundaries require a cleared intermediate position')
            for i, c in enumerate(points[1:], 1):
                pose = Position2D(c.x_um[0], c.y_um[0])
                if backend.target_aod(trial.state.aod, pose).configuration() != c:
                    raise ValidationError('UNSUPPORTED_DEFORMATION', 'Single-trap strategy uses rigid translation')
                phase = 'depart' if i == 1 and depart else 'approach' if i == len(points)-1 and approach else None
                bindings = depart if phase == 'depart' else approach if phase == 'approach' else ()
                trial.add(K.AOD_MOVE, label, target=pose, bindings=bindings, phase=phase)
            for op in trial.operations:
                builder.add(op.operation_type, op.label, target=op.target_pose,
                            bindings=op.transfer_bindings, phase=op.transfer_phase)
            return
        except ValidationError as error:
            errors.append(error.violation.code)
    raise ValidationError('SINGLE_TRAP_ROUTE_EXHAUSTED', f'No route in {len(errors)} finite candidates; not proof of impossibility. {errors[:4]}')


@dataclass(frozen=True)
class SingleTrapCompiler:
    """Same compile(intent,state) interface as MotionCompiler; no executor coupling."""
    planner: object = None
    anchor_order: str = 'forward'
    id: str = 'single-trap-return-v1'

    def compile(self, intent, state):
        if len(intent.gate_ids) == 1:
            node = state.dag.nodes.get(next(iter(intent.gate_ids)))
            if node is not None and node.gate.u_parameters is not None:
                from .raman import compile_rotation
                return compile_rotation(intent, state)
        if state.hardware.backend != 'rigid' or (state.aod.rows, state.aod.columns) != (1, 1):
            raise ValidationError('SINGLE_TRAP_REQUIRED', 'Strategy requires a rigid AOD with exactly one active trap')
        if state.active_plan or state.event_queue or state.reservations or state.placement.mobile_occupancy:
            raise ValidationError('RESOURCE_BUSY', 'Single-trap return strategy requires idle, empty AOD')
        if intent.end_disposition != EndDisposition.RETURN_AND_OFFLOAD or len(intent.gate_ids) != 1:
            raise ValidationError('UNSUPPORTED_DISPOSITION', 'This strategy implements one CZ with individual returns')
        node = state.dag.nodes.get(next(iter(intent.gate_ids)))
        if node is None or node.status != GateStatus.READY:
            raise ValidationError('GATE_NOT_READY', 'Compile a READY gate')
        if node.gate.gate_type != 'CZ':
            raise ValidationError('UNSUPPORTED_GATE', 'Single-trap physical compilation currently supports CZ only')
        for q in node.gate.qubit_ids:
            if state.placement.atom_to_holder[q].holder_type != HolderType.STATIC or not in_zone(
                    state, state.placement.position(q, state.world, state.aod), ZoneType.STORAGE):
                raise ValidationError('STORAGE_SOURCE_REQUIRED', 'Return baseline starts both operands at storage traps')
        sites = [t for _, t in sorted(state.world.traps.items()) if
                 t.id not in state.placement.static_occupancy and in_zone(state, t.position, ZoneType.ENTANGLEMENT)]
        if not sites:
            raise ValidationError('NO_EZ_PARKING_SITE', 'No empty SLM candidate trap in EZ')
        if self.anchor_order not in ('forward', 'reverse'):
            raise ValueError('anchor_order must be forward or reverse')
        operands = sorted(node.gate.qubit_ids, reverse=self.anchor_order == 'reverse')
        planner = self.planner or HalfGridPlanner()
        failures = []
        for a, b in (operands, operands[::-1]):
            for site in sites[:32]:
                try:
                    return self._compile_at(intent, state, a, b, site, planner)
                except ValidationError as error:
                    failures.append(f'{a}@{site.id}: {error.violation.code}')
        raise ValidationError('SINGLE_TRAP_CANDIDATES_EXHAUSTED',
                              f'Finite anchor/site search failed, not physical impossibility: {failures[:8]}')

    def _compile_at(self, intent, state, a, b, site, planner):
        p = ProgramBuilder(state, intent)
        cell = MobileCellIndex(0, 0)
        source = {q: CaptureBinding(q, cell, state.placement.atom_to_holder[q].holder_id) for q in (a, b)}
        parked = CaptureBinding(a, cell, site.id)
        def load(binding, label):
            route(p, state.world.traps[binding.static_trap_id].position, planner)
            p.add(K.AOD_LOAD, label, bindings=(binding,))
        load(source[a], 'Load anchor in SZ')
        route(p, site.position, planner, depart=(source[a],), approach=(parked,), label='Transport anchor to EZ')
        p.add(K.AOD_OFFLOAD, 'Park anchor in EZ SLM', bindings=(parked,))
        load(source[b], 'Load partner in SZ')
        offset = state.hardware.interaction_offset
        target = Position2D(site.position.x_um+offset.x_um, site.position.y_um+offset.y_um)
        pulse_route_start = len(p.operations)
        route(p, target, planner, depart=(source[b],), label='Transport partner to CZ')
        outbound = p.operations[pulse_route_start:]
        p.add(K.ENTANGLING_PULSE, 'CZ pulse')
        # Reverse the already validated partner route, ending at its own storage trap.
        positions = [state.world.traps[source[b].static_trap_id].position] + [op.target_pose for op in outbound]
        for i, position in enumerate(reversed(positions[:-1])):
            last = i == len(positions)-2
            p.add(K.AOD_MOVE, 'Return partner to SZ', target=position,
                  bindings=(source[b],) if last else (), phase='approach' if last else None)
        p.add(K.AOD_OFFLOAD, 'Offload partner in SZ', bindings=(source[b],))
        load(parked, 'Pick up anchor from EZ')
        route(p, state.world.traps[source[a].static_trap_id].position, planner,
              depart=(parked,), approach=(source[a],), label='Return anchor to SZ')
        p.add(K.AOD_OFFLOAD, 'Offload anchor in SZ', bindings=(source[a],))
        route(p, state.aod.pose, planner)
        return p.finish(f'{self.id}/{self.anchor_order}/{planner.id}')
