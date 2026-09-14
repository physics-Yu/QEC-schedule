"""Optimization equivalence against independent geometry/parking expectations."""
from dataclasses import FrozenInstanceError, replace
from math import hypot, nextafter, inf
from random import Random
import json

import pytest

from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import GateStatus, HolderType, MobileCellIndex as Cell, Position2D as P, ZoneType
from neutral_atom_env.hardware.ez_neighbors import validate_ez_neighbors
from neutral_atom_env.world import AODRuntimeState
from test_ez_neighbors import dense_state


def brute_violation(state, aod=None, holders=None):
    """Full scan independent of production reservations, caches and broad phase."""
    holders = state.placement.atom_to_holder if holders is None else holders
    aod = state.aod if aod is None else aod
    pending = {}
    for gate in state.dag.circuit.gates:
        if gate.gate_type == 'CZ' and state.dag.nodes[gate.id].status != GateStatus.COMPLETED:
            a, b = gate.qubit_ids
            pending.setdefault(a, (gate.id, b))
            pending.setdefault(b, (gate.id, a))
    def position(holder):
        return state.world.traps[holder.holder_id].position if holder.holder_type == HolderType.STATIC else aod.position(holder.holder_id)
    zones = [z.bounds for z in state.world.zones if z.zone_type == ZoneType.ENTANGLEMENT]
    pitch = state.world.grid_spacing_um
    for atom, holder in holders.items():
        if holder.holder_type != HolderType.STATIC or atom not in pending or not state.atoms[atom].alive:
            continue
        center = position(holder)
        if not any(z.contains(center) for z in zones):
            continue
        gate_id, partner = pending[atom]
        points = [P(center.x_um + dx, center.y_um + dy) for dx, dy in ((-pitch, 0), (pitch, 0), (0, -pitch), (0, pitch))]
        for other, other_holder in holders.items():
            if other in (atom, partner) or not state.atoms[other].alive or other_holder.holder_type == HolderType.LOST:
                continue
            pos = position(other_holder)
            for point in points:
                if state.world.bounds.contains(point) and any(z.contains(point) for z in zones) and hypot(pos.x_um-point.x_um, pos.y_um-point.y_um) <= state.hardware.alignment_tolerance_um + 1e-9:
                    return atom, other, holder.holder_id, point
    return None


def actual_violation(state, aod=None, holders=None):
    try:
        validate_ez_neighbors(state, aod=aod, holders=holders)
    except ValidationError as error:
        v = error.violation
        assert v.code == 'EZ_NEIGHBOR_OCCUPIED'
        return *v.atom_ids, v.holder_id, v.position
    return None


@pytest.mark.parametrize('pitch', [5., 10.])
def test_broad_phase_matches_brute_scan_and_first_violation(pitch):
    state = dense_state(mobile=(1, 2, 3), pitch=pitch)
    radius = state.hardware.alignment_tolerance_um + 1e-9
    rng = Random(7293)
    offsets = [0., radius, -radius, nextafter(radius, inf), nextafter(radius, -inf), .7*radius]
    # The matching atom can be any AOD column, including the exempt partner.
    poses = [P(dx*pitch-col*2*pitch+offset, dy*pitch+offset_y)
             for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1))
             for col in range(3) for offset in offsets for offset_y in (0., .7*radius)]
    poses += [P(rng.uniform(-4*pitch, 4*pitch), rng.uniform(-4*pitch, 4*pitch)) for _ in range(100)]
    for pose in poses:
        target = replace(state.aod, pose=pose)
        assert actual_violation(state, target) == brute_violation(state, target)
    # Two conflicts, sorted x order opposite to holder insertion order.
    from neutral_atom_env.domain.models import HolderRef
    holders = dict(state.placement.atom_to_holder)
    holders['Q002'] = HolderRef(HolderType.MOBILE, Cell(0, 1))
    holders['Q003'] = HolderRef(HolderType.MOBILE, Cell(0, 0))
    target = replace(state.aod, pose=P(-pitch, 0))
    expected = brute_violation(state, target, holders)
    assert expected[:2] == ('Q000', 'Q002')
    assert actual_violation(state, target, holders) == expected


def test_warm_geometry_never_caches_partner_or_completion_permission():
    state = dense_state(mobile=(1, 2), pairs=((0, 1), (0, 2)))
    # Q1 is at (-5,0), Q2 at (5,0); only current partner is exempt.
    target = replace(state.aod, pose=P(-5, 0))
    assert actual_violation(state, target)[:2] == ('Q000', 'Q002')
    dag = state.dag
    for status in (GateStatus.RESERVED, GateStatus.RUNNING, GateStatus.COMPLETED):
        dag = dag.transitioned('G000', status)
    after = replace(state, dag=dag)
    assert actual_violation(after, target)[:2] == ('Q000', 'Q001')
    for status in (GateStatus.RESERVED, GateStatus.RUNNING, GateStatus.COMPLETED):
        dag = dag.transitioned('G001', status)
    assert actual_violation(replace(state, dag=dag), target) is None
    assert actual_violation(state, target) == brute_violation(state, target)


def test_cached_axes_remain_exact_immutable_and_geometry_sensitive():
    base = AODRuntimeState(rows=2, columns=36, spacing_um=10, pose=P(-5, 7))
    assert base.configuration().x_um == tuple(-5+10*i for i in range(36))
    assert base.configuration().y_um == (7, 17)
    with pytest.raises(FrozenInstanceError):
        base.configuration().x_um = (0,)
    enabled = replace(base, enabled_rows=(True, False), enabled_columns=(True,)*36)
    assert enabled.configuration() == base.configuration()
    assert enabled.active_cells != base.active_cells
    changed = replace(base, pose=P(2, 3), columns=3, enabled_columns=None,
                      column_offsets_um=(0, 7, 25), row_offsets_um=(0, 13))
    assert changed.configuration().x_um == (2, 9, 27)
    assert changed.configuration().y_um == (3, 16)
    assert changed.position(Cell(1, 2)) == P(27, 16)
    assert base.position(Cell(1, 35)) == P(345, 17)
    with pytest.raises(ValidationError):
        replace(changed, column_offsets_um=(0, 7, 7))
    with pytest.raises(ValidationError):
        replace(changed, column_offsets_um=(0, 7, float('inf')))


def test_axes_cache_preserves_numeric_serialization_and_is_not_state_schema():
    from dataclasses import asdict
    integer = AODRuntimeState(rows=1, columns=1, spacing_um=10, pose=P(0, 0))
    floating = AODRuntimeState(rows=1, columns=1, spacing_um=10., pose=P(0., 0.))
    negative = AODRuntimeState(rows=1, columns=1, pose=P(-0., -0.),
        column_offsets_um=(-0.,), row_offsets_um=(-0.,))
    assert json.dumps(asdict(integer.configuration())) == '{"x_um": [0], "y_um": [0]}'
    assert json.dumps(asdict(floating.configuration())) == '{"x_um": [0.0], "y_um": [0.0]}'
    assert json.dumps(asdict(negative.configuration())) == '{"x_um": [-0.0], "y_um": [-0.0]}'
    assert '_configuration' not in asdict(integer)
