# MSD experiment standard

The continuous campaign integration is in progress. `campaign_worker.py` connects
explicit offline calibration tasks, bounded witnesses, continuous pilots and
fixed-window production to the existing isolated experiment runner. The fast
kernel only reads exact joint records; a missing frontier becomes a deterministic
dependency request. `campaign_policy.py` freezes the observation window from a
preset rule and the pilot's complete worker cost, including calibration/replay.
`production_metrics.py` accounts for whole-world joint actions once and checks
output consumption/release against the resource ledger.
Current task records separate `process_wall_s` (launch through observed exit,
including startup) from child-reported `worker_wall_s`. Pilot allocation uses the
former; older records fall back to their explicitly labelled legacy timer.

The first server configuration is
[`campaign-single-aod-20261025.json`](campaign-single-aod-20261025.json): single-level
d=3/5/7 and equal-distance L1/L2 pairs (3,3), (5,5), (7,7). Different target
distances across levels are a separate disabled extension, not an acceptance or
submission prerequisite. Every target distance retains the existing d3 injection
with three postselected SE rounds followed by accepted ordinary code growth.
The approved limits are four workers, 8 GiB per worker, 24 hours, 50 GiB of
artifacts, and 5,000 atoms. Load/store remain 10 us, measurement 100 us and
classical processing 0 us, with one AOD and unchanged noise parameters.

The staged follow-up configuration is
[`../analysis/msd-two-level-3600s.json`](../analysis/msd-two-level-3600s.json).
`python -m experiments.analysis.msd_two_level_scan` waits for the existing L1
campaign to close and release its workers, verifies its original results, and
freezes the L2 candidate pool from those arrivals. It uses the same-distance
d3/5/7, N2=1/2, capacity=1/2, columns=1/2 and three layout-family axes, with the
existing 12-cell selection rule and 16 production seeds. All new calibrations
have a 3,600 s cap. Timed-out L1 calibration queries are supplementary new tasks;
their original failures and production trajectories are not relabeled.

The follow-up spends only the remaining original 24-hour/50-GiB budget, with
four workers total and the existing export reserve. It does not launch a second
concurrent pool. No remaining budget means an explicit excluded handoff. The
CLI requires `--config`, `--upstream`, `--upstream-plan`, `--output`, and `--gate`
paths; its sibling `*-control/status.json` records queued/running/terminal state.
Core acceptance is reused only when the complete original core source hash and
reference-path selection match byte-for-byte. The new adapter/configuration are
additionally frozen in the execution identity. Historical L1 source identities
and original result hashes remain intact.

The scan report checks each full result and case hash before retaining its
metrics, computes supply diagnostics from that case, and loads representative
schedules singly. This avoids retaining the full multi-seed execution corpus in
one worker. Existing statistics and native-action exporters are reused. Saved
representatives have publication hashes for checked reuse after interruption.

Continuous execution requires an explicit output sink. The currently selectable
`ideal_external` capability requires `acknowledge_excluded_costs: true`: external
transport, consumption and external reset costs are excluded, while the factory's
next-cycle preparation remains counted. It is not a physical delivery protocol
and is not selected automatically. The same-atom `BlockTranslationComponent`
uses existing native transport into explicitly vacant sites. Native goals can
share a frontier with SE, gates and readout. Offline joint calibration and its
cache accept explicit `transport_targets`; keys include the current complete
world and destinations, and goal endpoints are checked without relaxing the
return-home rule for ordinary frontiers. `OutputHandoff` retains reserved tokens
and distinguishes producer replacement from terminal consumption. The ledger
can record referenced transport intervals and lease a free carrier without
incrementing its preparation epoch. The fast kernel commits validated world and
binding transitions after full-wave admission; missing calibration tasks carry
the current world snapshot and exact destinations. Runtime role exchange requires
committed transport receipts and an unchanged token identity. Explicit empty
buffer grids add no atoms and retain existing control/timing capabilities.
`FactorySupply` now connects actual accepted L1 tokens to L2 through a finite,
producer-held FIFO and three same-atom relocations per input. Both levels retain
one clock, world, ledger and AOD. A terminal consumer stops further production;
an already-running surplus output is retained rather than silently released.
`msd.two_level_witness` runs finite same-distance production. The
`msd.two_level_pilot` and `msd.two_level_produce` adapters use the existing pilot
and frozen-window policy contracts, counting all physical work but only L2
outputs in the output denominator. In-flight producer drain may extend the case
past the observation window; it does not enlarge that window.

