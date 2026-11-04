# Physical logical Pauli components

Status: physical-string route explicitly confirmed by the user on 2026-10-23.

For the [current code definition](../definition.md):

- logical_x applies X0 X3 X6.
- logical_z applies Z0 Z1 Z2.
- logical_y applies Y0 Z1 Z2 X3 X6, equal to i logical_x logical_z.

The source contains actual single-qubit Pauli gates; native translation emits
atom rotations. No data or ancilla reset, measurement, implicit SE, transport,
logical-frame execution, or auxiliary-state consumption is inserted. The 17-role
reference binding is retained for compatibility; the auxiliary atoms are idle.
The output uses the same encoding, role mapping and reference layout.

Fowler et al., [Surface codes: Towards practical large-scale quantum computation,
Sec. IX](https://arxiv.org/pdf/1208.0928), distinguishes software tracking of
logical Pauli strings from applying their physical bit/phase flips. The physical
route is selected here by the user so that this component has actual atom actions.
The specific supports above come from this repository's code convention, not
from copying a differently oriented paper diagram.

Quantum verification must check stabilizer preservation and the operation on
all six logical Pauli eigenstates, using both the source and actual compiled
rotations. A valid position-only replay cannot establish these quantum effects.

The animation must show the addressed data atoms and rotation axes/angles while
all positions remain fixed. Pauli Y combines the overlapping X/Z action on data0
into Y0; it is not a Y pulse on every data atom. Browser verification and the
user's visual acceptance are recorded separately from quantum tests.

Example:

```powershell
& modules/physical_compiler/.venv/Scripts/python.exe -m modules.codes.rotated_surface_d3.examples.build_components --operations logical_x logical_y logical_z --output modules/codes/rotated_surface_d3/artifacts/pauli-review
```

H, S/Sdagger, transversal CNOT, raw T and Y-state preparation are separate
protocol decisions. This approval does not authorize substituting routes for them.
