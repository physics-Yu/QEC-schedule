"""Native parity gadgets with semantic result/provenance sidecars.

No coordinates, pulses, duration estimates or hardware constraints are invented
here. The existing neutral-atom environment owns those decisions and checks.
"""
from dataclasses import dataclass
from typing import Mapping

from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate

from .ir import GateTask, PauliMeasurement, PBCProgram


@dataclass(frozen=True)
class MeasurementBinding:
    result_id: str
    raw_gate_id: str
    bit_flip: int
    purpose: str


@dataclass(frozen=True)
class CompiledPBC:
    program: PBCProgram
    circuit: PhysicalCircuit
    bindings: tuple[tuple[str, str], ...]
    measurements: tuple[MeasurementBinding, ...]
    provenance: tuple[tuple[str, str, str], ...]
    exits: tuple[tuple[str, tuple[str, ...]], ...]

    def semantic_results(self, raw_measurements: Mapping[str, int]):
        result = {}
        for item in self.measurements:
            bit = raw_measurements[item.raw_gate_id]
            if type(bit) is not int or bit not in (0, 1):
                raise ValueError('Raw measurement must be an integer bit')
            result[item.result_id] = bit ^ item.bit_flip
        return result

    def classical_outputs(self, raw_measurements):
        bits = self.semantic_results(raw_measurements)
        return {'detectors': {d.id: d.expression.evaluate(bits) for d in self.program.detectors},
                'observables': {o.id: o.expression.evaluate(bits) for o in self.program.observables}}

    def to_dict(self):
        from dataclasses import asdict
        return {'schema': 'qec-pbc-compiled/1', 'program': self.program.to_dict(),
                'bindings': dict(self.bindings),
                'gates': [asdict(g) for g in self.circuit.gates],
                'measurements': [asdict(m) for m in self.measurements],
                'provenance': [{'gate_id': g, 'operation_id': op, 'phase': phase}
                               for g, op, phase in self.provenance],
                'operation_exits': dict(self.exits),
                'claim': 'ideal instrument; no circuit-noise fault-tolerance claim'}


def lower_to_physical(program: PBCProgram, bindings: Mapping[str, str] | None = None,
                      *, require_fault_tolerant: bool = False):
    """Compile signed X/Z Pauli measurements, preserving all explicit edges.

All current parity gadgets use a bare ancilla. Requiring fault tolerance fails
closed; accepting a functional prototype never silently changes that promise.
Y products stay valid IR but are rejected until native S/Sdg support exists.
"""
    if not isinstance(program, PBCProgram):
        raise TypeError('lower_to_physical requires PBCProgram; LogicalPauliProgram and '
                        'MagicInjection have no implemented physical lowering')
    if require_fault_tolerant:
        raise ValueError('No validated fault-tolerant Pauli-measurement backend is installed')
    ids = tuple(r.id for r in program.roles)
    mapping = dict(bindings) if bindings is not None else {
        role: f'Q{i:03d}' for i, role in enumerate(ids)}
    if (set(mapping) != set(ids) or len(set(mapping.values())) != len(ids) or
            any(not isinstance(q, str) or not q for q in mapping.values())):
        raise ValueError('Bindings must cover exactly all roles with distinct physical IDs')
    for op in program.operations:
        if isinstance(op, PauliMeasurement) and any(p == 'Y' for _, p in op.product.factors):
            raise ValueError(f'{op.id}: Y measurement requires an explicit S/Sdg-capable backend')
    gates, records, provenance = [], [], []
    exits, record_map = {}, {}
    last_wire, last_operation = {}, {}

    for op in program.operations:
        op_targets = op.targets if isinstance(op, GateTask) else (*op.product.support, op.ancilla)
        # Native wire edges alone would allow two overlapping parity gadgets to
        # interleave before either ancilla has been read out. Preserve the whole
        # IR instrument's lifetime on every supported role, not just last CZ use.
        parents = tuple(dict.fromkeys((*op.depends_on, *(last_operation[r] for r in
            op_targets if r in last_operation))))
        frontier = tuple(dict.fromkeys(g for parent in parents for g in exits[parent]))
        counter = 0

        def emit(kind, roles, phase, condition=(), *, measurement_id=None):
            nonlocal counter, frontier
            physical_ids = tuple(mapping[r] for r in roles)
            gid = measurement_id or f'{op.id}__g{counter:03d}'
            counter += 1
            dependencies = tuple(dict.fromkeys((*frontier, *(last_wire[q] for q in
                physical_ids if q in last_wire))))
            native_condition = tuple((record_map[key].raw_gate_id,
                                     bit ^ record_map[key].bit_flip) for key, bit in condition)
            gates.append(PhysicalGate(gid, kind, physical_ids,
                                      condition=native_condition, depends_on=dependencies))
            provenance.append((gid, op.id, phase))
            for q in physical_ids:
                last_wire[q] = gid
            frontier = (gid,)
            return gid

        if isinstance(op, GateTask):
            gid = emit(op.gate_type, op.targets, 'primitive', op.condition)
            if op.gate_type == 'MEASURE':
                item = MeasurementBinding(op.id, gid, 0, 'terminal_readout')
                records.append(item)
                record_map[op.id] = item
        else:
            emit('RESET', (op.ancilla,), 'ancilla_prepare')
            emit('H', (op.ancilla,), 'ancilla_prepare')
            basis = dict(op.product.factors)
            for role in op.coupling_order:
                if basis[role] == 'X':
                    emit('H', (role,), 'basis_change')
                emit('CZ', (op.ancilla, role), 'controlled_pauli')
                if basis[role] == 'X':
                    emit('H', (role,), 'basis_restore')
            emit('H', (op.ancilla,), 'ancilla_readout')
            gid = emit('MEASURE', (op.ancilla,), 'ancilla_readout')
            item = MeasurementBinding(op.id, gid, int(op.product.sign == -1), op.purpose)
            records.append(item)
            record_map[op.id] = item
            emit('RESET', (op.ancilla,), 'ancilla_release')
        exits[op.id] = frontier
        for role in op_targets:
            last_operation[role] = op.id
    return CompiledPBC(program, PhysicalCircuit(tuple(gates)), tuple(mapping.items()),
                       tuple(records), tuple(provenance), tuple(exits.items()))
