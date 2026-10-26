# Changelog

## Unreleased

### Fixed

- MSD standard/2 changes only LOAD and STORE to 10 us each; measurement remains
  100 us and result processing zero. Full conditional injection/growth replays
  preserve all transport actions, stage boundaries and occupied spectator atoms.

- Raw-T now injects at d3 and grows to the requested target distance. The staged
  version-3 postselection API rejects only small-patch injection events, then
  executes ordinary target SE with an explicit decoded Pauli-frame handoff.
  Defaults retain three injection rounds; target growth uses d rounds. Probability
  caches separate the acceptance event from target delivery and reject stale
  all-d profiles. Injection transport planning accounts for unused target atoms.
  The previous all-d implementation remains an explicitly named control.

- Normal raw-T postselection now uses total SE rounds equal to distance, while
  preserving the raw-T primitive. Logical preparation calls explicitly carry the
  resolved round count. Protocol and fast-profile versioning reject stale
  two-round probability/cost caches; historical short rounds require an explicit
  control policy. The unchanged MSD layout, timing and illustrative noise support
  a new d3/5/7 acceptance and resource comparison.

- Readout placement searches geometry/occupancy-derived destinations when the
  nearest point, corners or fixed-grid anchors are occupied. Candidate search
  no longer scales with readout-region area; AOD ordering, capture and occupied
  positions remain checked. Finite execution windows can represent unlimited
  readout experiments without enumerating a huge grid.

- Full and fast factory-array experiments now select the theoretical joint
  15-to-1 MX checks with an explicit accepted-input Z-error parameter. The
  confirmed reference study uses p=0.01; raw rejection remains a separate supply
  model. Physical no-fault diagnostics include the full owned-carrier window,
  including raw loss and other patches' storage during retries, and no longer
  control theoretical output acceptance. Historical proxy mode requires explicit
  selection and retains its old artifacts and scope limitations.

### Added

- Complete d9/d11 surface component providers and explicit translation entries.
  A shared catalog and production command export all 16 supported operations per
  distance, including real S, carrier-rotating H, joint CNOT, fixed-d3 raw injection
  and conditional postselection/growth under the current 10 us transfer standard.
  Saved sources, templates, pending outputs, validation and resource metrics are
  kept together; full factory execution and decoded output LER remain separate.

- Distance-aware raw-T detector acceptance from actual compiled injection and
  repeated-SE traces. Explicit noise profiles, code/source/device fingerprints,
  exact small-space convolution and bounded-memory Monte Carlo with Wilson
  intervals replace the missing generic probability producer. Legacy d3 APIs
  retain their bounds and behavior. A fixed-standard d3/5/7 experiment includes
  zero-noise and analytic readout-only controls; accepted-state quality and
  generic joint preparation-class/fast-factory integration remain unsupported.

- Joint SE scaling on the unchanged vertical MSD world: all N W1 rounds enter
  one physical DAG and existing global scheduler. Full joint/serial/per-position
  solo traces, actual transport batches and signed phase-wise controls separate
  position cost from the net effects of shared scheduling without assuming
  independent hardware or attributing every residual to pure AOD contention.

- Odd-distance rotated-surface definitions and concrete components, preserving
  d3 source conventions and adding the d5 facade. Real S/Sdag, raw preparation
  with repeated-SE postselection, retained logical readout, transversal CNOT,
  and H with explicit carrier rotation follow the existing template contract.
  Generic joint preparation-class/canonicalization adapters remain future work.
- Versioned MSD timing and vertical-layout experiment standard, bounded compact
  component calibration, full-world exposure accounting, source fingerprints,
  a first-level benchmark plan and explicit second-level input requirements.
- Audited fast/slow/bench test tiers, explicit module/consumer selection, and
  per-tier outcome reports. Routine pytest excludes bench; expensive tests
  require an explicit profile or marker selection. Existing tests are retained.

- Explicit factory and downstream physical no-fault cost-proxy ports with
  disjoint scope evidence, once-only loss accounting and opt-in ideal routing.
  Actual noisy resource quality and logical success remain unknown. Raw detector
  events still use their actual compiled source; inventory and loss replacement
  are outside this experiment.

