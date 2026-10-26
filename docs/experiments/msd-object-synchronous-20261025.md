# Local asynchronous versus synchronous factory estimates

Historical report: these results used synchronous/v1, whose accepted-output
quota barrier was subsequently identified as the wrong production model.
They are not acceptance evidence for continuous round-synchronous production.
See [the corrected policy](../decisions/0053-factory-strategy-boundaries.md).
The [v2 acceptance report](msd-object-round-sync-v2-20261025.md) replaces these
results for the corrected production-round workload.
The original artifacts remain unchanged. The commands below describe the old
run; current `factory-objects-sync-d{3,5,7}.json` files now select v2 round mode
and no longer reproduce these old quota results. Old artifact summaries retain
their original configuration and source hashes.

This implements the approved stage-synchronization draft using the existing
cooperative runtime, probability backend and component scheduler. No physical
compiler, atomic expansion, new probability calculation or server run was used.

## Implemented coordination

- Initial preparation and each rotation's raw supply join after every required
  state is usable, including accepted-only growth/correction. Successful states
  retain their carrier/token identity while failed members retry locally.
- Corresponding deterministic compute/uncompute gates and T-consumption CX/MZ
  steps align. Conditional branches join after the existing S+SE when needed;
  the branch that skips S waits. No new S failure model or idle SE is introduced.
- All component waves remain homogeneous and share one AOD. Barrier waiting
  occurs after safe component exit and does not reserve the AOD.
- Each production epoch retains its original members. Accepted outputs use the
  existing immediate ideal sink. Successful factories then park; only failed
  factories repeat a batch. No factory starts the next cycle until every member
  has delivered its accepted output for the current epoch.
- A required member failure aborts the estimate with cycle, stage and cause.
  It cannot disappear from the cohort and allow partial success. The supported
  policy has matching finite cycle counts; horizon-based policies are rejected.

The asynchronous implementation is unchanged. Policy names and barrier keys do
not enter probability sampling identities. The actual raw, conditional S and
final-acceptance outcomes therefore remain paired by their original semantic IDs.

## Matched local comparison

Both strategies were run at d=3/5/7, N=1/2 and seeds=0/1 with two accepted outputs
per factory, giving **12 pairs / 24 local cases**. The layouts, one-AOD budget,
recorded component catalogs, probability ports, accepted-input p=0.01 and all
retry budgets are identical within each pair. Only the strategy changes.

Every pair preserves all event outcomes and component counts: **1278 semantic
events and 4581 invocation IDs** match across policies. All asynchronous case
objects and layouts also match the previously saved d3/d5/d7 runs exactly.

N=2 results (four accepted outputs in each row):

| d | Seed | Asynchronous ms | Synchronous ms | Total-time reduction | Async first output ms | Sync first output ms |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 3 | 0 | 312.989714 | 233.479402 | 25.403% | 148.940192 | 123.854252 |
| 3 | 1 | 445.059592 | 346.292065 | 22.192% | 131.047537 | 103.453632 |
| 5 | 0 | 828.693112 | 632.987313 | 23.616% | 438.846491 | 357.605400 |
| 5 | 1 | 975.260360 | 801.292181 | 17.838% | 310.879592 | 242.804020 |
| 7 | 0 | 959.844836 | 719.978516 | 24.990% | 435.293157 | 362.298097 |
| 7 | 1 | 1176.310101 | 1136.921683 | 3.348% | 388.158737 | 393.454858 |

N=1 is an exact control: both strategies have identical timing and zero protocol
barrier wait. Their two-output makespans are 181.018904 / 163.032706 ms at d3,
397.397964 / 376.658391 ms at d5 and 477.388940 / 544.250126 ms at d7 (seeds 0/1).

The improvement comes from more common commands, not fewer operations or better
random outcomes. For d3, N2, seed0, the same 236 CNOT calls occupy 143 waves under
asynchronous coordination, with 32 shared-command waves. Synchronous coordination
uses 118 waves, all shared, reducing CNOT wave charges from 120.477 to 68.955 ms.
Total AOD occupied time falls from 306.840 to 228.255 ms.

Deliberate waiting is still charged: the same synchronous case has 31.452 ms of
protocol-barrier waiting for F0 and 37.883 ms for F1. These are factory-time
quantities, not additional global makespan terms. For d7, N2, seed1, F0 waits
417.202 ms across protocol barriers, including the peer's final batch retry.
That sample improves total completion only slightly and delays its first output
by 5.296 ms. The policy is not uniformly better on every metric.

