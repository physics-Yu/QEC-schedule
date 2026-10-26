# Continuous production rounds: corrected synchronous factory acceptance

Date: 2026-10-25.
Scope: local object estimates with recorded probabilities; no physical compilation.

## Correction and workload

Synchronous/v1 incorrectly waited for every factory's next accepted output.
Synchronous/v2 aligns attempted production rounds: an accepted output is
delivered immediately, a final rejection produces no output, and both factories
enter the next round after finishing their current branches. Raw-success waiting,
conditional S+SE joins, deterministic-stage barriers and one-AOD homogeneous waves
are retained. The external sink remains ideal; actual downstream injection is
not costed. The [policy ADR](../decisions/0053-factory-strategy-boundaries.md) and
[next layout task](../../modules/logical_compiler/docs/msd-layout-implementation-plan.md)
now use this corrected interpretation. Layout experiments remain pending.

Both policies ran d=3/5/7, N=1/2, seeds=0/1 and **two attempted production rounds
per factory**: 12 pairs / 24 real-factory cases. Input Z error remains 0.01;
all component records, raw probabilities, geometry and timing parameters are
unchanged. Each round executes the complete 4+11 raw-input / 59-CNOT recipe.
Raw failures retry inside a round; a final factory rejection advances the round.
The original reset costs occur in the next round's preparation components.
No replacement success is requested inside the rejected round.

## Matched results

For N=2 there are four total factory attempts per row. Both strategies have
the same acceptance outcomes and output counts. Times are milliseconds.

| d | Seed | Outputs | Final rejects | Async | Sync v2 |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 3 | 0 | 4 | 0 | 312.989714 | 233.479402 |
| 3 | 1 | 3 | 1 | 324.722119 | 243.052855 |
| 5 | 0 | 4 | 0 | 828.693112 | 632.987313 |
| 5 | 1 | 3 | 1 | 742.745745 | 567.161877 |
| 7 | 0 | 4 | 0 | 959.844836 | 719.978516 |
| 7 | 1 | 3 | 1 | 905.945173 | 814.063659 |

N=1 is an exact timing control under both policies, with two accepted outputs
in these seeds: d3 181.018904 / 163.032706 ms; d5 397.397964 / 376.658391 ms;
d7 477.388940 / 544.250126 ms (seeds 0/1).

The key d3 N2 seed1 trace now has:

| Factory | Round | Start ms | Final branch completed ms | Result |
| --- | ---: | ---: | ---: | --- |
| F0 | 1 | 0 | 103.453632 | Accepted and delivered immediately |
| F1 | 1 | 0 | 103.452632 | Rejected; no output |
| F0 | 2 | 103.453632 | 243.052855 | Accepted and delivered |
| F1 | 2 | 103.453632 | 243.052855 | Accepted and delivered |

F1 waits one microsecond for F0's current final correction/delivery; both then
start fresh production. F0 does not wait for F1 to obtain its next success.
The old v1 case took 346.292065 ms for five attempts and four outputs. That is
a different workload, not a directly comparable speedup baseline. Historical
results and source/configuration snapshots are retained. Future layout comparisons
must also use equal attempted-round counts, not accepted-output quotas.

These are finite batches and two seeds, not a steady-state throughput estimate
or a physical correctness/decoded logical-error claim. Per-case JSON retains
startup latency, finite-batch rate, atom/storage-area-time per accepted output,
operation counts/exposures and wait/transport accounting. Full-device/readout
area and actual decoded error remain unavailable. Zero-output runs are valid:
rate zero, startup and per-output cost null.

## Verification and reuse

- Focused baseline: 40 fast passed, 8.41 s. The first command selected a module
  pytest configuration that lacked the tier plugin; rerunning with root
  `-c pytest.ini` resolved collection without changing test scope.
- Regression first reproduced five final decisions instead of four in the old
  d3 N2 seed1 implementation. The revised acceptance assertions intentionally
  replace the old success-quota expectation under the user's corrected model.
- Final focused checks: 45 fast passed, 7.76 s. They cover final rejection and
  common next-round start, retained raw/S synchronization, paired event/call
  identities, rejected v1/invalid production basis, zero outputs and report
  handling, required-member failure and a deliberate zero-budget timeout.
- Mapped consumers: **583 fast passed**, 26.66 s pytest time / 27.763 s bounded
  process time; 138 slow and 9 bench deselected. No blanket full-suite run.