A saved d3, 1+1-factory native case produced one L2 output at 1,473,819.017 us
and completed surplus retention at 1,537,917.207 us. Independent saved-action
replay verified 15 unique inputs, four adoptions, eleven consumptions, 45
relocations and 241,537 native action rows. The 204-atom case used a capacity-one
buffer, but did not trigger buffer-full waiting. This is finite-cycle acceptance,
not steady-state scaling or a logical-error result. Local evidence is under
`modules/physical_compiler/artifacts/msd-goal/local-two-level-d3-read-index`;
its sibling source archive records source hash
`80273225162f15800dae992c8d808fdccc0117750596c236c436187ad4d06e17`.
The continuous policy adapters were added after that snapshot and have separate
fast interface checks. Arrival-driven candidate generation and its dependency
drivers are connected; formal multi-stage results, cross-distance delivery and
server submission remain unfinished.

Optional derived read indexes accelerate complete-cache lookup while retaining
byte hashes of the original action, trace and probability artifacts. Lookup is
read-only. `msd.prepare_cache` builds indexes for explicit hash-checked completed
queries with both scientific producers disabled; its setup cost is recorded.

The bounded native acceptance entry is
`python -m experiments.analysis.joint_translation_acceptance --output <new-dir>`;
add `--cached` for a forward/backward current-world cache witness. Its explicitly
vacant receiver is a fixture, not a complete L1/L2 production run. The ordinary
mode exports native action schedules as CSV; cached mode retains exact traces.
The runner also accepts `msd.transport_witness`, which explicitly acknowledges a
prepared-token fixture and exercises three physical relocations plus SE through
the fast kernel, current-world calibration tasks and atomic role exchange. It is
not a distillation-output source and cannot satisfy the full two-level gate.

`campaign.py resolve` expands an explicit configuration into independent layout
drivers and a terminal summary. Each driver requests its pilot, persists a fixed
observation policy, then requests the production seeds. The standard d=3/5/7,
N=1/2/4/8 factor-grid axes give 30 layouts and 480 trajectory identities. Missing
budget fields or sink acknowledgement are errors; no server defaults are filled.
Without source-matched interface evidence the resolved plan stays non-runnable,
and single-level resolution never declares two-level readiness.

An explicit `two_level` configuration adds a terminal-dependency Stage 3 driver.
It reserves `worker_seconds_fraction` of the available worker budget before L1
pilots are allocated. Its `candidate_rule` declares distance pairs, L2 counts,
buffer capacities, grid columns, layout families, production seeds, minimum
arrival-seed coverage, the existing 40 um parking gap, and finite common atom/SLM
footprint budgets. Arrival hashes are resolved automatically after L1 completes;
they cannot be supplied as stale configuration. Separate pilot seed, observation
rule, retry/cycle/call limits and theory-transport acknowledgement are required.
No default server quota or observation window is inferred.

An optional `max_candidate_layouts` freezes a bounded selection from all eligible
geometry/capacity cells; the first configuration uses 12. Distances take turns in
ascending order. Within each distance, N1/N2 pairs rank by the best independently
eligible source group's minimum complete-seed arrival rate divided by 15*N2,
then fewer atoms and counts; cells rank by columns, family aliases, geometry and
capacity. This is a declared budget priority, not a throughput prediction or
optimality claim. The plan saves scores and source evidence. Unselected cells
remain `selection_excluded` in coverage and reports, and receive no worker budget.

The optional `pilot_cost_model.mode: cached_replay` measures an identical-seed
warm replay after the cold pilot. All preparation, calibration and replay costs
are charged once; the successful warm worker determines the per-cycle slope.
The first configuration reserves 25% of remaining layout worker-seconds for
future misses before allocating fixed windows. That reserve is a planning rule;
the runner's unchanged time, memory and storage caps remain authoritative.

The driver verifies actual saved L1 task/result/policy identities and output
lifecycles, then freezes arrival evidence and candidates under `two-level/`.
It never multiplies a singleton rate by N or merges seeds into one arrival stream.
Each original layout/seed must supply the predeclared coverage for a candidate.
Equivalent layout families share geometry metadata; different buffer capacities
have distinct policy/statistics identities. Allocated area includes the empty
parking grid. The geometrically local layout still uses the same global FIFO.
Cross-distance protocols and missing sources remain explicit dependencies.
Equivalent physical cells from different L1 source groups execute once, while
each group's independent eligibility and original seed evidence remain visible.