These are short finite batches using two seeds, not a steady-state estimate,
an optimal-scheduling proof, a matched physical output-quality comparison or a
decoded logical error-rate result. Existing fake-backend probabilities do not
change as waiting changes.

## Verification and runtime

- Initial focused baseline: **85 fast passed**, 9.64 s.
- The six new actual-factory synchronization checks first failed against the
  draft-only resolver, then passed after implementation. They cover raw waiting,
  conditional branches and aligned CNOTs, identical outcomes, final rejection
  and next-epoch alignment, member failure, and an intentional zero-budget error.
- Final mapped related regression: **578 fast passed**, 26.07 s pytest time,
  27.193 s bounded process time. 138 slow and 9 bench tests were not selected.
- Ruff format/check passed for all nine changed/new Python files; strict mypy
  passed for the five changed production modules.
- Independent readback of all paired results verified identical probability
  documents/outcomes, call IDs/counts and layouts; homogeneous waves; one-AOD
  resource intervals; and epoch release at the last required delivery.
- All 24 standalone HTML schedules contain their complete saved traces. Reported
  protocol-barrier time matches the independent state ledger per factory. The
  report retains waiting after an early ideal delivery rather than labeling that
  factory finished. JavaScript syntax and local links were checked; no browser
  screenshot or physical-route validation is claimed.

| d | Async worker wall seconds | Sync worker wall seconds |
| ---: | ---: | ---: |
| 3 | 4.884 | 4.811 |
| 5 | 7.175 | 6.981 |
| 7 | 7.696 | 7.530 |

Each worker covers four cases and includes startup/imports. Total worker time is
39.077 seconds. Every worker completes normally. The experiment retains 20 s
per-case, 5 s per-wave and 60 s per-worker limits. Timeout handling terminates
the run, reports the reason/last stage and does not continue or retry. The
deliberate zero-budget unit test is a negative control, not an experiment timeout.

Each worker loads ten fixed component templates once. Async and sync have equal
reuse counts: d3 4892 lookups / 4862 hits / 30 numeric bindings; d5 4814 / 4784 / 30;
d7 4817 / 4787 / 30. Template identities remain stable within every run, and
physical compilation, atom binding/expansion and atom construction counters are
all zero. Starting a separate worker rereads numeric records; it does not compile.

## Full schedules and reproducible entry

- [Comparison HTML with links to all 24 complete schedules](../../artifacts/msd-object-local/20261025-strategy-comparison/index.html).
- [Representative d3 N2 seed0 synchronous schedule](../../artifacts/msd-object-local/20261025-strategy-compare-d3-synchronous/d3-n2-seed0-schedule.html).
- [Matched asynchronous schedule](../../artifacts/msd-object-local/20261025-strategy-compare-d3-asynchronous/d3-n2-seed0-schedule.html).
- [Machine-readable paired audit](../../artifacts/msd-object-local/20261025-strategy-comparison/comparison.json).
- [HTML accounting audit](../../artifacts/msd-object-local/20261025-strategy-comparison/render-audit.json).

Configurations are [sync d3](../../experiments/msd/factory-objects-sync-d3.json),
[sync d5](../../experiments/msd/factory-objects-sync-d5.json),
[sync d7](../../experiments/msd/factory-objects-sync-d7.json) and the corresponding
existing `factory-objects-d{3,5,7}.json` asynchronous files. They differ only in
the strategy field. Output directories must be new.

```powershell
$msdPython = 'C:\Users\yuyqp\Documents\ChatGPT\NADiT\modules\physical_compiler\.venv\Scripts\python.exe'
$env:PYTHONPATH = "$PWD;$PWD\modules\physical_compiler\src"
& $msdPython -m modules.logical_compiler.examples.factory_objects `
  --config experiments/msd/factory-objects-sync-d3.json `
  --output artifacts/msd-object-local/sync-d3-reproduction
& $msdPython -m modules.logical_compiler.examples.factory_schedule `
  --case artifacts/msd-object-local/sync-d3-reproduction/d3-n2-seed0.json `
  --baseline-case artifacts/msd-object-local/20261025-strategy-compare-d3-asynchronous/d3-n2-seed0.json `
  --output artifacts/msd-object-local/sync-d3-reproduction/complete-schedule.html
```

This was local implementation and acceptance only. Existing server tasks and
saved asynchronous results were not changed.
