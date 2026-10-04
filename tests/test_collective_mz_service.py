"""Actual stable-SLM collective pulses, exact captures and original-holder return."""
from collections import Counter
from dataclasses import replace

import pytest

from neutral_atom_env.circuit import DynamicGateDAG, PhysicalCircuit
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import Atom, GateStatus, GridCoord, HolderRef, HolderType, PhysicalGate, Position2D as P, Rectangle, StaticTrap
from neutral_atom_env.domain.operations import OperationType as K
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.quantum.stabilizer import StabilizerState
from neutral_atom_env.world import PlacementState
from neutral_atom_strategies.scheduling.collective_mz import compile_collective_mz

from test_patch_service_groups import patch_state
from test_rigid_readout_placement import service_state


def declare_slots(state, atoms=None, translations=None):
    atoms = tuple(atoms or state.atoms)
    traps = dict(state.world.traps)
    for q in atoms:
        home = traps[state.placement.atom_to_holder[q].holder_id]
        dy = translations[q] if translations else -120
        p = P(home.position.x_um, home.position.y_um + dy)
        key = 'mz.' + home.id
        traps[key] = StaticTrap(key, GridCoord(round(p.x_um / 5), round(p.y_um / 5)), p, False)
    # Production prefix devices declare fixed envelopes. Retain complete AOD
    # origin identity through the existing scheduled ENV replay contract.
    primary = replace(state.aod, envelope=state.aod.envelope or state.world.bounds)
    return replace(state, world=replace(state.world, traps=traps), slm_enabled=None, aod=primary)


def drive_and_check(state, plan, atoms, expected_reports=()):
    initial = state.snapshot()
    homes = dict(state.placement.atom_to_holder)
    executor = Executor(state)
    executor.submit(plan)
    completed, report_batches, effects = set(), [], []
    while state.event_queue:
        reports = set(state.measurement_results)
        executor.step()
        now = {gid for gid, node in state.dag.nodes.items() if node.status == GateStatus.COMPLETED}
        new = now - completed
        if new:
            assert not state.placement.mobile_occupancy
            assert not state.transfers and not any(a.is_moving for a in state.aods.values())
            for q in atoms:
                holder = state.placement.atom_to_holder[q]
                assert holder.holder_id == 'mz.' + homes[q].holder_id
                assert state.slm_enabled[holder.holder_id]
            effects.append(new)
        if set(state.measurement_results) != reports:
            report_batches.append(set(state.measurement_results) - reports)
        completed = now
    assert dict(state.placement.atom_to_holder) == homes
    assert not state.placement.mobile_occupancy
    assert all(not state.slm_enabled['mz.' + homes[q].holder_id] for q in atoms)
    assert all(not a.active_cells for a in state.aods.values())
    assert report_batches == ([set(expected_reports)] if expected_reports else [])
    replay = SimulationState.restore(initial)
    Executor(replay).submit(plan)
    Executor(replay).run()
    assert replay.snapshot() == state.snapshot()
    return effects


@pytest.mark.parametrize('geometry', ('canonical', 'SA'))
def test_all_initial_reset_carriers_collect_before_one_pulse_and_return(geometry):
    state, roles = patch_state(geometry=geometry)
    state = declare_slots(state)
    gates, initial = state.dag.ready_gates(), state.snapshot()
    plan, included, evidence = compile_collective_mz(state, gates, roles)
    assert state.snapshot() == initial and not included
    pulses = [op for op in plan.operations if op.operation_type == K.RESET]
    assert len(pulses) == 1 and pulses[0].effect_gate_ids == tuple(g.id for g in gates)
    assert evidence['service_cohort_size'] == 17
    assert evidence['transport_waves_are_not_service_batches']
    assert len(evidence['collection_waves']) > 1 and len(evidence['return_waves']) > 1
    for direction in ('collection_waves', 'return_waves'):
        assert Counter(q for wave in evidence[direction] for q in wave['atom_ids']) == Counter(tuple(state.atoms))
        assert all(wave['operation_ids'] and wave['source_traps'] and wave['target_traps'] for wave in evidence[direction])
    assert not evidence['full_enola_kernel_claimed']
    assert drive_and_check(state, plan, tuple(state.atoms)) == [{g.id for g in gates}]
    assert state.physical_metrics.reset_busy_time_us == 100
    assert state.physical_metrics.aod_load_count == evidence['transport_wave_count']
    assert state.physical_metrics.aod_offload_count == evidence['transport_wave_count']


def test_whole_syndrome_measurement_reports_then_original_full_barrier_reset():
    state, roles = patch_state(kinds=('MEASURE',), only=tuple(f'{basis}{i}' for basis in 'XZ' for i in range(4)))
    measurements = state.dag.circuit.gates
    barrier = tuple(g.id for g in measurements)
    resets = tuple(PhysicalGate('reset.' + g.id, 'RESET', g.qubit_ids, depends_on=barrier) for g in measurements)
    state = declare_slots(replace(state, dag=DynamicGateDAG(PhysicalCircuit(measurements + resets))))
    initial = state.snapshot()
    plan, included, evidence = compile_collective_mz(state, measurements, roles, decision=3)
    assert state.snapshot() == initial and included == resets
    service = [op for op in plan.operations if op.operation_type in {K.MEASUREMENT, K.RESET}]
    assert [op.operation_type for op in service] == [K.MEASUREMENT, K.RESET]
    assert service[1].depends_on == (service[0].id,)
    assert service[1].effect_gate_ids == tuple(g.id for g in resets)
    assert all(g.depends_on == barrier for g in included)
    expected = [{g.id for g in measurements}, {g.id for g in resets}]
    assert drive_and_check(state, plan, tuple(g.qubit_ids[0] for g in measurements), barrier) == expected
    assert state.measurement_results == {gid: 0 for gid in barrier}
    assert all(not state.atoms[g.qubit_ids[0]].measured for g in measurements)
    assert state.physical_metrics.measurement_busy_time_us == 500
    assert state.physical_metrics.reset_busy_time_us == 100
    assert evidence['measurement_report_ids'] == list(barrier)


