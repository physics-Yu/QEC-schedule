"""Independent algebra and validation checks for QEC Pauli observables."""

from dataclasses import FrozenInstanceError
from itertools import product

import pytest

from neutral_atom_experiments.qec_pbc.pauli import PauliProduct


_MATRICES = {
    "I": ((1, 0), (0, 1)),
    "X": ((0, 1), (1, 0)),
    "Y": ((0, -1j), (1j, 0)),
    "Z": ((1, 0), (0, -1)),
}


def _matrix_product(left, right):
    return tuple(
        tuple(sum(left[row][k] * right[k][col] for k in range(len(right))) for col in range(len(right)))
        for row in range(len(left))
    )


def _scaled(matrix, scalar):
    return tuple(tuple(scalar * entry for entry in row) for row in matrix)


def _observable_matrix(observable, roles):
    factors = dict(observable.factors)
    result = ((observable.sign,),)
    for role in roles:
        local = _MATRICES[factors.get(role, "I")]
        result = tuple(
            tuple(entry * local_entry for entry in row for local_entry in local_row)
            for row in result
            for local_row in local
        )
    return result


@pytest.mark.parametrize("left_basis,right_basis,left_sign,right_sign", product("IXYZ", "IXYZ", (-1, 1), (-1, 1)))
def test_single_qubit_multiplication_matches_explicit_matrices(left_basis, right_basis, left_sign, right_sign):
    left = PauliProduct(() if left_basis == "I" else (("q", left_basis),), left_sign)
    right = PauliProduct(() if right_basis == "I" else (("q", right_basis),), right_sign)
    phase, result = left.multiply(right)

    expected = _matrix_product(_scaled(_MATRICES[left_basis], left_sign), _scaled(_MATRICES[right_basis], right_sign))
    assert _scaled(_observable_matrix(result, ("q",)), phase) == expected
    assert phase in (1, -1, 1j, -1j)
    assert result.sign == 1


@pytest.mark.parametrize(
    "left,right",
    [
        (PauliProduct((("a", "X"), ("b", "X"))), PauliProduct((("a", "Z"), ("b", "Z")))),
        (PauliProduct((("a", "X"), ("b", "X"))), PauliProduct((("a", "Z"),), -1)),
        (PauliProduct((("a", "Y"),), -1), PauliProduct((("b", "Y"),))),
        (PauliProduct((), -1), PauliProduct((("a", "Z"), ("b", "X")))),
    ],
)
def test_multiqubit_algebra_and_commutation_match_tensor_matrices(left, right):
    left_matrix = _observable_matrix(left, ("a", "b"))
    right_matrix = _observable_matrix(right, ("a", "b"))
    left_right = _matrix_product(left_matrix, right_matrix)
    right_left = _matrix_product(right_matrix, left_matrix)
    phase, result = left.multiply(right)

    assert _scaled(_observable_matrix(result, ("a", "b")), phase) == left_right
    assert left.commutes_with(right) == (left_right == right_left)
    assert left.commutes_with(right) == right.commutes_with(left)


def test_canonical_storage_is_immutable_and_json_ready():
    source = [["data.2", "Y"], ["data.1", "X"]]
    observable = PauliProduct(source, -1)
    source[0][1] = "Z"

    assert observable.factors == (("data.1", "X"), ("data.2", "Y"))
    assert observable.support == ("data.1", "data.2")
    assert observable.to_dict() == {"sign": -1, "factors": [["data.1", "X"], ["data.2", "Y"]]}
    assert observable == PauliProduct((("data.1", "X"), ("data.2", "Y")), -1)
    assert hash(observable) == hash(PauliProduct((("data.2", "Y"), ("data.1", "X")), -1))
    with pytest.raises(FrozenInstanceError):
        observable.sign = 1


def test_mapping_retains_sign_and_canonicalizes_physical_names():
    observable = PauliProduct((("ancilla", "Y"), ("data", "Z")), -1)
    result = observable.mapped({"ancilla": "Q010", "data": "Q002", "unused": "Q099"})

    assert result == PauliProduct((("Q002", "Z"), ("Q010", "Y")), -1)
    assert PauliProduct((), -1).mapped({}) == PauliProduct((), -1)


def test_mapping_rejects_collisions_and_requires_all_roles():
    observable = PauliProduct((("left", "X"), ("right", "X")))
    with pytest.raises(ValueError, match="Duplicate"):
        observable.mapped({"left": "Q000", "right": "Q000"})
    with pytest.raises(KeyError, match="right"):
        observable.mapped({"left": "Q000"})
    with pytest.raises(ValueError, match="nonempty"):
        observable.mapped({"left": "", "right": "Q001"})
    with pytest.raises(TypeError, match="mapping"):
        observable.mapped((("left", "Q000"), ("right", "Q001")))


@pytest.mark.parametrize("sign", [0, 2, -2, True, False, 1.0, -1.0, "1", None])
def test_invalid_signs_are_rejected(sign):
    with pytest.raises(ValueError, match="sign"):
        PauliProduct((), sign)


@pytest.mark.parametrize(
    "factors",
    [
        None,
        "X",
        ("aX",),
        (("a",),),
        (("a", "X", "extra"),),
        (("", "X"),),
        ((" ", "X"),),
        ((None, "X"),),
        (("a", "I"),),
        (("a", "x"),),
        (("a", None),),
        (("a", "X"), ("a", "Z")),
    ],
)
def test_malformed_factors_are_rejected(factors):
    with pytest.raises(ValueError):
        PauliProduct(factors)


def test_nonobservables_are_rejected_by_algebra_methods():
    observable = PauliProduct((("q", "X"),))
    with pytest.raises(TypeError, match="PauliProduct"):
        observable.multiply({"q": "Y"})
    with pytest.raises(TypeError, match="PauliProduct"):
        observable.commutes_with({"q": "Y"})
