"""CSS parity extraction with explicit ancilla lifecycle and gate dependencies."""
from ..compiler.physical_gate_ir import GateType, PhysicalCircuit, PhysicalGate
from .code import CSSCode


def generate_syndrome_circuit(code: CSSCode, *, rounds: int = 1, primitive: str = "CZ") -> PhysicalCircuit:
    if not isinstance(code, CSSCode):
        raise TypeError("Generic CSS extraction needs CSSCode; other codes implement syndrome_round")
    if type(rounds) is not int or rounds < 1:
        raise ValueError("rounds must be a positive integer")
    if primitive not in ("CZ", "CNOT"):
        raise ValueError("primitive must be CZ or CNOT")
    code.validate()
    checks = code.stabilizers()
    gates: list[PhysicalGate] = []
    last: dict[str, str] = {}
    previous_resets: tuple[str, ...] = ()

    def emit(kind, qubits, metadata, extra=()):
        gate_id = f"{checks[0].id if checks else code.name}:g{len(gates):06d}"
        predecessors = tuple(sorted(set(extra) | {last[q] for q in qubits if q in last}))
        gates.append(PhysicalGate(gate_id, GateType(kind), tuple(qubits), predecessors, metadata))
        last.update((q, gate_id) for q in qubits)
        return gate_id

    for round_index in range(rounds):
        def meta(check, **extra):
            return {"round": round_index, "stabilizer": check.id,
                    "ancilla": check.ancilla, "basis": check.basis, **extra}

        for check in checks:
            emit("PREPARE", (check.ancilla,), meta(check, state="0"), previous_resets)
            if check.basis == "X":
                emit("H", (check.ancilla,), meta(check, phase="prepare_plus"))

        interactions = sorted((slot, i, q) for i, check in enumerate(checks) for slot, q in check.interactions)
        for slot, check_index, data in interactions:
            check = checks[check_index]
            control, target = (check.ancilla, data) if check.basis == "X" else (data, check.ancilla)
            metadata = meta(check, slot=slot, data_qubit=data, control=control, target=target)
            if primitive == "CNOT":
                emit("CNOT", (control, target), metadata)
            else:
                # CX(c,t) = H(t) CZ(c,t) H(t); keep all basis changes explicit.
                emit("H", (target,), {**metadata, "phase": "before_cz"})
                emit("CZ", (control, target), metadata)
                emit("H", (target,), {**metadata, "phase": "after_cz"})

        resets = []
        for check in checks:
            if check.basis == "X":
                emit("H", (check.ancilla,), meta(check, phase="measure_x"))
            emit("MEASURE_Z", (check.ancilla,), meta(check, measurement_key=f"r{round_index}:{check.id}"))
            resets.append(emit("RESET", (check.ancilla,), meta(check, state="0")))
        previous_resets = tuple(resets)

    return PhysicalCircuit(code.data_qubits() + code.ancilla_qubits(), tuple(gates))
