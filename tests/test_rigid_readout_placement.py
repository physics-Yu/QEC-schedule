"""Independent MZ origin intervals and actual rigid readout services.

The expected origin rectangles are derived from authored fixture coordinates,
without reusing the policy's private geometry generation.
"""
from dataclasses import replace

import pytest

from neutral_atom_env.circuit import DynamicGateDAG, PhysicalCircuit
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import (
    Atom, GridCoord, HolderRef, HolderType as H, MobileCellIndex as C,
    PhysicalGate, Position2D as P, Rectangle, StaticTrap, Zone, ZoneType,
)
from neutral_atom_env.domain.operations import CaptureBinding, HardwareConfig, OperationType as K, TaskIntent, TaskTarget
from neutral_atom_env.program.builder import ProgramBuilder
from neutral_atom_env.quantum.stabilizer import StabilizerState
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.world import AODRuntimeState, PlacementState, WorldState
from neutral_atom_strategies.motion.validated_rigid import append_rigid_route

from neutral_atom_strategies.scheduling.rigid_readout_placement import RigidReadoutPlacementPolicy


def service_state(*, dual=False, obstruction=False, mz_bounds=None, envelope_lower_y=-160):
    bounds = Rectangle(P(-30, -200), P(220, 100))
    mz_bounds = mz_bounds or Rectangle(P(0, -80), P(50 if dual else 100, -20))
    zones = [Zone('MZ_LEFT', ZoneType.MEASUREMENT, mz_bounds),
             Zone('COMPUTE', ZoneType.ENTANGLEMENT, Rectangle(P(-30, 0), P(220, 100)))]
    points = {'Q000': P(10, 20), 'Q001': P(10, 40)}
    primary = AODRuntimeState(pose=P(0, 0), rows=4, columns=3, spacing_um=10,
        row_offsets_um=(0, 20, 40, 60), enabled_rows=(False,) * 4,
        enabled_columns=(False,) * 3,
        envelope=Rectangle(P(-20, envelope_lower_y), P(60 if dual else 120, 80)))
    devices = {'AOD_0': primary}
    if dual:
        zones.append(Zone('MZ_RIGHT', ZoneType.MEASUREMENT, Rectangle(P(100, -80), P(160, -20))))
        points.update({'Q100': P(110, 20), 'Q101': P(110, 40)})
        devices['AOD_MAGIC'] = AODRuntimeState(pose=P(100, 0), rows=4, columns=3, spacing_um=10,
            row_offsets_um=(0, 20, 40, 60), enabled_rows=(False,) * 4,
            enabled_columns=(False,) * 3, aod_id='AOD_MAGIC',
            envelope=Rectangle(P(80, -160), P(200, 80)))
    if obstruction:
        points['SPECTATOR'] = P(10, -40)
    traps = {q: StaticTrap(q, GridCoord(round(p.x_um / 5), round(p.y_um / 5)), p)
             for q, p in points.items()}
    service_atoms = tuple(q for q in points if q != 'SPECTATOR')
    gates = tuple(PhysicalGate(f'm.{q}', 'MEASURE', (q,)) for q in service_atoms)
    gates += tuple(PhysicalGate(f'r.{q}', 'RESET', (q,), depends_on=(f'm.{q}',)) for q in service_atoms)
    return SimulationState(WorldState(bounds, traps, tuple(zones)),
        PlacementState({q: HolderRef(H.STATIC, q) for q in points}), {q: Atom(q) for q in points},
        primary, DynamicGateDAG(PhysicalCircuit(gates)),
        hardware=HardwareConfig(ez_neighbor_guard_enabled=False, interaction_distance_um=6),
        aods=devices, quantum_state=StabilizerState.zero(tuple(points)))


def points(target):
    return {q: P(x, y) for q, (x, y) in target.positions}


def pose(target):
    return P(*target.features['target_pose_um'])