- Actual-source raw-A joint acceptance/byproduct events from explicit `noise/v1`
  Pauli/readout channels, retaining the complete occupied world and provenance.
  Noisy accepted-state quality is explicitly unsupported rather than inferred
  from rejection or a physical no-fault proxy.

- Code-owned six-patch 15-to-1 recipe, ideal joint preparation classes and final
  four-check reference probabilities; retained-atom logical X/Z readout and real
  local preparation corrections. The complete 102-atom layout supports serial
  composition with explicit resource consumption and reset boundaries. Global
  frame/decoding, full physical-noise factory qualification and supply policies
  remain outside this first pipeline.

- User-selected `noise/v1` illustrative raw-T postselection profile: two total
  SE rounds and twelve detectors, with explicit example/non-calibrated labeling
  and physical loss retained separately from Pauli/readout acceptance.

- Portable event-probability ports with immutable joint outcomes, local branch
  steps and complete model fingerprints. Surface-code producers estimate raw-T
  postselection and specified logical T-consumption measurement branches;
  the logical compiler owns occurrence sampling and dynamic case expansion.
  The detailed syndrome/decoder backend remains reserved.

- Required raw-T resource-use composition: preserve the one-round injection
  primitive, append at least one ordinary SE, and postselect four initial
  boundary detectors plus all adjacent-round syndrome differences. Results,
  detector readiness and final physical completion gate resource use; exports
  include the complete sequence without fabricating measurement values.

- Approved d3 physical logical Pauli, H with real six-stroke atom permutation,
  independent mid-cycle S/Sdag extraction, transversal CNOT, raw-T center
  injection and composed Y preparation. Relative templates retain explicit
  physical exits, participant identities, local syndrome relations and raw-T
  acceptance; source/action quantum checks and animation exporters are included.

- Callable d3 `initialize_0`, `initialize_plus` and `se_round` components using
  full N/Z stabilizer measurement, relative Atom IR binding and checked entry/exit
  layouts. Outputs preserve measurement identity, availability and symbolic
  correction relations; frame management and decoding are not implemented.

- `stim/v1` saved-result method with explicit `noise/v1` evaluation, native
  Clifford conversion, duration-aware channel insertion and stable measurement
  identity mapping. Loss/leakage remain separate from Pauli simulation.
- Standard rotated-memory preparation at d3/d5/d7/d9 with rounds=d, explicit
  surface-code homes for nonzoned and Search Smarter QEC, and Stim/PyMatching
  sampling with decoded failures and confidence intervals. Formal scans are not run.
- Configurable zero-default load/store Pauli channels alongside movement noise.

- Fast logical factory experiments with an explicit code/profile entry and the
  common factory state machine, event sampler and resource ledger. Offline
  calibration supports component timing and scoped no-fault estimates without
  per-case atom compilation. Accounting separates member work, shared busy time,
  makespan and software time; fixed-capacity seed sweeps keep physical validation
  marked not run and decoded logical success unknown.

- Code-declared joint and measurement component waves: corresponding translated
  transversal CNOT pairs share one AOD with both participants and signed relative
  geometry checked; MX/MZ retain nine distinct results per member. Local Pauli
  and canonicalization families align real physical pulses without a global
  Pauli frame. Same-entry factory-array controls use `max_parallel=1` with the
  same code, Device, seed and cohort policy.

- Synchronized factory arrays on one AOD with configurable shared/readout area
  and capacity budgets, cooperative stage barriers, independent retries and
  per-line success/failure resource histories. Costs select each line's actual
  atoms and preserve peer-wait exposure inside their factory evaluation windows.

- Shared-AOD component admission and physical grid composition. Same-component
  waves share rows and combine separate column bands with aggregate grid/readout
  capacity checks. The factory comparison defaults to one AOD, retains independent
  retries, and exports the actual Device inventory and fused-action evidence.

