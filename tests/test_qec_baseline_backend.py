"""Fixed authored grouping and truthful canonical physical-evidence helpers."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from neutral_atom_env.domain.models import PhysicalGate, Position2D, ZoneType
from neutral_atom_env.domain.operations import HardwareConfig
from neutral_atom_experiments.qec_pbc.baseline import (
    baseline_destinations, canonical_native_inputs, phase_schedule)
from neutral_atom_experiments.qec_pbc.canonical import canonical_memory_program
from neutral_atom_experiments.qec_pbc.neutral_atom import build_native_qec_inputs
from neutral_atom_strategies.motion.single_trap import in_zone
from neutral_atom_strategies.scheduling import qec_baseline
from neutral_atom_strategies.scheduling.qec_baseline import (
    fixed_row_cz_groups, fixed_row_readout_groups)


class _Placement:
    def __init__(self, points):
        self.points = {q: Position2D(*xy) for q, xy in points.items()}

    def position(self, atom, world, aod):
        return self.points[atom]


def _state(points, hardware=None):
    return SimpleNamespace(placement=_Placement(points), world=object(), aod=object(),
                           hardware=hardware or HardwareConfig())


def _row_fixture():
    points = {'d0': (0, 0), 'a0': (-10, -10), 'd1': (20, 0), 'a1': (10, -10),
              'd2': (0, 20), 'a2': (-10, 10), 'd3': (40, 0), 'a3': (20, -10)}
    gates = (PhysicalGate('g0', 'CZ', ('d0', 'a0')),
             PhysicalGate('g1', 'CZ', ('a1', 'd1')),
             PhysicalGate('g2', 'CZ', ('a2', 'd2')),
             PhysicalGate('g3', 'CZ', ('d3', 'a3')))
    return points, gates, frozenset(f'a{i}' for i in range(4))


def test_fixed_cz_rows_use_only_designated_carriers_and_declared_offset():
    points, gates, ancillas = _row_fixture()
    state = _state(points, replace(HardwareConfig(), interaction_offset=Position2D(-4, 0)))
    groups = tuple(fixed_row_cz_groups(state, gates, ancillas))
    # The explicitly supplied offset is (-4, 0), so this first displacement is
    # (6, 10), not a hardcoded (+4, 0) pulse-site convention.
    assert groups == (
        ((6, 10), (('g0', 'd0', 'a0'), ('g1', 'd1', 'a1'))),
        ((6, 10), (('g0', 'd0', 'a0'),)),
        ((6, 10), (('g1', 'd1', 'a1'),)),
        ((6, 10), (('g2', 'd2', 'a2'),)),
        ((16, 10), (('g3', 'd3', 'a3'),)),
    )
    for shift, members in groups:
        wires = [q for _, anchor, mobile in members for q in (anchor, mobile)]
        assert len(wires) == len(set(wires))
        assert all(mobile in ancillas and anchor not in ancillas for _, anchor, mobile in members)
        assert len({points[mobile][1] for _, _, mobile in members}) == 1
        for _, anchor, mobile in members:
            assert (points[mobile][0] + shift[0], points[mobile][1] + shift[1]) == (
                points[anchor][0] - 4, points[anchor][1])
    assert {q: (p.x_um, p.y_um) for q, p in state.placement.points.items()} == points


def test_grouping_is_authored_order_and_has_no_cost_scoring():
    points, gates, ancillas = _row_fixture()
    first = tuple(fixed_row_cz_groups(_state(points), gates, ancillas))
    expensive = replace(HardwareConfig(), load_duration_us=1500,
                        offload_duration_us=2000, pulse_duration_us=100,
                        measurement_duration_us=10000, reset_duration_us=3000)
    assert tuple(fixed_row_cz_groups(_state(points, expensive), gates, ancillas)) == first
    reverse = tuple(fixed_row_cz_groups(_state(points, expensive), gates[::-1], ancillas))
    assert reverse[0][1] == (('g3', 'd3', 'a3'),)
    assert reverse[1][1] == (('g2', 'd2', 'a2'),)
    assert reverse[2][1] == (('g1', 'd1', 'a1'), ('g0', 'd0', 'a0'))


def test_a_different_declared_offset_changes_destinations_without_changing_carriers():
    points, gates, ancillas = _row_fixture()
    hardware = replace(HardwareConfig(), interaction_offset=Position2D(0, -3))
    groups = tuple(fixed_row_cz_groups(_state(points, hardware), gates, ancillas))
    assert groups[0] == ((10, 7), (('g0', 'd0', 'a0'), ('g1', 'd1', 'a1')))
    assert groups[-1] == ((20, 7), (('g3', 'd3', 'a3'),))


@pytest.mark.parametrize('gate,mobiles', (
    (PhysicalGate('h', 'H', ('a0',)), {'a0'}),
    (PhysicalGate('g', 'CZ', ('d0', 'a0')), set()),
    (PhysicalGate('g', 'CZ', ('d0', 'a0')), {'a0', 'd0'}),
))
def test_fixed_cz_partition_rejects_ambiguous_carrier_protocols(gate, mobiles):
    with pytest.raises(ValueError):
        tuple(fixed_row_cz_groups(_state({'a0': (0, 0), 'd0': (10, 0)}), (gate,), mobiles))


def test_readout_rows_preserve_authoring_order_with_explicit_singleton_fallbacks():
    state = _state({'q0': (40, -80), 'q1': (0, -100), 'q2': (20, -80)})
    gates = tuple(PhysicalGate(f'm{i}', 'MEASURE', (f'q{i}',)) for i in range(3))
    assert tuple(fixed_row_readout_groups(state, gates)) == (
        (gates[0], gates[2]), (gates[0],), (gates[2],), (gates[1],))
    with pytest.raises(ValueError):
        tuple(fixed_row_readout_groups(state, (PhysicalGate('h', 'H', ('q0',)),)))


def test_baseline_adapter_injects_fixed_factories_without_changing_other_arguments(monkeypatch):
    points, gates, ancillas = _row_fixture()
    state = _state(points)
    captured = {}

    def sparse(argument, **kwargs):
        captured.update(kwargs)
        assert argument is state
        return 'sentinel-result'

    monkeypatch.setattr(qec_baseline, 'run_qec_sparse', sparse)
    destinations = {'a0': 'existing-site'}
    assert qec_baseline.run_qec_baseline(state, mobile_atoms=ancillas,
        working_destinations=destinations, max_decisions=7) == 'sentinel-result'
    assert captured['working_destinations'] is destinations and captured['max_decisions'] == 7
    assert captured['readout_groups_factory'] is fixed_row_readout_groups
    assert tuple(captured['cz_groups_factory'](state, gates)) == tuple(
        fixed_row_cz_groups(state, gates, ancillas))
    with pytest.raises(ValueError, match='Explicit mobile'):
        qec_baseline.run_qec_baseline(state, mobile_atoms=(), working_destinations={})


@pytest.mark.parametrize('basis', ('X', 'Z'))
def test_canonical_native_inputs_relabel_syndromes_without_altering_physical_inputs(basis):
    memory = canonical_memory_program(basis=basis, rounds=1)
    legacy_adapter = build_native_qec_inputs(memory.program, seed=11)
    inputs = canonical_native_inputs(memory, seed=11, initial_placement='storage')
    assert inputs.circuit == inputs.compiled.circuit == legacy_adapter.circuit
    assert inputs.platform == legacy_adapter.platform and inputs.placement == legacy_adapter.placement
    assert inputs.seed == 11 and len(inputs.placement) == 34
    assert inputs.compiled.bindings == legacy_adapter.compiled.bindings
    assert {m.result_id for m in inputs.compiled.measurements if m.purpose == 'syndrome'} == {
        f'A.r1.{kind}{i}' for kind in ('X', 'Z') for i in range(4)}
    assert {m.result_id for m in inputs.compiled.measurements if m.purpose == 'terminal_readout'} == {
        f'A.final.m{i}' for i in range(9)}
    assert tuple((m.result_id, m.raw_gate_id, m.bit_flip) for m in inputs.compiled.measurements) == tuple(
        (m.result_id, m.raw_gate_id, m.bit_flip) for m in legacy_adapter.compiled.measurements)


def test_working_destinations_use_exact_existing_ez_sites_and_preserve_hardware():
    memory = canonical_memory_program(rounds=1)
    inputs = canonical_native_inputs(memory)
    env = inputs.create_environment()
    initial = env.snapshot()
    destinations = baseline_destinations(memory, inputs)
    binding = dict(inputs.compiled.bindings)
    assert set(destinations) == set(binding.values()) and len(set(destinations.values())) == 17
    for role, (x, y) in memory.role_coordinates:
        trap = env.state.world.traps[destinations[binding[role]]]
        assert in_zone(env.state, trap.position, ZoneType.ENTANGLEMENT)
        assert (trap.position.x_um, trap.position.y_um) == (10 * (x - 1), -100 + 10 * (y - 1))
    assert inputs.platform.hardware == HardwareConfig(ez_neighbor_guard_enabled=False)
    assert env.snapshot() == initial
    invalid = replace(memory, role_coordinates=(('A.d0', (500, 500)), *memory.role_coordinates[1:]))
    with pytest.raises(ValueError, match='not an existing EZ site'):
        baseline_destinations(invalid, inputs)


def test_every_canonical_cz_layer_partitions_into_disjoint_ancilla_source_rows():
    memory = canonical_memory_program(rounds=1)
    inputs = canonical_native_inputs(memory)
    destinations = baseline_destinations(memory, inputs)
    env = inputs.create_environment()
    points = {q: (env.state.world.traps[site].position.x_um,
                  env.state.world.traps[site].position.y_um) for q, site in destinations.items()}
    state = _state(points, env.state.hardware)
    gate_map = {g.id: g for g in inputs.circuit.gates}
    ancillas = {dict(inputs.compiled.bindings)[r.id] for r in memory.program.roles
                if r.kind == 'syndrome_ancilla'}
    for phase in memory.phases:
        if phase.kind != 'cx_cz':
            continue
        gates = tuple(gate_map[g] for g in phase.native_gate_ids)
        assert len(gates) == 6
        groups = tuple(fixed_row_cz_groups(state, gates, ancillas))
        assert {gid for _, members in groups for gid, _, _ in members} == set(phase.native_gate_ids)
        assert any(len(members) > 1 for _, members in groups)
        for _, members in groups:
            wires = [q for _, anchor, mobile in members for q in (anchor, mobile)]
            assert len(wires) == len(set(wires))
            assert {mobile for _, _, mobile in members} <= ancillas


def test_phase_schedule_counts_actual_pulses_and_keeps_incomplete_phases_visible():
    memory = canonical_memory_program(rounds=1)
    phase = next(p for p in memory.phases if p.kind == 'cx_cz')
    ids = phase.native_gate_ids
    gate_rows = [{'id': key, 'start_us': 10 + i, 'end_us': 11 + i}
                 for i, key in enumerate(ids)]

    def operation(key, kind, gate_ids, start):
        return {'plan_id': f'plan-{key}', 'operation_id': key, 'kind': kind,
                'gate_ids': list(gate_ids), 'start_us': start, 'end_us': start + .36}

    operations = [operation('pulse-a', 'entangling_pulse', ids[:3], 10),
                  operation('pulse-b', 'entangling_pulse', ids[3:], 13),
                  operation('move', 'move', ids, 9),
                  operation('elsewhere', 'entangling_pulse', ('unrelated-cz',), 20)]
    report = phase_schedule(memory, gate_rows, operations)
    actual = next(p for p in report if p['id'] == phase.id)
    assert actual['complete'] is True and actual['start_us'] == 10 and actual['end_us'] == 16
    assert actual['physical_pulse_count'] == 2
    assert [p['operation_id'] for p in actual['physical_pulses']] == ['pulse-a', 'pulse-b']
    assert [p['gate_ids'] for p in actual['physical_pulses']] == [list(ids[:3]), list(ids[3:])]
    assert all(p['physical_pulse_count'] == 0 for p in report if p['id'] != phase.id)
    incomplete = next(p for p in phase_schedule(memory, gate_rows[:-1], operations) if p['id'] == phase.id)
    assert incomplete['complete'] is False and incomplete['physical_pulse_count'] == 2
    untouched = next(p for p in report if p['kind'] == 'initialize_reset')
    assert untouched['complete'] is False and untouched['start_us'] is None and untouched['end_us'] is None