def make_realizer(state, atoms, *, aod_id='AOD_0', origin=P(0, 0)):
    # The fixture owns its authored row/cell identity, independently of policy.
    bindings = tuple(CaptureBinding(q, C(i + 1, 1, aod_id), q) for i, q in enumerate(atoms))
    gates = tuple(state.dag.nodes[f'm.{q}'].gate for q in atoms)
    resets = tuple(state.dag.nodes[f'r.{q}'].gate for q in atoms)
    intent = TaskIntent('MZ-independent-proof', TaskTarget(), frozenset(atoms), phase='program',
                        gate_effects=frozenset(g.id for g in (*gates, *resets)))
    def realize(target):
        builder = ProgramBuilder(state, intent)
        builder.add(K.AOD_LOAD, 'Load original SLM sources', bindings=bindings, aod_id=aod_id)
        append_rigid_route(builder, target, aod_id=aod_id, depart=bindings)
        builder.add(K.MEASUREMENT, 'Actual MZ readout', gate_ids=tuple(g.id for g in gates), aod_id=aod_id)
        builder.add(K.RESET, 'Actual dependent MZ reset', gate_ids=tuple(g.id for g in resets), aod_id=aod_id)
        append_rigid_route(builder, origin, aod_id=aod_id, approach=bindings)
        builder.add(K.AOD_OFFLOAD, 'Restore original SLM holders', bindings=bindings, aod_id=aod_id)
        return builder.finish('rigid-MZ-placement-test')
    return realize


def run_and_replay(state, plan, atoms):
    initial, original_world = state.snapshot(), state.world
    holders = dict(state.placement.atom_to_holder)
    mobile = dict(state.placement.mobile_occupancy)
    executor, observed = Executor(state), []
    executor.submit(plan)
    while state.event_queue:
        old = set(state.measurement_results)
        executor.step()
        for report in set(state.measurement_results) - old:
            q = state.dag.nodes[report].gate.qubit_ids[0]
            holder = state.placement.atom_to_holder[q]
            p = state.placement.position(q, state.world, state.aods)
            assert holder.holder_type == H.MOBILE
            assert any(z.zone_type == ZoneType.MEASUREMENT and z.bounds.contains(p)
                       for z in state.world.zones)
            observed.append(report)
    assert set(observed) == {f'm.{q}' for q in atoms}
    assert {key: state.measurement_results[key] for key in observed} == {key: 0 for key in observed}
    assert dict(state.placement.atom_to_holder) == holders
    assert dict(state.placement.mobile_occupancy) == mobile
    assert state.world == original_world
    assert all(state.dag.nodes[f'r.{q}'].status.value == 'completed' for q in atoms)
    replay = SimulationState.restore(initial)
    executor = Executor(replay)
    executor.submit(plan)
    executor.run()
    assert replay.snapshot() == state.snapshot()


def test_nearest_clamp_uses_all_actual_carrier_offsets_not_empty_origin_or_spare_row():
    state = service_state()
    before = state.snapshot()
    policy = RigidReadoutPlacementPolicy()
    candidates = policy.candidates(state, ('Q000', 'Q001'), aod_id='AOD_0', origin=P(0, 0))
    assert candidates and pose(candidates[0]) == P(0, -60)
    # Only occupied rows 1/2 must enter MZ. Row 0 is empty and row 3 is a
    # disabled spare; neither may replace actual carrier offsets in the clamp.
    assert points(candidates[0]) == {'Q000': P(10, -40), 'Q001': P(10, -20)}
    mz = state.world.zones[0].bounds
    for target in candidates:
        assert target.support == 'aod' and target.slm == ()
        assert all(mz.contains(p) for p in points(target).values())
        assert target.features['aod_id'] == 'AOD_0'
        assert target.features['zone_id'] == 'MZ_LEFT'
    assert state.snapshot() == before


def test_x_and_y_clamp_are_independently_correct_when_mz_is_laterally_shifted():
    state = service_state(mz_bounds=Rectangle(P(30, -80), P(60, -20)))
    candidates = RigidReadoutPlacementPolicy().candidates(state, ('Q000', 'Q001'), origin=P(0, 0))
    assert pose(candidates[0]) == P(20, -60)
    assert points(candidates[0]) == {'Q000': P(30, -40), 'Q001': P(30, -20)}


def test_full_disabled_capacity_stays_inside_envelope_while_not_all_spares_need_mz():
    state = service_state()
    aod = state.aod
    candidates = RigidReadoutPlacementPolicy().candidates(state, ('Q000', 'Q001'), origin=P(0, 0))
    for target in candidates:
        p = pose(target)
        for x in (p.x_um, p.x_um + 20):
            for y in (p.y_um, p.y_um + 60):
                assert aod.envelope.contains(P(x, y)) and state.world.bounds.contains(P(x, y))
    assert pose(candidates[0]).y_um + 60 == 0  # spare row outside MZ, still legal


