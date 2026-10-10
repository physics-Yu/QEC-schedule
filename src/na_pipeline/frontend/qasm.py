"""Export-only OpenQASM 3.0 source subset, not a general QASM parser."""

from .program import FrontendError, iter_logical_ops, validate_logical


def to_openqasm3(program: dict) -> str:
    """Export complete source including unsynthesized P angles and bit conditions.

    Source export is allowed before Clifford+T synthesis. This output is not
    evidence of an executable physical program or a result-producing backend.
    """
    errors = validate_logical(program)
    if errors:
        raise FrontendError(f"INVALID_PROGRAM: {errors}")
    qubits = {q["id"]: f"q[{i}]" for i, q in enumerate(program["qubits"])}
    bits = {b["id"]: f"phase[{i}]" for i, b in enumerate(program["classical_bits"])}
    lines = ["OPENQASM 3.0;", 'include "stdgates.inc";',
             "// Logical source; inspect synthesis status before physical lowering.",
             "// q[0]=ctrl, q[1..4]=work w0..w3 (w0 LSB).",
             "// phase[0..7] is MSB first; measured in reverse order.",
             f"qubit[{len(qubits)}] q;", f"bit[{len(bits)}] phase;"]
    for op in iter_logical_ops(program):
        lines.append("// source_op: " + op["id"])
        if "branch_global_phase_pi" in op:
            phase = op["branch_global_phase_pi"]
            scalar_statement = f"gphase({phase['numerator']}*pi/{phase['denominator']});"
            if op["condition"] is not None:
                condition = op["condition"]
                scalar_statement = f"if ({bits[condition['bit']]} == {condition['equals']}) {{ {scalar_statement} }}"
            lines.append(scalar_statement)
        targets = ", ".join(qubits[q] for q in op["qubits"])
        if op["kind"] == "gate":
            name = op["params"]["name"].lower()
            if name == "p":
                angle = op["params"]["angle_pi"]
                name += f"({angle['numerator']}*pi/{angle['denominator']})"
            statement = f"{name} {targets};"
        elif op["kind"] == "reset":
            statement = f"reset {targets};"
        elif op["kind"] == "measure":
            statement = f"{bits[op['writes'][0]]} = measure {targets};"
        else:
            raise FrontendError(f"UNSUPPORTED_QASM_OPERATION: {op['id']}")
        if op["condition"] is not None:
            condition = op["condition"]
            statement = f"if ({bits[condition['bit']]} == {condition['equals']}) {{ {statement} }}"
        lines.append(statement)
    return "\n".join(lines) + "\n"
