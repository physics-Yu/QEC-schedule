"""Actual compiler integration of nearest MZ service targets and fixed mode."""
from dataclasses import replace

import pytest

from neutral_atom_env.circuit import DynamicGateDAG, PhysicalCircuit
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import Atom, HolderRef, HolderType as H, MobileCellIndex as C, PhysicalGate, Position2D as P, Rectangle
from neutral_atom_env.domain.operations import CaptureBinding, OperationType as K, TaskIntent, TaskTarget
from neutral_atom_env.program.builder import ProgramBuilder, apply_operation
from neutral_atom_env.quantum.stabilizer import StabilizerState
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_strategies.motion.validated_rigid import LEGACY_ROUTING
from neutral_atom_strategies.scheduling.parallel_patch import compile_dual_reset_prologue, compile_readout_group

from test_rigid_readout_placement import run_and_replay, service_state


def gates_for(state, atoms):
    return tuple(state.dag.nodes[f'm.{q}'].gate for q in atoms)


def readout_positions(state, plan):
    """Infer actual service support from physical operations, not policy log."""
    work = state
    for op in plan.operations:
        if op.operation_type in {K.MEASUREMENT, K.RESET}:
            atoms = tuple(work.dag.nodes[g].gate.qubit_ids[0] for g in op.effect_gate_ids)
            return {q: work.placement.position(q, work.world, work.aods) for q in atoms}
        work = apply_operation(work, op, None)
    raise AssertionError('Compiled service has no native readout effect')


def test_default_standard_mode_chooses_nearest_mz_even_with_legacy_translation_argument():
    state = service_state()
    initial = state.snapshot()
    atoms, log = ('Q000', 'Q001'), []
    # The supplied -100 is only the explicit fixed-mode target. Standard
    # compilation now chooses its own closest complete legal service.
    plan, resets = compile_readout_group(state, gates_for(state, atoms), translation_um=-100,
                                       readout_placement_log=log)
    assert readout_positions(state, plan) == {'Q000': P(10, -40), 'Q001': P(10, -20)}
    assert {g.id for g in resets} == {'r.Q000', 'r.Q001'}
    assert state.snapshot() == initial
    assert len(log) == 1 and log[0]['aod_id'] == 'AOD_0'
    assert log[0]['source_origin_um'] == [10, 20]
    assert log[0]['selected']['target_pose_um'] == [10, -40]
    assert set(log[0]['gate_ids']) == {'m.Q000', 'm.Q001'}
    assert set(log[0]['included_reset_gate_ids']) == {'r.Q000', 'r.Q001'}
    assert log[0]['kind'] == 'MEASURE' and log[0]['schema']
    assert log[0]['optimality_claim'] is False
    run_and_replay(state, plan, atoms)


def test_explicit_fixed_mode_preserves_translation_and_has_independent_cost_difference():
    state = service_state()
    initial = state.snapshot()
    atoms, automatic_log, fixed_log = ('Q000', 'Q001'), [], []
    auto, _ = compile_readout_group(state, gates_for(state, atoms), translation_um=-100,
                                   readout_placement_log=automatic_log)
    fixed, _ = compile_readout_group(state, gates_for(state, atoms), translation_um=-100,
        readout_placement='fixed_translation', readout_placement_log=fixed_log)
    assert readout_positions(state, fixed) == {'Q000': P(10, -80), 'Q001': P(10, -60)}
    # Loaded round trip is 200 um instead of 120 um. Source positioning,
    # handoffs, native MEASURE and actual dependent RESET remain identical.
    assert fixed.estimated_distance_um - auto.estimated_distance_um == 80
    assert fixed.estimated_duration_us - auto.estimated_duration_us == pytest.approx(160)
    assert fixed_log[0]['selected']['target_pose_um'] == [10, -80]
    assert state.snapshot() == initial
    run_and_replay(state, fixed, atoms)


def test_legacy_routing_defaults_to_fixed_target_without_silent_mode_change():
    state = service_state()
    atoms, log = ('Q000', 'Q001'), []
    plan, _ = compile_readout_group(state, gates_for(state, atoms), translation_um=-100,
        routing_policy=LEGACY_ROUTING, readout_placement_log=log)
    assert readout_positions(state, plan) == {'Q000': P(10, -80), 'Q001': P(10, -60)}
    assert log[0]['selected']['target_pose_um'] == [10, -80]
    run_and_replay(state, plan, atoms)


def test_magic_targets_its_distinct_mz_boundary_and_does_not_move_foreign_loaded_holder():
    state = service_state(dual=True)
    right = state.world.zones[-1]
    right = replace(right, bounds=Rectangle(P(100, -120), P(160, -60)))
    primary = replace(state.aod, enabled_rows=(True, False, False, False),
                      enabled_columns=(True, False, False))
    holders = dict(state.placement.atom_to_holder, FOREIGN=HolderRef(H.MOBILE, C(0, 0)))
    atoms = dict(state.atoms, FOREIGN=Atom('FOREIGN'))
    state = replace(state, aod=primary, world=replace(state.world, zones=state.world.zones[:-1] + (right,)),
        placement=type(state.placement)(holders), atoms=atoms,
        quantum_state=StabilizerState.zero(tuple(atoms)))
    initial, selected, log = state.snapshot(), ('Q100', 'Q101'), []
    plan, _ = compile_readout_group(state, gates_for(state, selected), aod_id='AOD_MAGIC',
                                   readout_placement_log=log)
    assert readout_positions(state, plan) == {'Q100': P(110, -80), 'Q101': P(110, -60)}
    assert log[0]['aod_id'] == 'AOD_MAGIC'
    assert log[0]['selected']['zone_id'] == 'MZ_RIGHT'
    assert log[0]['selected']['target_pose_um'] == [110, -80]
    assert state.snapshot() == initial
    run_and_replay(state, plan, selected)
    assert state.aods['AOD_0'] == primary
    assert state.placement.atom_to_holder['FOREIGN'] == HolderRef(H.MOBILE, C(0, 0))
    assert state.placement.position('FOREIGN', state.world, state.aods) == P(0, 0)


