"""Independent discrete EZ parking contracts on a custom dense candidate grid.

These are occupancy rules; a legal MOVE may cross a reserved point. Existing
atom/support sweep restrictions remain active in every positive MOVE witness.
"""
from dataclasses import replace

import pytest

from neutral_atom_env.circuit import DynamicGateDAG, PhysicalCircuit
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import (Atom, GateStatus, GridCoord, HolderRef,
    HolderType as H, MobileCellIndex as Cell, PhysicalGate, Position2D as P,
    Rectangle, StaticTrap, Zone, ZoneType)
from neutral_atom_env.domain.operations import (CaptureBinding as Binding,
    HardwareConfig, OperationType as K, TaskIntent, TaskTarget)
from neutral_atom_env.hardware import get_backend
from neutral_atom_env.hardware.dynamic_traps import (begin_transfer, finish_transfer,
    switch_traps, trap_state)
from neutral_atom_env.hardware.ez_neighbors import reservations, validate_ez_neighbors
from neutral_atom_env.motion.program import ProgramBuilder
from neutral_atom_env.motion.scheduled import scheduled_program
from neutral_atom_env.simulation import Executor, operation_program
from neutral_atom_env.simulation.runtime_validation import validate_runtime
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.world import AODRuntimeState, PlacementState, WorldState


def site(x, y):
    return f'E_{x}_{y}'


def dense_state(*, positions=None, mobile=(), pose=None, pitch=5., pairs=((0, 1),),
                backend='rigid', completed=(), gates=None):
    bounds = Rectangle(P(-5*pitch, -5*pitch), P(7*pitch, 7*pitch))
    zone = Rectangle(P(-4*pitch, -4*pitch), P(6*pitch, 6*pitch))
    traps = {site(x, y): StaticTrap(site(x, y), GridCoord(x, y), P(x*pitch, y*pitch), False)
             for x in range(-4, 7) for y in range(-4, 7)}
    world = WorldState(bounds, traps, (Zone('dense_ez', ZoneType.ENTANGLEMENT, zone),),
                       grid_spacing_um=pitch)
    coords = {0: (0, 0), 1: (4, 4), 2: (-3, -3), 3: (-3, 3)}
    coords.update(positions or {})
    holders = {f'Q{q:03d}': HolderRef(H.MOBILE, Cell(0, mobile.index(q))) if q in mobile
               else HolderRef(H.STATIC, site(*coords[q])) for q in range(4)}
    circuit = PhysicalCircuit(tuple(gates) if gates is not None else tuple(
        PhysicalGate(f'G{i:03d}', 'CZ', tuple(f'Q{q:03d}' for q in pair))
        for i, pair in enumerate(pairs)))
    dag = DynamicGateDAG(circuit)
    for index in completed:
        for status in (GateStatus.RESERVED, GateStatus.RUNNING, GateStatus.COMPLETED):
            dag = dag.transitioned(f'G{index:03d}', status)
    aod = AODRuntimeState(pose=pose or P(-4.5*pitch, -4.5*pitch), rows=1,
        columns=max(1, len(mobile)), spacing_um=2*pitch,
        enabled_rows=(bool(mobile),), enabled_columns=(bool(mobile),)*max(1, len(mobile)))
    masks = {key: key in {h.holder_id for h in holders.values() if h.holder_type == H.STATIC}
             for key in traps}
    return SimulationState(world, PlacementState(holders),
        {f'Q{q:03d}': Atom(f'Q{q:03d}') for q in range(4)}, aod, dag,
        hardware=HardwareConfig(backend=backend), slm_enabled=masks)


AXIAL = ((-1, 0), (1, 0), (0, -1), (0, 1))


@pytest.mark.parametrize('xy', AXIAL)
@pytest.mark.parametrize('holder', ['slm', 'aod'])
def test_all_four_sites_reject_unrelated_committed_atom(xy, holder):
    options = {'positions': {2: xy}} if holder == 'slm' else {
        'mobile': (2,), 'pose': P(5*xy[0], 5*xy[1])}
    with pytest.raises(ValidationError, match='EZ_NEIGHBOR_OCCUPIED'):
        dense_state(**options)


@pytest.mark.parametrize('xy', AXIAL)
@pytest.mark.parametrize('holder', ['slm', 'aod'])
def test_exact_next_partner_is_allowed_on_each_site(xy, holder):
    options = {'positions': {1: xy}} if holder == 'slm' else {
        'mobile': (1,), 'pose': P(5*xy[0], 5*xy[1])}
    validate_ez_neighbors(dense_state(**options))


@pytest.mark.parametrize('xy', [(1, 1), (-1, -1), (0, 2)])
def test_static_diagonal_and_non_nearest_sites_are_not_a_disk(xy):
    validate_ez_neighbors(dense_state(positions={2: xy}))


