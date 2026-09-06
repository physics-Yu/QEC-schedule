"""Default [[9, 1, 3]] rotated surface-code topology."""
from .code import CSSCode
from .stabilizer import PauliProduct, Stabilizer


class RotatedSurfaceCode(CSSCode):
    def __init__(self, distance: int = 3, *, block_id: str = "L0"):
        if type(distance) is not int or distance != 3:
            raise ValueError("This milestone implements distance=3 only")
        if not isinstance(block_id, str) or not block_id.strip():
            raise ValueError("block_id must be a nonempty string")
        self.distance = distance
        self.block_id = block_id
        self._data = tuple(f"{block_id}:d{i}" for i in range(9))
        # y increases downwards. X: NW, NE, SW, SE. Z: NW, SW, NE, SE.
        definitions = (
            ("X0", "X", ((0, 0), (1, 1), (2, 3), (3, 4))),
            ("X1", "X", ((0, 4), (1, 5), (2, 7), (3, 8))),
            ("X2", "X", ((2, 1), (3, 2))),  # top boundary
            ("X3", "X", ((0, 6), (1, 7))),  # bottom boundary
            ("Z0", "Z", ((0, 1), (1, 4), (2, 2), (3, 5))),
            ("Z1", "Z", ((0, 3), (1, 6), (2, 4), (3, 7))),
            ("Z2", "Z", ((2, 0), (3, 3))),  # left boundary
            ("Z3", "Z", ((0, 5), (1, 8))),  # right boundary
        )
        self._checks = tuple(
            Stabilizer(f"{block_id}:{label}", f"{block_id}:a{label}",
                       PauliProduct(tuple((self._data[i], basis) for _, i in order)),
                       tuple((slot, self._data[i]) for slot, i in order))
            for label, basis, order in definitions
        )
        self.validate()

    @property
    def name(self):
        return "rotated_surface"

    def data_qubits(self):
        return self._data

    def ancilla_qubits(self):
        return tuple(s.ancilla for s in self._checks)

    def stabilizers(self):
        return self._checks

    def logical_x(self):
        return (PauliProduct(tuple((self._data[i], "X") for i in (0, 3, 6))),)

    def logical_z(self):
        return (PauliProduct(tuple((self._data[i], "Z") for i in (0, 1, 2))),)

    def lattice_coordinates(self):
        """Dimensionless code coordinates, NOT hardware/atom positions."""
        return {q: (i % 3, i // 3) for i, q in enumerate(self._data)}