- Patch/component frontiers and declaration-based single-patch batching, including
  SE/S/X/Z, raw preparation and initialization. Actual lockstep composition retains
  full physical validation, independent raw retries and configurable AOD allocation.
  Same-device serial/parallel comparisons export component timelines and ledgers.

- Fixed-seed factory cost experiments with real raw rejection/reset/retry,
  disjoint physical no-fault proxies for batch acceptance and algorithm
  delivery, and static JSONL/CSV experiment ledgers. Proxy outcomes remain
  separate from unknown decoded logical success.

- Design documentation for protocol-aware fake measurement cases, T-resource
  consumption, factory acceptance/retries and shared resource scheduling.
  One AOD is an initial study configuration, with configurable resource interfaces
  reserved for future implementations; no runtime behavior changes.

- Explicit d3/d5 logical QASM entry points, code-owned component references,
  logical dependency construction and accuracy-checked Clifford+T synthesis.
  Initializers are named initialize_0/initialize_plus; safe H/inverse/phase
  reductions remove redundant gates. Outputs remain logical-only, with explicit
  source-profile, precision and expansion limits.

- Code-library and logical-compiler workspaces with independent rotated-surface
  d3/d5 component directories, shared contract/protocol locations and documented
  ownership. This is a documentation skeleton; executable interfaces remain open.

- Packaged `nadit view` for saved results and `experiment summarize --viewers`
  for anomaly exports, without depending on examples or rerunning compilation.
  Demo compilation now uses job/registry and delegates export to the same CLI.

- Independent replay size sliders for atoms, SLM sites and AOD spots (25–300%),
  with reset and fullscreen access; display multipliers preserve scene scaling
  and leave compilation, trace data and playback position unchanged.

- A reusable replay program strip with step/action/time previews, quieter storage
  geometry, and full-screen presentation with a HUD, playback controls,
  keyboard shortcuts and in-window fallback, based on the supplied redesign.

- Proportional scene scaling for replay atoms, trap spots and spatial highlights,
  without pixel-radius clamps; controls and labels retain their screen sizes.
  Atom/SLM/AOD marks and AOD lines are enlarged for easier presentation viewing.

- A physical-compiler configuration reference for external projects, people, and
  AI clients, covering architecture, Device, compiler, and experiment fields,
  defaults, supported combinations, complete examples, and invocation contracts.

- Optional Search Smarter QEC cross-layer reuse with immutable homes, separate
  placement/strategy adapters, safe lookahead boundaries, and a configuration
  switch. Existing per-layer return and adaptive implementations remain intact.

- Reusable viewer loss attribution and comparison: mean/max atom risk replaces
  all-survive, highlights the highest-risk atom, and compares load/store/move/
  residence contributions for all atoms and the highest-risk atom.

- Offline atom replay links a resource/action schedule to playback and optional
  noise reports: cumulative expected loss, per-atom risk coloring, final fidelity
  proxy and current-step leakage/native-channel inspection.

- Noise reports retain full upstream gate results, including native Kraus,
  unitary and superoperator channels, leakage diagnostics and model limitations.
  Deduplicated records are referenced by event; report revision v1.1 coexists
  with previous v1 estimates.

- Modular `noise/v1` post-processing: Stim-style per-event channels, pinned hsim
  magnetic/Raman/CZ channel adapters, configurable AOD transport/holder loss,
  exposure dephasing, and independent physical fidelity/loss estimates.
  Measurement identities and action/DAG references survive export; detailed
  transport dynamics remain an extension interface.

- Unified compiler registrations, canonical strategy kinds, per-compiler entry
  defaults, neutral experiment budgets, direct strategy overrides, compiler
  identity in provenance/run records/summaries, and registry-derived discovery.
- `shared/v1` reproduces the non-zoned example device and supports parameter
  sweeps. Whole-program adapters share admission and mandatory result validation.
- Device duration and saved-metrics validation; structured `search_exhausted`
  outcomes for IDS/A*, with a visited-node limit for IDS.

