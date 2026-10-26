# 0058: Bounded SMT compilation for surface-code architecture comparisons

Status: implementation and four-case pilot completed; unrestricted d3 optimization
and repository conformance-test adaptation remain unfinished.

## Context

Heuristic schedules do not establish an architecture's attainable performance.
Compare one complete distance-three rotated surface-code extraction round on
zoned/nonzoned devices with flexible/rigid AOD motion. Both motion models have
unlimited row and column capacity in this experiment.

## Decision

Add an optional `smt` ProgramCompiler. It consumes the native Physical DAG,
Device, explicit atom homes, and a finite coordinate alphabet and action horizon.
It emits ordinary Atom IR and uses the existing result validator and viewer.
The experiment also saves solver evidence, independently checked against the
input and emitted program. Z3 4.16.0.0 is the optional solver dependency.

The state contains atom coordinates and holders and every active AOD row and
column, including empty lines. A transition is none, LOAD, MOVE or STORE.
Independent native operations may overlap that transition. LOAD includes all
occupied Cartesian intersections; STORE releases atoms by deactivating lines.
Flexible movement preserves row/column order. Rigid movement translates every
active line by the same vector and cannot add lines while carrying atoms.
Atoms may remain in AOD across gates, and STORE may release only part of a batch.

CZ uses the declared whole CZ region. Every actual interaction must correspond
to a scheduled native CZ; isolated illumination follows Device.allow_spectators.
Readout observes Device holder, region, spacing and capacity rules. Concurrent
movement cannot cross CZ illumination. Gate/transport use of an atom is exclusive.

The source has 9 data atoms, 8 check atoms, 24 CX, 8 H, 8 ancilla resets and 8
measurements. Data is not reset. The scheduling input explicitly removes global
barriers from the existing N/Z extraction source, then nativeizes before DAG
construction. Per-wire operation order, measurement identity and N/Z hook order
remain fixed. This is circuit scheduling, not stabilizer-circuit synthesis.

Each case starts and ends at the same standard homes with an inactive AOD. It
does not require returning home after each gate layer. Common geometry contains
home traps, interaction guests, a translated data-shaped gate field, and a
translated ancilla-shaped readout field. Only the permitted CZ zone and AOD
motion model differ across the four cases. This first comparison fixes the
geometry; it does not optimize zone dimensions or a continuous trap landscape.

Minimize total synchronous Atom IR period time. Action durations use Device;
each step costs the longest concurrent action. SMT bounds use the declared time
quantum with upward rounding; emitted durations remain the exact Device values.
Report the rounding interval separately. Transport action-sum, timeline occupancy,
load/store atom counts, operation counts and compile time are secondary metrics.

## Evidence and scope

Save SAT witnesses, UNSAT bounds and UNKNOWN reasons separately. A constructive
valid program supplies an upper bound, not an optimization proof. Checking that
fixed witness with SMT does not count as an unrestricted search result. Optimum
claims require a lower-bound proof in the same finite coordinate alphabet,
horizon and control model. A larger horizon or additional coordinates may improve
the optimum. No capacity ceiling is inferred from the finite coordinate alphabet.

Independent checks cover every Atom IR action, DAG dependencies, timing, actual
CZ geometry, final home replay and the ideal extraction map. These establish one
SE round, not a decoded memory experiment or a circuit-level distance proof.

## Alternatives and consequences

OLSQ-DPQA provides useful coordinate/holder/shared-line constraints but does not
already encode this complete timed zoned/rigid/readout/round-return comparison.
ONEX's fixed-stage 1D solver is likewise a reference, not a drop-in 2D compiler.
Keep these differences explicit rather than inheriting their optimality claims.

Fast tests cover tiny SAT/UNSAT constraints and independent counterexamples;
small integration tests cover registry, lowering and result validation. The
authorized four-case d3 experiment runs separately with frozen inputs and budgets.

## First pilot outcome

The frozen four-case pilot used 174 steps, 16 X coordinates, 11 Y coordinates,
and a requested 600-second Z3 query budget per case. All four constructive
witnesses passed fixed-witness SMT membership, independent geometric/semantic
validation, ideal extraction/hook checks and final-home replay. Unrestricted
queries returned UNKNOWN in all four cases, with no improved schedule and no
optimality proof. The constructive schedules take 1382.561 us for nonzoned and
5664.236 us for zoned, identically for flexible/rigid because the same rigid-valid
reference is used. These values do not rank architecture optima.

Nonzoned Z3 checks returned after 1633.964 and 1494.491 seconds despite requesting
600 seconds; zoned checks returned after about 600 seconds. The solver timeout
is therefore not a reliable process wall-clock limit. Preserve the requested
and observed budgets separately. A process watchdog is needed before a strictly
equal-wall-time campaign. No terminal cases were retried.

New SMT tests: 21 fast and 22 slow passed. Repository check: 2270 fast and 2186
slow passed; 9 existing MSD geometry-hash failures were independently reproduced
without SMT, and 4 conformance cases fail because their example mapping contains
only the original compilers. Those tests also assume universal feedback,
automatic entry generation and rigid rejection. Their assertions remain unchanged
pending an agreed capability-aware update. No commit or push was made.

Evidence is under `modules/physical_compiler/artifacts/surface-smt-d3/`, including
the frozen source package, manifest, remote results, independent verification,
four-case viewer and assessment. Manifest SHA256:
`6c76c86e4f2a7e2843330b211ad1bfb1cee6e577c8690cd0771986fef741c81e`.
