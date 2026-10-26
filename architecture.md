# NADiT Architecture

Date: 2026-10-23.

## Goal

Build a configurable neutral-atom compiler and digital twin. The development
path is logical circuit -> QEC components -> physical circuit -> atom actions.
The implemented physical compiler produces a complete atom-action program for
one measurement case under a selected Device and compiler strategy. Code-library
and logical-compiler workspaces now define the next development boundary.

## Current state

| Part | State |
| --- | --- |
| OpenQASM 2.0 / 3.0 frontend and Physical DAG | Implemented |
| Configurable native translation before PhysicalDAG | Implemented |
| Scheduling, placement, and transport handoff contracts | Implemented |
| Measurement-result references and single-bit conditions | Implemented |
| Seeded fake measurement backend | Implemented |
| DAG feedback reference tester (`execute`) | Implemented |
| Flexible Device geometry, atom state, and transport constraints | Implemented |
| Atom IR structures, step timing, and text output | Implemented |
| Atom-action state replay with retained readout | Implemented |
| One-pair DAG-to-Atom-IR compilation with feedback | Implemented |
| Multi-pair fixed placement, sequential transport, and shared pulses | Implemented |
| Shared transport rules and direct strict parallel batches | Implemented |
| Rigid motion rules shared by placement and pair/sequential/strict transport | Implemented |
| Device pair arrays/roles, zoned/v1, strategy admission, and discovery | Implemented (ADR 0025) |
| Shared activity and post-compilation additive/hsim cost | Implemented (ADR 0026) |
| Frozen suites, experiment runner, resume, and summaries | Implemented (ADR 0027) |
| Next-CZ preview and matching-based atom reuse | Implemented |
| Routing-aware IDS placement and optional reuse | Implemented |
| Staged/relaxed routing | Implemented |
| Declarative jobs, CLI, and saved result replay | Implemented |
| Self-contained result v2 and independent semantic validation | Implemented |
| Code library and logical compiler workspaces | Structure accepted; documentation skeleton created (ADR 0037) |
| Code-selected logical QASM frontend and DAG | Implemented for the finite d3/d5 Clifford+T source profile (ADR 0039) |
| Reusable components and logical QEC compilation | Implementation remains open |

The module [README](modules/physical_compiler/README.md) defines the implemented API.
The [feedback study](modules/physical_compiler/docs/feedback-validation.md)
covers all 512 assignments to the supplied circuit's nine measurement results.

## Physical compilation

```text
QASM + GateSet
    -> parse and expand source gates/conditions
    -> native translation
    -> PhysicalDAG

Physical DAG + Device + strategy configuration + entry state
    -> compile one case using fake measurement results
    -> Atom IR + timeline + exit state
```

The compiler maintains DAG compilation progress, the ready set, predicted atom
positions and trap ownership, and planned operation times and resource use.
The strategy selects compatible operations and performs gate grouping,
placement, transport planning, and action generation.
Initial mapping and placement are optimization decisions; an entry state
supplies existing assignments and positions.

The frontend completes native gate translation before building PhysicalDAG.
GateSet selects the native basis without supplying zone or AOD geometry.
Source measurement identities survive translation even when DAG node IDs
change. See [ADR 0008](docs/decisions/0008-native-frontend-and-module-contracts.md).

A predecessor releases its successors after it has been compiled or skipped.
When compiling a measurement, the compiler obtains one result from the fake
backend and records it under that source measurement's identity. Later
conditions use this value to select or skip their operations. The original
DAG retains every branch.

Generated times preserve operation dependencies and measurement feedback
latency. The compiler advances through planned operations without waiting for
execution events. See [ADR 0005](docs/decisions/0005-case-driven-physical-compilation.md).

A gate group is a set of selected circuit operations. A transport batch is a
set of compatible movements. An AtomStep is a set of actions scheduled to
start together. A gate group can require several transport batches and steps.

`physical_ir.py` defines the native circuit; `atom_ir.py` defines concrete
atom actions. Strategies construct legal groups from Device rules.
Reference validators serve tests and explicit debugging, outside the default
construction path. [ADR 0007](docs/decisions/0007-explicit-physical-and-atom-ir.md)
records these contracts.

`nadit.result/2` preserves the native DAG, expanded Device, input content
hashes, Atom IR, and result records. The job hash uses content identities in
place of input paths. Provenance includes tracked-file git dirtiness.
Validation and viewing can read the snapshot after the original files move.

