# Rotated Surface Code d3: local definition

Status: the local [[9,1,3]] CSS definition is implemented and checked in
[definition.py](definition.py). Circuit-level fault tolerance is not claimed.

Data indices are row-major in a 3-by-3 diagram: 0/1/2, 3/4/5, 6/7/8.
X checks have supports (0,1), (1,2,4,5), (3,4,6,7), (7,8).
Z checks have supports (3,6), (0,1,3,4), (4,5,7,8), (2,5).
Canonical stabilizer signs are positive. Logical X is X0 X3 X6;
logical Z is Z0 Z1 Z2. Physical measurement bit 0 denotes eigenvalue +1.

The tests check stabilizer rank/commutation and exclude logical Paulis of
weight one or two; the listed weight-three logical operators witness distance 3.
Measured preparation can exit in a nonzero syndrome sector. Its symbolic
correction relation identifies the canonical logical state without applying it.

The reference geometry assigns data to odd/odd grid coordinates and checks to
the listed even/even coordinates. A physical implementation selects the pitch,
home/guest sites, readout region and origin through its compilation profile.

Measurement-ancilla roles and check-extraction schedules are implementation
choices associated with the selected components. Their definitions must
reference the same data-qubit roles as the code. Detector relationships and
logical-result interpretation belong to component protocols and their temporal
composition, rather than being inferred from a static stabilizer table alone.

Broader code serialization/discovery remain open. See
[components](components/README.md) and [shared contracts](../contracts/README.md).
