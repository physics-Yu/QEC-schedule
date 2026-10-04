"""Independent closure and committed MZ evidence for bounded service batches."""
from collections import Counter
from copy import deepcopy
from dataclasses import replace

import pytest

from neutral_atom_env.circuit import DynamicGateDAG, PhysicalCircuit
from neutral_atom_env.domain.errors import ValidationError
from neutral_atom_env.domain.models import (Atom, GateStatus, GridCoord, HolderRef,
    HolderType, PhysicalGate, Position2D as P, Rectangle, StaticTrap, Zone, ZoneType)
from neutral_atom_env.domain.operations import HardwareConfig, OperationType as K
from neutral_atom_env.quantum.stabilizer import StabilizerState
from neutral_atom_env.simulation import Executor
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.world import AODRuntimeState, PlacementState, WorldState
from neutral_atom_strategies.scheduling.parallel_patch import compile_readout_group
from neutral_atom_strategies.scheduling.patch_service_groups import select_readout_group


def patch_state(*, copies=1, geometry='canonical', kinds=('RESET',), only=None,
                followup_reset=False, capacity_one=False):
    # Pinned canonical rotated-code coordinates, in physical micrometres.
    # SA is its similarity transform: pairwise closest home distance is 10 um,
    # and the five/four data parity classes embed separately in 20 um axes.
    local = {f'd{i}': P(50 - 20 * (i % 3), 10 + 20 * (i // 3)) for i in range(9)}
    local.update(X0=P(40, 20), X1=P(20, 40), X2=P(20, 0), X3=P(40, 60),
                 Z0=P(20, 20), Z1=P(40, 40), Z2=P(60, 20), Z3=P(0, 40))
    if geometry == 'SA':
        local = {name: P((p.x_um - p.y_um) / 2 + 20,
                         (p.x_um + p.y_um) / 2 - 30) for name, p in local.items()}
    points, roles = {}, {}
    for patch in range(copies):
        for name, point in local.items():
            atom = f'p{patch}.{name}'
            points[atom] = P(point.x_um + patch * 100, point.y_um)
            roles[atom] = {'patch': f'p{patch}', 'role': atom,
                          'kind': 'data' if name.startswith('d') else 'syndrome_ancilla',
                          'aod_id': 'AOD_0'}
    selected = [atom for atom in points if only is None or atom.split('.')[-1] in only]
    gates = tuple(PhysicalGate(f'{kind}.{atom}', kind, (atom,)) for kind in kinds for atom in selected)
    if followup_reset:
        gates += tuple(PhysicalGate(f'after.{gate.id}', 'RESET', gate.qubit_ids,
                                  depends_on=(gate.id,)) for gate in gates if gate.gate_type == 'MEASURE')
    upper_x = 170 + 100 * (copies - 1)
    bounds = Rectangle(P(-30, -355), P(upper_x, 115))
    zones = (Zone('MZ', ZoneType.MEASUREMENT, Rectangle(P(-25, -350), P(upper_x - 5, -60))),
             Zone('COMPUTE', ZoneType.ENTANGLEMENT, Rectangle(P(-25, -40), P(upper_x - 5, 110))))
    traps = {atom: StaticTrap(atom, GridCoord(round(p.x_um / 5), round(p.y_um / 5)), p)
             for atom, p in points.items()}
    columns = 1 if capacity_one else 3 * copies
    offsets = None if capacity_one else tuple(100 * patch + x for patch in range(copies) for x in (0, 20, 40))
    aod = AODRuntimeState(pose=P(-5, -5), rows=1 if capacity_one else 3,
                          columns=columns, spacing_um=20, column_offsets_um=offsets)
    state = SimulationState(WorldState(bounds, traps, zones),
        PlacementState({atom: HolderRef(HolderType.STATIC, atom) for atom in points}),
        {atom: Atom(atom) for atom in points}, aod, DynamicGateDAG(PhysicalCircuit(gates)),
        hardware=HardwareConfig(ez_neighbor_guard_enabled=False, interaction_distance_um=6),
        quantum_state=StabilizerState.zero(tuple(points)))
    return state, roles


def local_names(gates):
    return {gate.qubit_ids[0].split('.')[-1] for gate in gates}


def test_maximum_initial_data_bundle_and_canonical_auxiliary_bundle():
    state, roles = patch_state(copies=2)
    ready = state.dag.ready_gates()
    group = select_readout_group(state, ready, roles)
    assert len(group) == 18 and local_names(group) == {f'd{i}' for i in range(9)}
    auxiliary = [gate for gate in ready if roles[gate.qubit_ids[0]]['kind'] == 'syndrome_ancilla']
    group = select_readout_group(state, auxiliary, roles)
    assert len(group) == 12
    assert local_names(group) == {'X0', 'X1', 'X2', 'Z0', 'Z1', 'Z2'}
    assert all(sum(g.qubit_ids[0].endswith('.' + name) for g in group) == 2
               for name in local_names(group))


def test_diagonal_sources_reject_unrequested_crossing_captures():
    state, roles = patch_state(copies=2, only=('X0', 'X1'))
    # A two-axis rectangle through X0/X1 also turns on occupied Z0/Z1
    # crossings. Merely checking requested diagonal cells would pick both.
    group = select_readout_group(state, state.dag.ready_gates(), roles)
    assert len(group) == 2 and local_names(group) == {'X0'}


def test_sa10_layout_uses_largest_parity_bundles_without_changing_axes():
    state, roles = patch_state(copies=2, geometry='SA')
    ready = state.dag.ready_gates()
    assert local_names(select_readout_group(state, ready, roles)) == {'d0', 'd2', 'd4', 'd6', 'd8'}
    odd = [gate for gate in ready if gate.qubit_ids[0].split('.')[-1] in {'d1', 'd3', 'd5', 'd7'}]
    assert len(select_readout_group(state, odd, roles)) == 8
    auxiliary = [gate for gate in ready if roles[gate.qubit_ids[0]]['kind'] == 'syndrome_ancilla']
    assert local_names(select_readout_group(state, auxiliary, roles)) == {'X0', 'X1', 'X2', 'X3'}


def test_selector_preserves_ready_order_identity_dependencies_and_all_inputs():
    state, roles = patch_state(copies=2, kinds=('MEASURE',), followup_reset=True)
    ready = tuple(reversed(state.dag.ready_gates()))
    before, metadata = state.snapshot(), deepcopy(roles)
    group = select_readout_group(state, ready, roles)
    assert group == tuple(gate for gate in ready if gate in group)
    assert all(any(gate is original for original in ready) for gate in group)
    assert all(gate.gate_type == 'MEASURE' for gate in group)
    assert state.snapshot() == before and roles == metadata
    assert ready == tuple(reversed(state.dag.ready_gates()))


def test_capacity_fallback_does_not_split_a_copied_role_bundle():
    state, roles = patch_state(capacity_one=True, only=('d0', 'd1'))
    group = select_readout_group(state, state.dag.ready_gates(), roles)
    assert len(group) == 1 and local_names(group) == {'d0'}
    state, roles = patch_state(copies=2, capacity_one=True, only=('d0',))
    before = state.snapshot()
    with pytest.raises(ValidationError, match='PATCH_SERVICE_NO_GROUP'):
        select_readout_group(state, state.dag.ready_gates(), roles)
    assert state.snapshot() == before


def test_readout_kind_and_family_remain_separate_and_blocked_gates_are_ignored():
    state, roles = patch_state(kinds=('MEASURE',), followup_reset=True)
    group = select_readout_group(state, state.dag.circuit.gates, roles)
    assert len(group) == 9 and all(g.gate_type == 'MEASURE' for g in group)
    assert all(roles[g.qubit_ids[0]]['kind'] == 'data' for g in group)
    assert select_readout_group(state, (), roles) == ()
    foreign = deepcopy(roles)
    for role in foreign.values():
        role['aod_id'] = 'AOD_MAGIC'
    assert select_readout_group(state, state.dag.ready_gates(), foreign) == ()


@pytest.mark.parametrize('geometry,reset_sizes,measure_sizes', (
    ('canonical', (18, 12, 2, 2), (12, 2, 2)),
    ('SA', (10, 8, 8, 8), (8, 8)),
))
def test_actual_mz_batches_commit_each_gate_and_replay_original_state(geometry, reset_sizes, measure_sizes):
    state, roles = patch_state(copies=2, geometry=geometry)
    first_reset = state.dag.circuit.gates
    barrier = tuple(g.id for g in first_reset)
    measurements = tuple(PhysicalGate('measure.' + q, 'MEASURE', (q,), depends_on=barrier)
                         for q, role in roles.items() if role['kind'] == 'syndrome_ancilla')
    trailing = tuple(PhysicalGate('after.' + g.id, 'RESET', g.qubit_ids, depends_on=(g.id,))
                     for g in measurements)
    state = replace(state, dag=DynamicGateDAG(PhysicalCircuit(first_reset + measurements + trailing)))
    initial, original_circuit = state.snapshot(), state.dag.circuit
    home = dict(state.placement.atom_to_holder)
    plans, reset_batches, measured_batches, observed = [], [], [], []
    executor = Executor(state)
    while not state.dag.completed:
        before = state.snapshot()
        group = select_readout_group(state, state.dag.ready_gates(), roles)
        plan, included = compile_readout_group(state, group, decision=len(plans))
        assert state.snapshot() == before
        if group[0].gate_type == 'RESET':
            reset_batches.append(len(group))
            assert not included
        else:
            measured_batches.append(len(group))
            assert {g.qubit_ids for g in included} == {g.qubit_ids for g in group}
            assert all(g.depends_on == ('measure.' + g.qubit_ids[0],) for g in included)
        plans.append(plan)
        completed = {g.id for g in original_circuit.gates if state.dag.nodes[g.id].status == GateStatus.COMPLETED}
        executor.submit(plan)
        while state.event_queue:
            executor.step()
            now = {g.id for g in original_circuit.gates if state.dag.nodes[g.id].status == GateStatus.COMPLETED}
            for gate_id in sorted(now - completed):
                gate = state.dag.nodes[gate_id].gate
                q = gate.qubit_ids[0]
                assert state.placement.atom_to_holder[q].holder_type == HolderType.MOBILE
                point = state.placement.position(q, state.world, state.aods)
                assert any(z.zone_type == ZoneType.MEASUREMENT and z.bounds.contains(point) for z in state.world.zones)
                observed.append(gate_id)
            completed = now
        assert dict(state.placement.atom_to_holder) == home and not state.placement.mobile_occupancy
    assert tuple(reset_batches) == reset_sizes and tuple(measured_batches) == measure_sizes
    assert Counter(observed) == Counter(g.id for g in original_circuit.gates)
    assert state.dag.circuit == original_circuit
    assert state.measurement_results == {g.id: 0 for g in measurements}
    assert all(atom.alive and not atom.measured for atom in state.atoms.values())
    assert state.quantum_state == StabilizerState.zero(tuple(state.atoms))
    assert state.physical_metrics.measurement_busy_time_us == 500 * len(measure_sizes)
    assert state.physical_metrics.aod_load_count == len(plans)
    assert state.physical_metrics.aod_offload_count == len(plans)
    assert sum(op.operation_type == K.MEASUREMENT for plan in plans for op in plan.operations) == len(measure_sizes)
    replay = SimulationState.restore(initial)
    for plan in plans:
        Executor(replay).submit(plan)
        Executor(replay).run()
    assert replay.snapshot() == state.snapshot()
