"""Interaction requests retain semantics while lowerers own physical geometry."""
from copy import deepcopy
from dataclasses import replace
import json
from time import perf_counter

import pytest

from neutral_atom_app.visualization.workbench import build_inputs, initialize_input
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.operations import OperationType as K
from neutral_atom_strategies.ir import (
    ApplyInteraction, InteractionBlock, InteractionPair, MoveToInteraction,
)
from neutral_atom_strategies.zoned.codegen import PhysicalCodegen
from neutral_atom_strategies.zoned.interaction import InteractionCompiler
from neutral_atom_strategies.zoned.placement import IDSPlacer


def environment(n=2, *, pair_count=1):
    value = dict(
        studio={'mode': 'custom'}, circuit_profile='physical', atom_count=n,
        layout='row', seed=13, ez_policy='adaptive', ez_neighbor_guard_enabled=True,
        aod_backend='row_column_orthogonal', aod_rows=1, aod_columns=2,
        aod_row_offsets_um=[0], aod_column_offsets_um=[0, 20],
        compilation=dict(strategy='legacy', implementation='zoned_ids', compile_timeout_s=90),
        gates=[dict(id=f'cz{i}', gate_type='CZ',
                    qubit_ids=[f'Q{2*i:03d}', f'Q{2*i+1:03d}'], column=0)
               for i in range(pair_count)],
    )
    normalized, circuit, platform, placement = build_inputs(value)
    return NeutralAtomEnv(initialize_input(normalized, circuit, platform, placement))


def compiler(deadline=None, *, resolver=None, lowerer=None):
    deadline = deadline or perf_counter() + 90
    return InteractionCompiler(
        resolver if resolver is not None else IDSPlacer(trials=2, queue_capacity=16, site_limit=4),
        lowerer if lowerer is not None else PhysicalCodegen(deadline), deadline,
    )


def block_for(env):
    return InteractionBlock.for_gates(env.state.dag.ready_gates(), id='interaction-0')


def test_production_controller_records_intent_and_resolved_binding():
    from neutral_atom_strategies.zoned import run_zoned
    env = environment(4, pair_count=1)
    spectator_holders = {q: env.state.placement.atom_to_holder[q] for q in ('Q002', 'Q003')}
    result = run_zoned(env, restore_layout=False)
    assert result.status == 'completed', result.diagnostics
    decisions = [d for d in result.decision_log if d['kind'] == 'CZ']
    assert len(decisions) == 1
    row = decisions[0]
    block = InteractionBlock.from_dict(row['interaction_ir'])
    assert block.move.atom_ids == {'Q000', 'Q001'}
    assert row['resolved_interaction']['request_id'] == block.move.id
    assert row['resolved_interaction']['placement']['choices'][0]['gate_id'] == 'cz0'
    assert row['cz_batches'] == [['cz0']]
    assert all(env.state.placement.atom_to_holder[q] == holder for q, holder in spectator_holders.items())


def test_controller_retries_smaller_intent_for_partial_placement():
    from neutral_atom_strategies.zoned import run_zoned
    value = dict(studio={'mode': 'custom'}, circuit_profile='physical', atom_count=4,
        layout='row', seed=13, ez_policy='adaptive', ez_neighbor_guard_enabled=True,
        aod_backend='row_column_orthogonal', aod_rows=1, aod_columns=2,
        aod_row_offsets_um=[0], aod_column_offsets_um=[0, 20],
        compilation=dict(strategy='legacy', implementation='zoned_ids'),
        gates=[dict(id=f'cz{i}', gate_type='CZ',
                    qubit_ids=[f'Q{2*i:03d}', f'Q{2*i+1:03d}'], column=0)
               for i in range(2)])
    normalized, circuit, platform, mapping = build_inputs(value)
    # A legal narrow target domain has room for one anchor, not both at once.
    platform = replace(platform, world=replace(platform.world, traps={
        key: trap for key, trap in platform.world.traps.items()
        if not key.startswith('EZ_') or key == 'EZ_0_25'}))
    env = NeutralAtomEnv(initialize_input(normalized, circuit, platform, mapping))
    initial = env.snapshot()
    partial = IDSPlacer().search(env.state, env.state.dag.ready_gates(), perf_counter()+30)
    assert partial and all([c.gate_id for c in p.choices] == ['cz0'] for p in partial)
    plans = []
    submit = env.submit
    def capture(plan):
        submit(plan)
        plans.append(plan)
    env.submit = capture
    # Stop after one accepted service: no claim that this tiny EZ supports the
    # whole remaining circuit without another residency/evacuation decision.
    result = run_zoned(env, max_decisions=1, restore_layout=False)
    assert result.status == 'stalled' and result.diagnostics[0]['code'] == 'DECISION_LIMIT'
    assert result.decisions == 1
    row = result.decision_log[0]
    block = InteractionBlock.from_dict(row['interaction_ir'])
    assert block.apply.gate_ids == ('cz0',)
    assert row['gate_ids'] == ['cz0'] and row['cz_batches'] == [['cz0']]
    assert [g.id for g in env.state.dag.ready_gates()] == ['cz1']
    replay = NeutralAtomEnv.restore(initial)
    for plan in plans:
        replay.submit(plan)
        replay.run()
    assert replay.snapshot() == env.snapshot()