Each admitted two-level cell uses the existing pilot-to-production driver. Only
L2 terminal outputs determine its frozen window, while costs include all levels.
The final summary exports separate `report/single-level/` and `report/two-level/`
results and retains failed, excluded, unsupported and not-run entries. This
multi-stage orchestration currently has fast integration evidence; it is not a
completed 480-trajectory campaign or a server execution result.

Supply reports integrate buffer occupancy and consumer starvation/producer
backpressure over the frozen observation window. Slot residence age includes
entries until explicit removal; unconsumed-output age is reported separately,
from L1 ready to ledger consumption/discard. Neither quantity is an inferred
logical error probability, and missing legacy timestamps yield unknown metrics.

From the committed source and existing Python 3.12 environment:

```text
python -m experiments.msd.campaign resolve --config campaign.json --output /absolute/server/run --resolved-plan resolved.json --acceptance-evidence interface-audit.json
python -m experiments.msd.campaign run --plan resolved.json --output /absolute/server/run
python -m experiments.msd.campaign resume --plan resolved.json --output /absolute/server/run
python -m experiments.msd.campaign status --output /absolute/server/run
python -m experiments.msd.campaign summarize --plan resolved.json --output /absolute/server/run --plots
```

For a configuration containing `two_level`, resolution additionally requires
`--two-level-evidence physical-two-level-audit.json`, matching the frozen source.
The reproducible first-campaign acceptance entry is:

```text
python -m experiments.analysis.msd_campaign_acceptance --output /absolute/new-acceptance-directory
```

It uses the configuration's identical `source_paths`, runs six bounded initial
tasks through the existing runner, independently audits their saved evidence,
exports native schedules, and checks that resume dispatches no new work. The
resulting `interface-audit.json` and `two-level-audit.json` are the resolution
inputs. This diagnostic uses 64 calibration shots; formal sampling remains 1024.
`--allow-dirty` is for preliminary inspection only and never emits passed final
gates. Final acceptance and packaging require clean committed source.

Configuration separates calibration sampling, pilot seed and production seeds,
the observation rule, physical retry/cycle/call limits, and worker/time/storage
budgets. Explicit `export_reserve_s` and `export_reserve_bytes` are carved out of
the hard campaign caps. Ordinary work stops at the reserve boundary while the
terminal summary may continue inside the unchanged total limits. Resolution
preserves the target host path; execution cannot relocate it
or replace an existing resolved plan. Representative exports include component
receipt spans and, when saved calibration records are supplied, native action
schedules counted once per joint wave. A sampled storage overshoot or downtime
can still exhaust the hard cap before summary completion; the runner records
that failure and retains its durable status. Multi-stage package acceptance also
requires the source-matched two-level delivery evidence; code-test success alone
does not enable that gate.

For the distance-generic fast factory and inspectable resource schedules, see
[the joint single-AOD factory experiment](JOINT_FAST_FACTORY.md). It uses the
existing logical runtime and shared-AOD claims with actual joint-frontier
calibration and retained cohort barriers. The previous whole-component-exclusive
[generic results](GENERIC_FAST_FACTORY.md) are withdrawn as parallel acceptance.

For actual simultaneous N-factory SE execution, use the
[parallel SE experiment](PARALLEL_SE.md). The single-component survey below
remains a position-dependent calibration, not a concurrency measurement.

The current raw-T protocol uses fixed d3 injection followed by ordinary growth.
See [the 10 us transfer animation](TRANSFER_10US_ANIMATION.md). The
[all-d experiment](RAW_T_DISTANCE_ROUNDS.md) and
[two-round results](RAW_T_ACCEPTANCE.md) are historical controls.

The accepted experiment uses real code-owned logical S components. Measurement
takes **100 us**, classical result processing **0 us**, and each SLM/AOD transfer
**10 us** under `nadit.msd.standard/2`. Standard/1 used 100 us transfers; its saved
results are unchanged and must be reproduced from their recorded source revision.
All other capability/timing values come from the existing d3 CNOT
reference: CZ 0.5 us, rotation 1 us, reset 5 us, movement 1 us/um. This is a
comparison standard, not a calibrated hardware specification.

`standard.py` builds an explicit six-patch world for odd distance d and any
positive integer N, including N=3. Roles W1..W5,R run left to right; factory rows
run top to bottom. Positions come from the shared logical
[placement module](../../modules/logical_compiler/docs/placement.md), while this
file retains Device, SLM-site, atom identity and binding construction. The code
owns its actual components; this experiment does not implement another scheduler.

## Geometry and resource interpretation

