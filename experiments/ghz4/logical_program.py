"""Logical GHZ program and its hardware-independent physical lowering.

This module is intentionally an experiment compiler, not a second scheduler.
It emits the existing ``PhysicalCircuit`` IR; ``GateLowerer`` then turns that
IR into semantic requests and ``RuntimeScheduler`` owns placement and timing.
"""
from qec_schedule.compiler import GateType, PhysicalCircuit, PhysicalGate
from qec_schedule.logical import LogicalInstruction, LogicalOp, LogicalProgram
from qec_schedule.qec import PauliProduct, QECCode, RotatedSurfaceCode


class FourLogicalSurfaceCode(QECCode):
    """A composite of four independent rotated [[9,1,3]] surface codes."""

    def __init__(self, block_ids=("L0", "L1", "L2", "L3"), distance=3):
        self.block_ids = tuple(block_ids)
        if self.block_ids != ("L0", "L1", "L2", "L3"):
            raise ValueError("GHZ4 uses logical block IDs L0, L1, L2, L3")
        self.distance = distance
        self.blocks = tuple(RotatedSurfaceCode(distance, block_id=block_id)
                            for block_id in self.block_ids)
        self._by_id = {block.block_id: block for block in self.blocks}
        self.validate()

    @property
    def name(self):
        return "four_logical_rotated_surface_d3"

    def data_qubits(self):
        return tuple(qubit for block in self.blocks for qubit in block.data_qubits())

    def ancilla_qubits(self):
        return tuple(qubit for block in self.blocks for qubit in block.ancilla_qubits())

    def stabilizers(self):
        return tuple(check for block in self.blocks for check in block.stabilizers())

    def logical_x(self):
        return tuple(operator for block in self.blocks for operator in block.logical_x())

    def logical_z(self):
        return tuple(operator for block in self.blocks for operator in block.logical_z())

    def block_data(self, block_id):
        return self._by_id[block_id].data_qubits()

    def block_ancilla(self, block_id):
        return self._by_id[block_id].ancilla_qubits()

    def block_qubits(self, block_id):
        return self.block_data(block_id) + self.block_ancilla(block_id)

    def block(self, block_id):
        return self._by_id[block_id]

    def syndrome_round(self, *, rounds=1, primitive="CZ"):
        """Expose the normal QECCode interface for a composite code."""
        if type(rounds) is not int or rounds < 1:
            raise ValueError("rounds must be a positive integer")
        if primitive not in ("CZ", "CNOT"):
            raise ValueError("primitive must be CZ or CNOT")
        builder = _CircuitBuilder(self)
        terminals = ()
        for round_index in range(rounds):
            terminals = builder.emit_qec_round(round_index, primitive=primitive,
                                              dependencies=terminals)
        return PhysicalCircuit(builder.qubits, tuple(builder.gates))


def build_logical_program(*, measurement_basis="Z", qec_rounds_after_prepare=1,
                          qec_rounds_between_layers=1, qec_rounds_before_measure=1):
    """Build the logical DAG; the second CNOT layer is parallel by dependency."""
    if measurement_basis not in ("X", "Z"):
        raise ValueError("measurement_basis must be X or Z")
    for value in (qec_rounds_after_prepare, qec_rounds_between_layers,
                  qec_rounds_before_measure):
        if type(value) is not int or value < 1:
            raise ValueError("QEC round counts must be positive integers")

    logical_qubits = ("L0", "L1", "L2", "L3")
    instructions = (
        LogicalInstruction("prepare_plus_L0", LogicalOp.PREPARE_PLUS, ("L0",),
                           metadata={"state": "+"}),
        LogicalInstruction("prepare_zero_L1", LogicalOp.PREPARE_0, ("L1",),
                           metadata={"state": "0"}),
        LogicalInstruction("prepare_zero_L2", LogicalOp.PREPARE_0, ("L2",),
                           metadata={"state": "0"}),
        LogicalInstruction("prepare_zero_L3", LogicalOp.PREPARE_0, ("L3",),
                           metadata={"state": "0"}),
        LogicalInstruction("initial_ec", LogicalOp.QEC_BARRIER, logical_qubits,
                           dependencies=("prepare_plus_L0", "prepare_zero_L1",
                                         "prepare_zero_L2", "prepare_zero_L3"),
                           rounds=qec_rounds_after_prepare,
                           metadata={"phase": "initial_stabilization"}),
        LogicalInstruction("cnot_L0_L1", LogicalOp.CNOT, ("L0", "L1"),
                           dependencies=("initial_ec",),
                           metadata={"logical_operation_id": "GHZ_CNOT_L0_L1",
                                     "layer": 1}),
        LogicalInstruction("ec_after_layer_1", LogicalOp.QEC_BARRIER, logical_qubits,
                           dependencies=("cnot_L0_L1",),
                           rounds=qec_rounds_between_layers,
                           metadata={"phase": "between_entangling_layers"}),
        LogicalInstruction("cnot_L0_L2", LogicalOp.CNOT, ("L0", "L2"),
                           dependencies=("ec_after_layer_1",),
                           metadata={"logical_operation_id": "GHZ_CNOT_L0_L2",
                                     "layer": 2}),
        LogicalInstruction("cnot_L1_L3", LogicalOp.CNOT, ("L1", "L3"),
                           dependencies=("ec_after_layer_1",),
                           metadata={"logical_operation_id": "GHZ_CNOT_L1_L3",
                                     "layer": 2}),
        LogicalInstruction("final_ec", LogicalOp.QEC_BARRIER, logical_qubits,
                           dependencies=("cnot_L0_L2", "cnot_L1_L3"),
                           rounds=qec_rounds_before_measure,
                           metadata={"phase": "final_stabilization"}),
        LogicalInstruction("measure_logical", LogicalOp.MEASURE_LOGICAL, logical_qubits,
                           dependencies=("final_ec",),
                           metadata={"basis": measurement_basis,
                                     "scope": "logical_final"}),
    )
    return LogicalProgram(logical_qubits, instructions)