def test_disabled_lowest_spare_axis_can_make_apparently_fitting_carriers_impossible():
    state = service_state(envelope_lower_y=-55)
    before = state.snapshot()
    policy = RigidReadoutPlacementPolicy()
    assert policy.candidates(state, ('Q000', 'Q001'), origin=P(0, 0)) == ()
    # Origin -60 would fit both carriers but put disabled row 0 below -55.
    with pytest.raises(ValidationError, match='READOUT_TARGETS_EXHAUSTED'):
        policy.choose(state, ('Q000', 'Q001'), make_realizer(state, ('Q000', 'Q001')), origin=P(0, 0))
    assert state.snapshot() == before


def test_other_device_chooses_its_own_mz_envelope_and_keeps_complete_world_visible():
    state = service_state(dual=True)
    before, world, primary = state.snapshot(), state.world, state.aods['AOD_0']
    atoms = ('Q100', 'Q101')
    policy = RigidReadoutPlacementPolicy()
    candidates = policy.candidates(state, atoms, aod_id='AOD_MAGIC', origin=P(100, 0))
    assert candidates and pose(candidates[0]) == P(100, -60)
    assert points(candidates[0]) == {'Q100': P(110, -40), 'Q101': P(110, -20)}
    assert all(c.features['zone_id'] == 'MZ_RIGHT' and c.features['aod_id'] == 'AOD_MAGIC'
               for c in candidates)
    selection = policy.choose(state, atoms, make_realizer(state, atoms, aod_id='AOD_MAGIC', origin=P(100, 0)),
                              aod_id='AOD_MAGIC', origin=P(100, 0))
    assert state.snapshot() == before and state.world is world
    run_and_replay(state, selection.plan, atoms)
    assert state.aods['AOD_0'] == primary and state.world == world
    assert all(op.aod_id == 'AOD_MAGIC' for op in selection.plan.operations)


def test_foreign_loaded_carrier_stays_supported_and_visible_during_secondary_readout():
    state = service_state(dual=True)
    primary = replace(state.aod, enabled_rows=(True, False, False, False),
                      enabled_columns=(True, False, False))
    holders = dict(state.placement.atom_to_holder, FOREIGN=HolderRef(H.MOBILE, C(0, 0)))
    atoms = dict(state.atoms, FOREIGN=Atom('FOREIGN'))
    state = replace(state, aod=primary, placement=PlacementState(holders), atoms=atoms,
                    quantum_state=StabilizerState.zero(tuple(atoms)))
    initial = state.snapshot()
    selected = ('Q100', 'Q101')
    selection = RigidReadoutPlacementPolicy(top_k=1).choose(state, selected,
        make_realizer(state, selected, aod_id='AOD_MAGIC', origin=P(100, 0)),
        aod_id='AOD_MAGIC', origin=P(100, 0))
    assert state.snapshot() == initial
    run_and_replay(state, selection.plan, selected)
    assert state.aods['AOD_0'] == primary
    assert state.placement.atom_to_holder['FOREIGN'] == HolderRef(H.MOBILE, C(0, 0))
    assert state.placement.position('FOREIGN', state.world, state.aods) == P(0, 0)


@pytest.mark.parametrize('epsilon', (-1e-10, 1e-10))
def test_alignment_tolerance_uses_actual_loaded_axis_at_strict_mz_boundary(epsilon):
    state = service_state()
    traps = dict(state.world.traps)
    traps['Q001'] = replace(traps['Q001'], position=P(10, 40 + epsilon))
    state = replace(state, world=replace(state.world, traps=traps))
    initial = state.snapshot()
    atoms = ('Q000', 'Q001')
    policy = RigidReadoutPlacementPolicy(top_k=1)
    targets = policy.candidates(state, atoms, origin=P(0, 0))
    assert pose(targets[0]) == P(0, -60)
    assert points(targets[0])['Q001'] == P(10, -20)
    selection = policy.choose(state, atoms, make_realizer(state, atoms), origin=P(0, 0))
    assert state.snapshot() == initial
    run_and_replay(state, selection.plan, atoms)
    assert state.world.traps['Q001'].position == P(10, 40 + epsilon)