- Optional Search Smarter `mode=qec` restores user-supplied or generated storage
  homes after every layer. Share existing gate placement and transport, disable
  retention, and skip adaptive storage search. Expose named `search_smarter`
  selection, Python mode, discovery, JSON Schema, and an explicit-home example.

- Optional `entry.kind=enola_initial` reference placement using the pinned
  ENOLA SAPlacer with a private seed and deterministic budget. Preserve the
  explicit-layout provider and fixed-home execution; expose both in discovery
  and job JSON Schema. Initial scoring does not sample measurement branches.

- Per-circuit `nonzoned` strategy with explicit SLM homes, ENOLA-inspired dual
  candidates and strict batching, one pulse per CZ layer, and exact return.
  Reuse retained batch readout and measurement feedback. Expose job/Python
  selection, discovery, and JSON Schema with an eight-qubit example.
- Device `cz.allow_spectators` permits isolated atoms under global shared-array
  illumination; unexpected couplings remain invalid. Default false preserves
  the existing zoned semantic policy.

- Flexible AOD batch readout with Device `readout.max_atoms`, closed pickups,
  monotone readout layouts, multi-result Measure, and return to entry sites.
  Preserve singleton defaults, physical measurement identities, and feedback
  latency. Validate per-channel concurrent readout capacity.

### Fixed

- Component exit and readout times now follow the same ordered AtomStep additions
  as a concatenated physical program. Raw probability documents rebase their
  private timing records consistently at large absolute clocks, retaining public
  events, real gaps and delivery delays without loosening validation tolerances.

- Place GlobalRY participants inside its configured coverage before pulsing,
  including atoms retained in a gate zone; move illuminated spectators out.
  Preserve the pinned original trace and record the resulting placement change.
- Match source placement float accumulation boundaries and operation order,
  including candidate means, lookahead, group cost, and displacement deviation.
- Match the source IDS indexed min/max heaps when equal-priority alternatives
  are removed, replaced, and selected for another trial.
- Correct upstream initial-array row reset/end access, exhausted-window
  termination, nearest-column distance assignment, and straddled-y nearest-SLM
  arithmetic; record executable source differences separately from equal cases.
- Correct the source gate-column spreading boundary and use endpoint-specific
  pair separations instead of limiting column count or forcing direct fallback.
- Match source distance/candidate tie ordering and drain ready local rotations
  before CZ selection to expose independent gates in the same layer.
- Carry actual retained-atom snapshots between compilation layers instead of
  treating every occupied gate site as a reuse anchor.
- Clear nonretained pulse-region occupants before greedy or IDS gate placement,
  emitting the preparation transport and its duration. Local-control relocation
  can no longer create false cross-pair anchors.

### Changed

- Default viewer motion to diagonal departure followed by axis-aligned display
  lanes, with matching trails and synchronized AOD lines. Keep Atom IR and
  recorded timing unchanged; retain a direct-preview selector.
- Pause the unfinished rigid partial-release optimization in ADR 0028.

- Remove staged transport's two-column cap and Cartesian-mask completion.
  Cached source-template stages supply actual AOD capacity, spacing, workspace,
  and occupied intersections instead of broad geometry envelopes.
- Lookahead can use already compiled measurement results during planned
  feedback latency; actual conditional actions still wait for result availability.
- Reuse comparison reports both atom-load and atom-store counts alongside
  transfer batches and predicted transport time.
- QASM import now translates to a configurable native GateSet before building
  PhysicalDAG; the default basis is RX/RY/RZ/CZ.
- Measurement references use stable pre-translation source identities,
  independently of final native node IDs. Native children retain their source
  IDs and conditions, including conditional decomposition phases.
- Renamed the physical circuit module to `physical_ir.py` and its tests to
  `test_physical_ir.py`; package-level circuit exports remain available.
- Positioned full transport checks as test/debug reference tools, with legal
  construction as the default compiler route.
- Clarified the physical compiler route: compiler-owned DAG progress and
  planned state, with fake results sampled during measurement compilation.
  The existing event executor remains the DAG feedback reference tester.

### Added