class _CircuitBuilder:
    def __init__(self, code: FourLogicalSurfaceCode):
        self.code = code
        self.qubits = code.data_qubits() + code.ancilla_qubits()
        self.gates = []
        self.last = {}
        self.serial = 0

    def emit(self, gate_type, qubits, *, stage, metadata=None, dependencies=()):
        qubits = tuple(qubits)
        predecessors = set(dependencies)
        predecessors.update(self.last[qubit] for qubit in qubits if qubit in self.last)
        gate_id = f"{stage}:{self.serial:06d}"
        self.serial += 1
        order = {gate.id: index for index, gate in enumerate(self.gates)}
        predecessors = tuple(sorted(predecessors, key=order.__getitem__))
        gate = PhysicalGate(gate_id, GateType(gate_type), qubits, predecessors,
                            metadata or {})
        self.gates.append(gate)
        for qubit in qubits:
            self.last[qubit] = gate_id
        return gate_id

    def terminals(self):
        return tuple(self.last[qubit] for qubit in self.qubits if qubit in self.last)

    def emit_data_preparation(self):
        terminals = []
        for block_id in self.code.block_ids:
            for qubit in self.code.block_data(block_id):
                terminals.append(self.emit(
                    "PREPARE", (qubit,), stage="PREPARE_DATA",
                    metadata={"state": "0", "logical_operation_id": f"PREPARE_{block_id}"}))
        # Simplified logical |+> preparation: apply H on one logical-X
        # representative string.  The experiment intentionally avoids a full
        # logical-H implementation, as specified by the GHZ design.
        for qubit in self.code.block(self.code.block_ids[0]).logical_x()[0].support:
            terminals.append(self.emit(
                "H", (qubit,), stage="PREPARE_PLUS",
                metadata={"gate": "H", "logical_operation_id": "PREPARE_PLUS_L0",
                          "logical_qubit": "L0"}))
        return tuple(terminals)

    def emit_qec_round(self, round_index, *, primitive="CZ", dependencies=()):
        """Emit one four-block syndrome round with common slot metadata."""
        round_id = f"QEC_R{round_index}"
        for block_id in self.code.block_ids:
            for check in self.code.block(block_id).stabilizers():
                self.emit(
                    "PREPARE", (check.ancilla,), stage=f"{round_id}_PREPARE",
                    dependencies=dependencies,
                    metadata={"state": "0", "round": round_index,
                              "logical_operation_id": round_id,
                              "block_id": block_id, "ancilla": check.ancilla})

        for slot in range(4):
            group = f"{round_id}_S{slot}"
            for block_id in self.code.block_ids:
                for check in self.code.block(block_id).stabilizers():
                    for check_slot, data in check.interactions:
                        if check_slot != slot:
                            continue
                        if primitive == "CNOT":
                            control, target = ((check.ancilla, data)
                                               if check.basis == "X" else (data, check.ancilla))
                            kind = "CNOT"
                        else:
                            control, target = check.ancilla, data
                            kind = "CZ"
                        self.emit(
                            kind, (control, target), stage=group,
                            metadata={"round": round_index, "slot": slot,
                                      "stabilizer": check.id, "block_id": block_id,
                                      "logical_operation_id": round_id,
                                      "interaction_group_id": group,
                                      "data_qubit": data, "control": control,
                                      "target": target})

        for block_id in self.code.block_ids:
            for check in self.code.block(block_id).stabilizers():
                basis = check.basis
                self.emit(
                    f"MEASURE_{basis}", (check.ancilla,), stage=f"{round_id}_MEASURE",
                    metadata={"round": round_index, "block_id": block_id,
                              "logical_operation_id": round_id,
                              "measurement_scope": "syndrome",
                              "measurement_key": f"qec:r{round_index}:{check.id}"})
                self.emit(
                    "RESET", (check.ancilla,), stage=f"{round_id}_RESET",
                    metadata={"round": round_index, "block_id": block_id,
                              "logical_operation_id": round_id, "state": "0"})
        return self.terminals()

    def emit_transversal_cnot(self, control_id, target_id, *, layer, dependencies=()):
        operation_id = f"GHZ_CNOT_{control_id}_{target_id}"
        control_data = self.code.block_data(control_id)
        target_data = self.code.block_data(target_id)
        common = {"logical_operation_id": operation_id, "layer": layer,
                  "control_logical": control_id, "target_logical": target_id}
        for index, target in enumerate(target_data):
            self.emit("H", (target,), stage=f"{operation_id}_H_BEFORE",
                      dependencies=dependencies,
                      metadata={**common, "phase": "before_cz", "transversal_index": index})
        for index, (control, target) in enumerate(zip(control_data, target_data)):
            self.emit("CZ", (control, target), stage=f"{operation_id}_CZ",
                      dependencies=dependencies,
                      metadata={**common, "interaction_group_id": operation_id,
                                "transversal_index": index})
        for index, target in enumerate(target_data):
            self.emit("H", (target,), stage=f"{operation_id}_H_AFTER",
                      metadata={**common, "phase": "after_cz", "transversal_index": index})
        return self.terminals()

    def emit_logical_measurement(self, basis, *, dependencies=()):
        kind = f"MEASURE_{basis}"
        terminals = []
        for block_id in self.code.block_ids:
            for index, qubit in enumerate(self.code.block_data(block_id)):
                terminals.append(self.emit(
                    kind, (qubit,), stage=f"FINAL_MEASURE_{basis}",
                    dependencies=dependencies,
                    metadata={"logical_operation_id": "GHZ_LOGICAL_MEASURE",
                              "measurement_scope": "logical_final",
                              "logical_qubit": block_id, "basis": basis,
                              "measurement_key": f"logical:{basis}:{block_id}:d{index}"}))
        return tuple(terminals)


