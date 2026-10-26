"""Logical T-consumption measurement statistics, without physical gate creation.

The specified circuit is CNOT(data, magic), MZ(magic), then S(data) iff m=1.
With T=diag(1, exp(i*pi/4)) and magic=T|+>, its Kraus operators are
K0=T/sqrt(2), K1=exp(i*pi/4)*T.dagger/sqrt(2). Thus S*K1=exp(i*pi/4)*K0.
Both probabilities are 1/2 even for data entangled with an external reference.

For an independent resource sigma and reduced data state rho, the exact ideal
circuit probabilities are p0=(1+Tr(rho Z)*Tr(sigma Z))/2 and p1=1-p0.
These statistics do not certify gate fidelity, physical T consumption, frame
propagation, factory acceptance, or individual syndrome outcomes. An arbitrary
resource still selects the specified S response; that response need not repair
its state error. Correlations between data and resource are unsupported.

Primary derivation: Bravyi and Kitaev, Phys. Rev. A 71, 022316 (2005), Sec. III,
Eq. (2), https://arxiv.org/pdf/quant-ph/0403025 (A_theta convention).
"""

from typing import Any

import numpy as np
from numpy.typing import ArrayLike, NDArray

from ...contracts.event_probability import ProbabilityPort

_DENSITY_TOLERANCE = 1e-12
_CANONICAL_MAGIC = np.array(
    [[0.5, np.exp(-1j * np.pi / 4) / 2], [np.exp(1j * np.pi / 4) / 2, 0.5]],
    dtype=np.complex128,
)


def _validated_density(value: ArrayLike, name: str) -> NDArray[np.complex128]:
    """Copy a physical one-qubit density matrix without normalizing its input."""
    try:
        matrix = np.array(value, dtype=np.complex128, copy=True)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"{name} must be a finite complex 2x2 density matrix"
        ) from error
    if matrix.shape != (2, 2) or not np.isfinite(matrix).all():
        raise ValueError(f"{name} must be a finite complex 2x2 density matrix")
    if not np.allclose(matrix, matrix.conj().T, atol=_DENSITY_TOLERANCE, rtol=0):
        raise ValueError(f"{name} must be Hermitian")
    if not np.isclose(np.trace(matrix), 1, atol=_DENSITY_TOLERANCE, rtol=0):
        raise ValueError(f"{name} must have unit trace")
    if np.linalg.eigvalsh(matrix).min() < -_DENSITY_TOLERANCE:
        raise ValueError(f"{name} must be positive semidefinite")
    return matrix


def _inputs(
    data_density: ArrayLike | None, magic_density: ArrayLike | None
) -> tuple[NDArray[np.complex128] | None, NDArray[np.complex128]]:
    data = (
        None
        if data_density is None
        else _validated_density(data_density, "data_density")
    )
    magic = (
        _CANONICAL_MAGIC.copy()
        if magic_density is None
        else _validated_density(magic_density, "magic_density")
    )
    return data, magic


def _z_expectation(matrix: NDArray[np.complex128]) -> float:
    return float((matrix[0, 0] - matrix[1, 1]).real)


def _probabilities(
    data: NDArray[np.complex128] | None, magic: NDArray[np.complex128]
) -> tuple[float, float]:
    magic_z = _z_expectation(magic)
    if data is None and magic_z != 0:
        raise ValueError(
            "data_density is required when magic_density has nonzero Z expectation; "
            "unknown data with a biased resource is unsupported"
        )
    product = 0.0 if data is None else _z_expectation(data) * magic_z
    probabilities = ((1 + product) / 2, (1 - product) / 2)
    if any(probability < 0 or probability > 1 for probability in probabilities):
        raise ValueError("density inputs produce out-of-range branch probabilities")
    return probabilities