- Add shared AtomActivity accounting and validated-result cost evaluation,
  additive/v1, and a lazy hsim-aqc adapter pinned to an upstream commit.
- Add fixed suites, Cartesian/zip/exclude experiment specs, isolated timeout
  workers, version/content locks, resumable JSONL, independent noise reevaluation,
  baseline statistics, coverage-aware Pareto summaries, and outlier commands.

- Add Device-owned pair arrays and zone roles, deterministic `zoned/v1`
  architecture generation, and exact reproduction parameter files for the
  existing five configurations.
- Declare strategy support before object construction, report unsupported
  jobs with CLI exit code 4, and expose `nadit describe` plus the job JSON Schema.

- Add `AOD.motion`, rigid MOVE and loaded-grid checks, and shared
  `TransportRules`/`RigidRules` selected by `rules_for` in placement and routing.
  Pair, sequential, and strict support rigid translation; staged and relaxed
  reject it before compilation or fallback.
- Add unlimited flexible, 16-by-16 flexible, and 16-by-16 rigid profiles with
  identical geometry and timing, plus a capacity/feedback comparison that
  saves validated self-contained results and checks final replay.

- Self-contained `nadit.result/2` documents with native DAG and Device snapshots,
  captured input hashes, location-independent job identity, and `git_dirty`.
- Independent CZ, addressing, readout, dependency, branch, and feedback checks;
  bounded failure details with complete counts, explicit Device overrides,
  and version-1 structural-validation compatibility.
- Saved example jobs and a result-document input for the offline viewer;
  existing example command options and output remain unchanged.
- `nadit compile`, `nadit validate`, and `nadit compare` commands with JSON
  output, documented exit codes, and optional Atom IR text export.
- Declarative `nadit.job/1` loading and a per-stage strategy registry, with
  resolved paths/defaults, explicit or automatic entry layouts, and stable
  source-measurement overrides.
- Optional result validation with the first transport constraint, source-operation
  coverage, or replay mismatch, separate from normal compilation.
- Shared compilation metrics used by saved results, examples, and the candidate
  benchmark runner, preserving the existing example output.
- Versioned `nadit.result/1` JSON serialization for all Atom IR actions,
  layouts, result records, Device snapshots, and software provenance.
- Offline Atom IR animation with sparse replay patches, step/time seeking,
  AOD and SLM geometry, pulse coverage, measurement availability, and atom
  inspection. Includes two feedback outcomes and a compiled 60-atom example.
- Complete pinned C++ static-stage traces and first-divergence comparison,
  preserving original source failures separately from matching executions.
- Original capacity-based ASAP scheduling and endpoint-priority reuse policies,
  alongside the existing measurement-feedback and complete-edge policies.
- Multi-region gate catalogues, union CZ coverage, global RY and addressed U,
  source integer-unit staging offsets, and cross-zone transport batches.
- A* using shared placement candidates/scores, the paper's distance-to-time
  profile, and a saved-input 26-circuit benchmark and ablation runner.
- Source-layout SLM geometry, cached nearest-SLM/site queries, automatic initial
  storage placement, and configurable candidate windows with source expansion.
- Original gate-option score-distance metadata and full-free-array score ranks,
  with executed pinned C++ candidate and search-node comparisons.
- Optional relaxed routing with source-aligned compatibility, weighted conflicts,
  donor-group redistribution, and a configurable strict-fallback cost threshold.
- Device-admitted row/column reordering using the existing staged generator and
  explicit-grid Atom IR, with finite-capacity and occupancy constraints.
- Executed pinned C++ router and reversed-axis movement comparisons, plus
  measurement-feedback and per-action replay coverage.
- Staged strict transport with distance-ordered groups, row/column pickup,
  lattice offsets, combined transfers, and explicit AOD-grid Atom IR.
- Regular SLM staging geometry with optional explicit pitches and direct strict
  fallback for regions without the required space or supported geometry.
- A pinned upstream C++ rearrangement harness and small-case event comparison,
  plus staged feedback, per-action legality, and exit-replay coverage.