def build_physical_circuit(program=None, *, code=None, measurement_basis="Z",
                           primitive="CZ"):
    """Lower the GHZ logical DAG to a hardware-independent physical DAG."""
    code = FourLogicalSurfaceCode() if code is None else code
    if not isinstance(code, FourLogicalSurfaceCode):
        raise TypeError("GHZ4 physical lowering requires FourLogicalSurfaceCode")
    program = (build_logical_program(measurement_basis=measurement_basis)
               if program is None else program)
    if measurement_basis not in ("X", "Z"):
        raise ValueError("measurement_basis must be X or Z")
    if primitive not in ("CZ", "CNOT"):
        raise ValueError("primitive must be CZ or CNOT")

    instructions = {instruction.id: instruction for instruction in program.instructions}
    builder = _CircuitBuilder(code)
    preparation = builder.emit_data_preparation()

    qec_index = 0
    initial = instructions["initial_ec"]
    after_initial = preparation
    for _ in range(initial.rounds):
        after_initial = builder.emit_qec_round(qec_index, primitive=primitive,
                                               dependencies=after_initial)
        qec_index += 1

    cnot01 = builder.emit_transversal_cnot("L0", "L1", layer=1,
                                          dependencies=after_initial)

    between = instructions["ec_after_layer_1"]
    after_between = cnot01
    for _ in range(between.rounds):
        after_between = builder.emit_qec_round(qec_index, primitive=primitive,
                                               dependencies=after_between)
        qec_index += 1

    cnot02 = builder.emit_transversal_cnot("L0", "L2", layer=2,
                                          dependencies=after_between)
    cnot13 = builder.emit_transversal_cnot("L1", "L3", layer=2,
                                          dependencies=after_between)

    final = instructions["final_ec"]
    after_final = tuple(dict.fromkeys(cnot02 + cnot13))
    for _ in range(final.rounds):
        after_final = builder.emit_qec_round(qec_index, primitive=primitive,
                                             dependencies=after_final)
        qec_index += 1

    measure = instructions["measure_logical"]
    builder.emit_logical_measurement(measure.metadata["basis"], dependencies=after_final)
    return PhysicalCircuit(builder.qubits, tuple(builder.gates))


__all__ = ["FourLogicalSurfaceCode", "build_logical_program", "build_physical_circuit"]
