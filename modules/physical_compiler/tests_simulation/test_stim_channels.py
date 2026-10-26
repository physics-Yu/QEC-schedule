"""Physical noise insertion, Clifford signs and measurement record semantics."""

import json
from math import pi
from pathlib import Path
from typing import Any

import pytest
import stim
from test_stim_method import compile_document

from nadit_physical_compiler.activity import ActivityEvent
from nadit_physical_compiler.cost.noise.config import resolve
from nadit_physical_compiler.cost.noise.transport import RateTransportModel
from nadit_physical_compiler.methods import run_method
from nadit_physical_compiler.methods.clifford import local_clifford
from nadit_physical_compiler.methods.memory import sample_memory
from nadit_physical_compiler.methods.surface_memory import prepare_memory


def small_document(tmp_path: Path, body: str) -> dict[str, Any]:
    paths = prepare_memory(tmp_path, distance=3)
    Path(paths["qasm"]).write_text(
        'OPENQASM 3.0; include "stdgates.inc"; qubit[2] q; bit[2] c; ' + body,
        encoding="utf-8",
        newline="\n",
    )
    job_path = Path(paths["jobs"]["nonzoned"])
    spec = json.loads(job_path.read_text())
    spec["entry"]["atoms"] = spec["entry"]["atoms"][:2]
    job_path.write_text(json.dumps(spec))
    return compile_document(job_path)


@pytest.mark.parametrize(
    "axis,angle,expected",
    [
        ("X", pi / 2, "SQRT_X"),
        ("X", -pi / 2, "SQRT_X_DAG"),
        ("Y", pi / 2, "SQRT_Y"),
        ("Y", -pi / 2, "SQRT_Y_DAG"),
        ("Z", pi / 2, "S"),
        ("Z", -pi / 2, "S_DAG"),
        ("X", pi, "X"),
    ],
)
def test_native_clifford_sign(axis: str, angle: float, expected: str) -> None:
    assert stim.Tableau.from_circuit(
        local_clifford(axis, (angle,))
    ) == stim.Tableau.from_named_gate(expected)


def test_u_hadamard_and_non_clifford_rejection(tmp_path: Path) -> None:
    assert stim.Tableau.from_circuit(
        local_clifford("U", (pi / 2, 0, pi))
    ) == stim.Tableau.from_named_gate("H")
    doc = small_document(tmp_path, "rz(pi/4) q[0];")
    with pytest.raises(ValueError, match="Non-Clifford"):
        run_method("stim/v1", doc)


@pytest.mark.parametrize("kind", ["Load", "Store"])
def test_transfer_pauli_is_configurable(kind: str) -> None:
    params = resolve({"transport": {kind.lower() + "_pauli": [0.1, 0.2, 0.3]}})
    effect = RateTransportModel(params["transport"]).evaluate(
        ActivityEvent(kind, 0, 10, (7,), ((0, 0),), ((0, 0),)), 0
    )
    assert effect.pauli == (0.1, 0.2, 0.3)
    assert effect.survival == 1


def test_transfer_and_move_channels_are_not_dropped(tmp_path: Path) -> None:
    doc = small_document(tmp_path, "reset q; h q[0]; cz q[0],q[1]; c = measure q;")
    exported = run_method(
        "stim/v1",
        doc,
        noise_params={
            "transport": {
                "load_pauli": [0.01, 0, 0],
                "store_pauli": [0, 0.02, 0],
                "move_pauli": [0, 0, 0.03],
            }
        },
    )
    channels = [
        i for i in stim.Circuit(exported.circuit) if i.name == "PAULI_CHANNEL_1"
    ]
    for name, weights in (
        ("Load", [0.01, 0, 0]),
        ("Store", [0, 0.02, 0]),
        ("Move", [0, 0, 0.03]),
    ):
        key = "targets" if name == "Move" else "bindings"
        expected = sum(
            len(a[key])
            for s in doc["program"]["steps"]
            for a in s["actions"]
            if a["kind"] == name
        )
        assert (
            sum(
                len(c.targets_copy()) for c in channels if c.gate_args_copy() == weights
            )
            == expected
            > 0
        )


def test_reset_and_measurement_errors_have_distinct_placement(tmp_path: Path) -> None:
    doc = small_document(tmp_path, "reset q; c = measure q;")
    for params, expected in (
        ({}, False),
        ({"reset_flip": 1}, True),
        ({"readout_flip": 1}, True),
        ({"reset_flip": 1, "readout_flip": 1}, False),
    ):
        exported = run_method("stim/v1", doc, noise_params=params)
        samples = stim.Circuit(exported.circuit).compile_sampler(seed=2).sample(16)
        assert (samples == expected).all()


def test_fixed_case_is_explicit_and_not_a_dynamic_memory(tmp_path: Path) -> None:
    doc = small_document(
        tmp_path,
        "c[0] = measure q[0]; if (c[0] == true) { x q[1]; } c[1] = measure q[1];",
    )
    with pytest.raises(ValueError, match="Conditional"):
        run_method("stim/v1", doc)
    exported = run_method("stim/v1", doc, allow_fixed_case=True)
    assert exported.report["branch_semantics"] == "fixed_case"
    with pytest.raises(ValueError, match="unconditional"):
        sample_memory(exported, shots=1, seed=0)