The independent validator checks transport, exact CZ illumination and
interaction pairs, zone/holder/addressing/readout rules, native-operation
execution counts, DAG dependencies, and measurement feedback. Intervals come
from the actual Atom IR timeline, then are compared with recorded intervals.
Reports retain the first 20 failures and count all failures. Version-1 results
receive structural checks and are marked semantically unavailable. See
[ADR 0023](docs/decisions/0023-semantic-validation-and-self-contained-results.md).

## Device requirements

| Capability | Requirement |
| --- | --- |
| AOD motion | Configure workspace, row/column capacity, and line spacing. Support rigid translation and order-preserving motion for every intermediate move. |
| AOD intersections | Account for every atom affected by activated row/column intersections. |
| SLM sites | Represent fixed trapping sites; track holders and transfer feasibility and cost during planning. |
| Zoning | Configure bounds and operation capabilities for storage, entanglement, and measurement; allow overlapping regions. |
| CZ pulses | Configure interaction distances separately from illumination. Support SLM-SLM, AOD-SLM, and AOD-AOD holder pairs. |
| Single-qubit operations | Address explicit atoms. |
| Measurement | Configure readout positions, addressing, holders, and retention. Permit measurement in AOD without STORE. |
| Timing | Configure transfer, pulse, reset, measurement, and feedback times; compute movement time from distance. |

Device capabilities constrain placement, transport grouping, and action
expansion. The compiler uses a distance-to-time model for motion.

The first strategy assigns atoms dynamically to fixed candidate interaction
pairs. Device legality also supports strategies that generate candidate
coordinates. The [device design](modules/physical_compiler/docs/device-and-zones.md)
defines the single-row gate geometry, 5 um storage grid, and flexible and
rigid profiles. [ADR 0006](docs/decisions/0006-device-zones-and-interaction-sites.md)
records this separation.

The complete compiler strategy is replaceable. Strategies share input and
Atom IR contracts and implement the Device models they support. Device
selection and strategy selection are separate configuration choices.

## Measurement cases and state

The fake backend supplies deterministic test bits from a seed and stable
source measurement identity. Repeated reads share one result. Gate
decomposition, placement, and routing preserve that identity.

The implemented IR uses `0/1`. A provider using `+1/-1` maps `+1` to `0` and
`-1` to `1`. Results belong to a case; they are not part of reusable templates.

The existing `execute` function checks DAG conditions and dependency timing
with abstract completion and result events. It remains a reference tester.
The compiler consumes the result provider directly. Atom IR replay applies
the generated transfers and movement to reconstruct the exit state.

The first strategy supports at most two atoms: fixed SLM CZ pairs, grouped
same-row transport or singleton transfers, and retained readout in AOD.
Readout returns the atom to its preceding SLM site. This leaves a common
SLM boundary for subsequent layers. See
[ADR 0009](docs/decisions/0009-one-pair-compilation.md).

The multi-pair baseline uses an explicit catalogue of isolated SLM pairs.
The scheduler selects disjoint CZ gates up to its capacity. Placement clears
pulse-region spectators, assigns distinct pairs, and returns CZ participants
to storage afterward. Sequential transport moves one atom at a time; one CZ
pulse executes the whole placed layer. The compiler and measurement protocol
remain shared with the one-pair strategy.

StrictTransport replaces the sequential constructor through the same interface.
It uses a movement conflict map plus batch capacity and current occupancy.
Occupied grid intersections are closed over compatible pending requests before
emitting common LOAD/MOVE/STORE phases. Source measurement identities and
branch decisions remain unchanged. See
[ADR 0011](docs/decisions/0011-strict-parallel-transport.md).

`AOD.motion` selects flexible order preservation or rigid translation.
`rules_for` supplies the same compatibility relation to layout scoring and
transport batching. Rigid batches require equal displacement vectors;
active lines keep their relative positions. A carrying rigid AOD cannot add
lines during LOAD. Pair, sequential, and strict support rigid motion;
staged and relaxed reject it. Three otherwise identical device profiles
separate unlimited flexible motion, 16-by-16 capacity, and rigid translation.
See [ADR 0024](docs/decisions/0024-rigid-aod-motion.md).

Optional matching reuse retains atoms between known CZ layers. The compiler
previews the next layer using a local frontier and dependency-count overlay.
Uncompiled measurements stop the preview without sampling. Compiled results
can select a known branch during planning; actual conditional operations
still wait for the result's availability time. Maximum
matching chooses compatible retained atoms; placement reserves their gate
pairs and strict transport moves the other participants. Transport batches
and duration depend on placement and routing costs.
See [ADR 0012](docs/decisions/0012-lookahead-and-matching-reuse.md).

