"""Reuse is persistent SLM residency, not a new atom or an implicit transfer."""
from neutral_atom_env.domain.models import GateStatus


def future_partners(state, excluded=()):
    excluded = set(excluded)
    partners = {}
    for gate in state.dag.circuit.gates:
        if gate.gate_type != 'CZ' or gate.id in excluded or state.dag.nodes[gate.id].status == GateStatus.COMPLETED:
            continue
        a, b = gate.qubit_ids
        partners.setdefault(a, b)
        partners.setdefault(b, a)
    return partners
