"""Rotated surface-code topology for odd distances >= 3."""
from .code import CSSCode
from .stabilizer import PauliProduct, Stabilizer


class RotatedSurfaceCode(CSSCode):
    def __init__(self, distance: int = 3, *, block_id: str = "L0"):
        if type(distance) is not int or distance < 3 or distance % 2 == 0:
            raise ValueError("distance must be an odd integer >= 3")
        if not isinstance(block_id, str) or not block_id.strip():
            raise ValueError("block_id must be a nonempty string")
        self.distance = distance
        self.block_id = block_id
        self._data = tuple(f"{block_id}:d{i}" for i in range(distance * distance))

        def index(row, column):
            return row * distance + column

        # The bulk checks are the (d-1)^2 plaquettes.  Checkerboard parity
        # matches the d=3 ordering: X at (0,0), Z at (0,1), etc.  Boundary
        # checks alternate across each side and complete the d^2-1 checks.
        definitions = {"X": [], "Z": []}
        for row in range(distance - 1):
            for column in range(distance - 1):
                basis = "X" if (row + column) % 2 == 0 else "Z"
                support = (index(row, column), index(row, column + 1),
                           index(row + 1, column), index(row + 1, column + 1))
                definitions[basis].append((tuple((slot, data) for slot, data in enumerate(support))))
        # Boundary checks have two interactions, but their slots cannot be
        # copied blindly from d=3: an interior boundary atom can already use
        # two of the four slots in adjacent bulk plaquettes.  Select boundary
        # slots from the remaining colors and retain the CSS ordering rule
        # against the fixed bulk checks.  This is a small deterministic edge
        # coloring problem (four colors, at most two boundary endpoints per
        # check), so a backtracking solver keeps the topology readable while
        # supporting every odd distance without a distance-specific table.
        boundary_specs = []
        for column in range(distance - 1):
            if column % 2 == 1:
                boundary_specs.append(("X", (index(0, column), index(0, column + 1)), (2, 3)))
            else:
                boundary_specs.append(("X", (index(distance - 1, column),
                                               index(distance - 1, column + 1)), (0, 1)))
        for row in range(distance - 1):
            if row % 2 == 0:
                boundary_specs.append(("Z", (index(row, 0), index(row + 1, 0)), (2, 3)))
            else:
                boundary_specs.append(("Z", (index(row, distance - 1),
                                               index(row + 1, distance - 1)), (0, 1)))

        def ordering_compatible(left, right):
            left_slots = dict((qubit, slot) for slot, qubit in left)
            right_slots = dict((qubit, slot) for slot, qubit in right)
            common = left_slots.keys() & right_slots.keys()
            return sum(left_slots[qubit] < right_slots[qubit] for qubit in common) % 2 == 0

        bulk_by_basis = {
            basis: [order for order in definitions[basis]] for basis in ("X", "Z")
        }
        used_by_data = {}
        for order in (*definitions["X"], *definitions["Z"]):
            for slot, qubit in order:
                used_by_data.setdefault(qubit, set()).add(slot)

        candidates = []
        for basis, (left, right), preferred in boundary_specs:
            available_left = set(range(4)) - used_by_data.get(left, set())
            available_right = set(range(4)) - used_by_data.get(right, set())
            boundary_candidates = []
            for left_slot in sorted(available_left):
                for right_slot in sorted(available_right):
                    if left_slot == right_slot:
                        continue
                    order = tuple(sorted(((left_slot, left), (right_slot, right))))
                    opposite = "Z" if basis == "X" else "X"
                    if all(ordering_compatible(order, bulk_order)
                           for bulk_order in bulk_by_basis[opposite]):
                        boundary_candidates.append(order)
            boundary_candidates.sort(
                key=lambda order: (
                    0 if dict((qubit, slot) for slot, qubit in order).get(left) == preferred[0]
                    and dict((qubit, slot) for slot, qubit in order).get(right) == preferred[1]
                    else 1,
                    order,
                )
            )
            if not boundary_candidates:
                raise ValueError("Unable to assign interaction slots to surface-code boundary")
            candidates.append(boundary_candidates)

        selected_boundaries = []

        def select_boundary(spec_index):
            if spec_index == len(boundary_specs):
                return True
            basis, (left, right), _ = boundary_specs[spec_index]
            for order in candidates[spec_index]:
                if any(slot in used_by_data.get(qubit, set()) for slot, qubit in order):
                    continue
                opposite = "Z" if basis == "X" else "X"
                if any(other_basis == opposite and not ordering_compatible(order, other_order)
                       for other_basis, other_order in selected_boundaries):
                    continue
                for slot, qubit in order:
                    used_by_data.setdefault(qubit, set()).add(slot)
                selected_boundaries.append((basis, order))
                if select_boundary(spec_index + 1):
                    return True
                selected_boundaries.pop()
                for slot, qubit in order:
                    used_by_data[qubit].remove(slot)
            return False

        if not select_boundary(0):
            raise ValueError("Unable to find a valid surface-code interaction ordering")
        for basis, order in selected_boundaries:
            definitions[basis].append(order)
        self._checks = tuple(
            Stabilizer(f"{block_id}:{basis}{number}", f"{block_id}:a{basis}{number}",
                       PauliProduct(tuple((self._data[data], basis) for _, data in order)),
                       tuple((slot, self._data[data]) for slot, data in order))
            for basis in ("X", "Z")
            for number, order in enumerate(definitions[basis])
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
        return (PauliProduct(tuple((self._data[row * self.distance], "X")
                                   for row in range(self.distance))),)

    def logical_z(self):
        return (PauliProduct(tuple((self._data[column], "Z")
                                   for column in range(self.distance))),)

    def lattice_coordinates(self):
        """Dimensionless code coordinates, NOT hardware/atom positions."""
        return {q: (i % self.distance, i // self.distance) for i, q in enumerate(self._data)}