HeuristicPlacer adds source-aligned full candidate generation, first-fit
compatible movement-group scoring, partner lookahead, and bounded IDS.
Matched atoms can stay in the gate zone or return to storage. Placement scores
remain separate from the generated transport timeline; strict transport
constructs final legal batches using Device timing and occupancy.
See [ADR 0013](docs/decisions/0013-routing-aware-ids-placement.md).

## Development order

1. Implement Device, atom state, and flexible transport constraints (complete).
2. Implement Atom IR structures, text output, and retained-readout replay (complete).
3. Implement native frontend translation, module handoffs, and one-pair case
   compilation (complete).
4. Implement the multi-pair baseline, direct strict transport, matching reuse,
   and IDS placement, then staged/relaxed routing (complete).
5. Implement the rigid 16-by-16 variant and compare equal zoned layouts
   (complete). Shared-zone layouts follow separately.
6. Package reusable components and connect logical QEC compilation.

The [implementation plan](modules/physical_compiler/docs/implementation-plan.md)
specifies file ownership and acceptance criteria for these steps.
[ADR 0010](docs/decisions/0010-multipair-compilation.md) defines conflict-map
semantics and the multi-pair module sequence.

Device-aware compilation must emit the chosen source operations as legal atom
actions, preserve their dependencies and case decisions, and return the
resulting layout and planned timeline. Test/debug validation checks source-operation
coverage, movement legality, pulse addressing, and dependency timing.

## Components and logical compilation

### MSD object-estimation path

The MSD resource-estimation path reuses staged component cost objects and the
logical scheduler with precomputed probability events; it does not lower each
case to atoms. Homogeneous waves share one AOD, while different component waves
remain serial. Recorded d3/d5/d7/d9/d11 catalogs and asynchronous/synchronous policies
are described in [ADR 0053](docs/decisions/0053-factory-strategy-boundaries.md).
Synchronous/v2 aligns attempted production rounds: accepted T outputs are
delivered immediately, final rejection produces no output, and both outcomes
advance to the next round. It does not synchronize successful-output ordinals.
Paired studies declare the same round count for both scheduling policies.
The [d9/d11 integration report](docs/experiments/msd-object-d911-20261025.md)
records reuse of saved stage templates and exact probability evidence, without
new physical compilation or probability estimation.
This bounded estimation path is distinct from the physical compilation and
atom-level validation contracts below.

The d3 N4 local study now compares whole-factory vertical, horizontal and 2D
layouts while preserving those policies and model inputs; wider studies remain
deferred. The [local report](docs/experiments/msd-object-layout-d3-n4-20261025.md)
records results and full schedules.
[ADR 0054](docs/decisions/0054-msd-layout-cost-comparison.md) fixes its cost,
reuse and interpretation boundaries; the
[implementation plan](modules/logical_compiler/docs/msd-layout-implementation-plan.md)
records ownership, staged tasks and local acceptance criteria. No physical
compilation or new probability calculation belongs in its parameter-scan loop.

Same-distance two-level object production is specified
in [ADR 0055](docs/decisions/0055-two-level-object-factory-supply.md) and the
[L2 implementation plan](modules/logical_compiler/docs/msd-level2-implementation-plan.md).
L2 progressively adopts four L1 outputs into work states and consumes eleven
later inputs through R. Retained tokens keep their real carrier identity;
finite producer-held inventory and costed block exchanges replace the L1 ideal
external sink. Both levels share one resource scheduler but use separate
synchronization cohorts. FIFO supply and fair homogeneous-wave admission form
the initial policy. The two-level implementation is available through
`examples.factory_level2`: `ObjectFactorySupply` uses the existing cooperative
runtime and ledger, while the code-owned `DeliveryObjectProfile` supplies
versioned three-leg Load/Move/Store costs. Its
[local acceptance](docs/experiments/msd-object-level2-d3-20261025.md) is a finite
one-round witness. The [N1=2 policy comparison](docs/experiments/msd-object-level2-n2-20261025.md)
adds the existing recorded-distance, L1-count and placement parameters. L2 remains
one same-distance consumer below the L1 array; the policies affect L1 only.
Factory/token identities and costed delivery remain unchanged. Configuration
coverage is distinct from complete-production acceptance at d3 N1=1/2. No
atomic compilation, new raw probability estimation or campaign framework is selected.

