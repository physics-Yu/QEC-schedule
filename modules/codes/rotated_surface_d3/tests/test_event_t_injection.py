"""Exact logical T-consumption branch statistics against small quantum oracles."""

import json

import numpy as np
import pytest

from modules.codes.rotated_surface_d3.probabilities.t_injection import (
    injection_probabilities,
    t_injection_port,
)

IDENTITY = np.eye(2, dtype=complex)
T_GATE = np.diag([1, np.exp(1j * np.pi / 4)])
S_GATE = np.diag([1, 1j])
MAGIC = T_GATE @ np.array([1, 1], dtype=complex) / np.sqrt(2)
# Tensor order is data, magic. The second qubit is the CNOT target.
CNOT = np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 0, 1], [0, 0, 1, 0]])


def density(vector):
    return np.outer(vector, np.conjugate(vector))


def full_circuit_probabilities(data, magic):
    evolved = CNOT @ np.kron(data, magic) @ CNOT.conj().T
    return tuple(float(np.trace(evolved[m::2, m::2]).real) for m in (0, 1))


def test_ideal_kraus_operators_and_s_correction():
    input_map = np.kron(IDENTITY, MAGIC.reshape(2, 1))
    kraus = [np.kron(IDENTITY, IDENTITY[m : m + 1]) @ CNOT @ input_map for m in (0, 1)]
    assert np.allclose(kraus[0], T_GATE / np.sqrt(2))
    assert np.allclose(kraus[1], np.exp(1j * np.pi / 4) * T_GATE.conj().T / np.sqrt(2))
    for operator in kraus:
        assert np.allclose(operator.conj().T @ operator, IDENTITY / 2)
    assert np.allclose(S_GATE @ kraus[1], np.exp(1j * np.pi / 4) * kraus[0])


@pytest.mark.parametrize(
    "vector",
    [
        [1, 0],
        [0, 1],
        [1, 1],
        [1, -1],
        [1, 1j],
        [1, -1j],
        [np.sqrt(0.3), np.exp(0.47j) * np.sqrt(0.7)],
    ],
)
def test_arbitrary_ideal_data_has_uniform_branches(vector):
    vector = np.asarray(vector, dtype=complex)
    data = density(vector / np.linalg.norm(vector))
    assert injection_probabilities(data_density=data) == (0.5, 0.5)
    assert full_circuit_probabilities(data, density(MAGIC)) == pytest.approx((0.5, 0.5))


@pytest.mark.parametrize("reference_data", [[1, 0, 0, 1], [1, 2j, -0.3, 0.8j]])
def test_entangled_reference_is_preserved_in_both_corrected_branches(reference_data):
    state = np.asarray(reference_data, dtype=complex)
    state /= np.linalg.norm(state)
    evolved = np.kron(IDENTITY, CNOT) @ np.kron(state, MAGIC)
    target = np.kron(IDENTITY, T_GATE) @ state
    for m in (0, 1):
        branch = evolved.reshape(4, 2)[:, m]
        probability = np.vdot(branch, branch).real
        assert probability == pytest.approx(0.5)
        if m:
            branch = np.kron(IDENTITY, S_GATE) @ branch
        assert np.allclose(density(branch) / probability, density(target))
    reduced_data = state.reshape(2, 2).T @ state.reshape(2, 2).conj()
    assert injection_probabilities(data_density=reduced_data) == (0.5, 0.5)


@pytest.mark.parametrize(
    "data",
    [
        np.diag([1, 0]),
        np.diag([0, 1]),
        IDENTITY / 2,
        np.array([[0.7, 0.1j], [-0.1j, 0.3]]),
    ],
)
@pytest.mark.parametrize(
    "magic",
    [
        np.diag([0.8, 0.2]),
        IDENTITY / 2,
        np.array([[0.3, 0.12 - 0.2j], [0.12 + 0.2j, 0.7]]),
    ],
)
def test_independent_density_inputs_match_full_unitary(data, magic):
    probabilities = injection_probabilities(data_density=data, magic_density=magic)
    assert probabilities == pytest.approx(full_circuit_probabilities(data, magic))
    port = t_injection_port(data_density=data, magic_density=magic)
    assert tuple(outcome.probability for outcome in port.outcomes) == probabilities
    assert port.to_dict()["model"]["kind"] == "ideal_exact"