def injection_probabilities(
    *, data_density: ArrayLike | None = None, magic_density: ArrayLike | None = None
) -> tuple[float, float]:
    """Return (p_m0, p_m1) for ideal gates and independent logical inputs.

    Args:
        data_density: Optional physical 2x2 reduced data density matrix. Omission
            means arbitrary unknown input, including entanglement with a reference.
        magic_density: Optional physical 2x2 independent resource density matrix.
            Omission selects canonical T|+>. Supplying a mixed/noisy state changes
            input-state statistics only, not the ideal gate/readout assumption.

    Returns:
        Exact analytical measurement probabilities evaluated in floating point.

    Raises:
        ValueError: An input is not finite, Hermitian, unit trace or positive
            semidefinite within 1e-12, or unknown data meets a Z-biased resource.
            Input matrices and probabilities are never silently normalized.
    """
    return _probabilities(*_inputs(data_density, magic_density))


def _density_document(matrix: NDArray[np.complex128] | None) -> dict[str, Any] | None:
    if matrix is None:
        return None
    return {"real": matrix.real.tolist(), "imag": matrix.imag.tolist()}


def t_injection_port(
    *, data_density: ArrayLike | None = None, magic_density: ArrayLike | None = None
) -> ProbabilityPort:
    """Declare logical measurement branches and the local conditional S request.

    Args:
        data_density: Optional data state, with the semantics and validation of
            ``injection_probabilities``. It is copied into finite JSON provenance.
        magic_density: Optional independent resource state, otherwise T|+>.

    Returns:
        Immutable static port with m0/no correction and m1/logical_s(data).
        ``ideal_exact`` describes branch statistics under ideal gates/readout;
        it does not assert an ideal output T channel for general resource inputs.

    Raises:
        ValueError: Density inputs are invalid or the data state is required to
            determine the distribution. No physical actions or sampled bits arise.
    """
    data, magic = _inputs(data_density, magic_density)
    probabilities = _probabilities(data, magic)
    default_inputs = data_density is None and magic_density is None
    return ProbabilityPort.from_dict(
        {
            "schema": "nadit.event_probability/1",
            "port_id": "rotated_surface_d3.t_injection.logical_z",
            "protocol_id": "rotated_surface_d3.t_injection.data_to_magic_mz",
            "protocol_version": "1",
            "model": {
                "id": "ideal_equatorial_magic"
                if default_inputs
                else "ideal_cnot_independent_density_inputs",
                "kind": "ideal_exact",
                "assumptions": [
                    (
                        "Data and magic resource are independent; "
                        "data may be entangled "
                        "with an external reference independent of the resource"
                    ),
                    "Ideal logical CNOT(data, magic), then ideal logical "
                    "Z measurement of magic",
                    "Canonical T|+> resource"
                    if magic_density is None
                    else "Resource is the supplied physical logical density matrix",
                    "Canonical logical bases are inputs; no frame correction "
                    "or propagation is inferred",
                    "Only measurement branch statistics are certified, "
                    "not output gate fidelity",
                ],
                "parameters": {
                    "data_density": _density_document(data),
                    "magic_density": _density_document(magic),
                    "unknown_data": data is None,
                    "density_validation_atol": _DENSITY_TOLERANCE,
                },
                "evidence": {
                    "scope": "logical_branch_statistics_only",
                    "calculation": (
                        "p_m0=(1+z_data*z_magic)/2; p_m1=(1-z_data*z_magic)/2"
                    ),
                    "z_data": None if data is None else _z_expectation(data),
                    "z_magic": _z_expectation(magic),
                    "canonical_magic_kraus": [
                        "T/sqrt(2)",
                        "exp(i*pi/4)*T_dagger/sqrt(2)",
                    ],
                    "source": "https://arxiv.org/pdf/quant-ph/0403025",
                    "source_location": "Section III, Eq. (2), A_theta with theta=pi/4",
                },
            },
            "outcomes": [
                {
                    "key": "m0",
                    "probability": probabilities[0],
                    "values": {"logical_m": 0},
                    "branch_id": "no_correction",
                },
                {
                    "key": "m1",
                    "probability": probabilities[1],
                    "values": {"logical_m": 1},
                    "branch_id": "apply_s",
                },
            ],
            "branches": [
                {"key": "no_correction", "transition": "continue", "steps": []},
                {
                    "key": "apply_s",
                    "transition": "continue",
                    "steps": [
                        {
                            "component_id": "rotated_surface_d3/logical_s",
                            "participant_roles": ["data"],
                        }
                    ],
                },
            ],
        }
    )