def test_nearest_physical_collision_has_recorded_refusal_before_valid_compiler_fallback():
    state = service_state(obstruction=True)
    initial, atoms, log = state.snapshot(), ('Q000', 'Q001'), []
    plan, _ = compile_readout_group(state, gates_for(state, atoms), readout_placement_log=log)
    assert log[0]['candidates'][0]['target_pose_um'] == [10, -40]
    assert log[0]['candidates'][0]['status'] == 'rejected'
    assert log[0]['candidates'][0]['code']
    assert log[0]['selected']['target_pose_um'] != [10, -40]
    supported = readout_positions(state, plan)
    assert supported['Q000'] != P(10, -40)
    assert all(state.world.zones[0].bounds.contains(p) for p in supported.values())
    assert state.snapshot() == initial
    run_and_replay(state, plan, atoms)
    assert state.world.traps['SPECTATOR'].position == P(10, -40)


def test_auto_impossible_mz_keeps_failed_policy_provenance_and_input_state():
    state = service_state(mz_bounds=Rectangle(P(0, -40), P(100, -30)))
    initial, log = state.snapshot(), []
    with pytest.raises(ValidationError, match='READOUT_TARGETS_EXHAUSTED'):
        compile_readout_group(state, gates_for(state, ('Q000', 'Q001')), readout_placement_log=log)
    assert state.snapshot() == initial and not state.event_queue
    assert len(log) == 1 and log[0]['generated'] == 0 and log[0]['selected'] is None
    assert log[0]['generation_rejections']['MZ_PAYLOAD_DOES_NOT_FIT']
    assert log[0]['source_origin_um'] == [10, 20]


def test_explicit_fixed_target_outside_mz_does_not_silently_choose_another_target():
    state = service_state()
    initial = state.snapshot()
    # Target fits world/envelope but falls below the measurement zone.
    with pytest.raises(ValidationError, match='READOUT_ZONE_UNAVAILABLE'):
        compile_readout_group(state, gates_for(state, ('Q000', 'Q001')), translation_um=-150,
                              readout_placement='fixed_translation')
    assert state.snapshot() == initial and not state.event_queue


def test_loaded_selected_device_is_rejected_without_changing_holders_or_pending_reports():
    state = service_state()
    builder = ProgramBuilder(state, TaskIntent('source-loaded', TaskTarget(), phase='program'))
    bindings = (CaptureBinding('Q000', C(1, 1), 'Q000'), CaptureBinding('Q001', C(2, 1), 'Q001'))
    builder.add(K.AOD_LOAD, 'Actual already loaded source', bindings=bindings)
    loaded, initial = builder.state, builder.state.snapshot()
    with pytest.raises(ValidationError, match='PARALLEL_PATCH_LOADED'):
        compile_readout_group(loaded, gates_for(loaded, ('Q000', 'Q001')))
    assert loaded.snapshot() == initial and not loaded.measurement_results


def test_real_dual_reset_uses_separate_nearest_boundaries_before_shared_effect_and_replays():
    state = service_state(dual=True)
    right = replace(state.world.zones[-1], bounds=Rectangle(P(100, -120), P(160, -60)))
    native = tuple(PhysicalGate(f'r.{q}', 'RESET', (q,)) for q in ('Q000', 'Q001', 'Q100', 'Q101'))
    state = replace(state, world=replace(state.world, zones=state.world.zones[:-1] + (right,)),
                    dag=DynamicGateDAG(PhysicalCircuit(native)))
    initial, holders, log = state.snapshot(), dict(state.placement.atom_to_holder), []
    plan = compile_dual_reset_prologue(state, native[:2], native[2:], readout_placement_log=log)
    assert state.snapshot() == initial and len(log) == 2
    target = {entry['aod_id']: entry['selected']['target_pose_um'] for entry in log}
    assert target == {'AOD_0': [10, -40], 'AOD_MAGIC': [110, -80]}
    executor, observed = Executor(state), None
    executor.submit(plan)
    while state.event_queue:
        previously_complete = state.dag.completed
        executor.step()
        if state.dag.completed and not previously_complete:
            observed = {q: state.placement.position(q, state.world, state.aods) for q in holders}
            assert not any(aod.is_moving for aod in state.aods.values())
    assert observed == {'Q000': P(10, -40), 'Q001': P(10, -20),
                        'Q100': P(110, -80), 'Q101': P(110, -60)}
    assert dict(state.placement.atom_to_holder) == holders and not state.placement.mobile_occupancy
    assert state.quantum_state == StabilizerState.zero(tuple(holders))
    replay = SimulationState.restore(initial)
    executor = Executor(replay)
    executor.submit(plan)
    executor.run()
    assert replay.snapshot() == state.snapshot()
