# Two-level MSD synchronous scan preparation

Date: 2026-10-25 (Asia/Shanghai).
Status: **prepared; awaiting user approval for implementation and experiments**.
Historical status above records the preparation revision. The user subsequently
approved execution on ZeroTier network `166359304ed7c7a5`. The executable adapter
uses [level2-sync-server-scan.json](../../experiments/msd/level2-sync-server-scan.json);
its source commit is supplied to the frozen-run manifest, avoiding a self-hash.
The preparation JSON remains the immutable parameter reference. Local readiness
passed 165 related fast tests and three one-shot controls; remote validation and
the full matrix must still succeed before any experiment-complete claim.
Implementation baseline: `6db07b9`, branch `codex/msd-level2-factory`.
Current execution status (2026-10-26): the approved 30 s attempt stopped on a
shot timeout. The user subsequently authorized a larger-budget continuation;
see the [stop and continuation record](msd-level2-sync-continuation-20261026.md).
The historical preparation parameters below remain unchanged.
Decision: [ADR 0056](../decisions/0056-single-consumer-synchronous-msd-scan.md).
Frozen parameters: [preparation JSON](../../experiments/msd/level2-sync-scan-preparation.json).

## Authorization and scope

This revision records the user's latest choices: synchronous L1 only, one L2,
89 single-thread workers, 30 s per shot and the corresponding 3060 s per
100-shot cell. It supersedes the earlier dual-policy 540-cell / 54000-shot
proposal and its 16-worker / 20 s shot / 2060 s cell limits. The batch cap stays
24 hours. Historical async code, results and local acceptance configs remain.

Preparation is authorized; implementation changes, tests that execute factories,
server preflight, job submission and experiment execution are not authorized by
this document. Stop after preparation and wait for the user's explicit approval.
There is no runnable scan command for this preparation schema yet.

## Frozen experimental matrix

| Axis | Values |
| --- | --- |
| Target distance | 3, 5, 7, 9, 11; d1=d2=d |
| L1 factory count | 1, 2, 4, 6, 8, 10 |
| L2 factory count / pipeline count | Exactly 1; not a scaling axis |
| L1 policy | synchronous/v2 only |
| L2 policy | Independent single consumer; no cross-level stage barrier |
| Supply queue | B=1, producer-held output states |
| Added storage blocks | 0 |
| Parking | 1 vacant block-sized location |
| Seeds | 0..99, 100 per cell |
| Shot endpoint | One completed L2 attempt, then drain admitted work |
| Output sink | Ideal external sink only after L2 |

| N1 | Complete rectangles (rows x columns) |
| --- | --- |
| 1 | 1x1 |
| 2 | 1x2, 2x1 |
| 4 | 1x4, 2x2, 4x1 |
| 6 | 1x6, 2x3, 3x2, 6x1 |
| 8 | 1x8, 2x4, 4x2, 8x1 |
| 10 | 1x10, 2x5, 5x2, 10x1 |

There are 18 N1/array combinations. Each has three L2 positions, five distances
and one L1 policy: **18 x 3 x 5 = 270 cells; 27000 shots**. Nonsquare orientations
are distinct. Only identical carrier identities, coordinates and resource
constraints are aliases; validate the complete manifest before dispatch.

## Exact layout and delivery definition

Use existing code-owned geometry. For the recorded surface catalogs, block
extent b=20d um, internal and inter-factory gaps g=40 um, factory width
w=6b+5g, and slot pitches px=w+g and py=b+g. Do not rotate or reorder a
factory's six internal roles W1-W5,R.

For an R-row, C-column L1 array, factory i has column c=i mod C and row
r=floor(i/C), with base origin `(c*px, -b-r*py)`. Role j is offset by
`(j*(b+g), 0)` inside that factory. Stable identities remain `L1-factory{i}`
and `L2-factory0` across all layout variants.

| L2 position | L2 factory origin | L1 modification |
| --- | --- | --- |
| below_center | `((C-1)*px/2, -b-R*py)` | None |
| right_center | `(C*px, -b-(R-1)*py/2)` | None |
| above_center | `((C-1)*px/2, -b)` | Shift every L1 factory down by py |

Half-pitch translations are allowed; they do not imply physical code rotation.
Compatibility and cost binding must use the resulting actual coordinates.
After placing both levels, place parking at `(factory_union_x_max+g, -b)`.
Its footprint is b x b. Include it in the reported storage bounding box.

Each handoff retains its original token, carrier and epoch and consists of:

1. Reusable receiver block to parking.
2. Producer output block to the receiver position.
3. Parked reusable block to the producer position.