def test_pauli_mixture_is_uniform_but_amplitude_damping_can_bias_branches():
    paulis = [
        IDENTITY,
        np.array([[0, 1], [1, 0]]),
        np.array([[0, -1j], [1j, 0]]),
        np.diag([1, -1]),
    ]
    mixture = sum(
        weight * density(pauli @ MAGIC)
        for weight, pauli in zip([0.4, 0.3, 0.2, 0.1], paulis, strict=True)
    )
    assert injection_probabilities(magic_density=mixture) == (0.5, 0.5)
    assert injection_probabilities(magic_density=IDENTITY / 2) == (0.5, 0.5)
    gamma = 0.4
    damped = np.array(
        [
            [(1 + gamma) / 2, np.sqrt(1 - gamma) * np.exp(-1j * np.pi / 4) / 2],
            [np.sqrt(1 - gamma) * np.exp(1j * np.pi / 4) / 2, (1 - gamma) / 2],
        ]
    )
    assert injection_probabilities(
        data_density=np.diag([1, 0]), magic_density=damped
    ) == pytest.approx((0.7, 0.3))
    assert injection_probabilities(
        data_density=np.diag([0, 1]), magic_density=damped
    ) == pytest.approx((0.3, 0.7))
    with pytest.raises(ValueError, match="data_density"):
        t_injection_port(magic_density=damped)


def test_uniform_probability_does_not_certify_t_channel_fidelity():
    plus = density(np.array([1, 1]) / np.sqrt(2))
    evolved = CNOT @ np.kron(plus, IDENTITY / 2) @ CNOT.conj().T
    for m in (0, 1):
        branch = 2 * evolved[m::2, m::2]
        if m:
            branch = S_GATE @ branch @ S_GATE.conj().T
        assert np.allclose(branch, IDENTITY / 2)
        assert not np.allclose(branch, density(MAGIC))
    assert injection_probabilities(magic_density=IDENTITY / 2) == (0.5, 0.5)


@pytest.mark.parametrize("magic_zero", [True, False])
def test_fully_biased_known_inputs_preserve_zero_probability_branches(magic_zero):
    magic = np.diag([1, 0] if magic_zero else [0, 1])
    port = t_injection_port(data_density=np.diag([1, 0]), magic_density=magic)
    expected = (1.0, 0.0) if magic_zero else (0.0, 1.0)
    assert tuple(outcome.probability for outcome in port.outcomes) == expected
    assert len(port.branches) == 2


@pytest.mark.parametrize(
    "bad_density",
    [
        [1, 0],
        np.eye(3) / 3,
        [[np.nan, 0], [0, 1]],
        [[np.inf, 0], [0, 1]],
        [[0.5, 0.1], [0, 0.5]],
        [[0.6, 0], [0, 0.5]],
        [[1.1, 0], [0, -0.1]],
        [[0.5, 0.6], [0.6, 0.5]],
    ],
)
@pytest.mark.parametrize("name", ["data_density", "magic_density"])
def test_invalid_density_is_rejected_even_when_ideal_formula_is_uniform(
    bad_density, name
):
    with pytest.raises(ValueError, match=name):
        t_injection_port(**{name: bad_density})


def test_port_wire_contract_provenance_and_input_copy():
    port = t_injection_port()
    document = port.to_dict()
    assert document["port_id"] == "rotated_surface_d3.t_injection.logical_z"
    assert document["protocol_id"] == "rotated_surface_d3.t_injection.data_to_magic_mz"
    assert document["model"]["id"] == "ideal_equatorial_magic"
    assert [
        (outcome.key, outcome.probability, dict(outcome.values))
        for outcome in port.outcomes
    ] == [("m0", 0.5, {"logical_m": 0}), ("m1", 0.5, {"logical_m": 1})]
    assert port.branch(port.outcome("m0").branch_id).steps == ()
    correction = port.branch(port.outcome("m1").branch_id)
    assert correction.transition == "continue"
    assert len(correction.steps) == 1
    assert correction.steps[0].component_id == "rotated_surface_d3/logical_s"
    assert correction.steps[0].participant_roles == ("data",)
    assert document["model"]["evidence"]["scope"] == "logical_branch_statistics_only"
    assert "independent" in " ".join(document["model"]["assumptions"]).lower()
    assert json.loads(json.dumps(document, allow_nan=False)) == document
    data = np.diag([0.7, 0.3])
    density_port = t_injection_port(data_density=data)
    saved = density_port.to_dict()
    assert saved["model"]["id"] != document["model"]["id"]
    assert density_port.content_sha256 != port.content_sha256
    data[0, 0] = 0
    assert density_port.to_dict() == saved
    document["outcomes"][0]["probability"] = 0.9
    assert port.outcome("m0").probability == 0.5
