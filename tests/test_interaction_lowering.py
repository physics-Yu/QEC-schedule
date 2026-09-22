"""Interaction preparation is real checked motion, never an implicit CZ."""
from dataclasses import FrozenInstanceError, replace
from time import perf_counter

import pytest

from neutral_atom_app.visualization.workbench import build_inputs, initialize_input
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import GateStatus, HolderRef, HolderType
from neutral_atom_env.domain.operations import OperationType as K
from neutral_atom_env.hardware import get_backend
from neutral_atom_env.hardware.dynamic_traps import trap_state
from neutral_atom_env.world import PlacementState
from neutral_atom_strategies.motion.ordered_primitives import finish, new_builder
from neutral_atom_strategies.zoned.codegen import PhysicalCodegen, fork


@pytest.fixture
def setup():
    value = dict(studio={'mode': 'custom'}, circuit_profile='physical', atom_count=2,
                 layout='row', seed=13, ez_policy='adaptive', ez_neighbor_guard_enabled=True,
                 aod_backend='row_column_orthogonal', aod_rows=1, aod_columns=1,
                 aod_row_offsets_um=[0], aod_column_offsets_um=[0],
                 compilation=dict(strategy='legacy', implementation='zoned_ids'),
                 gates=[dict(id='cz', gate_type='CZ', qubit_ids=['Q000', 'Q001'], column=0)])
    normalized, circuit, platform, mapping = build_inputs(value)
    state = initialize_input(normalized, circuit, platform, mapping)
    # Declared fixture initial condition: one resident EZ anchor, one SZ atom.
    site = state.world.traps['EZ_5_25']
    holders = dict(state.placement.atom_to_holder)
    holders['Q000'] = HolderRef(HolderType.STATIC, site.id)
    switches = dict(state.slm_enabled)
    switches[site.id] = True
    state = replace(state, placement=PlacementState(holders), slm_enabled=switches)
    env = NeutralAtomEnv(state)
    lower = PhysicalCodegen(perf_counter()+30, route_budget=16)
    p = new_builder(env.state, ('cz',))
    assignments = (('cz', 'Q000', 'Q001', site.position.x_um,
                    site.position.y_um+state.hardware.interaction_distance_um),)
    return env, lower, p, assignments


def test_prepare_is_motion_only_then_explicit_effect_executes_and_replays(setup):
    env, lower, p, assignments = setup
    origin = env.snapshot()
    initial_dag = p.state.dag
    prepared = lower.prepare_interaction(p, assignments)
    assert env.snapshot() == origin
    assert p.state.dag == initial_dag
    assert p.state.dag.nodes['cz'].status == GateStatus.READY
    assert p.state.placement.mobile_occupancy
    assert all(not op.effect_gate_ids for op in p.operations)
    assert any(op.operation_type == K.AOD_LOAD for op in p.operations)
    assert any(op.operation_type == K.AOD_MOVE for op in p.operations)
    assert get_backend(p.state.hardware).actual_pairs(p.state) == frozenset({('Q000', 'Q001')})
    with pytest.raises(FrozenInstanceError):
        prepared.operation_count = 0
    lower.execute_interaction(p, prepared)
    pulses = [op for op in p.operations if op.operation_type == K.ENTANGLING_PULSE]
    assert len(pulses) == 1 and pulses[0].effect_gate_ids == ('cz',)
    assert p.state.dag.completed and not p.state.placement.mobile_occupancy
    assert env.snapshot() == origin
    plan = finish(p, compiler='interaction-lowering-test')
    env.submit(plan)
    env.run()
    replay = NeutralAtomEnv.restore(origin)
    replay.submit(plan)
    replay.run()
    assert replay.snapshot() == env.snapshot()
    assert env.state.dag.completed


def test_resident_slm_pair_prepares_without_motion_then_emits_only_pulse():
    from neutral_atom_experiments.qmap_native import compatible_architecture, make_state
    from neutral_atom_strategies.qmap_native.adapter import NativeProgramAdapter
    native = NativeProgramAdapter('atom (1, 60) atom0\natom (3, 60) atom1\n@+ cz zone0')
    state = make_state(dict(atom_count=2, gates=[dict(type='CZ', qubits=[0, 1])]),
                       dict(architecture=compatible_architecture(2, rows=1, columns=2)), native)
    env = NeutralAtomEnv(state)
    p = new_builder(env.state, ('g00000',))
    lower = PhysicalCodegen(perf_counter()+30)
    receipt = lower.prepare_interaction(p, (('g00000', 'Q000', 'Q001', 3, 60),))
    assert p.operations == [] and p.state == state
    assert receipt.batch.bindings == ()
    assert state.dag.nodes['g00000'].status == GateStatus.READY
    lower.execute_interaction(p, receipt)
    assert [op.operation_type for op in p.operations] == [K.ENTANGLING_PULSE]
    plan = finish(p, compiler='interaction-lowering-test')
    env.submit(plan)
    env.run()
    assert env.state.dag.completed
    assert env.state.placement == state.placement
    assert env.state.time_us == state.hardware.pulse_duration_us