Cartesian y increases upward. Storage and gates occupy y<=0; readout occupies
y>=50 um. The intervening 50 um strip is transport-only. Both operating domains
are mathematically unbounded. The existing physical `Region` API remains finite:
each run derives an enclosing execution window from its actual source geometry
and worst-case readout row demand. The window is not a hardware footprint budget.
Compare an enlarged window to check it does not determine the measured result.
An empty enlargement can change a symbolic CZ coverage rectangle; acceptance
compares the replay-time illuminated atom identities as well as all actual
targets, trajectories and times. Spectator illumination remains part of exposure.

Area metrics distinguish configured home-block footprints and actual visited
coordinates. Fixed home-area-time is labelled explicitly; dynamic occupied
area-time is not inferred from movement endpoints. No area metric uses the ideal
half-plane or finite execution window. The baseline has one flexible
AOD with the reference's unbounded row/column counts; finite capacities can later
define separate matched-budget experiments. Order, line spacing, capture closure,
occupancy and pulse semantics still constrain concurrent operations.

`VerticalFactoryPlacement` reproduces the original default coordinates exactly:
role j in factory i has origin `(j*(20*d+patch_gap),
-20*d-i*(20*d+factory_gap))` in micrometers. Both default gaps remain 40 um.
`build_world(spec, placement_plan=plan)` also accepts a validated explicit plan;
the world builder independently checks the requested blocks, code geometry and
storage half-plane. Its exported `placement` metadata is separate from the
unchanged default Device and entry-state records. Changing positions does not
select readout destinations or qualify component compatibility.

## Deliverables and status

- `level1_plan.json`: independent d/N axes, frozen timing and geometry, metric
  definitions, proposed production observation windows and explicit run limits.
- `standard.build_world(ExperimentSpec(...))`: complete Device, AtomLayout and
  code-owned ComponentBinding records, exportable via `.document()`; an optional
  PlacementPlan supplies user-selected initial/return positions.
- `calibrate.py`: compact statistics from an actual component source lowered by
  `compile_physical` and `NonZonedStrategy` in the complete spectator world.
- `../../docs/experiments/msd-interface-audit.md`: actual integration APIs and the
  remaining external fast-runner/vertical-parallel admission dependencies.

Component calibration reports no accepted-output throughput or output error.
All other factories are idle spectators in each calibration cell. A pipeline
count axis therefore measures the physical world and location dependence, not
parallel production speedup. The compiled physical measurements are case
fixtures; this is not a noisy quantum-state simulation or hardware execution.

The current production adapters above use sustained logical execution, explicit
output lifecycle, rejection/retry accounting and the existing EC policy. The
single-component survey described here remains a historical calibration tool,
not a production benchmark. Whole-factory timing comes from complete joint
frontiers, including final MX. Two-level sizing uses measured accepted arrival
traces; unknown output quality remains unknown.

## Reproduction

Use the existing Python 3.12 physical-compiler environment, with this checkout's
`modules/physical_compiler/src` and repository root on `PYTHONPATH`. No dependency
changes are needed. From the repository root:

```powershell
$env:PYTHONPATH="$PWD\modules\physical_compiler\src;$PWD"
python -m experiments.msd.calibrate --distance 3 --pipelines 1 --operation logical_s --output output/d3-n1-s.json --witness
python -m experiments.msd.survey --output output/component-survey
python -m experiments.msd.plot output/component-survey
python -m pytest experiments/msd/tests -q
```

`--factory-index` selects the actual row; default 0 is closest to readout. Use
the final index N-1 to assess the bottom row. `--padding 1000` repeats the cell
with an enlarged execution window. Output files are exclusive-create and retain
source/device identities. `compile_wall_s` measures host calculation time;
`execution_duration_us` measures planned device time. These are different axes.

`transport_elapsed_us` is the union of transport time intervals, while
`transport_action_sum_us` sums Load/Move/Store action durations including any
concurrency. Atom idle/busy costs include every retained spectator and conserve
`atom_count * execution_duration_us`. Exposure is broken down by actual action
type; an error probability must be computed with a separately named noise model.

The survey enforces subprocess timeouts, a campaign time limit and an atom-count
admission limit. It fingerprints physical, code and experiment sources, stops if
they change, records failed/censored cells, limits numerical library threads,
and saves compact rows plus one full d3 S witness. Its default 72 cells cover
d=3/5/7, N=1/2/4 and eight components, always at the bottom factory row. `raw_t`
is the primitive; required repeated-SE postselection is separately implemented
in the code library and verified by component contract tests. These calibration
cells do not constitute the complete factory production cycle.
