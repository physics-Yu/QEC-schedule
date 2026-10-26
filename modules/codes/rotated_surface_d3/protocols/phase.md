# Measured S, Sdagger and Y preparation

Status: the user confirmed separate S-SE protocols for S/Sdagger and
`initialize_plus -> logical_s` for Y preparation on 2026-10-23. These are
implemented by [PhaseComponent](../components/phase.py). They do not change the
ordinary [N/Z extraction circuit](../components/circuits.py).

## Source and mapping

The implementation follows Chen et al.,
[arXiv:2412.01391v1, Fig. 2 and Fig. S1](https://arxiv.org/html/2412.01391v1),
and the authors' [phase_gadget.py](https://github.com/Zihan-Chen-PhMA/Dynamical-S-gate-decoding/blob/c3b7a1e2f95d49a5853d5534a4596854317890e9/phase_gadget.py)
and [surface_codes.py](https://github.com/Zihan-Chen-PhMA/Dynamical-S-gate-decoding/blob/c3b7a1e2f95d49a5853d5534a4596854317890e9/surface_codes.py).
The pinned source revision is `c3b7a1e2f95d49a5853d5534a4596854317890e9`.
At the SE midpoint, a fold operation acts on data and syndrome atoms, followed
by the remaining extraction gates. The resulting rotated patch retains its
logical information while the measurement relations change. The later
[PRL publication](https://doi.org/10.1103/m7tq-9v3g) includes an additional H
proposal; its existence does not change this pinned S implementation.

The author's coordinates `(u,v)` map to this code's normalized coordinates
`(2-v,u)`. Actual local coordinates are `(2*x+1, 2*y+1)`. This maps the
stabilizers to [the current definition](../definition.py); the logical strings
may differ by stabilizers. It does not justify using the ordinary SE slots
unchanged. The dedicated S-SE order is:

| Check | CNOT direction | Corner order |
| --- | --- | --- |
| X | ancilla -> data | NE, NW, SE, SW |
| Z | data -> ancilla | NE, SE, NW, SW |

Missing boundary corners retain empty slots. After slot 2, apply:

- CZ on `(data2,data6)`, `(data1,data3)`, `(data5,data7)`, and `(X1,X2)`.
- S on `data0,data4,data8`.
- Sdagger on `Z1,Z2`.

Sdagger exchanges S and Sdagger in this fold layer. It keeps the resets,
four extraction slots and measurements in forward order. Slots 3 and 4 finish
the round; X ancillas receive H before computational-basis measurement.

## Local quantum and measurement contract

`logical_s` and `logical_sdag` preserve encoded input data in any fixed
stabilizer-sign sector. They reset the eight auxiliary atoms, not the data.
With the logical strings fixed by this repository, S maps
`X_L -> Y_L`, `Y_L -> -X_L`, `Z_L -> Z_L`; Sdagger maps
`X_L -> -Y_L`, `Y_L -> X_L`, `Z_L -> Z_L`.

Let input stabilizer signs be `(-1)^xi` and `(-1)^zi`. In the ideal protocol,
the eight ports `phase.X0..X3, phase.Z0..Z3` satisfy:

```text
mX = (x0 XOR z1, x1 XOR z2, x2 XOR z3, x3)
mZ = (z0, z1, z2, z3)
output_X = (mX0, mX1 XOR mZ0, mX2, mX3)
output_Z = (mZ0, mZ1, mZ2, mZ3)
```

In particular, `phase.X1` alone is not the output X1 stabilizer sign.
`MEASURED_INPUT_PARITIES` describes the first equation;
`EXIT_SYNDROME_PARITIES` describes the output equations. The latter is retained
in both template and expansion as `output_syndrome_parities`. The port names
are local to the invocation and resolve to its measurement identities.

These are fixed local protocol relations. There is no evaluation of a global
frame, no cross-gate propagation engine, and no noisy syndrome decoder.
S/Sdagger do not return a correction that canonicalizes arbitrary input sectors.
All measurements retain their actual values when supplied and their individual
availability times.

## Y resource preparation

`prepare_y` first executes the complete approved `initialize_plus`, preserving
its eight measurements as `prepare.X0..X3, prepare.Z0..Z3`, then executes S-SE
with eight `phase.*` ports. No measured correction is physically applied
between these stages. This is a two-round preparation; the fused one-round
alternative was not selected.

The following products, applied conditionally to the final data, select the
canonical `+Y_L` state in every ideal branch:

| Port equals one | Pauli product |
| --- | --- |
| prepare.Z0 | X6 Z2 |
| prepare.Z1 | Y0 |
| prepare.Z2 | X8 Z2 |
| prepare.Z3 | X2 Z6 |

Each product repairs the corresponding output stabilizer signs and commutes
with logical Y. `CorrectionTerm` and the bound `CorrectionRelation` expose
these products for later processing. Production code neither applies them nor
rejects an initializer branch because a bulk result is one.

## Resources, binding and exits

| Component | Atoms | Resets | Source H | Source CX | Extra CZ | S/Sdagger | Results |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| logical_s | 17 | 8 | 8 | 24 | 4 | 5 | 8 |
| logical_sdag | 17 | 8 | 8 | 24 | 4 | 5 | 8 |
| prepare_y | 17 | 25 | 25 | 48 | 4 | 5 | 16 |

These are source-circuit counts, not native pulse counts or a physical-cost
optimality claim. The current `nonzoned` compiler chooses transport and pulse
batches under the supplied Device. Atom action costs must be read from the
result for that resource profile.

All 17 roles enter at their reference SLM homes with inactive flexible AODs.
Expansion checks complete device occupancy. At exit, every atom returns to
its entry home and the AODs are inactive. Data remain encoded; ancillas remain
in their measured states. Result availability can extend beyond action end.
Relative-coordinate reuse requires equivalent bound sites, channels, timing
and resource capacity; expansion never silently recompiles a binding.

## Evidence and animation acceptance

[test_phase.py](../tests/test_phase.py) verifies all 256 encoded input-sign
sectors, logical Pauli eigenstates, S followed by Sdagger, and all 16 nonzero
Y-preparation branches. Source QASM is independently parsed to Clifford
operations. Actual atom gates are reconstructed from illuminated atoms,
positions and rotation matrices, with separate physical replay. The tests
compare the two quantum evolutions, including Y's intermediate measurement
and reset, and verify translation with changed resource and result identities.

```powershell
& modules/physical_compiler/.venv/Scripts/python.exe -m pytest -q modules/codes/rotated_surface_d3/tests/test_phase.py
```

Animation review must expose the two SE halves, fold pairs, phase rotations,
readout and return to homes. Y must show the initial complete SE and its
separate S-SE. Browser operation and human visual acceptance are separate
evidence; quantum tests alone do not establish visual acceptance.

No complete circuit-level fault distance, noisy logical failure probability,
or comparison proving minimal physical cost is claimed.
