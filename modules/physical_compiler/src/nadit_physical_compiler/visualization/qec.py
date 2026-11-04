"""Bind explicit stabilizer annotations to replay atom identities."""

from collections.abc import Mapping
from typing import Any, cast

from ..state import AtomLayout


def build_overlay(metadata: Mapping[str, Any], layout: AtomLayout) -> dict[str, Any]:
    """Resolve static X/Z supports from physical qubits, without inferring gates.

    Args:
        metadata: nadit.qec-overlay/1 with checks identified by id, basis,
            ancilla_qubit and data_qubits. An optional title labels the code.
        layout: Result's entry binding from physical qubit to atom identity.
    Raises:
        ValueError: Malformed, ambiguous or unbound check annotations.
    """
    if (
        not isinstance(metadata, Mapping)
        or metadata.get("schema") != "nadit.qec-overlay/1"
    ):
        raise ValueError("qec.schema: expected nadit.qec-overlay/1")
    entries = metadata.get("checks")
    if not isinstance(entries, list):
        raise ValueError("qec.checks: expected an array")
    atoms = {atom.id for atom in layout.atoms}

    def atom_for(qubit: Any) -> int:
        if type(qubit) is not int or not 0 <= qubit < len(layout.qubit_to_atom):
            raise ValueError(f"qec: unknown physical qubit {qubit!r}")
        atom = layout.qubit_to_atom[qubit]
        if atom not in atoms:
            raise ValueError(f"qec: qubit {qubit} has no replay atom")
        return atom

    checks = []
    ids: set[str] = set()
    ancillas: set[int] = set()
    data: set[int] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ValueError("qec.checks: each check must be an object")
        identifier, basis = entry.get("id"), entry.get("basis")
        if not isinstance(identifier, str) or not identifier or identifier in ids:
            raise ValueError("qec.checks.id: expected a unique nonempty label")
        if basis not in ("X", "Z"):
            raise ValueError("qec.checks.basis: expected X or Z")
        ancilla = entry.get("ancilla_qubit")
        ancilla_atom = atom_for(ancilla)
        support = entry.get("data_qubits")
        if not isinstance(support, list) or not support:
            raise ValueError("qec.checks.data_qubits: expected a nonempty array")
        support_atoms = [atom_for(qubit) for qubit in support]
        if ancilla in ancillas or len(set(support)) != len(support):
            raise ValueError("qec: duplicate ancilla or support qubit")
        ids.add(identifier)
        ancillas.add(cast(int, ancilla))
        data.update(support)
        checks.append(
            {
                "id": identifier,
                "basis": basis,
                "ancilla": ancilla_atom,
                "data": support_atoms,
                "ancilla_qubit": ancilla,
                "data_qubits": list(support),
            }
        )
    if ancillas & data:
        raise ValueError("qec: a qubit cannot be both data and a check ancilla")
    title = metadata.get("title", "QEC structure")
    if not isinstance(title, str):
        raise ValueError("qec.title: expected text")
    return {
        "title": title,
        "checks": checks,
        "data": [{"atom": atom_for(q), "qubit": q} for q in sorted(data)],
    }