Every leg costs Load 10 us + Euclidean distance times the catalog movement
coefficient + Store 10 us. Current catalogs use 1 us/um. Commit each completed
leg's actual position/version, then commit role exchange after all receipts.
No extra SE/reset, free teleportation, token copy or physical compilation is
added. Transit clearance remains the declared object-model assumption; this is
not atomic collision validation. Both readout and inter-level distances vary
with layout. Storage/gate y<=0 and readout y>=50 um remain unchanged.

## Supply, synchronization and stopping

L2 initializes W1 locally, adopts four distinct L1 outputs into W2-W5, then
consumes eleven further outputs through R at the existing recipe boundaries.
Do not require four or fifteen simultaneously queued states. Accepted L1 inputs
are not re-injected, postselected or grown again by L2.

B counts published, reserved and in-transit entries until committed delivery.
Delivered R remains reserved until injection, although it no longer occupies a
queue slot. Pending publication remains on its producer carrier, at most one
output per producer, and prevents that carrier's reuse. Parking adds no atoms.
Audit queue entry, carrier occupancy and consumption as separate transitions.

The existing demand-driven activation remains: L1 production continues on one
timeline while demand exists; no speculative prefetch or new nearest-source
policy is introduced. Freeze and verify deterministic admission/FIFO semantics,
including pending-to-published ordering, rather than claiming a stronger global
ready-time order than the current implementation establishes.

All L1 factories belong to the synchronous cohort. Raw successes wait for local
peer retries; conditional S+SE branches join before the next deterministic stage.
Final acceptance makes output available immediately; rejection still finishes
the attempt. No barrier waits for the kth successful T. L2 and supply can progress
while L1 members wait for handoff/round completion. Capacity waits hold no AOD.

The L2 final decision, accepted or rejected, closes new demand after this one
attempt. Drain already-started L1 rounds and admitted exchanges. Record any
surplus as retained on its actual carrier, not consumed or released. Such retained
surplus is a valid terminal round disposition. Include drainage in total time;
report L2 completion and drain tail separately. No success quota retries L2.

Retain existing local safety limits: 32 L1 rounds per producer, 32 raw attempts
per preparation, batch limit 16 and 10000 component calls per factory. Budget
exhaustion is an execution error that stops the scan, not a valid zero-output
sample. Ordinary final rejection is a valid sample. Never increase these limits
automatically when an unlucky trajectory exhausts them.

## Timing, probability and model provenance

Use surface code and recorded logical S implementation costs, not transversal S.
Measurement is 100 us, classical processing 0, Load/Store 10 us each. All other
timing and noise inputs come unchanged from the five numeric catalogs named in
the JSON. Their canonical fingerprints are frozen there.

Injection remains d3 with three total SE rounds and injection-only postselection.
Accepted inputs grow with ordinary SE/decoding: 0/5/7/9/11 growth rounds for
target d=3/5/7/9/11. No target-wide syndrome postselection is added.

Keep original raw acceptance ports and accepted raw-input Z-error p=0.01. The
existing iid theoretical L1 output quality supplies the L2 input model. Prepare
theoretical ports once per model input; layout, waits, transport and policy do
not re-estimate probabilities. Preserve the future code-family boundary. These
theoretical errors are not actual decoded LER, so this scan makes no real
output-error-matched or hardware-optimality claim.

## Worker and timeout budgets

| Limit | Frozen value / interpretation |
| --- | --- |
| Wave planning | 5 s |
| Shot | 30 s, including execution, metrics and selected trace serialization |
| Seeds per cell | 100 |
| Cell startup allowance | 60 s |
| Cell / worker | 3060 s = 100 x 30 + 60 |
| Concurrent workers | At most 89, one thread per selected physical core |
| BLAS / OpenMP threads | 1 per worker |
| Entire scan | 86400 s (24 h), unchanged from the preceding two-level design |

The 89-worker cap is inherited from the prior scan, not a claim of measured
80 percent CPU utilization. After approval, verify current CPU, memory and disk
availability; do not assume the old server's free resources persist. If the
requested allocation cannot fit, report it before submission rather than silently
changing the frozen workload or oversubscribing cores. No remote preflight occurs
in this preparation task. The 3060 s cell cap does not change historical local
60 s worker configs or the previous scan's saved parameters.

The aggregate cell-wall allowance is 270 x 3060 = 826200 s (229.5 worker-hours),
not measured CPU time. Four full batches of 89 slots would cover 270 cells;
4 x 3060 = 12240 s is only an idealized budget calculation, not a runtime forecast.
The global cap remains independent of this arithmetic.

First error or timeout: stop dispatch, terminate only this scan's owned children,
save cell/seed/stage, last progress, original cause and committed resource prefix,
and mark the run incomplete. Never retry, resume, skip a cell, relax a budget or
present a partial matrix as complete. Do not touch older server tasks/results.

## Reuse and readiness gaps

