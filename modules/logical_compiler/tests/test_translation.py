"""Independent semantic checks for logical source translation."""

import numpy as np
import pytest
from qiskit import QuantumCircuit, qasm3
from qiskit.quantum_info import Operator, Statevector

from modules.logical_compiler import TranslationError, loads_qasm


def source(body: str, n: int = 3) -> str:
    return f'OPENQASM 3.0; include "stdgates.inc"; qubit[{n}] q; bit[2] c; {body}'


def circuit(result, values=None):
    qc = QuantumCircuit(result.num_qubits)
    for op in result.operations:
        if op.guard and not op.guard.evaluate(values or {}):
            continue
        if op.name == "global_phase":
            qc.global_phase += op.params[0]
        elif op.name == "initialize_plus":
            qc.h(op.qubits[0])
        elif op.name not in ("initialize_0", "measure", "barrier"):
            getattr(qc, op.name)(*op.params, *op.qubits)
    return qc


def test_explicit_code_is_required_before_parsing():
    with pytest.raises(TypeError):
        loads_qasm(source("h q[0];"))
    with pytest.raises(TranslationError, match="UNKNOWN_CODE"):
        loads_qasm("not QASM", code="missing")


@pytest.mark.parametrize("distance", [3, 5])
def test_code_entry_and_initialization(distance):
    result = loads_qasm(source("h q[0];", 2), code=f"rotated_surface_d{distance}")
    assert [(o.name, o.qubits) for o in result.operations] == [
        ("initialize_plus", (0,)),
        ("initialize_0", (1,)),
    ]
    assert result.code == f"rotated_surface_d{distance}"
    assert not result.execution_ready
    assert all(o.component is not None for o in result.operations)


def test_inverse_cancellation_across_independent_wires():
    result = loads_qasm(
        source("h q[0]; x q[1]; h q[0]; cx q[1],q[2]; cx q[1],q[2];"),
        code="rotated_surface_d3",
        input_state="external",
    )
    assert [(o.name, o.qubits) for o in result.operations] == [("x", (1,))]


def test_entanglement_is_an_optimization_boundary():
    result = loads_qasm(
        source("h q[0]; cx q[0],q[1]; h q[0];"),
        code="rotated_surface_d3",
        input_state="external",
    )
    assert [o.name for o in result.operations] == ["h", "cx", "h"]


@pytest.mark.parametrize(
    "body",
    [
        "s q[0]; sdg q[0];",
        "t q[0]; tdg q[0];",
        "x q[0]; x q[0];",
        "y q[0]; y q[0];",
        "z q[0]; z q[0];",
        "h q[0]; h q[0];",
    ],
)
def test_exact_identity_reductions(body):
    result = loads_qasm(
        source(body, 1), code="rotated_surface_d3", input_state="external"
    )
    assert not result.operations


@pytest.mark.parametrize(
    "body",
    [
        "h q[0]; cx q[0],q[1];",
        "ccx q[2],q[0],q[1];",
        "swap q[0],q[2];",
        "cz q[0],q[1];",
        "sx q[0];",
        "rz(pi/4) q[1];",
        "gate custom a,b { h a; cx a,b; } custom q[1],q[2];",
    ],
)
def test_exact_translation_matches_full_unitary(body):
    text = source(body)
    result = loads_qasm(text, code="rotated_surface_d3", input_state="external")
    np.testing.assert_allclose(
        Operator(circuit(result)).data,
        Operator(qasm3.loads(text)).data,
        atol=1e-12,
        rtol=0,
    )
    assert result.synthesis_error_bound == 0


@pytest.mark.parametrize(
    "body",
    [
        "rx(0.123) q[0]; ry(-0.234) q[1]; rz(0.731) q[2];",
        "U(0.3,-0.7,1.2) q[1]; cp(0.42) q[0],q[2];",
        "gate custom(t) a,b { crx(t) b,a; } custom(pi/7) q[0],q[2];",
    ],
)
def test_general_rotations_obey_circuit_error_budget(body):
    text = source(body)
    result = loads_qasm(
        text, code="rotated_surface_d3", input_state="external", error_budget=1e-5
    )
    actual = np.linalg.norm(
        Operator(circuit(result)).data - Operator(qasm3.loads(text)).data, 2
    )
    assert actual <= result.synthesis_error_bound + 1e-12
    assert 0 < result.synthesis_error_bound <= 1e-5
    assert all(o.name in result.target_operations for o in result.operations)