- Source-aligned routing-aware placement with full gate/storage candidates,
  compatible movement-group scoring, partner lookahead, and bounded IDS.
- Optional retention in the storage-placement search: matched atoms can stay
  at a gate site or return to storage according to the reference proxy score.
- An IDS placement mode and search configuration in the multi-pair study,
  sharing strict transport, measurement feedback, and action replay.
- Pure next-CZ preview using compiler progress and compiled results, stopping
  at unresolved feedback without sampling measurements.
- Maximum matching of shared CZ endpoints and reuse-aware placement that
  retains gate-site anchors across partner changes and addressed rotations.
- Optional `reuse_analyzer` strategy composition and `--reuse` study switch,
  with feedback, pulse geometry, strict transport, and terminal replay tests.
- Separate atom-load and transport-time metrics: reuse reduces loaded atoms
  in the current study but can increase strict batch count and duration.
- Shared strict movement rules, a pairwise conflict map, batch row/column
  capacity checks, stable endpoint frames, and a distance-based batch cost.
- Strict parallel transport with fixed-point source/target occupancy closure
  and direct common LOAD/MOVE/STORE actions.
- Sequential/strict comparison on the existing multi-pair example and
  independent tests for phase legality, capacity, ghosts, feedback, and replay.
- Multi-pair correctness baseline with explicit isolated SLM-pair catalogues,
  capacity-limited CZ layers, distinct pair assignments, spectator clearing,
  and storage returns between layers.
- Sequential singleton transport using an occupancy index and destination
  vacancy ordering, plus one shared CZ pulse for every placed gate layer.
- A multi-pair QASM example covering changed interaction partners and
  measurement-conditioned CZ layers, with geometry, timing, and replay tests.
- One-pair native-DAG-to-Atom-IR compilation, connecting ready-layer selection,
  fixed SLM pair placement, grouped/singleton AOD transport, and pulse emission.
- Compile-time measurement sampling with stable identities, conditional action
  selection, preserved phase, and explicit feedback waits.
- Device CZ, local-control, and readout capability records with optional JSON
  fields, plus direct atom-state replay for retained readout.
- An executable two-atom QASM study, explicit device configuration, and tests
  comparing constructed transport, replayed exit state, and selected branches.
- Separate parsing, native translation, and DAG adaptation modules, using the
  existing Qiskit dependency and a per-import gate-translation cache.
- Gate-layer, placement, and Atom IR fragment records with small scheduling,
  reuse, placement, and transport protocols.
- Immutable Atom IR actions, parallel steps, program timing, and Stim-style
  text output, with source-operation links and stable measurement references.
- A concrete atom program example covering transfer, movement, pulse,
  rotation, AOD-held readout, and feedback waiting.
- Flexible device geometry and JSON loading, explicit atom/holder and active
  AOD line state, and collective loading, movement, and unloading checks.
- A small zoned device fixture with 5 um storage spacing, paired gate sites,
  and a measurement region without SLM traps.
- Device and zoning design separating fixed SLM sites, interaction candidates,
  AOD motion, pulse coverage, and AOD-held measurement.
- A staged physical compiler implementation plan with file ownership and
  acceptance criteria, starting with the flexible zoned pipeline and then
  the rigid 16-by-16 variant.
- A Python 3.12 physical compiler package with OpenQASM 2.0 and 3.0 loading
  functions for static operations and single-bit measurement feedback.
- A device-independent Physical DAG with operation records, quantum and
  classical wire dependencies, register metadata, and global phase.
- Same-source custom-gate expansion and explicit rejection of unsupported
  control flow and external includes. Text and file input accept only
  the standard `qelib1.inc` (OpenQASM 2.0) or `stdgates.inc` (OpenQASM 3.0).
- Measurement-occurrence references and fixed single-bit conditional bodies,
  including `if` / `else`, with explicit result dependencies.
- Dependency execution traces with reproducible fake measurement results,
  explicit result overrides, and result latency separate from operation time.
- Module-local dependency locking, frontend and IR tests, formatting, linting,
  and type-checking configuration.