def test_actual_nearest_endpoint_obstruction_rejects_then_uses_next_candidate():
    state = service_state(obstruction=True)
    before = state.snapshot()
    atoms = ('Q000', 'Q001')
    policy = RigidReadoutPlacementPolicy(candidate_budget=8, top_k=3)
    candidates = policy.candidates(state, atoms, origin=P(0, 0))
    assert points(candidates[0])['Q000'] == P(10, -40)
    selection = policy.choose(state, atoms, make_realizer(state, atoms), origin=P(0, 0))
    log = policy.log[-1]
    assert log['candidates'][0]['status'] == 'rejected'
    assert log['candidates'][0]['target_pose_um'] == [0, -60]
    assert selection.target_pose != P(0, -60)
    assert log['selected']['target_pose_um'] == [selection.target_pose.x_um, selection.target_pose.y_um]
    assert 1 < len(log['candidates']) <= 8 and log['optimality_claim'] is False
    accepted = [entry for entry in log['candidates'] if entry['status'] == 'accepted']
    assert len(accepted) <= 3
    assert log['selected']['actual_us'] == min(entry['actual_us'] for entry in accepted)
    assert state.snapshot() == before and state.world.traps['SPECTATOR'].position == P(10, -40)
    run_and_replay(state, selection.plan, atoms)
    assert state.placement.atom_to_holder['SPECTATOR'] == HolderRef(H.STATIC, 'SPECTATOR')


def test_clamp_selection_real_readout_reset_return_and_original_plan_replay():
    state = service_state()
    before = state.snapshot()
    atoms = ('Q000', 'Q001')
    policy = RigidReadoutPlacementPolicy(candidate_budget=4, top_k=2)
    selection = policy.choose(state, atoms, make_realizer(state, atoms), origin=P(0, 0))
    assert selection.target_pose == P(0, -60)
    assert state.snapshot() == before
    assert sum(op.operation_type == K.AOD_LOAD for op in selection.plan.operations) == 1
    assert sum(op.operation_type == K.AOD_OFFLOAD for op in selection.plan.operations) == 1
    assert [op.operation_type for op in selection.plan.operations if op.effect_gate_ids] == [K.MEASUREMENT, K.RESET]
    assert selection.plan.estimated_duration_us == 200 + 120 / state.hardware.speed_um_per_us + 500 + 100
    run_and_replay(state, selection.plan, atoms)
    assert state.aod.pose == P(0, 0) and state.dag.completed


def test_too_thin_mz_generates_no_candidate_and_fails_without_realizer_or_state_mutation():
    state = service_state(mz_bounds=Rectangle(P(0, -40), P(100, -30)))
    before, calls = state.snapshot(), []
    def unexpected(target):
        calls.append(target)
        raise AssertionError('No actual carrier span fits this MZ')
    policy = RigidReadoutPlacementPolicy()
    assert policy.candidates(state, ('Q000', 'Q001'), origin=P(0, 0)) == ()
    with pytest.raises(ValidationError, match='READOUT_TARGETS_EXHAUSTED'):
        policy.choose(state, ('Q000', 'Q001'), unexpected, origin=P(0, 0))
    assert not calls and state.snapshot() == before


def test_candidate_budget_is_a_real_bound_after_physical_failure():
    state = service_state(obstruction=True)
    before = state.snapshot()
    policy = RigidReadoutPlacementPolicy(candidate_budget=1, top_k=1)
    with pytest.raises(ValidationError, match='READOUT_TARGETS_EXHAUSTED'):
        policy.choose(state, ('Q000', 'Q001'), make_realizer(state, ('Q000', 'Q001')), origin=P(0, 0))
    assert len(policy.log[-1]['candidates']) == 1
    assert policy.log[-1]['candidates'][0]['status'] == 'rejected'
    assert policy.log[-1]['selected'] is None and state.snapshot() == before


def test_nonstatic_sources_fail_and_cannot_be_relabelled_by_placement_policy():
    state = service_state()
    builder = ProgramBuilder(state, TaskIntent('already-loaded', TaskTarget(), phase='program'))
    bindings = (CaptureBinding('Q000', C(1, 1), 'Q000'), CaptureBinding('Q001', C(2, 1), 'Q001'))
    builder.add(K.AOD_LOAD, 'Real loaded state', bindings=bindings)
    loaded, policy = builder.state, RigidReadoutPlacementPolicy()
    before = loaded.snapshot()
    with pytest.raises(ValidationError, match='READOUT_POLICY_START'):
        policy.candidates(loaded, ('Q000', 'Q001'), origin=P(0, 0))
    assert loaded.snapshot() == before


def test_source_must_embed_in_existing_fixed_axes_without_changing_placement():
    state = service_state()
    before = state.snapshot()
    with pytest.raises(ValidationError, match='RIGID_MZ_SOURCE_EMBEDDING'):
        RigidReadoutPlacementPolicy().candidates(state, ('Q000', 'Q001'), origin=P(2.5, 0))
    assert state.snapshot() == before
