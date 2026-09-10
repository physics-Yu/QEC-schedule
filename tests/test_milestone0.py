from dataclasses import FrozenInstanceError, replace
import json
import pytest
from neutral_atom_env.domain.models import *
from neutral_atom_env.simulation import make_demo_state
from neutral_atom_env.testing.logical_executor import LogicalTestExecutor as Executor
from neutral_atom_env.simulation.event_queue import EventQueue
from neutral_atom_env.world import PlacementState
from neutral_atom_env.circuit import PhysicalCircuit, DynamicGateDAG
from neutral_atom_env.testing.artifacts import render


def test_world_layout(test_context):
    state = test_context["state"]
    assert len(state.world.traps) == 4
    assert {z.zone_type for z in state.world.zones} == set(ZoneType)
    storage, entanglement, measurement = state.world.zones
    assert storage.bounds.lower.y_um > entanglement.bounds.upper.y_um
    assert entanglement.bounds.lower.y_um > measurement.bounds.upper.y_um
    assert all(z.bounds.lower.x_um == storage.bounds.lower.x_um and
               z.bounds.upper.x_um == storage.bounds.upper.x_um for z in state.world.zones)
    assert state.placement.position("Q002", state.world, state.aod) == Position2D(10, 0)
    assert not hasattr(state.atoms["Q000"], "position")
    assert not hasattr(state.atoms["Q000"], "home")


def test_ready_frontier(test_context):
    state = test_context["state"]
    assert [g.id for g in state.dag.ready_gates()] == ["g1", "g2"]
    assert state.dag.nodes["g3"].remaining_predecessors == 2
    assert state.placement.position("Q000", state.world, state.aod).y_um == 0


def test_event_integration(test_context):
    state = test_context["state"]
    traps = {key: replace(trap, position=Position2D(trap.position.x_um, -20)) for key, trap in state.world.traps.items()}
    state = replace(state, world=replace(state.world, traps=traps))
    test_context.update(state=state, initial=state.snapshot())
    executor = Executor(state)
    for gate in ("g1", "g2", "g3"):
        for kind in (EventType.GATE_RESERVED, EventType.GATE_STARTED, EventType.GATE_COMPLETED):
            executor.schedule(SimulationEvent(state.time_us + 1, kind, gate))
            executor.step()
    assert state.dag.completed
    assert state.version == 9 and state.time_us == 9
    assert len(state.trace.records) == 9
    assert state.metrics()["completed_gate_count"] == 3
    assert json.loads(test_context["initial"])["placement"] == json.loads(state.snapshot())["placement"]


def test_failed_gate_does_not_release(test_context):
    state = test_context["state"]
    ex = Executor(state)
    for kind in (EventType.GATE_RESERVED, EventType.GATE_FAILED):
        ex.schedule(SimulationEvent(0, kind, "g1"))
        ex.step()
    assert state.dag.nodes["g3"].remaining_predecessors == 2


def test_invalid_transition_atomic(test_context):
    state = test_context["state"]
    ex = Executor(state)
    ex.schedule(SimulationEvent(5, EventType.GATE_COMPLETED, "g1"))
    before = state.snapshot()
    with pytest.raises(ValueError):
        ex.step()
    assert state.snapshot() == before and not state.trace.records


def test_queue_stable_order():
    queue = EventQueue()
    events = [SimulationEvent(t, EventType.WAIT_COMPLETED) for t in (2, 1, 1)]
    for event in events:
        queue = queue.push(event)
    for expected in (events[1], events[2], events[0]):
        event, queue = queue.pop()
        assert event is expected


@pytest.mark.parametrize("time", [-1, float("nan"), float("inf")])
def test_invalid_time(time):
    with pytest.raises(ValueError):
        SimulationEvent(time, EventType.WAIT_COMPLETED)


def test_no_past_events(test_context):
    ex = Executor(test_context["state"])
    ex.schedule(SimulationEvent(2, EventType.WAIT_COMPLETED))
    ex.step()
    with pytest.raises(ValueError):
        ex.schedule(SimulationEvent(1, EventType.WAIT_COMPLETED))