Keep this branch's supplier, delivery profile, shared runtime and schedule viewer.
Single-level reference source is `12816435bfa0599a4c44c937a02b969b3a1e4438`, with
report code at `634d5f1`, in the sibling `msd-object-scheduler/NADiT` worktree.
Its generated results are untracked/ignored and are not transferred by commits.
Audit exact files before selective reuse; no whole-branch merge or adoption of
unrelated uncommitted edits.

| Existing owner | Readiness requirement before an approved run |
| --- | --- |
| `object_delivery.py` / existing placement | Add three L2-position rules; current entry only places L2 below-left |
| `factory_level2.py` | Bind frozen scan parameters, preserve one attempted L2 round and all surplus/drain accounting |
| `object_supply.py` / cooperative runtime | Verify multi-producer B=1 publication ordering and synchronous liveness; reuse existing contracts |
| Sibling `scan_objects.py` | Adapt the existing bounded runner; its current single-level entry cannot execute this record |
| Sibling `scan_metrics.py` / `object-motion-reference.json` | Reuse numeric motion reference and aggregation; add whole-block delivery, real receipt carrier IDs and L2 waiting metrics |
| Sibling `report_object_scan.py` / HTML | Reuse uncertainty/report logic; use d/N1/layout axes with N2=1 and only one L1 policy |
| Current `factory_schedule.py` | Preserve complete saved traces, delivery/parking and retained-output labels |

In particular, static `factory/role` occupancy and component-name-only motion
lookup are insufficient after carrier handoff. Delivery atom-distance is the
sum of whole-block atoms times each leg length; AOD command distance counts
each actual shared movement once. Neither is reconstructed from atom trajectories.

After user approval, readiness requires relevant fast checks and bounded local
controls before server submission, plus frozen executable source/config hashes.
Any failing readiness gate stops progression. No implementation tasks are marked
complete merely because this preparation has been documented.

## Statistics and deliverables

At fixed d/N1, layout comparisons share one AOD and atom count
`6*(N1+1)*(2*d*d-1)`; maximum in the matrix is 15906. Include all configured idle
carriers once. Across d/N1, report actual atoms, width, depth, bounding area and
Pareto tradeoffs; do not claim a fixed-atom comparison. Do not introduce a new
physical storage/readout capacity limit. Full device/readout/swept area is null.

Primary rate is sum(L2 accepted outputs)/sum(drained shot duration), not the mean
of reciprocal durations. Resource-time per output includes all valid failed
shots. Report sample means/unbiased variances (m-1), separate ratio-estimator
variances and 95 percent intervals. No-output startup is null; report conditional
startup, no-output frequency and the explicit independent-restart startup estimate.
These finite shot-restart statistics are not continuous-pipeline steady state.

Required metrics: L2 starvation and scheduler waiting, recipe computation versus
delivery, first output/L2 completion/drain completion, L1 attempts/rejections,
barrier/backpressure, queue time-weighted occupancy and token residence, retained
inventory, AOD occupancy and sharing, Move/Load/Store, atom/command distance,
operation counts, allocation-based idle exposure, actual runtime/RSS and reuse.
Do not double count overlapping input waits or add resource times to makespan.

Audit shared semantic events for the same seed/level/factory/round/model across
layouts. Demand and backpressure can change the executed L1 prefix; compare
common events and conservation, not necessarily full-call signature equality.
Keep all 15 input IDs per L2 attempt and every committed carrier movement.

Save compact records for all 27000 shots, compressed complete seed0 traces per
cell, and the first ordinary L2 rejection trace per cell when observed. Save
failure prefixes separately as incomplete. Render representative full HTML
schedules offline, without rerunning probability sampling. Save source/catalog/
motion-reference hashes, all coordinates and configuration, manifests, logs,
runtime/reuse/guard counts, independent audits, d/N1 scaling and resource Pareto
figures, and a short assumptions/bottleneck report. Guards for physical compile,
atom construction and expansion must remain zero.

## Preparation verification

This commit contains only documentation and a non-executable parameter record.
Apply the documentation-only policy in [testing.md](../testing.md): JSON parsing,
matrix counts, timeout arithmetic, catalog fingerprints, coordinate/footprint
arithmetic, local links and `git diff --check`. Arithmetic geometry checks are
not physical route validation or factory runs. No fast/slow/bench suite, model
execution, server access or submission belongs to this preparation step.

Approval is pending at the user's explicit request. Wait after delivering these
files; do not infer execution permission from the frozen parameter values.

Preparation check result (2026-10-25): JSON/status assertions, all five catalog
fingerprints, 270 distinct identity/coordinate configurations, 27000 shots,
timeout arithmetic, nonoverlapping storage/parking footprints with the declared
gaps, 37 local document links and diff whitespace checks passed. Maximum width
and maximum depth across the matrix are 17380 um and 2820 um, respectively;
they occur in different configurations and are not new device capacity limits.
No factory, compiler or server execution was used for these checks.
