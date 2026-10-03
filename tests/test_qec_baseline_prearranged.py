"""Prepared baseline inputs preserve physical geometry and quantum preparation."""
import pytest

from neutral_atom_env.domain.models import HolderRef, HolderType, ZoneType
from neutral_atom_env.program.task_validation import validate_target
from neutral_atom_env.quantum.stabilizer import StabilizerState
from neutral_atom_experiments.qec_pbc.baseline import (
    baseline_destinations, canonical_native_inputs)
from neutral_atom_experiments.qec_pbc.canonical import canonical_memory_program
from neutral_atom_experiments.qec_pbc.neutral_atom import build_native_qec_inputs
from neutral_atom_strategies.motion.single_trap import in_zone
from neutral_atom_strategies.scheduling.m3 import initial_terminal


@pytest.mark.parametrize('basis', ('Z', 'X'))
def test_default_initial_placement_has_all_roles_at_declared_ez_sites(basis):
    memory = canonical_memory_program(basis=basis, rounds=3)
    prepared = canonical_native_inputs(memory, seed=11)
    storage = canonical_native_inputs(memory, seed=11, initial_placement='storage')
    explicit = canonical_native_inputs(memory, seed=11, initial_placement='prearranged')
    assert prepared == explicit
    state = prepared.create_environment().state
    binding = dict(prepared.compiled.bindings)
    active = set(binding.values())
    assert len(active) == 17 and len(state.atoms) == len(prepared.placement) == 34
    assert set(state.atoms) == set(storage.placement)
    for role, (x, y) in memory.role_coordinates:
        atom = binding[role]
        holder = state.placement.atom_to_holder[atom]
        trap = state.world.traps[holder.holder_id]
        assert holder.holder_type == HolderType.STATIC
        assert in_zone(state, trap.position, ZoneType.ENTANGLEMENT)
        assert (trap.position.x_um, trap.position.y_um) == (10 * (x - 1), -100 + 10 * (y - 1))
        assert trap.enabled and state.slm_enabled[trap.id]
    spectators = set(state.atoms) - active
    assert len(spectators) == 17
    for atom in spectators:
        assert prepared.placement[atom] == storage.placement[atom]
        point = state.placement.position(atom, state.world, state.aod)
        assert in_zone(state, point, ZoneType.STORAGE)
    enabled = {key for key, value in state.slm_enabled.items() if value}
    assert enabled == set(prepared.placement.values())
    assert len(enabled) == 34
    assert all(not state.slm_enabled[storage.placement[q]] for q in active)


@pytest.mark.parametrize('basis', ('Z', 'X'))
def test_prepared_inputs_change_only_initial_placement_and_support_flags(basis):
    memory = canonical_memory_program(basis=basis, rounds=3)
    prepared = canonical_native_inputs(memory, seed=7)
    storage = canonical_native_inputs(memory, seed=7, initial_placement='storage')
    legacy = build_native_qec_inputs(memory.program, seed=7)
    assert storage.placement == legacy.placement
    assert storage.platform == legacy.platform
    assert prepared.compiled == storage.compiled
    assert prepared.circuit == storage.circuit == legacy.circuit
    assert prepared.seed == storage.seed == 7
    assert prepared.platform.hardware == storage.platform.hardware
    assert prepared.platform.aod == storage.platform.aod
    a, b = prepared.platform.world, storage.platform.world
    assert a.bounds == b.bounds and a.zones == b.zones
    assert a.grid_spacing_um == b.grid_spacing_um and a.grid_origin == b.grid_origin
    assert a.traps.keys() == b.traps.keys()
    for key, trap in a.traps.items():
        source = b.traps[key]
        assert (trap.id, trap.grid, trap.position) == (source.id, source.grid, source.position)
        assert trap.enabled == (key in prepared.placement.values())
    # Construction of a prepared input must not mutate the old input object.
    assert storage.platform == legacy.platform
    assert storage.placement == legacy.placement


@pytest.mark.parametrize('basis', ('Z', 'X'))
def test_prepared_geometry_does_not_preexecute_quantum_preparation_or_transport(basis):
    memory = canonical_memory_program(basis=basis, rounds=3)
    inputs = canonical_native_inputs(memory, seed=19)
    env = inputs.create_environment()
    state = env.state
    assert state.time_us == state.version == state.committed_events == 0
    assert not state.trace.records and not state.measurement_results
    assert not state.placement.mobile_occupancy and not state.aod.is_moving
    assert all(atom.alive and not atom.measured for atom in state.atoms.values())
    assert state.quantum_state == StabilizerState.zero(tuple(sorted(state.atoms)))
    initial_reset = next(phase for phase in memory.phases if phase.kind == 'initialize_reset')
    gates = {gate.id: gate for gate in inputs.circuit.gates}
    assert len(initial_reset.native_gate_ids) == 17
    assert all(gates[key].gate_type == 'RESET' for key in initial_reset.native_gate_ids)
    assert {gate.id for gate in state.dag.ready_gates()} == set(initial_reset.native_gate_ids)
    assert sum(g.gate_type == 'RESET' for g in inputs.circuit.gates) == 41


@pytest.mark.parametrize('basis', ('Z', 'X'))
def test_prepared_working_holders_and_terminal_need_no_initial_or_sz_return_transfer(basis):
    memory = canonical_memory_program(basis=basis, rounds=1)
    inputs = canonical_native_inputs(memory)
    env = inputs.create_environment()
    before = env.snapshot()
    working = baseline_destinations(memory, inputs)
    for atom, site in working.items():
        assert env.state.placement.atom_to_holder[atom] == HolderRef(HolderType.STATIC, site)
    terminal = initial_terminal(env.state)
    assert dict(terminal.holders) == dict(env.state.placement.atom_to_holder)
    assert all(dict(terminal.holders)[q].holder_id == site for q, site in working.items())
    validate_target(terminal, env.state)
    assert env.snapshot() == before


@pytest.mark.parametrize('mode', ('', 'unknown', None, True))
def test_unknown_initial_placement_modes_fail_closed(mode):
    memory = canonical_memory_program(rounds=1)
    with pytest.raises(ValueError, match='initial_placement'):
        canonical_native_inputs(memory, initial_placement=mode)