def assert_code(expected, call):
    with pytest.raises(ValidationError) as error:
        call()
    assert error.value.violation.code == expected


def test_coordinate_free_request_round_trips_without_resolved_sites():
    block = block_for(environment(4, pair_count=2))
    document = block.to_dict()
    assert document == {
        'schema': 'interaction-ir-v1',
        'move': {'id': 'interaction-0', 'zone': 'entanglement', 'pairs': [
            {'gate_id': 'cz0', 'atom_ids': ['Q000', 'Q001']},
            {'gate_id': 'cz1', 'atom_ids': ['Q002', 'Q003']},
        ]},
        'apply': {'move_id': 'interaction-0', 'gate_ids': ['cz0', 'cz1']},
    }
    assert InteractionBlock.from_dict(json.loads(json.dumps(document))) == block


@pytest.mark.parametrize('location,field', [
    ('root', 'site'), ('move', 'coordinates'), ('pair', 'trap_id'), ('apply', 'aod_axes'),
])
def test_external_ir_rejects_concrete_or_unknown_fields(location, field):
    document = block_for(environment()).to_dict()
    target = {'root': document, 'move': document['move'],
              'pair': document['move']['pairs'][0], 'apply': document['apply']}[location]
    target[field] = 'concrete-target'
    with pytest.raises(ValueError):
        InteractionBlock.from_dict(document)


@pytest.mark.parametrize('pairs', [
    (InteractionPair('g0', ('Q000', 'Q001')), InteractionPair('g1', ('Q001', 'Q002'))),
    (InteractionPair('g0', ('Q000', 'Q001')), InteractionPair('g0', ('Q002', 'Q003'))),
])
def test_block_rejects_overlapping_operands_or_duplicate_gates(pairs):
    with pytest.raises(ValueError):
        MoveToInteraction('move', pairs)


@pytest.mark.parametrize('change,code', [
    ('atoms', 'INTERACTION_GATE_MISMATCH'),
    ('gate', 'INTERACTION_GATE_MISMATCH'),
    ('zone', 'INTERACTION_ZONE_UNSUPPORTED'),
])
def test_request_must_match_ready_circuit_operands_and_supported_zone(change, code):
    env = environment(4)
    move = block_for(env).move
    if change == 'atoms':
        move = replace(move, pairs=(InteractionPair('cz0', ('Q000', 'Q002')),))
    elif change == 'gate':
        move = replace(move, pairs=(InteractionPair('unknown', ('Q000', 'Q001')),))
    else:
        move = replace(move, zone='storage')
    assert_code(code, lambda: compiler().resolve(env.state, move))


def test_resolver_is_injectable_and_resolve_is_not_execution():
    env = environment()
    block = block_for(env)
    original = deepcopy(env.snapshot())
    deadline = perf_counter() + 90
    chosen = IDSPlacer(trials=1, queue_capacity=16, site_limit=4).search(
        env.state, env.state.dag.ready_gates(), deadline)[0]

    class SelectedResolver:
        calls = []

        def search(self, state, gates, deadline):
            self.calls.append((state, tuple(g.id for g in gates)))
            return (chosen,)

    class UnusedLowerer:
        def layer(self, builder, placement):
            pytest.fail('Resolution must not generate or execute physical operations')

    resolver = SelectedResolver()
    resolved, = compiler(deadline, resolver=resolver, lowerer=UnusedLowerer()).resolve(env.state, block.move)
    assert resolved.placement is chosen
    assert resolver.calls == [(env.state, ('cz0',))]
    assert env.snapshot() == original
    assert not env.state.dag.completed