@pytest.mark.parametrize('change', ['state', 'history', 'prefix', 'origin', 'consumed'])
def test_prepared_receipt_rejects_stale_state_or_builder_history(setup, change):
    _, lower, p, assignments = setup
    prepared = lower.prepare_interaction(p, assignments)
    if change == 'state':
        p.state = replace(p.state, time_us=p.state.time_us+1)
    elif change == 'history':
        # A no-op switch leaves endpoint geometry unchanged but adds an event.
        p.add(K.TRAP_SWITCH, 'Additional explicit event', switch_state=trap_state(p.state))
    elif change == 'prefix':
        p.operations[-1] = replace(p.operations[-1], label='Different builder history')
    elif change == 'origin':
        p.origin = replace(p.origin, time_us=p.origin.time_us+1)
    else:
        lower.execute_interaction(p, prepared)
    before = (p.state, list(p.operations))
    with pytest.raises(ValidationError) as error:
        lower.execute_interaction(p, prepared)
    assert error.value.violation.code == 'INTERACTION_STALE'
    assert (p.state, p.operations) == before


def test_preparation_checks_actual_ez_pairs_without_completing_gate(setup):
    _, lower, p, _ = setup
    # A nearby pair outside EZ is not a valid interaction preparation.
    original = p.state
    holders = dict(original.placement.atom_to_holder)
    holders['Q000'] = HolderRef(HolderType.STATIC, 'S000')
    p.state = replace(original, placement=PlacementState(holders))
    before = (p.state, list(p.operations))
    with pytest.raises(ValidationError) as error:
        lower.prepare_interaction(p, (('cz', 'Q000', 'Q001', 2, 0),))
    assert error.value.violation.code == 'ZONED_ROUTE_EXHAUSTED'
    assert any(row['code'] == 'UNINTENDED_PAIR' for row in lower.rejections)
    assert (p.state, p.operations) == before


def test_wrong_operands_and_unauthorized_effect_are_rejected_before_motion(setup):
    _, lower, p, assignments = setup
    before = (p.state, list(p.operations))
    wrong = (('cz', 'Q000', 'Q404', assignments[0][3], assignments[0][4]),)
    with pytest.raises(ValidationError) as error:
        lower.prepare_interaction(p, wrong)
    assert error.value.violation.code == 'INTERACTION_EFFECT_MISMATCH'
    prepared = lower.prepare_interaction(p, assignments)
    p.intent = replace(p.intent, gate_effects=frozenset())
    prepared_before = (p.state, list(p.operations))
    with pytest.raises(ValidationError) as error:
        lower.execute_interaction(p, prepared)
    assert error.value.violation.code == 'INTERACTION_EFFECT_MISMATCH'
    assert (p.state, p.operations) == prepared_before
    assert not before[1]


def test_failed_cleanup_is_atomic_and_combined_service_backtracks(setup, monkeypatch):
    _, lower, p, assignments = setup
    original_landing = lower._land_interaction
    failures = []
    def reject_first(work, batch, path):
        failures.append(tuple(path))
        if len(failures) == 1:
            raise ValidationError('TEST_LANDING_REJECTED', 'Reject after pulse prediction')
        return original_landing(work, batch, path)
    monkeypatch.setattr(lower, '_land_interaction', reject_first)
    lower.cz_group(p, assignments)
    assert len(failures) >= 2 and failures[0] != failures[1]
    assert p.state.dag.completed
    assert sum(op.operation_type == K.ENTANGLING_PULSE for op in p.operations) == 1
    assert lower.stats['cz_batches'] == [['cz']]
    assert len(lower.stats['landings']) == 1


def test_explicit_execution_failure_keeps_prepared_state_intact(setup, monkeypatch):
    _, lower, p, assignments = setup
    prepared = lower.prepare_interaction(p, assignments)
    before = fork(p)
    def reject(*args):
        raise ValidationError('TEST_LANDING_REJECTED', 'No post-pulse landing')
    monkeypatch.setattr(lower, '_land_interaction', reject)
    with pytest.raises(ValidationError):
        lower.execute_interaction(p, prepared)
    assert p.state == before.state and p.operations == before.operations
    assert p.state.dag.nodes['cz'].status == GateStatus.READY
    assert lower.stats['cz_batches'] == [] and lower.stats['landings'] == []
