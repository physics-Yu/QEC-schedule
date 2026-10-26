# Distance-three initialization and syndrome-extraction study

Historical experiment only. Its eight-CX unitary initializers were not the
requested production route and are superseded by the
[measured component implementations](../../components/README.md).
The public initializers use data preparation followed by all eight N/Z checks
and return correction relations. Do not use this experiment as their default.

Status: concrete, independently checked compilation examples. The shared
component interface and circuit-level fault-tolerance qualification remain open.

This bounded study generates `initialize_0`, `initialize_plus`, and `se_round`,
then compiles each through the existing `nonzoned` fixed-home backend. It adds
no production compiler API, dependencies, or decoder. It does not select an
optimal protocol or claim minimum transport time.

## Circuit convention

Data numbering is row-major:

```text
0 1 2
3 4 5
6 7 8
```

| Ancilla | Stabilizer support |
| --- | --- |
| 9 | X0 X1 |
| 10 | X1 X2 X4 X5 |
| 11 | X3 X4 X6 X7 |
| 12 | X7 X8 |
| 13 | Z3 Z6 |
| 14 | Z0 Z1 Z3 Z4 |
| 15 | Z4 Z5 Z7 Z8 |
| 16 | Z2 Z5 |

Logical X is X0 X3 X6; logical Z is Z0 Z1 Z2. The executable experiment
convention does not replace the pending general code-definition contract.

`initialize_0` resets the nine data wires, applies H on 0/2/6/8, then uses
eight CX gates in three disjoint layers. `initialize_plus` resets the data,
applies H on 1/3/4/5/7, then uses its own eight-CX, three-layer circuit.
Both are deterministic ideal encoders without measurements. Ancillas remain
present as untouched spectators, so the three examples share one entry layout.
Gate counts and ideal correctness do not establish fault-tolerant preparation.

The SE circuit resets only the eight ancillas, prepares X-check ancillas with
H, executes four CX slots, rotates X-check ancillas back, and measures all eight
in Z. It does not reset data or reset ancillas again at the exit.

Coordinates increase rightward/downward in the diagram. X checks use
NW -> NE -> SW -> SE (Z-shaped); Z checks use NW -> SW -> NE -> SE (N-shaped).
Boundary checks leave missing-corner slots empty. Full-wire barriers preserve
the source slots through native translation and compilation. This reverses
both interaction orders in Stim's rotated-code construction together; the
measurement operators are independently verified instead of inferred from the
shape names. See the [Stim source](https://github.com/quantumlib/Stim/blob/v1.16.0/src/stim/gen/gen_surface_code.cc).

## Reference device and geometry

The code-role grid is embedded into a 7 by 7 double-trap array at 10 um pitch.
Each of the 17 atoms occupies its home trap; the paired guest trap is empty.
Pair separation is 2 um and CZ radius is 4.6 um. Readout is in a separate
region with retained AOD readout and unlimited count capacity; geometric,
spacing, occupancy, and AOD constraints still apply.

Illustrative timing: load/store 10 us each, movement 1 us/um, CZ 0.5 us,
local rotation 1 us, reset 5 us, readout 10 us, and feedback latency 500 us.
These are explicit study inputs, not hardware calibrations. No layout or
protocol optimization search is performed.

Verified on 2026-10-23 with compiler source `e218709` and Stim 1.16.0:

| Operation | CX / native CZ pairs | CZ pulses | Measured atoms / exposures | Action duration (us) | All results ready (us) |
| --- | ---: | ---: | ---: | ---: | ---: |
| initialize_0 | 8 | 3 | 0 / 0 | 618.177776 | 618.177776 |
| initialize_plus | 8 | 3 | 0 / 0 | 614.377279 | 614.377279 |
| se_round | 24 | 4 | 8 / 1 | 658.817490 | 1058.817490 |

All three base results and their translated counterparts passed semantic
validation and exact entry-layout restoration. The final local evidence is
under `artifacts/verified-e218709/`; `report.json` contains the individual
assertions and `index.html` contains all three replay traces. Earlier output
directories are exploratory runs, not the final evidence location.

`relative_layout.json` records role offsets. A second compilation translates
the whole resource tile by (120, 80) um, including readout, AOD bounds and
illumination. Removing that translation must reproduce every Atom IR field.
This is an equivariance check by recompilation, not a delivered template-binding
API or support for arbitrary placement beside fixed external resources.

## Run and evidence

From the repository root, with the existing physical-compiler environment:

```powershell
& modules/physical_compiler/.venv/Scripts/python.exe modules/codes/rotated_surface_d3/experiments/three_operations/run.py --compiler-revision e218709 --output modules/codes/rotated_surface_d3/experiments/three_operations/artifacts/my-run
```

The output must be a fresh directory. The script extracts the committed
physical-compiler package at the explicitly supplied revision into the output directory and imports that
snapshot. Concurrent uncommitted work is excluded. It records the exact Git
revision, compiler-file hashes, study-script hashes and input hashes. Qiskit,
NumPy and Stim must already be installed; the runner does not install packages.
Use ordinary Python, without `-O`, because evidence checks use assertions.

Artifacts include QASM, source Stim circuits and SVGs, jobs, self-contained
`nadit.result/2` snapshots, Atom IR text, ideal Stim reconstructions from atom
actions, validation reports, a combined HTML viewer, and report JSON/Markdown.
Generated artifacts and compiler snapshots are ignored by Git.

Checks establish:

- Eight independent commuting generators, one logical qubit, and distance 3
  by enumerating all 2,619 nonidentity Paulis of weights one through three.
- Both initializer states through stabilizer/logical expectations and an
  independent nine-qubit dense-state calculation against explicit codewords.
- Source-to-atom Clifford unitary equality, up to global phase. The quantum
  reconstruction derives CZ pairs from illumination and actual positions;
  it does not copy gate pairs from the source DAG.
- Each SE measurement's Heisenberg operator, plus 84 input/error combinations:
  three logical Pauli states times no error or one of 27 single-data Paulis.
  Both source and atom circuits are checked, including logical preservation.
- Four representative mid-check ancilla hooks with horizontal X and vertical Z
  data support. Negative controls distinguish wrong hook order (which can still
  pass ideal measurement checks) from a missing stabilizer coupling.
- Device-aware semantic validation, DAG coverage/timing, result availability,
  and exact return to the entry layout, including an empty AOD.
- Identical normalized actions at the two co-translated resource positions.

Compilation result bits come from FakeBackend. Ideal quantum checks never use
those bits. The standalone SE accepts an unknown encoded input; its fake case
is not a quantum-state simulation of a particular initialized block. The ideal
source/action checks are separate, noiseless quantum calculations.

Open work includes faults inside native pulses, full circuit-level distance,
noise and logical failure rates, preparation qualification before entangling
operations, protocol/layout optimization, and the production relative-coordinate
component interface. The full physical-compiler regression suite is not needed
for this standalone study; its production source is unchanged.