def test_initialization_optimization_preserves_bell_state():
    text = source("h q[0]; cx q[0],q[1]; h q[2]; h q[2];")
    result = loads_qasm(text, code="rotated_surface_d3")
    np.testing.assert_allclose(
        Statevector(circuit(result)).data,
        Statevector(qasm3.loads(text)).data,
        atol=1e-12,
        rtol=0,
    )
    assert sum(o.name == "h" for o in result.operations) == 0


def test_measurement_reset_and_plus_initialization():
    result = loads_qasm(
        source("c[0] = measure q[0]; reset q[0]; h q[0];"), code="rotated_surface_d3"
    )
    names = [o.name for o in result.operations if o.qubits == (0,)]
    assert names == ["initialize_0", "measure", "initialize_plus"]
    assert result.measurements


def test_conditions_preserve_measurement_occurrences_and_block_cancellation():
    result = loads_qasm(
        source(
            "c[0] = measure q[0]; if(c[0]) { h q[1]; } "
            "c[0] = measure q[2]; if(c[0]) { h q[1]; }"
        ),
        code="rotated_surface_d3",
        input_state="external",
    )
    gates = [o for o in result.operations if o.name == "h"]
    assert len(gates) == 2
    assert gates[0].guard.references != gates[1].guard.references
    producers = {
        o.result_id: i for i, o in enumerate(result.operations) if o.name == "measure"
    }
    for i, op in enumerate(result.operations):
        if op.guard:
            assert all((producers[r], i) in result.edges for r in op.guard.references)


def test_bounded_loop_expands_and_optimizes():
    text = source("for int i in [0:1] { h q[0]; } x q[1];")
    result = loads_qasm(text, code="rotated_surface_d3", input_state="external")
    assert [o.name for o in result.operations] == ["x"]


def test_qasm2_register_condition():
    text = (
        'OPENQASM 2.0; include "qelib1.inc"; qreg q[2]; creg c[2]; '
        "measure q -> c; if(c==2) x q[0];"
    )
    result = loads_qasm(text, code="rotated_surface_d3", input_state="external")
    gate = result.operations[-1]
    refs = sorted(gate.guard.references)
    assert gate.guard.evaluate({refs[0]: 0, refs[1]: 1})
    assert not gate.guard.evaluate({refs[0]: 1, refs[1]: 0})


@pytest.mark.parametrize(
    "body", ["while(c[0]) { x q[0]; }", "if(c[0]) { c[1] = measure q[0]; }"]
)
def test_unsupported_dynamic_semantics_are_explicit(body):
    with pytest.raises(TranslationError, match="UNSUPPORTED"):
        loads_qasm(source(body), code="rotated_surface_d3")


def test_invalid_precision_and_expansion_limit():
    with pytest.raises(TranslationError, match="ERROR_BUDGET"):
        loads_qasm(
            source("h q[0];"), code="rotated_surface_d3", error_budget=float("nan")
        )
    with pytest.raises(TranslationError, match="EXPANSION_LIMIT"):
        loads_qasm(
            source("for int i in [0:100] { x q[0]; }"),
            code="rotated_surface_d3",
            max_operations=10,
        )


def test_synthesis_is_deterministic():
    args = {
        "code": "rotated_surface_d3",
        "input_state": "external",
        "error_budget": 1e-5,
    }
    assert loads_qasm(source("rz(0.123) q[0];"), **args) == loads_qasm(
        source("rz(0.123) q[0];"), **args
    )


def test_inverse_rotations_cancel_before_approximation():
    result = loads_qasm(
        source("rx(0.123) q[0]; rx(-0.123) q[0];"),
        code="rotated_surface_d3",
        input_state="external",
    )
    assert not result.operations
    assert not result.synthesis


def test_barrier_blocks_h_cancellation():
    result = loads_qasm(
        source("h q[0]; barrier q[0]; h q[0];"),
        code="rotated_surface_d3",
        input_state="external",
    )
    assert [o.name for o in result.operations] == ["h", "barrier", "h"]


