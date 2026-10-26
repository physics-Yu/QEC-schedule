# Rotated Surface Code d3: definition scope

Status: identity/workspace selected; mathematical and executable definition open.

The intended identity is rotated surface code with target distance 3.
This note reserves the definition location; it is not a validated code object.

A later code-definition ADR must specify:

- Physical data-qubit ordering and stabilizer generators.
- Logical-qubit count, logical operators, signs and basis conventions.
- Boundary orientation and reference geometry.
- Consistency checks and evidence for the intended code distance.

Measurement-ancilla roles and check-extraction schedules are implementation
choices associated with the selected components. Their definitions must
reference the same data-qubit roles as the code. Detector relationships and
logical-result interpretation belong to component protocols and their temporal
composition, rather than being inferred from a static stabilizer table alone.

The serialization format and executable representation remain open. See
[components](components/README.md) and [shared contracts](../contracts/README.md).