- Ruff format/lint passed for nine changed Python files. Scoped strict mypy
  passed for six production/example modules with the existing physical-module
  config, explicit package bases and silent imported-module checking. An earlier
  unrestricted invocation exposed pre-existing imported Qiskit/pymatching stub
  and d3 measurement-export issues; no repository-wide type-clean claim is made.
- Independent saved-data audit: **1185 probability event records and 4233
  invocation IDs** match across the 12 pairs. Counts and layouts match; every
  wave is homogeneous, modeled AOD intervals do not overlap, every round has
  exactly one terminal decision per factory, output tokens are unique, and
  next-round starts join both accepted and rejected members.
- All 24 complete HTML schedules are generated from those saved traces. Per-line
  time categories sum to makespan; rendered call/output counts match the JSON.
  Source hashes match across all six workers. The shared inline JavaScript passes
  Node syntax checking; 27 HTML links, 72 documentation links and the JSON
  configurations validate. No browser screenshot or atom-route
  validation is claimed.

| d | Async worker seconds | Sync worker seconds | Lookups per worker | Cache hits | Numeric bindings |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 3 | 3.637 | 3.527 | 4515 | 4485 | 30 |
| 5 | 6.117 | 5.362 | 4452 | 4422 | 30 |
| 7 | 6.051 | 5.995 | 4452 | 4422 | 30 |

Each worker loads ten component templates once and retains their identities.
All physical compilation, atom expansion/binding and atom-construction counters
are zero. Numeric binding misses are coordinate evaluation, not compilation.
Worker work totals 30.690 s; summed case work is 27.313 s; end-to-end launcher
time including subprocess startup/imports is 48.591 s. These coarse timings
locate most in-worker time in case execution/accounting; no function-level
bottleneck profile was run. Reports are rendered separately from saved data.

All real cases completed without timeout. Limits remain 20 s/case, 5 s/wave,
60 s/worker. Failure stops the worker and later cases; no automatic continuation
or increased budget was used. Local only: no server task was started or changed.

## Reproduce and inspect

Use [async round d3](../../experiments/msd/factory-objects-rounds-d3.json) and
[sync v2 d3](../../experiments/msd/factory-objects-sync-d3.json); corresponding
d5/d7 files have the same workload, limits and seeds. The older asynchronous
`factory-objects-d{3,5,7}.json` files retain accepted-output semantics and are not
the paired workload used here. The updated sync configs explicitly select v2.

```powershell
$msdPython = 'C:\Users\yuyqp\Documents\ChatGPT\NADiT\modules\physical_compiler\.venv\Scripts\python.exe'
$env:PYTHONPATH = "$PWD;$PWD\modules\physical_compiler\src"
& $msdPython -m modules.logical_compiler.examples.factory_objects `
  --config experiments/msd/factory-objects-rounds-d3.json `
  --output artifacts/msd-object-local/round-v2-async-reproduction
if ($LASTEXITCODE -ne 0) { throw 'Async run failed; stop before later cases' }
& $msdPython -m modules.logical_compiler.examples.factory_objects `
  --config experiments/msd/factory-objects-sync-d3.json `
  --output artifacts/msd-object-local/round-v2-sync-reproduction
if ($LASTEXITCODE -ne 0) { throw 'Sync run failed; stop before rendering' }
& $msdPython -m modules.logical_compiler.examples.factory_schedule `
  --case artifacts/msd-object-local/round-v2-sync-reproduction/d3-n2-seed1.json `
  --baseline-case artifacts/msd-object-local/round-v2-async-reproduction/d3-n2-seed1.json `
  --output artifacts/msd-object-local/round-v2-sync-reproduction/complete-schedule.html
```

- [Acceptance index and all 24 schedules](../../artifacts/msd-object-local/20261025-round-sync-v2-comparison/index.html).
- [d3 N2 seed1 complete synchronous schedule](../../artifacts/msd-object-local/20261025-round-sync-v2-d3-synchronous/d3-n2-seed1-schedule-v2.html).
- [Paired numerical data and historical workload comparison](../../artifacts/msd-object-local/20261025-round-sync-v2-comparison/comparison.json).
- [Independent rendering/accounting audit](../../artifacts/msd-object-local/20261025-round-sync-v2-comparison/render-audit.json).
- [Launcher timing records](../../artifacts/msd-object-local/20261025-round-sync-v2-comparison/launch-records.json).
