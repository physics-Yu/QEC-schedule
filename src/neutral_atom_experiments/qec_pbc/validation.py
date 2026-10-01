"""Ideal semantic validation only; deliberately separate from physical execution.

This helper has no placement, duration, noise, decoder latency or fidelity model.
Production timing must use NeutralAtomEnv and its ordinary validated executor.
"""
from random import Random

from neutral_atom_env.quantum.stabilizer import StabilizerState


def simulate_ideal(compiled, *, seed=0, fault_before=None):
    """Return (ideal stabilizer state, native readout bits).

    ``fault_before=(operation_id, role_id, X/Y/Z)`` is a declared validation
    insertion, never an observed syndrome or information given to a decoder.
    """
    bindings = dict(compiled.bindings)
    state = StabilizerState.zero(tuple(bindings.values()))
    rng, raw = Random(seed), {}
    provenance = {g: op for g, op, _ in compiled.provenance}
    if fault_before is not None:
        operation, role, kind = fault_before
        if operation not in {op.id for op in compiled.program.operations} or role not in bindings or kind not in {'X', 'Y', 'Z'}:
            raise ValueError('Unknown fault operation/role or non-Pauli fault')
    inserted = False
    for gate in compiled.circuit.gates:
        if fault_before is not None and not inserted and provenance[gate.id] == operation:
            state = state.apply_gate(kind, (bindings[role],))
            inserted = True
        if gate.condition and not all(raw[key] == bit for key, bit in gate.condition):
            continue
        if gate.gate_type == 'MEASURE':
            state, raw[gate.id] = state.measure_z(gate.qubit_ids[0], rng.getrandbits(1))
        elif gate.gate_type == 'RESET':
            state, _ = state.reset_zero(gate.qubit_ids[0], rng.getrandbits(1))
        else:
            state = state.apply_gate(gate.gate_type, gate.qubit_ids)
    return state, raw


def bell_parity_program():
    """Prepare two patches and a Bell state through logical PBC ZZ measurement.

    Functional measurement-only entanglement baseline, using 34 patch roles and
    one bare bus ancilla. This is deliberately an ideal non-FT logical gadget.
    """
    from .ir import GateTask, Observable, BitExpr, PBCProgram, Role
    from .pauli import PauliProduct
    from .surface import memory_program, logical_measurement
    roles, ops = [], []
    previous = ()
    for patch in ('A', 'B'):
        source = memory_program(basis='X', rounds=1, patch=patch)
        roles.extend(source.roles)
        # Keep preparation and one storage round, before destructive readout.
        body = [op for op in source.operations if not op.id.startswith(f'{patch}.final.')]
        from dataclasses import replace
        body[0] = replace(body[0], depends_on=previous)
        ops.extend(body)
        previous = (body[-1].id,)
    roles.append(Role('bus', 'parity_ancilla'))
    zz = logical_measurement(PauliProduct((('A', 'Z'), ('B', 'Z'))),
                             result_id='bell.ZZ', depends_on=previous)
    ops.append(zz)
    previous = (zz.id,)
    for local in (0, 3, 6):
        key = f'bell.correct.{local}'
        ops.append(GateTask(key, 'X', (f'B.d{local}',), previous, ((zz.id, 1),)))
        previous = (key,)
    xx = logical_measurement(PauliProduct((('A', 'X'), ('B', 'X'))),
                             result_id='bell.XX', depends_on=previous)
    ops.append(xx)
    return PBCProgram(tuple(roles), tuple(ops), observables=(
        Observable('bell.XX', BitExpr(('bell.XX',)), 'ideal Bell check after measured ZZ correction'),),
        name='d3-logical-pbc-bell-ideal-non-ft')
