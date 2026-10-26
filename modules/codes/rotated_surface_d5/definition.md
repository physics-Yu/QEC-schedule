# Rotated Surface Code d5: definition scope

Status: executable [definition.py](definition.py) reuses the explicit odd-distance
construction in [rotated_surface](../rotated_surface/README.md).

The code contains 25 row-major data atoms and 24 dedicated syndrome atoms. X
checks are ordered by row and Z checks by column in the existing d3 convention.
There is one encoded qubit; left-column X and top-row Z are the declared logical
operators. The top/bottom boundaries carry X checks, left/right boundaries Z
checks. Data coordinates are `(2*c+1,2*r+1)` before caller-owned physical scaling.

Tests independently check check rank/commutation, logical anticommutation, slot
disjointness, concrete ideal gate action, and complete-world atom replay. These
checks establish the code/component conventions; they do not establish noisy
circuit-level distance or a decoded logical failure rate.

Measurement-ancilla roles and check-extraction schedules are implementation
choices associated with the selected components. Their definitions must
reference the same data-qubit roles as the code. Detector relationships and
logical-result interpretation belong to component protocols and their temporal
composition, rather than being inferred from a static stabilizer table alone.

Components use the existing atom-template/expansion contract and retain concrete
QASM and action provenance. See [components](components/README.md) and
[shared contracts](../contracts/README.md).
