"""Hard four-site parking exclusion around an EZ SLM's next CZ operand.

This is a user-defined discrete parking rule, not a laser/fidelity model.
Transit through a neighbor is allowed; committing an unrelated atom there is not.
Reservations are derived from holders and circuit order, never compiler labels.
"""
from math import hypot, nextafter, inf
from bisect import bisect_left, bisect_right
from functools import lru_cache

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import GateStatus, HolderType, Position2D, ZoneType


@lru_cache(maxsize=4096)
def _neighbor_points(bounds,zones,center,pitch):
    """Cache only immutable grid geometry, never holder/DAG permissions."""
    return tuple(p for dx,dy in ((-pitch,0),(pitch,0),(0,-pitch),(0,pitch))
                 if bounds.contains(p:=Position2D(center.x_um+dx,center.y_um+dy))
                 and any(zone.contains(p) for zone in zones))


def next_cz(state):
    """Exactly one next unfinished CZ per atom; future partners get no exemption."""
    result = {}
    for gate in state.dag.circuit.gates:
        if gate.gate_type != 'CZ' or state.dag.nodes[gate.id].status == GateStatus.COMPLETED:
            continue
        a, b = gate.qubit_ids
        result.setdefault(a, (gate.id, b))
        result.setdefault(b, (gate.id, a))
    return result


def reservations(state, *, holders=None):
    if not state.hardware.ez_neighbor_guard_enabled:
        return
    holders = state.placement.atom_to_holder if holders is None else holders
    pending = next_cz(state)
    zones = tuple(z.bounds for z in state.world.zones if z.zone_type == ZoneType.ENTANGLEMENT)
    pitch = state.world.grid_spacing_um
    for atom, holder in holders.items():
        if holder.holder_type != HolderType.STATIC or atom not in pending or not state.atoms[atom].alive:
            continue
        center = state.world.traps[holder.holder_id].position
        if not any(z.contains(center) for z in zones):
            continue
        gate_id, partner = pending[atom]
        points = _neighbor_points(state.world.bounds,zones,center,pitch)
        yield atom, partner, gate_id, holder.holder_id, points


def validate_ez_neighbors(state, *, aod=None, holders=None):
    """Validate a committed/target configuration, deliberately not its sweep."""
    if not state.hardware.ez_neighbor_guard_enabled:
        return
    holders = state.placement.atom_to_holder if holders is None else holders
    guards = tuple(reservations(state, holders=holders))
    if not guards:
        return
    aod = state.aod if aod is None else aod
    tolerance = state.hardware.alignment_tolerance_um
    positions = {}
    for atom, holder in holders.items():
        if not state.atoms[atom].alive:
            continue
        if holder.holder_type == HolderType.STATIC:
            positions[atom] = state.world.traps[holder.holder_id].position
        elif holder.holder_type == HolderType.MOBILE:
            positions[atom] = aod.position(holder.holder_id)
    # Exact x-range broad phase replaces the previous guards x all atoms x four
    # points scan. Candidate distances retain the original Euclidean tolerance.
    ordered=sorted((position.x_um,index,atom,position) for index,(atom,position) in enumerate(positions.items()))
    xs=[item[0] for item in ordered];radius=tolerance+1e-9
    for anchor, partner, gate_id, trap_id, points in guards:
        violation=None
        for point_index,point in enumerate(points):
            # One ulp outward avoids broad-phase exclusion after floating-point
            # subtraction at the exact original tolerance boundary.
            left=bisect_left(xs,nextafter(point.x_um-radius,-inf))
            right=bisect_right(xs,nextafter(point.x_um+radius,inf))
            for _,index,other,position in ordered[left:right]:
                if other in (anchor,partner):continue
                if hypot(position.x_um-point.x_um,position.y_um-point.y_um)<=radius:
                    candidate=(index,point_index,other,point)
                    if violation is None or candidate[:2]<violation[:2]:violation=candidate
        if violation is not None:
            _,_,other,point=violation
            raise ValidationError('EZ_NEIGHBOR_OCCUPIED',
                f'{anchor} at {trap_id} reserves its four nearest EZ sites for '
                f'{gate_id} with {partner}; unrelated {other} cannot park at '
                f'({point.x_um:g}, {point.y_um:g}) um. Transit is allowed.',
                atom_ids=(anchor,other),holder_id=trap_id,position=point)
