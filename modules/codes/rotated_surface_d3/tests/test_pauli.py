"""Physical logical Pauli strings, exact phases, and composable atom actions."""

import json
from dataclasses import replace
from math import cos, sin
from pathlib import Path

import numpy as np
import pytest
import qiskit.qasm3
import stim
from nadit_physical_compiler.architectures import generate
from nadit_physical_compiler.atom_ir import LocalU, Rotation
from nadit_physical_compiler.device import Position, loads_device
from nadit_physical_compiler.state import AtomLayout, AtomState, SLMHolder

from modules.codes._support import atom_template
from modules.codes.contracts.component import ComponentBinding, InvocationContext
from modules.codes.rotated_surface_d3.components import get_component
from modules.codes.rotated_surface_d3.definition import CHECKS, REFERENCE_HOMES
from modules.codes.rotated_surface_d3.tests.quantum_checks import action_stim, pauli

NAMES = ("logical_x", "logical_y", "logical_z")
STRINGS = {
    "logical_x": {0: "X", 3: "X", 6: "X"},
    "logical_y": {0: "Y", 1: "Z", 2: "Z", 3: "X", 6: "X"},
    "logical_z": {0: "Z", 1: "Z", 2: "Z"},
}
MATRICES = {
    "X": np.array([[0, 1], [1, 0]], dtype=complex),
    "Y": np.array([[0, -1j], [1j, 0]], dtype=complex),
    "Z": np.diag([1, -1]).astype(complex),
}


@pytest.fixture(scope="module")
def device():
    path = Path(__file__).parents[1] / "configs/nonzoned_reference.json"
    spec = json.loads(path.read_text())
    return loads_device(json.dumps(generate(spec["family"], spec["params"])))


@pytest.fixture(scope="module")
def templates(device):
    return {
        name: get_component(name).compile(
            device,
            home_sites=REFERENCE_HOMES,
            origin=Position(0, 0),
            aod_id="transport",
        )
        for name in NAMES
    }


def expand(template, device, origin=None):
    atoms = tuple(range(200, 217))
    world = AtomLayout(
        tuple(
            AtomState(a, device.site(s).position, SLMHolder(s))
            for a, s in zip(atoms, REFERENCE_HOMES, strict=True)
        ),
        qubit_to_atom=atoms,
    )
    return template.bind(
        ComponentBinding("A", origin or Position(0, 0), atoms, "transport")
    ).expand(InvocationContext("apply-pauli", 123, 500, device, world))


def source_pauli_circuit(source):
    """Parse only the approved physical strings, independent of production data."""
    parsed = qiskit.qasm3.loads(source)
    assert parsed.num_qubits == 17 and parsed.num_clbits == 0
    result = stim.Circuit("I 16")
    locals_ = [np.eye(2, dtype=complex) for _ in range(9)]
    for inst in parsed.data:
        basis = inst.operation.name.upper()
        assert basis in MATRICES and len(inst.qubits) == 1
        q = parsed.find_bit(inst.qubits[0]).index
        assert q < 9
        result.append(basis, [q])
        locals_[q] = MATRICES[basis] @ locals_[q]
    return result, tensor(locals_, float(parsed.global_phase))


def tensor(locals_, phase=0):
    """Build the nine-data-qubit matrix in little-endian wire order."""
    result = np.ones((1, 1), dtype=complex) * np.exp(1j * phase)
    for matrix in reversed(locals_):
        result = np.kron(result, matrix)
    return result


def actual_unitary(expansion):
    """Read actual pulse angles and global phase without the source/DAG gates."""
    locals_ = [np.eye(2, dtype=complex) for _ in range(9)]
    touched = set()
    for step in expansion.program.steps:
        for action in step.actions:
            assert isinstance(action, Rotation | LocalU)
            if isinstance(action, Rotation):
                a = action.angle / 2
                matrix = cos(a) * np.eye(2) - 1j * sin(a) * MATRICES[action.axis]
            else:
                a, p, lam = action.theta / 2, action.phi, action.lam
                matrix = np.array(
                    [
                        [cos(a), -np.exp(1j * lam) * sin(a)],
                        [np.exp(1j * p) * sin(a), np.exp(1j * (p + lam)) * cos(a)],
                    ]
                )
            for atom in action.atoms:
                q = expansion.wire_atoms.index(atom)
                assert q < 9  # Ancillas must not be reset, measured, or rotated.
                touched.add(q)
                locals_[q] = matrix @ locals_[q]
    return tensor(locals_, expansion.program.global_phase), touched


