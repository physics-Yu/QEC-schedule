"""Shape-preserving transport on one rigid two-dimensional AOD.

Groups come from geometry, never logical patch names. Row/column masks and
capture closure remain enforced by the ordinary transfer backend.
"""
from dataclasses import replace
from neutral_atom_env.domain.models import HolderType as H, MobileCellIndex, Position2D
from neutral_atom_env.domain.operations import CaptureBinding, OperationType as K
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.hardware.dynamic_traps import trap_state
from .astar import AStarHalfGridPlanner
from .single_trap import route


class PatchArrayCompiler:
    id = 'rigid-2d-array-v1'

    def __init__(self, route_expansions=100000):
        self.planner = AStarHalfGridPlanner(max_expansions=route_expansions)

    def route(self, builder, target, **kwargs):
        route(builder, target, self.planner, **kwargs)

    def bindings(self, state, atoms):
        if state.hardware.backend != 'rigid':
            raise ValidationError('PATCH_PLATFORM', 'This transport family uses rigid translation of configurable rectangular axes')
        if state.placement.mobile_occupancy:
            raise ValidationError('PATCH_AOD_BUSY', 'Begin a new group with an empty AOD')
        sites = {}
        for q in sorted(atoms):
            holder = state.placement.atom_to_holder[q]
            if holder.holder_type != H.STATIC:
                raise ValidationError('PATCH_STATIC_ORIGIN', 'All group operands must start on SLM')
            sites[q] = state.world.traps[holder.holder_id]
        axes=state.aod.configuration()
        xs=tuple(x-state.aod.pose.x_um for x in axes.x_um)
        ys=tuple(y-state.aod.pose.y_um for y in axes.y_um)
        def align(values, offsets):
            first=min(values)
            for offset in offsets:
                origin=first-offset
                indices={v:next((i for i,o in enumerate(offsets) if abs(origin+o-v)<1e-7),None)
                         for v in values}
                if all(i is not None for i in indices.values()):return origin,indices
            raise ValidationError('PATCH_CAPACITY', 'Selected atoms do not fit the configured nonuniform AOD axes')
        x,columns=align({t.position.x_um for t in sites.values()},xs)
        y,rows=align({t.position.y_um for t in sites.values()},ys)
        origin = Position2D(x,y)
        bindings = []
        for q, site in sites.items():
            c=columns[site.position.x_um];r=rows[site.position.y_um]
            bindings.append(CaptureBinding(q, MobileCellIndex(r,c), site.id))
        return origin, tuple(bindings)

    def transfer_group(self, p, destinations, label='Translate array'):
        destinations = {q: site for q, site in destinations.items()
                        if p.state.placement.atom_to_holder[q].holder_id != site}
        if not destinations:
            return
        origin, bindings = self.bindings(p.state, destinations)
        shifts = set(); unload = []
        for b in bindings:
            destination = p.state.world.traps[destinations[b.atom_id]]
            if destination.id in p.state.placement.static_occupancy:
                raise ValidationError('OCCUPIED_TASK_TARGET', 'Array destination must be free')
            source = p.state.world.traps[b.static_trap_id].position
            shifts.add((destination.position.x_um-source.x_um, destination.position.y_um-source.y_um))
            unload.append(CaptureBinding(b.atom_id, b.cell, destination.id))
        if len(shifts) != 1:
            raise ValidationError('PATCH_SHAPE', 'Group destinations must be one rigid translation')
        dx, dy = shifts.pop(); unload = tuple(unload)
        self.route(p, origin)
        p.add(K.AOD_LOAD, f'{label}: load {len(bindings)} atoms', bindings=bindings)
        self.route(p, Position2D(origin.x_um+dx, origin.y_um+dy), depart=bindings,
                   approach=unload, label=label)
        p.add(K.AOD_OFFLOAD, f'{label}: offload {len(bindings)} atoms', bindings=unload)

    def restore(self, p, target):
        # This family restores a rigidly translated full layout, not arbitrary
        # permutations. Input edits change gates, not the terminal contract.
        self.transfer_group(p, {q:h.holder_id for q,h in target.holders}, 'Return all patches to SZ')
        if target.aod_configuration:
            axes = target.aod_configuration
            self.route(p, Position2D(axes.x_um[0], axes.y_um[0]))
        if target.traps and trap_state(p.state) != target.traps:
            p.add(K.TRAP_SWITCH, 'Restore original supports', switch_state=target.traps)

    def pulse_group(self, p, members, shift):
        """members=(gate_id, anchor, mobile), identical source-to-pair shift."""
        origin, bindings = self.bindings(p.state, [mobile for _,_,mobile in members])
        self.route(p, origin)
        p.add(K.AOD_LOAD, f'Load {len(bindings)} parallel CZ operands', bindings=bindings)
        start = len(p.operations)
        self.route(p, Position2D(origin.x_um+shift[0], origin.y_um+shift[1]),
                   depart=bindings, label='Interlace matching two-dimensional operands')
        outbound = p.operations[start:]
        p.add(K.ENTANGLING_PULSE, f'Global pulse: {len(members)} parallel CZ pairs',
              gate_ids=tuple(g for g,_,_ in members))
        # Reverse the already validated geometry. Every reversed segment is
        # validated again against the post-pulse state and current permissions.
        positions = [origin] + [op.target_pose for op in outbound]
        for i, point in enumerate(reversed(positions[:-1])):
            last = i == len(positions)-2
            p.add(K.AOD_MOVE, 'Separate patches before any single-qubit light', target=point,
                  bindings=bindings if last else (), phase='approach' if last else None)
        p.add(K.AOD_OFFLOAD, 'Restore separated SLM operands', bindings=bindings)