@pytest.mark.parametrize("first", [0, 1])
@pytest.mark.parametrize("second", [0, 1])
def test_nested_branches_and_approximation_preserve_each_branch(first, second):
    text = source(
        "c[0] = measure q[0]; c[1] = measure q[1]; "
        "if(c[0]) { if(c[1]) { U(0.3,0.4,0.5) q[2]; } else { s q[2]; } } "
        "else { h q[2]; }"
    )
    result = loads_qasm(
        text, code="rotated_surface_d3", input_state="external", error_budget=1e-5
    )
    expected = QuantumCircuit(3)
    if first:
        if second:
            expected.u(0.3, 0.4, 0.5, 2)
        else:
            expected.s(2)
    else:
        expected.h(2)
    values = dict(zip((m.result_id for m in result.measurements), (first, second)))
    actual = np.linalg.norm(
        Operator(circuit(result, values)).data - Operator(expected).data, 2
    )
    assert actual <= result.synthesis_error_bound + 1e-12


def test_parameterized_for_loop_preserves_angles():
    result = loads_qasm(
        source("for int i in [1:2] { rz(i*pi/4) q[0]; }"),
        code="rotated_surface_d3",
        input_state="external",
    )
    expected = QuantumCircuit(3)
    expected.rz(3 * np.pi / 4, 0)
    np.testing.assert_allclose(
        Operator(circuit(result)).data, Operator(expected).data, atol=1e-12
    )


def test_static_classical_guard_allows_initialization_folding():
    result = loads_qasm(
        source("if(!c[0]) { h q[0]; } else { x q[1]; }"), code="rotated_surface_d3"
    )
    assert [o.name for o in result.operations] == [
        "initialize_plus",
        "initialize_0",
        "initialize_0",
    ]


def test_bad_synthesis_is_rejected_independently(monkeypatch):
    from modules.logical_compiler.src.translation import synthesis

    monkeypatch.setattr(
        synthesis, "gridsynth_rz", lambda angle, epsilon: QuantumCircuit(1)
    )
    with pytest.raises(TranslationError, match="SYNTHESIS_PRECISION_NOT_MET"):
        loads_qasm(source("rz(0.123) q[0];"), code="rotated_surface_d3")


def test_precision_floor_is_explicit():
    with pytest.raises(TranslationError, match="PRECISION_UNSUPPORTED"):
        loads_qasm(
            source("rz(0.123) q[0];"), code="rotated_surface_d3", error_budget=1e-15
        )


def test_nonfinite_parameter_rejected_before_optimization():
    with pytest.raises(TranslationError, match="NONFINITE_PARAMETER"):
        loads_qasm(source("rx(1e309) q[0];"), code="rotated_surface_d3")


def test_component_references_and_json_are_code_specific():
    import json

    body = source("cx q[0],q[1]; t q[1]; c[0] = measure q[0];")
    a = loads_qasm(body, code="rotated_surface_d3", input_state="external")
    b = loads_qasm(body, code="rotated_surface_d5", input_state="external")
    assert a.operations[0].component == "rotated_surface_d3/trans_cnot"
    assert b.operations[0].component == "rotated_surface_d5/trans_cnot"
    assert a.operations[1].component.endswith("/t")
    assert not a.operations[1].component.endswith("/raw_t")
    document = json.loads(json.dumps(a.to_dict(), allow_nan=False))
    assert document["t_count"] == 1
    assert document["execution_ready"] is False