@pytest.mark.parametrize("name", NAMES)
def test_exact_pauli_phase_source_and_atom_actions(name, templates, device):
    expansion = expand(templates[name], device)
    source, source_matrix = source_pauli_circuit(get_component(name).source_qasm)
    actual, results = action_stim(expansion, device)
    actual_matrix, touched = actual_unitary(expansion)
    expected = tensor([MATRICES.get(STRINGS[name].get(q), np.eye(2)) for q in range(9)])
    if name == "logical_y":
        xz = [
            (MATRICES["X"] if q in (0, 3, 6) else np.eye(2))
            @ (MATRICES["Z"] if q in (0, 1, 2) else np.eye(2))
            for q in range(9)
        ]
        np.testing.assert_allclose(expected, 1j * tensor(xz), atol=1e-12)
    np.testing.assert_allclose(source_matrix, expected, atol=1e-12)
    np.testing.assert_allclose(actual_matrix, expected, atol=1e-12)
    assert stim.Tableau.from_circuit(source) == stim.Tableau.from_circuit(actual)
    assert touched == STRINGS[name].keys()
    assert not results and not expansion.measurements
    assert not expansion.correction_relations
    assert not expansion.description.measurements
    assert expansion.entry_state == expansion.exit_state
    assert expansion.results_ready_us == expansion.action_end_us
    assert expansion.program.duration_us > 0


@pytest.mark.parametrize("name", NAMES)
@pytest.mark.parametrize("basis", "XYZ")
@pytest.mark.parametrize("sign", (-1, 1))
def test_six_logical_states_and_stabilizer_sign_sectors(
    name, basis, sign, templates, device
):
    expansion = expand(templates[name], device)
    source, _ = source_pauli_circuit(get_component(name).source_qasm)
    actual, _ = action_stim(expansion, device)
    lx, lz = pauli("X", (0, 3, 6)), pauli("Z", (0, 1, 2))
    logicals = {"X": lx, "Y": 1j * lx * lz, "Z": lz}
    expected_action = logicals[name[-1].upper()]
    observable = logicals[basis]
    for sector in ((1,) * 8, (-1, 1, -1, 1, 1, -1, 1, -1)):
        stabilizers = [
            value * pauli(b, support)
            for value, (b, support) in zip(sector, CHECKS, strict=True)
        ]
        prepared = stim.Tableau.from_stabilizers(
            [*stabilizers, sign * observable, *(pauli("Z", (q,)) for q in range(9, 17))]
        )
        reference = stim.TableauSimulator()
        reference.set_inverse_tableau(prepared.inverse())
        reference.do_pauli_string(expected_action)
        for circuit in (source, actual):
            sim = stim.TableauSimulator()
            sim.set_inverse_tableau(prepared.inverse())
            sim.do(circuit)
            assert sim.canonical_stabilizers() == reference.canonical_stabilizers()
            assert all(sim.peek_observable_expectation(s) == 1 for s in stabilizers)
            expected_sign = sign * (1 if observable.commutes(expected_action) else -1)
            assert sim.peek_observable_expectation(observable) == expected_sign


@pytest.mark.parametrize("name", NAMES)
def test_translated_pauli_reuse_without_compilation(
    name, templates, device, monkeypatch
):
    shift = Position(125, 230)

    def region(r):
        return replace(
            r,
            x_min=r.x_min + shift.x,
            x_max=r.x_max + shift.x,
            y_min=r.y_min + shift.y,
            y_max=r.y_max + shift.y,
        )

    translated = replace(
        device,
        zones=tuple(replace(z, bounds=region(z.bounds)) for z in device.zones),
        slm_sites=tuple(
            replace(
                s, position=Position(s.position.x + shift.x, s.position.y + shift.y)
            )
            for s in device.slm_sites
        ),
        aods=tuple(replace(a, workspace=region(a.workspace)) for a in device.aods),
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Pauli expansion must not compile")

    monkeypatch.setattr(atom_template, "compile_physical", forbidden)
    original = expand(templates[name], device)
    moved = expand(templates[name], translated, shift)
    # Local pulses contain no global coordinates.
    assert moved.program == original.program
    assert moved.exit_state == moved.entry_state
    assert not moved.measurements and not moved.correction_relations
