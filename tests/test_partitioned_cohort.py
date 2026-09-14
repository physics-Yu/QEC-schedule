"""Bounded four-patch geometry probe through the unchanged physical Executor.

This is transport + one 18-pair pulse, not a complete QEC protocol experiment.
"""
from collections import Counter
from dataclasses import replace
import json
from math import isclose
from time import perf_counter

from neutral_atom_env.domain.models import HolderType, ZoneType
from neutral_atom_env.domain.operations import OperationType as K, TaskIntent, TaskTarget
from neutral_atom_env.experiments.qec_four_layout import build_qec_four_inputs, coordinates
from neutral_atom_env.motion.partitioned_cohort import PartitionedCohortCompiler
from neutral_atom_env.motion.compiler import exact_validate
from neutral_atom_env.motion.program import ProgramBuilder
from neutral_atom_env.motion.task_validation import validate_target
from neutral_atom_env.replay.operation_codec import plan_from_dict
from neutral_atom_env.replay.serializer import primitive
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.m3 import initial_terminal
from neutral_atom_env.simulation.patch_greedy import patch_assignment
from neutral_atom_env.simulation.pipeline import initialize
from neutral_atom_env.simulation.state import SimulationState


def test_all68_stage_parallel18_cz_restore_and_independent_replay(tmp_path):
    # 0..17 = A/B data; 18..35 = C/D data. The 32 dedicated ancillas
    # remain present throughout every capture, empty-cell sweep and CZ audit.
    gates = [dict(id=f'cross{i:02d}', gate_type='CZ', qubit_ids=(f'Q{i:03d}', f'Q{i+18:03d}'))
             for i in range(18)]
    _, circuit, platform, placement = build_qec_four_inputs({'gates': gates})
    state = initialize(circuit, platform, placement)
    assert len(state.atoms) == len(set(coordinates())) == 68
    assert state.aod.rows == 7 and state.aod.columns == 14
    assert state.hardware.backend == 'rigid' and not state.hardware.ez_neighbor_guard_enabled
    original = state.snapshot()
    (tmp_path / 'initial.json').write_text(original, encoding='utf-8')
    terminal = initial_terminal(state)
    compiler = PartitionedCohortCompiler()
    encoded_plans = []
    recovery_checkpoints = []
    load_observations = []
    started = perf_counter()

    def progress(label):
        print(f'partitioned probe {perf_counter()-started:.2f}s: {label}', flush=True)

    def execute(plan):
        progress(f'execute {plan.id}')
        encoded_plans.append(primitive(plan))
        executor = Executor(state)
        executor.submit(plan)
        checkpoint = None
        while state.event_queue:
            executor.step()
            if checkpoint is None and state.transfer is not None:
                checkpoint = state.snapshot()
            record = json.loads(state.trace.records[-1])
            if record.get('event', {}).get('event_type') == 'operation_completed':
                operation_id = record['event'].get('operation_id')
                op = next((o for o in plan.operations if o.id == operation_id), None)
                if op is not None and op.operation_type == K.AOD_LOAD:
                    load_observations.append((len(state.placement.mobile_occupancy), len(state.aod.active_cells)))
        if checkpoint is not None:
            recovery_checkpoints.append((checkpoint, state.snapshot()))
            (tmp_path / f'recovery-{len(recovery_checkpoints)}.json').write_text(checkpoint, encoding='utf-8')
            (tmp_path / f'recovery-expected-{len(recovery_checkpoints)}.json').write_text(state.snapshot(), encoding='utf-8')
        (tmp_path / 'plans.json').write_text(json.dumps(encoded_plans, ensure_ascii=False), encoding='utf-8')
        progress(f'executed {plan.id}')

    destinations = patch_assignment(state)
    shifts = {(state.world.traps[destinations[q]].position.x_um - state.world.traps[placement[q]].position.x_um,
               state.world.traps[destinations[q]].position.y_um - state.world.traps[placement[q]].position.y_um)
              for q in state.atoms}
    assert shifts == {(0, -100)}
    p = ProgramBuilder(state, TaskIntent('four-stage-probe', TaskTarget(), frozenset(state.atoms), phase='prepare'))
    progress('build stage')
    compiler.transfer_group(p, destinations, 'Stage all four complete patches')
    p.intent = replace(p.intent, target=TaskTarget(tuple(sorted(p.state.placement.atom_to_holder.items()))))
    stage = p.finish('four-stage-probe')
    assert state.snapshot() == original  # Compilation is pure.
    loads = [o for o in stage.operations if o.operation_type == K.AOD_LOAD]
    assert len(loads) == 2 and [len(o.transfer_bindings) for o in loads] == [34, 34]
    assert Counter(b.atom_id for o in loads for b in o.transfer_bindings) == Counter({q: 1 for q in state.atoms})
    execute(stage)
    assert dict(state.placement.static_occupancy) == {site: q for q, site in destinations.items()}
    assert load_observations == [(34, 98), (34, 98)]  # 64 empty active cells also validated.
    ez = next(z for z in state.world.zones if z.zone_type == ZoneType.ENTANGLEMENT)
    assert all(ez.bounds.contains(state.placement.position(q, state.world, state.aod)) for q in state.atoms)

    members = tuple((f'cross{i:02d}', f'Q{i:03d}', f'Q{i+18:03d}') for i in range(18))
    progress('build 18-pair pulse')
    pulse, cohort = compiler.pulse(state, members, (2, -40))
    pulses = [o for o in pulse.operations if o.operation_type == K.ENTANGLING_PULSE]
    assert len(pulses) == 1 and len(pulses[0].gate_ids) == 18
    execute(pulse)
    assert state.dag.completed and len(state.placement.mobile_occupancy) == 18
    assert load_observations[-1] == (18, 18)
    effects = [json.loads(r) for r in state.trace.records if json.loads(r).get('effect_completed')]
    assert len(effects) == 1
    assert Counter(effects[0]['effect_gate_ids']) == Counter({g['id']: 1 for g in gates})
    assert len(effects[0]['actual_pairs']) == 18
    assert isclose(state.physical_metrics.laser_busy_time_us, state.hardware.pulse_duration_us, abs_tol=1e-9)
    release, _ = compiler.release(state, cohort)
    execute(release)

    p = ProgramBuilder(state, TaskIntent('four-return-probe', terminal, frozenset(state.atoms), phase='cleanup'))
    progress('build terminal restoration')
    compiler.restore(p, terminal)
    returned = p.finish('four-return-probe')
    assert [len(o.transfer_bindings) for o in returned.operations if o.operation_type == K.AOD_LOAD] == [34, 34]
    execute(returned)
    validate_target(terminal, state)
    assert all(h.holder_type == HolderType.STATIC for h in state.placement.atom_to_holder.values())
    assert {q: h.holder_id for q, h in state.placement.atom_to_holder.items()} == placement
    assert state.aod == platform.aod
    assert state.physical_metrics.aod_load_count == state.physical_metrics.aod_offload_count == 5
    final = state.snapshot()
    (tmp_path / 'final.json').write_text(final, encoding='utf-8')
    assert SimulationState.restore(final).snapshot() == final

    # Replay only serialized plans: no routing/compiler call participates.
    replay = SimulationState.restore(original)
    progress('independent serialized-plan replay')
    for value in encoded_plans:
        executor = Executor(replay)
        executor.submit(plan_from_dict(value))
        executor.run()
    assert replay.snapshot() == final
    (tmp_path / 'replay.json').write_text(json.dumps({'exact': True}), encoding='utf-8')
    progress('handoff checkpoint continuation')
    # Resume genuine target-supported handoff boundaries, with pending events.
    assert len(recovery_checkpoints) == 4
    for checkpoint, expected in recovery_checkpoints:
        restored = SimulationState.restore(checkpoint)
        assert restored.snapshot() == checkpoint
        Executor(restored).run()
        assert restored.snapshot() == expected
    (tmp_path / 'verification.json').write_text(json.dumps({'status': 'PASS', 'physical_atoms': 68,
        'aod_capacity': 98, 'loaded_active_counts': load_observations, 'parallel_cz_pairs': 18,
        'load_count': state.physical_metrics.aod_load_count, 'offload_count': state.physical_metrics.aod_offload_count,
        'terminal_exact': True, 'serialized_plan_replay_exact': True, 'handoff_resume_exact_count': 4,
        'elapsed_seconds': perf_counter()-started}), encoding='utf-8')
    progress('PASS')