def test_source_file_loader_and_cli(tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path

    from modules.logical_compiler import load_qasm

    path = tmp_path / "input.qasm"
    path.write_text(source("h q[0]; cx q[0],q[1];"), encoding="utf-8")
    result = load_qasm(path, code="rotated_surface_d3")
    output = tmp_path / "result.json"
    command = [
        sys.executable,
        "-m",
        "modules.logical_compiler",
        str(path),
        "--code",
        "rotated_surface_d3",
        "-o",
        str(output),
    ]
    run = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(output.read_text()) == json.loads(run.stdout)
    assert json.loads(run.stdout)["source_sha256"] == result.source_sha256
    original = path.read_bytes()
    command[-1] = str(path)
    rejected = subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode == 2
    assert json.loads(rejected.stdout)["code"] == "OUTPUT_COLLISION"
    assert path.read_bytes() == original


@pytest.mark.parametrize("seed", range(5))
def test_mixed_circuits_against_independent_state_evolution(seed):
    rng = np.random.default_rng(seed)
    original = QuantumCircuit(3)
    for _ in range(18):
        a, b = rng.choice(3, 2, replace=False)
        choice = int(rng.integers(5))
        if choice == 0:
            original.h(a)
        elif choice == 1:
            original.cx(a, b)
        elif choice == 2:
            original.rz(float(rng.uniform(-3, 3)), a)
        elif choice == 3:
            original.cp(float(rng.uniform(-3, 3)), a, b)
        else:
            original.u(*rng.uniform(-3, 3, 3), a)
    result = loads_qasm(
        qasm3.dumps(original), code="rotated_surface_d3", error_budget=1e-5
    )
    actual = np.linalg.norm(
        Statevector(circuit(result)).data - Statevector(original).data
    )
    assert actual <= result.synthesis_error_bound + 1e-12


@pytest.mark.parametrize(
    "body",
    [
        "ctrl(2) @ x q[0],q[1],q[2];",
        "inv @ s q[0];",
        "gphase(pi/3); h q[0];",
    ],
)
def test_modifiers_and_global_phase(body):
    text = source(body)
    result = loads_qasm(text, code="rotated_surface_d3", input_state="external")
    np.testing.assert_allclose(
        Operator(circuit(result)).data,
        Operator(qasm3.loads(text)).data,
        atol=1e-12,
        rtol=0,
    )


def test_rotation_merge_does_not_lose_small_angles_to_roundoff():
    from modules.logical_compiler.src.model import Operation
    from modules.logical_compiler.src.translation.optimize import simplify

    source_ops = tuple(Operation("rz", (0,), (a,)) for a in (1e16, 1.0, -1e16))
    original = QuantumCircuit(1)
    reduced = QuantumCircuit(1)
    for op in source_ops:
        original.rz(op.params[0], 0)
    for op in simplify(source_ops):
        reduced.rz(op.params[0], 0)
    np.testing.assert_allclose(
        Operator(original).data, Operator(reduced).data, atol=1e-12, rtol=0
    )


def test_component_implementation_choice_belongs_to_code_entry():
    from modules.codes.contracts import CodeEntry

    entry = CodeEntry("example", "example", ("cx",), (("cx", "surgery_cnot"),))
    assert entry.component_for("cx") == "example/surgery_cnot"
    assert entry.component_for("barrier") is None
    with pytest.raises(ValueError, match="Unsupported operation"):
        entry.component_for("h")


def test_unknown_scheme_does_not_fall_back_to_surface_default():
    with pytest.raises(TranslationError, match="UNKNOWN_SCHEME"):
        loads_qasm("not QASM", code="rotated_surface_d3", scheme="unknown")


@pytest.mark.parametrize(
    "text",
    [
        'OPENQASM 3.0; include "external.inc"; qubit q;',
        "OPENQASM 2.0; opaque mystery a; qreg q[1]; mystery q[0];",
        (
            'OPENQASM 3.0; include "stdgates.inc"; '
            "input float[64] theta; qubit q; rz(theta) q;"
        ),
        'OPENQASM 3.0; include "stdgates.inc"; qubit q; delay[10ns] q;',
    ],
)
def test_source_boundaries_fail_instead_of_dropping_semantics(text):
    with pytest.raises(TranslationError):
        loads_qasm(text, code="rotated_surface_d3")


def test_multiple_registers_keep_output_wire_names():
    text = (
        'OPENQASM 2.0; include "qelib1.inc"; '
        "qreg a[2]; qreg b[1]; creg left[1]; creg right[1]; "
        "measure b[0] -> right[0]; measure a[1] -> left[0];"
    )
    result = loads_qasm(text, code="rotated_surface_d3")
    assert {r.name: r.bits for r in result.quantum_registers} == {
        "a": (0, 1),
        "b": (2,),
    }
    assert {r.name: r.bits for r in result.classical_registers} == {
        "left": (0,),
        "right": (1,),
    }
    assert [(m.qubits, m.clbits) for m in result.measurements] == [
        ((2,), (1,)),
        ((1,), (0,)),
    ]