@pytest.mark.parametrize('change,code', [
    ('atoms', 'INTERACTION_BINDING_MISMATCH'),
    ('gate', 'INTERACTION_BINDING_MISMATCH'),
    ('zone', 'INTERACTION_BINDING_ZONE'),
    ('spectator', 'INTERACTION_BINDING_MISMATCH'),
])
def test_resolved_binding_cannot_change_semantics_or_stage_spectators(change, code):
    env = environment(4)
    block = block_for(env)
    service = compiler()
    resolved = service.resolve(env.state, block.move)[0]
    choice = resolved.placement.choices[0]
    if change == 'atoms':
        choice = replace(choice, mobile='Q003')
    elif change == 'gate':
        choice = replace(choice, gate_id='unknown')
    elif change == 'zone':
        choice = replace(choice, site=env.state.placement.atom_to_holder['Q000'].holder_id)
    placement = replace(resolved.placement, choices=(choice,))
    if change == 'spectator':
        placement = replace(placement, staging=(('Q003', choice.site),))
    invalid = replace(resolved, placement=placement)
    original = env.snapshot()
    assert_code(code, lambda: service.lower(env.state, invalid, block.apply))
    assert env.snapshot() == original


def test_lowering_requires_matching_explicit_effect_and_fresh_state():
    env = environment()
    block = block_for(env)
    service = compiler()
    resolved = service.resolve(env.state, block.move)[0]
    with pytest.raises(ValueError):
        service.lower(env.state, resolved, ApplyInteraction('different-move', block.apply.gate_ids))
    with pytest.raises(ValueError):
        service.lower(env.state, resolved, ApplyInteraction(block.move.id, ('different-gate',)))
    plan = service.lower(env.state, resolved, block.apply).plan
    env.submit(plan)
    env.run()
    assert_code('INTERACTION_STALE_BINDING', lambda: service.lower(env.state, resolved, block.apply))


@pytest.mark.parametrize('n,pair_count', [(2, 1), (4, 2), (4, 1)])
def test_real_lowering_exact_effects_independent_replay_and_spectator_identity(n, pair_count):
    env = environment(n, pair_count=pair_count)
    block = block_for(env)
    initial = deepcopy(env.snapshot())
    service = compiler()
    resolved = service.resolve(env.state, block.move)[0]
    lowered = service.lower(env.state, resolved, block.apply)
    # Prediction includes paths and pulses, but does not change time, holders or DAG.
    assert env.snapshot() == initial
    assert not env.state.dag.completed
    plan = lowered.plan
    effects = [g for operation in plan.operations for g in operation.effect_gate_ids]
    assert sorted(effects) == sorted(block.apply.gate_ids)
    assert all(operation.operation_type == K.ENTANGLING_PULSE
               for operation in plan.operations if operation.effect_gate_ids)
    transported = {binding.atom_id for operation in plan.operations
                   if operation.operation_type in (K.AOD_LOAD, K.AOD_RECAPTURE)
                   for binding in operation.transfer_bindings}
    assert transported <= block.move.atom_ids
    spectators = set(env.state.atoms) - block.move.atom_ids
    original_holders = {q: env.state.placement.atom_to_holder[q] for q in spectators}
    env.submit(plan)
    env.run()
    assert env.state.dag.completed
    assert env.state.metrics()['completed_gate_count'] == pair_count
    assert not env.state.placement.mobile_occupancy
    for q, holder in original_holders.items():
        assert env.state.placement.atom_to_holder[q] == holder
    replay = NeutralAtomEnv.restore(initial)
    replay.submit(plan)
    replay.run()
    assert replay.snapshot() == env.snapshot()


def test_failed_physical_lowering_does_not_commit_private_transport():
    env = environment()
    block = block_for(env)
    deadline = perf_counter() + 90

    class RejectAfterTransport(PhysicalCodegen):
        def layer(self, builder, placement):
            self.transport(builder, placement.destinations)
            assert builder.operations
            raise ValidationError('TEST_REJECTED_EFFECT', 'Reject after private preparation')

    service = compiler(deadline, lowerer=RejectAfterTransport(deadline))
    resolved = service.resolve(env.state, block.move)[0]
    original = env.snapshot()
    assert_code('TEST_REJECTED_EFFECT', lambda: service.lower(env.state, resolved, block.apply))
    assert env.snapshot() == original
