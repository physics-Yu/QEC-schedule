# Physical logical Hadamard

Status: the user confirmed physical H on the data followed by real atom
rearrangement. The implementation uses six transport strokes, with the same
quantum protocol and final permutation as the earlier eight-stroke candidate.

## Protocol and source

Apply H to all nine data atoms, then rotate their positions by 90 degrees about
the data-grid center. The eight auxiliary atoms retain their positions and states.
There is no implicit SE, reset, measurement, physical SWAP gate, or frame update.

Hartweg et al., [Efficient atom rearrangements for quantum error correction
primitives with a single AOD, v1](https://arxiv.org/html/2607.28149v1), Sec. 3.1,
describes transversal H followed by data-block rotation. Section 2.4, Remark 2,
identifies a six-stroke distance-3 rotation. The batches below were independently
reconstructed for this repository's numbering and checked against its Device;
they are not asserted to be a literal transcription of Figure 3.

The [source QASM](../components/hadamard.py) contains H9 on stable physical-atom
wires. The component semantics additionally include physical relocation and the
returned output-role binding. H9 alone, interpreted with the old geometric roles,
is not the complete logical component.

## Physical permutation and exit

Input data roles occupy the usual rows `0 1 2 / 3 4 5 / 6 7 8`. After rotation,
the atoms at those same geometric homes are `6 3 0 / 7 4 1 / 8 5 2`.

- Original data role to destination home: `(2, 5, 8, 1, 4, 7, 0, 3, 6)`.
- Output data role to original atom: `(6, 3, 0, 7, 4, 1, 8, 5, 2)`.
- Auxiliary roles are unchanged. AODs are inactive at the exit.

`exit_state` contains the actual changed physical positions; the caller's world
wire map is preserved. `exit_binding` supplies the new role-to-atom mapping for
the next component. Passing the old role binding to ordinary SE is rejected.

For stabilizer indices in [the code definition](../definition.md), the output
signs obey `X_i = input.Z_i` and `Z_i = input.X_(3-i)`. These relations are
returned as static `output_syndrome_parities`, without evaluating or accumulating
frames. No new measurement record is created by H.

The logical-operator conjugations in the output geometry are

```text
X_L -> Z_L
Z_L -> X_L * X_check0 * X_check1 * X_check2 * X_check3
Y_L -> -Y_L * X_check0 * X_check1 * X_check2 * X_check3
```

Thus the operation is logical H on the all-positive code sector. In other
stabilizer-sign sectors, the explicitly declared product of check signs must be
retained when interpreting the fixed logical representatives. This metadata does
not implement global frame management or decoding.

## Six-stroke implementation

Let `a` be the data-grid pitch. Each row lists original data-atom roles, independent
of their changing geometric roles. Every stroke is LOAD, a rigid translation along
one axis, then STORE. Selected atoms form an occupied subset of the selected
row-by-column AOD grid; empty intersections are checked against the complete world.

| Stroke | Original data atoms | Translation |
| --- | --- | --- |
| 1 | 0, 1, 2 | x + a |
| 2 | 0, 2, 4, 7 | y + a |
| 3 | 0, 3, 4, 6, 7 | y - 2a |
| 4 | 2, 5, 7, 8 | x - 2a |
| 5 | 0, 2, 3, 5, 7 | x + a |
| 6 | 0, 1, 2, 3, 4, 5 | y + a |

The sum of stroke distances is `8a`; this is not the sum of individual atom
distances. Each axis requires four distinct nonzero net displacements. In the
rigid, single-axis stroke model, two strokes provide at most three distinct
nonzero subset sums, so at least three strokes per axis are required. Six strokes
reach that model's stroke-count bound. This is not a global optimum claim over
all motion modes supported by the physical compiler or over all logical-H protocols.

## Reference profile and timing

The [H reference profile](../configs/nonzoned_h_reference.json) uses an 11-by-11
array of home/guest pairs, anchored at `(-20, -20)` micrometres, with 10-micrometre
site pitch. `H_REFERENCE_HOMES` shifts the usual home row/column indices by two;
the physical data positions remain `(10, 30, 50)` on each axis. The data-grid
center is `(30, 30)` and `a = 20` micrometres.

Temporary destinations extend to x or y equal to -10 and 70 micrometres. All
required buffer sites are explicit template resources. The AOD workspace is
`[-25, 90] x [-25, 115]` micrometres. Missing buffers, occupied pickup/release
intersections, or incompatible capacities reject expansion.

For this illustrative profile, the current compiled component takes 282 us:
2 us of local H pulses, 120 us for six LOAD/STORE pairs, and 160 us for motion.
The earlier eight-stroke line-by-line candidate took 362 us on the same profile.
The difference is a transport implementation improvement, with unchanged logical
action and output permutation. These are Device-based costs using 10 us per
transfer and 1 us per micrometre, not the paper's constant-jerk timing or calibrated
hardware measurements.

## Binding and verification boundaries

Relative actions support an overall translation with equivalent sites and Device
resources. `expand` validates actual complete-world occupancy; binding does not
move atoms into the entry configuration. An explicit `site_ids` mapping belongs
to a particular compiled template. If one is supplied for H, the next component
needs its own complete map; carrying H's buffer-site map into SE is not sufficient.
With unique coordinate lookup and empty `site_ids`, the returned `exit_binding`
can directly bind the following SE template compiled for the same home geometry.

[Independent tests](../tests/test_hadamard.py) compare source H9 with the actual
local pulses, derive the permutation from replayed final positions, and verify
the six logical Pauli eigenstates in both standard and nonstandard syndrome
sectors. They also check H followed by ordinary SE using the changed role binding,
translated reuse, buffer spectators, and inconsistent exit metadata. They enforce
six LOAD/MOVE/STORE strokes and the reference-profile duration without weakening
the original quantum and permutation checks.

Physical validation checks endpoint transport, AOD grids, capacity, occupancy,
pulse semantics, timing, and the declared exit. It does not establish calibrated
transport phases, continuous collision avoidance, or complete circuit-level
fault tolerance. Animation is an inspection of the emitted actions; browser
review and user visual acceptance remain separate evidence.
