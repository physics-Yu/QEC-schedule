# 0059: Free initial placement and MOVE-depth search

Status: implemented; server proof and independent result verification completed.

## Scope

Use the existing rotated d3 extraction circuit: 17 atoms and four fixed N/Z
layers of six CX each. Native rotations/reset and all six barriers are retained
when lowering. Terminal measurement is omitted. Optimize the number of parallel
MOVE actions needed to complete the gates; final return and readout transport
are excluded. Initial placement is chosen by SMT, with at most one atom per
interaction cell. Thus the first CZ pulse also requires a MOVE. This boundary
is explicit; free interacting initial placement would give a different bound.

The shared nonzoned device has 5 by 5 cells, two SLM traps per cell, cell pitch
10 um and pair separation 2 um. CZ radius is 4.6 um. The entire shared region
is illuminated, isolated spectators are allowed, and all unintended couplings
are forbidden. Flexible AOD has unlimited line capacity. All 50 trap coordinates
are possible endpoints, including both offsets. This optimizes atom assignment
and subsequent layouts, not the continuous trap geometry or circuit structure.

## Depth encoding and normalization

The QF_BV model has K+1 placement states for exactly K nonempty MOVE transitions,
and four strictly ordered gate-state indices. A carrier flag can be true even
when an atom's coordinate is unchanged: Cartesian closure may require it.
Every non-carrier remains fixed; carrier row/column equality and ordering must
be preserved. At both endpoints, every occupied intersection of the active
rows and columns belongs to the carrier set. Actual interacting atom pairs
at every pulse equal that N/Z layer exactly.

All endpoints have SLM traps and transfers carry zero objective weight.
Consequently an arbitrary legal schedule can store all atoms after each MOVE
and reload its next carrier group without adding a MOVE. The original valid
pre-MOVE grid has no unselected occupied intersection, so this reload is closed.
Unused empty lines can be removed. Gates may be performed after the STORE
because SLM-SLM CZ is supported and geometry is unchanged. Conversely, each
model transition lowers to a validated LOAD/MOVE/STORE triple. This establishes
the normalization only for this endpoint bank and MOVE-count objective; it is
not valid as a claim about minimum elapsed time or arbitrary off-SLM endpoints.

Initial cells are singly occupied and the four matchings differ. With fixed
whole-field pulses, each successive matching requires changed geometry, so
four MOVE transitions are a lower bound. Search depth 4 rather than assuming
the answer must exceed 4. A SAT certificate at 4 plus the lower bound (and a
depth-3 UNSAT check) proves the minimum in this declared model.

## Integration and evidence

Keep this path in `experiments/surface_smt/depth/`; do not change the previous
time-objective compiler or its frozen evidence. Export the selected initial
layout, ordinary Atom IR, native DAG and Device. Independently validate Cartesian
geometry, pulse pair sets, order, source dependencies, action durations and
replay. Compare actual-geometry-derived Clifford action with the original
gate-prefix circuit. This is not a full noisy memory or fault-distance result.

The server campaign has a total 7200-second wall deadline, including child
construction and validation. Depth 3 receives at most 60 seconds; depth 4 receives
the remainder. Each child is a separate process; the coordinator kills its process
group at the deadline. Save inputs/source hashes and every terminal status.
Stop early when depth 4 is validated SAT and depth 3 is UNSAT. Do not use UNKNOWN
as a proof, rerun terminal attempts, or change the frozen inputs during a run.

## Observed result

The server completed in 4.194 seconds, below the 7200-second cap. Depth 3 was
UNSAT (0.235 seconds solving); depth 4 was SAT (1.052 seconds solving). The
independently validated certificate executes all four six-CZ layers after
MOVE states 1, 2, 3 and 4. Thus MOVE depth is exactly 4 under the stated boundary,
equal to the four CZ layers rather than strictly greater. LOAD/MOVE/STORE depth
is 12. The four carrier groups contain 6, 8, 9 and 11 atoms; all change position.

The emitted gate-prefix program takes 216.161 us with the declared timing model,
including 184.721 us of transport. Time was not the optimization objective.
There is no final home return or measurement in that number. This is not a
like-for-like duration comparison with the earlier fixed-home ENOLA run.

Verification: five fast tests, one slow d3 lowering test, local and server
process-timeout checks, frozen source/input/output hashes, independent geometric
certificate checks, Atom IR semantics/replay, and actual-pulse Clifford tableau.
No existing assertions or compiler algorithms were changed by this depth path.
No repository-wide suite was rerun for this standalone experimental addition,
and no commit was made in the already-dirty worktree.

Manifest: `68fa15d2c1a0a67a69bf573b908b92f641e07a1646c24d212ed504de4dec39dc`.
Local evidence: `modules/physical_compiler/artifacts/surface-d3-depth-free/`.
Server originals: `/home/yyq/nadit-experiments/surface-d3-depth-free-68fa15d2`.
