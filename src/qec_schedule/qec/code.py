"""Replaceable code contract, independent of the default surface-code example."""
from abc import ABC, abstractmethod
from .stabilizer import PauliProduct, Stabilizer


class QECCode(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def data_qubits(self) -> tuple[str, ...]: ...

    @abstractmethod
    def ancilla_qubits(self) -> tuple[str, ...]: ...

    @abstractmethod
    def stabilizers(self) -> tuple[Stabilizer, ...]: ...

    @abstractmethod
    def logical_x(self) -> tuple[PauliProduct, ...]: ...

    @abstractmethod
    def logical_z(self) -> tuple[PauliProduct, ...]: ...

    @abstractmethod
    def syndrome_round(self, *, rounds: int = 1, primitive: str = "CZ"):
        """Return a PhysicalCircuit; a non-CSS code can supply its own generator."""

    def x_stabilizers(self) -> tuple[Stabilizer, ...]:
        return tuple(s for s in self.stabilizers() if s.basis == "X")

    def z_stabilizers(self) -> tuple[Stabilizer, ...]:
        return tuple(s for s in self.stabilizers() if s.basis == "Z")

    def validate(self) -> None:
        data, ancillas, checks = self.data_qubits(), self.ancilla_qubits(), self.stabilizers()
        if not data or len(set(data)) != len(data) or len(set(ancillas)) != len(ancillas):
            raise ValueError("Qubit IDs must be unique and data must be nonempty")
        if any(not q for q in (*data, *ancillas)) or set(data) & set(ancillas):
            raise ValueError("Data and ancilla IDs must be nonempty and disjoint")
        if len({s.id for s in checks}) != len(checks):
            raise ValueError("Duplicate stabilizer IDs")
        if len({s.ancilla for s in checks}) != len(checks) or {s.ancilla for s in checks} != set(ancillas):
            raise ValueError("This interface requires one dedicated ancilla per check")
        for check in checks:
            if not set(check.operator.support) <= set(data):
                raise ValueError("Stabilizer refers to unknown data qubit")
        operators = [s.operator for s in checks]
        for i, left in enumerate(operators):
            if any(not left.commutes_with(right) for right in operators[i + 1:]):
                raise ValueError("Stabilizers must commute")
        xs, zs = self.logical_x(), self.logical_z()
        if len(xs) != len(zs):
            raise ValueError("Logical X/Z operators must form pairs")
        for op in (*xs, *zs):
            if not set(op.support) <= set(data) or any(not op.commutes_with(s) for s in operators):
                raise ValueError("Invalid logical operator support or commutation")
        for i, x in enumerate(xs):
            for j, z in enumerate(zs):
                if x.commutes_with(z) != (i != j):
                    raise ValueError("Logical X/Z commutation must be canonical")
        for ops in (xs, zs):
            if any(not a.commutes_with(b) for i, a in enumerate(ops) for b in ops[i + 1:]):
                raise ValueError("Same-basis logical operators must commute")


class CSSCode(QECCode):
    """Reusable extraction for pure-X / pure-Z stabilizer code implementations."""

    def validate(self) -> None:
        super().validate()
        if any(s.basis not in ("X", "Z") for s in self.stabilizers()):
            raise ValueError("CSS extraction only supports pure X and Z checks")
        occupied = set()
        for check in self.stabilizers():
            for slot, qubit in check.interactions:
                if (slot, qubit) in occupied:
                    raise ValueError("Two interactions share a data qubit in an ordering slot")
                occupied.add((slot, qubit))
        # Overlapping X/Z checks must encounter BOTH common data in the same
        # relative order; otherwise extraction can couple the two ancillas.
        for x in self.x_stabilizers():
            for z in self.z_stabilizers():
                xt, zt = dict((q, s) for s, q in x.interactions), dict((q, s) for s, q in z.interactions)
                if sum(xt[q] < zt[q] for q in xt.keys() & zt.keys()) % 2:
                    raise ValueError("Interaction ordering entangles X/Z syndrome ancillas")

    def syndrome_round(self, *, rounds: int = 1, primitive: str = "CZ"):
        from .syndrome_circuit import generate_syndrome_circuit
        return generate_syndrome_circuit(self, rounds=rounds, primitive=primitive)