def test_separate_devices_use_actual_slots_and_one_shared_pulse():
    state = service_state(dual=True)
    gates = tuple(PhysicalGate('reset.' + q, 'RESET', (q,)) for q in state.atoms)
    state = replace(state, dag=DynamicGateDAG(PhysicalCircuit(gates)))
    shifts = {'Q000': -60, 'Q001': -60, 'Q100': -100, 'Q101': -100}
    state = declare_slots(state, translations=shifts)
    roles = {q: {'aod_id': 'AOD_MAGIC' if q.startswith('Q1') else 'AOD_0',
                 'kind': 'data', 'role': q} for q in state.atoms}
    plan, _, evidence = compile_collective_mz(state, gates, roles)
    assert {wave['aod_id'] for wave in evidence['collection_waves']} == {'AOD_0', 'AOD_MAGIC'}
    assert len(evidence['service_pulses']) == 1
    assert {tuple(w['target_origin_um']) for w in evidence['collection_waves']} == {(10, -40), (110, -80)}
    assert drive_and_check(state, plan, tuple(state.atoms)) == [{g.id for g in gates}]
    assert state.physical_metrics.reset_busy_time_us == 100


def test_magic_complete_capture_preserves_disabled_spares_in_narrow_envelope():
    state = service_state(dual=True)
    points = {f'resource.d{i}': P(110 + 10 * (i % 3), 10 * (i // 3)) for i in range(9)}
    points.update({f'resource.{basis}{i}': P(150 + 10 * column, 10 * i)
                   for column, basis in enumerate('XZ') for i in range(4)})
    traps = {q: trap for q, trap in state.world.traps.items() if q.startswith('Q0')}
    traps.update({q: StaticTrap(q, GridCoord(int(p.x_um / 5), int(p.y_um / 5)), p) for q, p in points.items()})
    atoms = {q: Atom(q) for q in traps}
    gates = tuple(PhysicalGate('reset.' + q, 'RESET', (q,)) for q in points)
    magic = replace(state.aods['AOD_MAGIC'], columns=6, row_offsets_um=None, enabled_columns=None,
                    envelope=Rectangle(P(80, -160), P(180, 80)))
    state = replace(state, world=replace(state.world, traps=traps), atoms=atoms,
        placement=PlacementState({q: HolderRef(HolderType.STATIC, q) for q in atoms}),
        dag=DynamicGateDAG(PhysicalCircuit(gates)), aods=dict(state.aods, AOD_MAGIC=magic),
        slm_enabled=None, quantum_state=StabilizerState.zero(tuple(atoms)))
    state = declare_slots(state, tuple(points), {q: -70 for q in points})
    roles = {q: {'aod_id': 'AOD_MAGIC', 'role': q,
                 'kind': 'data' if q.startswith('resource.d') else 'syndrome_ancilla'} for q in points}
    plan, _, evidence = compile_collective_mz(state, gates, roles)
    assert [len(w['atom_ids']) for w in evidence['collection_waves']] == [17]
    assert [len(w['atom_ids']) for w in evidence['return_waves']] == [17]
    assert len(evidence['service_pulses']) == 1
    assert drive_and_check(state, plan, tuple(points)) == [{g.id for g in gates}]


def test_diagonal_cohort_does_not_capture_unrequested_cartesian_crossings():
    state, roles = patch_state(only=('X0', 'X1'))
    atoms = tuple(g.qubit_ids[0] for g in state.dag.ready_gates())
    state = declare_slots(state, atoms)
    plan, _, evidence = compile_collective_mz(state, state.dag.ready_gates(), roles)
    # X0/X1's rectangle also crosses occupied Z0/Z1. It must be two
    # independently closed real transports, followed by one two-target pulse.
    assert [len(w['atom_ids']) for w in evidence['collection_waves']] == [1, 1]
    assert all({b.atom_id for b in op.transfer_bindings} <= set(atoms) for op in plan.operations)
    assert drive_and_check(state, plan, atoms) == [{g.id for g in state.dag.circuit.gates}]


@pytest.mark.parametrize('problem', ('undeclared', 'outside', 'duplicate', 'blocked'))
def test_invalid_declarations_and_frontiers_leave_live_state_unchanged(problem):
    state, roles = patch_state(only=('d0',))
    gates = state.dag.ready_gates()
    if problem != 'undeclared':
        state = declare_slots(state, (gates[0].qubit_ids[0],))
    if problem == 'outside':
        traps = dict(state.world.traps)
        key = 'mz.' + state.placement.atom_to_holder[gates[0].qubit_ids[0]].holder_id
        traps[key] = replace(traps[key], position=P(10, 90), grid=GridCoord(2, 18))
        state = replace(state, world=replace(state.world, traps=traps))
    if problem == 'duplicate':
        gates = gates + gates
    if problem == 'blocked':
        barrier = PhysicalGate('barrier', 'RESET', ('p0.d1',))
        blocked = replace(gates[0], depends_on=(barrier.id,))
        state = replace(state, dag=DynamicGateDAG(PhysicalCircuit((barrier, blocked))))
        gates = (blocked,)
    initial = state.snapshot()
    with pytest.raises(ValueError):
        compile_collective_mz(state, gates, roles)
    assert state.snapshot() == initial and not state.event_queue
