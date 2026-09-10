"""Explicit M0 test harness. No hardware execution or physical success claims."""
from dataclasses import replace
from neutral_atom_env.simulation.executor import Executor
from neutral_atom_env.domain.models import EventType, ZoneType
from neutral_atom_env.hardware.measurement import MeasurementDevice, validate_atoms_in_zone
from neutral_atom_env.domain.errors import ValidationError


class LogicalTestExecutor(Executor):
    def _check_logical_event(self):
        pass

    def submit(self, plan):
        raise ValidationError('LOGICAL_TEST_ONLY', 'Use the physical Executor for compiled plans')

    def _logical_transition(self, state, event, target):
        dag, atoms = state.dag, state.atoms
        gate = dag.nodes[event.gate_id].gate
        if event.event_type in {EventType.GATE_STARTED, EventType.GATE_COMPLETED}:
            if gate.gate_type == 'MEASURE':
                MeasurementDevice().validate(state, gate)
            elif gate.is_two_qubit:
                validate_atoms_in_zone(state, gate, ZoneType.ENTANGLEMENT)
        dag = dag.transitioned(event.gate_id, target)
        if event.event_type == EventType.GATE_COMPLETED and gate.gate_type == 'MEASURE':
            atoms = {key: replace(atom, measured=True) if atom.id in gate.qubit_ids else atom
                     for key, atom in atoms.items()}
        return dag, atoms