def test_nine_ab_cz_candidate_on_pure_predicted_staged68(tmp_path):
    """Candidate validation only; this test deliberately does not run Executor."""
    gates = [dict(id=f'ab{i:02d}', gate_type='CZ', qubit_ids=(f'Q{i:03d}', f'Q{i+9:03d}'))
             for i in range(9)]
    _, circuit, platform, placement = build_qec_four_inputs({'gates': gates})
    state = initialize(circuit, platform, placement)
    original = state.snapshot()
    compiler = PartitionedCohortCompiler()
    p = ProgramBuilder(state, TaskIntent('nine-ab-predicted-stage', TaskTarget(), frozenset(state.atoms), phase='prepare'))
    compiler.transfer_group(p, patch_assignment(state), 'Pure predicted four-patch stage')
    stage = compiler._finish(p, 'nine-ab-predicted-stage')
    assert state.snapshot() == original
    staged = p.state
    staged_snapshot = staged.snapshot()
    assert len(staged.placement.static_occupancy) == 68
    members = tuple((f'ab{i:02d}', f'Q{i:03d}', f'Q{i+9:03d}') for i in range(9))
    pulse, cohort = compiler.pulse(staged, members, (-38, 0))
    exact_validate(pulse, staged)
    assert staged.snapshot() == staged_snapshot
    pulses = [o for o in pulse.operations if o.operation_type == K.ENTANGLING_PULSE]
    assert len(pulses) == 1 and len(pulses[0].effect_gate_ids) == 9
    assert cohort.atoms == frozenset(f'Q{i:03d}' for i in range(9, 18))
    (tmp_path / 'stage-plan.json').write_text(json.dumps(primitive(stage)), encoding='utf-8')
    (tmp_path / 'pulse-plan.json').write_text(json.dumps(primitive(pulse)), encoding='utf-8')
    (tmp_path / 'verification.json').write_text(json.dumps({'status': 'PASS',
        'scope': 'Candidate geometry and ordinary plan validators only; no Executor execution',
        'physical_atoms': 68, 'aod_capacity': 98, 'parallel_cz_pairs': 9,
        'shift_um': [-38, 0], 'input_state_unchanged': True, 'predicted_state_unchanged': True}), encoding='utf-8')