The next prepared campaign is a single-consumer, synchronous-L1 scan, recorded
in [ADR 0056](docs/decisions/0056-single-consumer-synchronous-msd-scan.md) and the
[preparation document](docs/experiments/msd-level2-sync-scan-preparation.md).
Its [parameter record](experiments/msd/level2-sync-scan-preparation.json) fixes
270 cells / 27000 shots, N2=B=1, 89 single-thread workers and 5/30/3060-second
wave/shot/cell budgets. Three relative L2 positions and adapted scan accounting
remain implementation gaps. This is preparation only: implementation and
experiment execution await explicit user approval; current runtime defaults and
historical asynchronous results remain unchanged.

Execution was subsequently approved for the frozen matrix. The adapted
`experiments.msd.scan_objects` accepts `nadit.level2_object_scan/1`, binds the
existing level2 entry to all three declared positions, and preserves common-round
event audits, real-carrier metrics, bounded workers and fail-stop ownership.
The preparation record remains a historical parameter reference; approval and
local readiness alone do not establish completion of the server matrix.

After the first shot timeout, the user explicitly authorized a continuation with
larger wall budgets. The [continuation record](docs/experiments/msd-level2-sync-continuation-20261026.md)
defines immutable prior results, exact seed-prefix imports, unchanged runtime
and accounting source checks, fresh output and continued fail-stop ownership.
This is an explicit experiment continuation, not an automatic recovery policy.

### Physical component path

The [code library](modules/codes/README.md), logical compiler and physical
compiler are peer workspaces. Concrete codes are listed directly under codes/;
each owns its definition, components, internal protocols and layouts. The d3
and d5 rotated-surface-code workspaces retain independent local files.

The logical compiler translates a logical circuit using code/protocol capabilities,
constructs a Logical DAG, checks frontier dependencies and logical constraints,
and binds/expands component invocations. Cross-code interactions are defined by
protocols in codes/protocols/, not inferred by the compiler. Shared interface
design belongs in codes/contracts/. Components accept block identities and
placements, including multiple participating blocks such as a CNOT's control
and target. See [ADR 0037](docs/decisions/0037-code-library-and-logical-compiler-workspaces.md).

The proposed component contract describes entry conditions, resources, measurement
outputs, and exit layout. Binding supplies concrete atoms, positions, and
resource choices. Reuse applies while its action structure and parallel groups
remain valid for those bindings. See the
[Atom IR and component design](modules/physical_compiler/docs/atom-ir-and-components.md).

Components target designed atom-level templates with participant and coordinate
binding. Logical parallel candidates still require device-wide physical
admission; independently compiled action tables cannot simply be overlapped.
The executable handoff, result continuity and reuse interfaces remain open in
the [logical compiler architecture](modules/logical_compiler/docs/architecture.md).

QEC protocols provide syndrome-extraction, correction, atom-refresh, and
leakage-handling circuits. Logical measurement results are derived from the
physical measurement records. Leakage handling produces an erasure record
and refreshes or replaces the carrier. Protocol selection and decoding remain
later work. Motivating workloads include PBC and magic-state distillation.

Noise models will consume atom actions, their timing, and measurement records.
A state-aware simulation backend can later supply measurement outcomes for
noise-dependent cases.

## References

- [Search Smarter, Not Harder](https://arxiv.org/html/2512.13790v1): scheduling,
  reuse analysis, placement, routing, and code generation. IDS improves the
  placement search; relaxed routing changes transport construction.
- [MQT QMAP v3.5.0 compiler](https://github.com/munich-quantum-toolkit/qmap/blob/cd8ec9131f99d93ce1601c9a1dcad5c9e09ce31d/include/na/zoned/Compiler.hpp):
  compile-time planning through those stages.
- [Enola](https://github.com/UCLA-VAST/Enola/blob/2944dbf4e163e8d2eeeec607add0d9139edce689/enola/enola.py)
  and [ZAC](https://github.com/UCLA-VAST/ZAC/blob/e5083362f99e6915f20c2bd0eaa88b6d1cdcecac/zac/scheduler/scheduler.py):
  additional scheduling and transport references.
- [Circuit-based leakage-to-erasure conversion](https://arxiv.org/abs/2405.10434):
  a reference for carrier-refresh components.

## Repository

[modules/codes/](modules/codes/README.md) contains the concrete code workspaces,
shared contract design and cross-code protocol workspace.
[modules/logical_compiler/](modules/logical_compiler/README.md) contains the
logical QASM translation frontend and its architecture notes. The code library
also provides explicit code-entry declarations for this frontend.
Atom-component implementations and physical lowering remain future work.

[modules/physical_compiler/](modules/physical_compiler/README.md) contains the
Python package, tests, design notes, configurations, and study examples.
Shared decisions are in `docs/decisions/`; engineering rules are in
[agent.md](agent.md).