@pytest.mark.parametrize("holder", [HolderRef(HolderType.STATIC, "s1"), HolderRef(HolderType.STATIC, "missing"), HolderRef(HolderType.LOST, None), HolderRef(HolderType.MOBILE, MobileCellIndex(9, 0))])
def test_invalid_holder(holder, test_context):
    state = test_context["state"]
    mapping = dict(state.placement.atom_to_holder)
    mapping["Q000"] = holder
    with pytest.raises(ValueError):
        replace(state, placement=PlacementState(mapping))


def test_mobile_derived_position(test_context):
    state = test_context["state"]
    mapping = dict(state.placement.atom_to_holder)
    mapping["Q000"] = HolderRef(HolderType.MOBILE, MobileCellIndex(1, 1))
    state = replace(state, placement=PlacementState(mapping))
    test_context.update(state=state, initial=state.snapshot())
    assert state.placement.position("Q000", state.world, state.aod) == Position2D(5, 5)
    assert "s0" not in state.placement.static_occupancy


def test_determinism_and_observer(tmp_path, test_context):
    state = test_context["state"]
    other = make_demo_state()
    for current in (state, other):
        ex = Executor(current)
        ex.schedule(SimulationEvent(1, EventType.WAIT_COMPLETED))
        ex.run()
    assert state.snapshot() == other.snapshot()
    assert state.trace.records == other.trace.records
    before = state.snapshot()
    render(before, tmp_path / "snapshot.png")
    assert state.snapshot() == before
    assert (tmp_path / "snapshot.png").stat().st_size > 1000


def test_read_only_state(test_context):
    state = test_context["state"]
    with pytest.raises(FrozenInstanceError):
        state.time_us = 4
    with pytest.raises(TypeError):
        state.placement.atom_to_holder["Q000"] = None
    with pytest.raises(FrozenInstanceError):
        state.dag.nodes["g1"].status = GateStatus.COMPLETED


def test_shared_predecessor_deduplicated():
    circuit = PhysicalCircuit((PhysicalGate("G000", "CZ", ("Q000", "Q001")), PhysicalGate("G001", "CZ", ("Q000", "Q001"))))
    assert DynamicGateDAG(circuit).nodes["G001"].remaining_predecessors == 1
    assert DynamicGateDAG(PhysicalCircuit(())).completed
    with pytest.raises(ValueError):
        PhysicalCircuit((circuit.gates[0], circuit.gates[0]))


def test_failure_artifact(tmp_path, test_context):
    from neutral_atom_env.domain.errors import ValidationError
    from neutral_atom_env.testing.renderer import render_layout
    state = test_context['state']
    holders = dict(state.placement.atom_to_holder)
    holders['Q001'] = holders['Q000']
    with pytest.raises(ValidationError) as result:
        replace(state, placement=PlacementState(holders))
    violation = result.value.violation
    render_layout(state.snapshot(), tmp_path / 'failure.svg', violation=violation)
    assert violation.code == 'DUPLICATE_HOLDER'
    assert violation.atom_ids == ('Q000', 'Q001')
    assert 'DUPLICATE_HOLDER' in (tmp_path / 'failure.svg').read_text(encoding='utf-8')


def test_missing_holder_and_disabled_trap(test_context):
    state = test_context["state"]
    mapping = dict(state.placement.atom_to_holder)
    del mapping["Q000"]
    with pytest.raises(ValueError):
        replace(state, placement=PlacementState(mapping))
    traps = dict(state.world.traps)
    traps["s0"] = replace(traps["s0"], enabled=False)
    with pytest.raises(ValueError):
        replace(state, world=replace(state.world, traps=traps))


def test_lost_atom(test_context):
    state = test_context["state"]
    atoms = dict(state.atoms)
    atoms["Q003"] = replace(atoms["Q003"], alive=False)
    holders = dict(state.placement.atom_to_holder)
    holders["Q003"] = HolderRef(HolderType.LOST, None)
    state = replace(state, atoms=atoms, placement=PlacementState(holders))
    test_context.update(state=state, initial=state.snapshot())
    assert state.placement.position("Q003", state.world, state.aod) is None