@pytest.mark.parametrize('point', [P(2.5, 0), P(5.001, 0), P(5, 2.5)])
def test_mobile_half_grid_and_off_point_positions_are_allowed(point):
    validate_ez_neighbors(dense_state(mobile=(2,), pose=point))


def test_guard_uses_world_pitch_and_alignment_tolerance():
    with pytest.raises(ValidationError, match='EZ_NEIGHBOR_OCCUPIED'):
        dense_state(mobile=(2,), pose=P(10, 0), pitch=10)
    validate_ez_neighbors(dense_state(mobile=(2,), pose=P(5, 0), pitch=10))
    with pytest.raises(ValidationError, match='EZ_NEIGHBOR_OCCUPIED'):
        dense_state(mobile=(2,), pose=P(5+5e-8, 0))


def test_empty_enabled_aod_is_not_an_atom_occupant():
    state = dense_state(pose=P(5, -2.5))
    active = switch_traps(state, replace(trap_state(state), rows=(True,), columns=(True,)))
    end = get_backend(active.hardware).move(active, P(5, 0))
    assert end.aod.active_cells == (Cell(0, 0),)
    assert not end.placement.mobile_occupancy


def test_neighbor_does_not_need_a_named_static_trap():
    state = dense_state(mobile=(2,), pose=P(5, -2.5))
    traps, masks = dict(state.world.traps), dict(state.slm_enabled)
    del traps[site(1, 0)]
    del masks[site(1, 0)]
    state = replace(state, world=replace(state.world, traps=traps), slm_enabled=masks)
    with pytest.raises(ValidationError, match='EZ_NEIGHBOR_OCCUPIED'):
        get_backend(state.hardware).move(state, P(5, 0))


def test_only_ez_centers_and_points_within_ez_are_protected():
    state = dense_state(mobile=(2,), pose=P(5, -2.5))
    storage = replace(state.world.zones[0], zone_type=ZoneType.STORAGE)
    state = replace(state, world=replace(state.world, zones=(storage,)))
    assert not tuple(reservations(state))
    assert get_backend(state.hardware).move(state, P(5, 0)).aod.pose == P(5, 0)
    # The center is on the EZ boundary; its world-inside but EZ-outside neighbor
    # is explicitly outside this parking contract.
    edge = dense_state(positions={0: (6, 0)}, mobile=(2,), pose=P(35, 0))
    assert all(P(35, 0) not in points for *_, points in reservations(edge))


@pytest.mark.parametrize('gates', [(), (PhysicalGate('H0', 'H', ('Q000',)),)])
def test_atoms_without_future_cz_have_no_guard(gates):
    state = dense_state(positions={2: (1, 0)}, gates=gates)
    assert tuple(reservations(state)) == ()


def test_only_next_partner_is_exempt_and_completion_changes_or_releases_guard():
    pairs = ((0, 1), (0, 2))
    with pytest.raises(ValidationError, match='EZ_NEIGHBOR_OCCUPIED'):
        dense_state(pairs=pairs, positions={2: (1, 0)})
    validate_ez_neighbors(dense_state(pairs=pairs, completed=(0,), positions={2: (1, 0)}))
    with pytest.raises(ValidationError, match='EZ_NEIGHBOR_OCCUPIED'):
        dense_state(pairs=pairs, completed=(0,), positions={1: (1, 0)})
    finished = dense_state(pairs=pairs, completed=(0, 1), positions={3: (1, 0)})
    assert not tuple(reservations(finished))


def test_blocked_next_cz_already_reserves_site():
    gates = (PhysicalGate('H0', 'H', ('Q000',)),
             PhysicalGate('CZ0', 'CZ', ('Q000', 'Q001')))
    state = dense_state(gates=gates)
    assert state.dag.nodes['CZ0'].status == GateStatus.BLOCKED
    with pytest.raises(ValidationError, match='EZ_NEIGHBOR_OCCUPIED'):
        dense_state(gates=gates, positions={2: (1, 0)})


def test_each_anchor_applies_its_own_partner_rule():
    # Q000 permits Q001, but Q001 still awaits Q003 and therefore excludes Q000.
    with pytest.raises(ValidationError, match='EZ_NEIGHBOR_OCCUPIED') as error:
        dense_state(pairs=((1, 3), (0, 1)), positions={1: (1, 0)})
    assert error.value.violation.atom_ids == ('Q001', 'Q000')


@pytest.mark.parametrize('backend_name', ['rigid', 'row_column'])
def test_long_move_can_cross_but_cannot_stop_on_reserved_site(backend_name):
    state = dense_state(mobile=(2,), pose=P(5, -2.5), backend=backend_name)
    assert not state.slm_enabled[site(1, 0)]
    backend = get_backend(state.hardware)
    before = state.snapshot()
    crossed = backend.move(state, P(5, 2.5))
    assert crossed.aod.position(Cell(0, 0)) == P(5, 2.5)
    with pytest.raises(ValidationError, match='EZ_NEIGHBOR_OCCUPIED'):
        backend.move(state, P(5, 0))
    assert state.snapshot() == before


