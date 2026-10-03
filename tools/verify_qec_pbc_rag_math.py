"""Independent small-matrix checks for RAG K07/K21/K28; no production imports.

Requires NumPy. This verifies ideal instruments, not encoded fault tolerance,
resource preparation, routing or physical execution.
"""
import json
import numpy as np


def cnot(n, control, target):
    matrix = np.zeros((2 ** n, 2 ** n), dtype=complex)
    for src in range(2 ** n):
        bits = [(src >> (n - 1 - k)) & 1 for k in range(n)]
        bits[target] ^= bits[control]
        dst = sum(bit << (n - 1 - k) for k, bit in enumerate(bits))
        matrix[dst, src] = 1
    return matrix


def verify():
    identity = np.eye(2, dtype=complex)
    x = np.array([[0, 1], [1, 0]], dtype=complex)
    y = np.array([[0, -1j], [1j, 0]], dtype=complex)
    z = np.diag([1, -1]).astype(complex)
    h = np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
    max_error = 0.0
    branches = 0

    def close(actual, expected):
        nonlocal max_error
        error = float(np.max(np.abs(actual - expected)))
        max_error = max(max_error, error)
        if error > 1e-12:
            raise AssertionError("matrix discrepancy: " + str(error))

    products = [("Z", z), ("X", x), ("XZ", np.kron(x, z)),
                ("Y", y), ("-Y", -y), ("-YX", -np.kron(y, x)),
                ("I", identity), ("-I", -identity)]
    for sign in (1, -1):
        w = np.exp(sign * 1j * np.pi / 4)
        resource = np.array([1, w], dtype=complex) / np.sqrt(2)
        for _, product in products:
            eye = np.eye(len(product))
            plus, minus = (eye + product) / 2, (eye - product) / 2
            target = plus + w * minus
            clifford = plus + sign * 1j * minus
            prepare = np.kron(eye, resource.reshape(2, 1))
            total_probability = np.zeros_like(eye, dtype=complex)
            for m in (0, 1):
                projector = (np.eye(2 * len(product)) +
                             (-1) ** m * np.kron(product, z)) / 2
                for r in (0, 1):
                    xbra = np.array([[1, (-1) ** r]], dtype=complex) / np.sqrt(2)
                    kraus = np.kron(eye, xbra) @ projector @ prepare
                    phase = 1 if m == 0 else (-1) ** r * w
                    expected = (np.linalg.matrix_power(product, r) @
                                (target if m == 0 else target.conj().T)) / 2
                    correction = (np.linalg.matrix_power(product, r) @
                                  np.linalg.matrix_power(clifford, m))
                    close(kraus, phase * expected)
                    close(kraus.conj().T @ kraus, eye / 4)
                    close(correction @ kraus, phase * target / 2)
                    total_probability += kraus.conj().T @ kraus
                    branches += 1
            close(total_probability, eye)

    # Data order d0,d1,ancilla; reset-to-|0> is an explicit isometry.
    prepare0 = np.kron(np.eye(4), np.array([[1], [0]]))
    unitary = cnot(3, 1, 2) @ cnot(3, 0, 2)
    for bit in (0, 1):
        bra = np.array([[1, 0]]) if bit == 0 else np.array([[0, 1]])
        kraus = np.kron(np.eye(4), bra) @ unitary @ prepare0
        close(kraus, (np.eye(4) + (-1) ** bit * np.kron(z, z)) / 2)
        bell = np.array([1, 0, 0, 1] if bit == 0 else [0, 1, 1, 0]) / np.sqrt(2)
        close(kraus @ bell, bell)
    cz = np.diag([1, 1, 1, -1]).astype(complex)
    for target in (0, 1):
        local_h = np.kron(h, identity) if target == 0 else np.kron(identity, h)
        close(local_h @ cz @ local_h, cnot(2, 1 - target, target))
    return {"ok": True, "scope": "ideal_matrix_instruments_only",
            "signed_products": [name for name, _ in products],
            "injection_branches": branches, "rotation_signs": [1, -1],
            "joint_branch_probability": 0.25, "zz_projectors": 2,
            "cnot_directions": 2, "max_absolute_matrix_error": max_error}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