def test_dictionary_order_independent(test_context):
    state = test_context["state"]
    other = replace(state, atoms=dict(reversed(list(state.atoms.items()))),
        placement=PlacementState(dict(reversed(list(state.placement.atom_to_holder.items())))))
    assert other.snapshot() == state.snapshot()


@pytest.mark.parametrize('activity', ['idle', 'moving', 'gating', 'measuring'])
def test_activity_colors(activity, test_context):
    from neutral_atom_env.testing.scene import atom_activity, activity_color, gate_label
    state = test_context['state']
    holders = dict(state.placement.atom_to_holder)
    holders['Q000'] = HolderRef(HolderType.MOBILE, MobileCellIndex(1, 1))
    state = replace(state, placement=PlacementState(holders),
                    aod=replace(state.aod, is_moving=activity == 'moving'))
    if activity in {'gating', 'measuring'}:
        # Prepared initial placement, not a simulated transport event.
        holders = dict(state.placement.atom_to_holder)
        holders['Q000'] = HolderRef(HolderType.STATIC, 's0')
        traps = dict(state.world.traps)
        for key in (('s0',) if activity == 'measuring' else ('s0', 's1')):
            traps[key] = replace(traps[key], position=Position2D(traps[key].position.x_um, -40 if activity == 'measuring' else -20))
        gate = PhysicalGate('g1', 'MEASURE' if activity == 'measuring' else 'CZ',
                            ('Q000',) if activity == 'measuring' else ('Q000', 'Q001'))
        state = replace(state, world=replace(state.world, traps=traps), placement=PlacementState(holders),
                        dag=DynamicGateDAG(PhysicalCircuit((gate,))))
    test_context.update(state=state, initial=state.snapshot())
    if activity in {'gating', 'measuring'}:
        ex = Executor(state)
        for kind in (EventType.GATE_RESERVED, EventType.GATE_STARTED):
            ex.schedule(SimulationEvent(0, kind, 'g1'))
            ex.step()
        test_context['active'] = state.snapshot()
    data = json.loads(state.snapshot())
    assert atom_activity(data, 'Q000') == activity
    assert atom_activity(data, 'Q002') == 'idle'
    theme = {'static_color': 'blue', 'moving_color': 'orange', 'active_color': 'red'}
    assert activity_color(activity, theme) == {'idle':'blue', 'moving':'orange', 'gating':'red', 'measuring':'red'}[activity]
    assert 'Q000' in gate_label(data['dag']['g1'])
    if activity in {'gating', 'measuring'}:
        ex.schedule(SimulationEvent(1, EventType.GATE_COMPLETED, 'g1'))
        ex.step()
        assert atom_activity(json.loads(state.snapshot()), 'Q000') == 'idle'
        assert state.dag.completed
        assert state.atoms['Q000'].measured == (activity == 'measuring')
        initial = json.loads(test_context['initial'])
        final = json.loads(state.snapshot())
        assert initial['placement'] == data['placement'] == final['placement']
        assert initial['world'] == data['world'] == final['world']
        assert initial['aod'] == data['aod'] == final['aod']


@pytest.mark.parametrize('gate_type', ['MEASURE', 'CZ'])
def test_wrong_zone_rejected(gate_type, test_context):
    state = test_context['state']
    gate = PhysicalGate('g1', gate_type, ('Q000',) if gate_type == 'MEASURE' else ('Q000', 'Q001'))
    state = replace(state, dag=DynamicGateDAG(PhysicalCircuit((gate,))))
    test_context.update(state=state, initial=state.snapshot())
    ex = Executor(state)
    ex.schedule(SimulationEvent(0, EventType.GATE_RESERVED, 'g1'))
    ex.step()
    ex.schedule(SimulationEvent(1, EventType.GATE_STARTED, 'g1'))
    before, trace = state.snapshot(), state.trace.records
    with pytest.raises(ValueError, match='must be in'):
        ex.step()
    assert state.snapshot() == before
    assert state.trace.records == trace
    assert not state.atoms['Q000'].measured