def test_incidental_loaded_cell_is_checked_even_when_main_cell_is_partner():
    state = dense_state(mobile=(1, 2), pose=P(-5, -2.5))
    with pytest.raises(ValidationError, match='EZ_NEIGHBOR_OCCUPIED') as error:
        get_backend(state.hardware).move(state, P(-5, 0))
    assert error.value.violation.atom_ids == ('Q000', 'Q002')


def test_empty_slm_switch_does_not_release_reservation():
    state = dense_state(mobile=(2,), pose=P(5, -2.5))
    masks = dict(state.slm_enabled)
    masks[site(1, 0)] = True
    lit = switch_traps(state, replace(trap_state(state), slm=tuple(sorted(masks.items()))))
    dark = switch_traps(lit, trap_state(state))
    assert tuple(reservations(dark)) == tuple(reservations(state))
    with pytest.raises(ValidationError, match='EZ_NEIGHBOR_OCCUPIED'):
        get_backend(dark.hardware).move(dark, P(5, 0))
    masks[site(0, 0)] = False
    with pytest.raises(ValidationError, match='HOLDER_SUPPORT_DISABLED'):
        switch_traps(state, replace(trap_state(state), slm=tuple(sorted(masks.items()))))


def test_load_retains_guard_until_holder_commit_then_releases_it():
    state = dense_state(pose=P(0, 0))
    backend = get_backend(state.hardware)
    binding = (Binding('Q000', Cell(0, 0), site(0, 0)),)
    middle = begin_transfer(backend, state, binding, K.AOD_LOAD)
    assert middle.placement.atom_to_holder['Q000'].holder_type == H.STATIC
    holders = dict(middle.placement.atom_to_holder)
    holders['Q002'] = HolderRef(H.STATIC, site(1, 0))
    with pytest.raises(ValidationError, match='EZ_NEIGHBOR_OCCUPIED'):
        validate_ez_neighbors(middle, holders=holders)
    loaded = finish_transfer(backend, middle, binding, K.AOD_LOAD)
    holders['Q000'] = loaded.placement.atom_to_holder['Q000']
    validate_ez_neighbors(loaded, holders=holders)
    assert all(anchor != 'Q000' for anchor, *_ in reservations(loaded))


def test_offload_activation_is_preflighted_atomically():
    state = dense_state(mobile=(0,), pose=P(0, 0), positions={2: (1, 0)})
    before = state.snapshot()
    binding = (Binding('Q000', Cell(0, 0), site(0, 0)),)
    with pytest.raises(ValidationError, match='EZ_NEIGHBOR_OCCUPIED'):
        begin_transfer(get_backend(state.hardware), state, binding, K.AOD_OFFLOAD)
    assert state.snapshot() == before and state.transfer is None
    legal = dense_state(mobile=(0,), pose=P(0, 0))
    backend = get_backend(legal.hardware)
    middle = begin_transfer(backend, legal, binding, K.AOD_OFFLOAD)
    assert all(anchor != 'Q000' for anchor, *_ in reservations(middle))
    finished = finish_transfer(backend, middle, binding, K.AOD_OFFLOAD)
    assert any(anchor == 'Q000' for anchor, *_ in reservations(finished))


def test_hot_expected_prefix_and_checkpoint_restore_cannot_hide_occupation():
    operation_program._runtime_prefixes.clear()
    try:
        state = dense_state(mobile=(2,), pose=P(5, 2.5))
        target = get_backend(state.hardware).target_aod(state.aod, P(5, -2.5)).configuration()
        builder = ProgramBuilder(state, TaskIntent('cross-neighbor', TaskTarget(aod_configuration=target)))
        builder.add(K.AOD_MOVE, 'cross the reserved point', target=P(5, -2.5))
        plan = scheduled_program(builder.finish('test-crossing'), state)
        executor = Executor(state)
        executor.submit(plan)
        executor.step()
        executor.step()
        validate_runtime(state)
        assert operation_program._runtime_prefixes
        before = state.snapshot()
        damaged = replace(state)
        # Deliberately bypass the constructor only to simulate external corruption.
        object.__setattr__(damaged, 'aod', replace(damaged.aod, pose=P(5, 0), is_moving=False))
        with pytest.raises(ValidationError, match='EZ_NEIGHBOR_OCCUPIED'):
            validate_runtime(damaged)
        with pytest.raises(ValidationError, match='EZ_NEIGHBOR_OCCUPIED'):
            SimulationState.restore(damaged.snapshot())
        assert state.snapshot() == before
        executor.run()
        assert state.aod.pose == P(5, -2.5)
        assert SimulationState.restore(state.snapshot()).snapshot() == state.snapshot()
    finally:
        operation_program._runtime_prefixes.clear()
