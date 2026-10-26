# d3 N4 whole-factory layout comparison

Date: 2026-10-25.
Implementation baseline: `cb3a089` on `codex/msd-object-scheduler`.
Scope: local first-level finite-round object estimation, no physical compilation.

## Workload and model

The user authorized vertical, horizontal and 2x2 placement with asynchronous/v1
and synchronous/v2 at d=3, N=4. All six conditions use seeds 0/1 and two attempted
production rounds per factory: twelve complete cases, eight factory attempts
per case. Seed 0 accepts six outputs and seed 1 accepts seven under every condition.
Synchronous production delivers success immediately and advances rejected rounds
without waiting for a successful-output quota. Raw waits and conditional S+SE
joins are retained. External consumption is the existing ideal sink.

The only geometric change is translation of whole factories. Six internal blocks
remain W1-W5,R, horizontal and unrotated. Reuse `GridFactoryPlacement`, with one,
four or two columns respectively. Storage/gate homes stay below y=0, readout above
y=50 micrometers; pitch is 10 micrometers, patch and factory gaps 40 micrometers.
Measurement is 100 microseconds, processing 0, Load/Store 10 each. All other
time/noise parameters, raw acceptance 51235/65536, input Z error 0.01, component
source hashes and probability ports remain unchanged. No calibration or compiler
is invoked by layout selection, cost binding, scheduling or reporting.

## Geometry and full-cycle time

All layouts allocate **408 atoms / 24 blocks**, with summed block area
86,400 square micrometers. Bounding area includes gaps and is not total device
area. Readout area remains unavailable.

| Layout | Factory rows x columns | Storage width x depth, micrometers | Storage bounding area, square micrometers |
| --- | --- | --- | ---: |
| Vertical | 4 x 1 | 560 x 360 | 201600 |
| Horizontal | 1 x 4 | 2360 x 60 | 141600 |
| Grid | 2 x 2 | 1160 x 160 | 185600 |

Complete finite-batch times in milliseconds:

| Layout | Async seed 0 | Sync seed 0 | Async seed 1 | Sync seed 1 |
| --- | ---: | ---: | ---: | ---: |
| Vertical | 550.028173 | 323.068896 | 531.752768 | 329.524479 |
| Horizontal | 431.428173 | 229.068896 | 407.552768 | 231.324479 |
| Grid 2x2 | 471.428173 | 260.468896 | 449.752768 | 262.124479 |

Under each fixed policy/seed, all three layouts have the same invocation and
shared-command grouping topology. Their gate-transport costs are identical;
the full makespan difference equals the readout-transport difference within
floating-point tolerance. This is an observation for these cases, not a rule
that arbitrary placements always preserve batching.

The current model places no penalty or capacity limit on horizontal width.
The horizontal layout is fastest here because it reduces readout depth while
retaining command sharing. It is not a demonstrated optimal physical layout,
nor a comparison under fixed device width or equal bounding area.

## Resource accounting

The following are shared-command durations in milliseconds. AOD occupied time
includes transfers and readout holds as well as movement; do not add these
columns to obtain makespan.

| Layout | Policy | Seed | AOD occupied | Readout transport | Gate transport |
| --- | --- | ---: | ---: | ---: | ---: |
| Vertical | Async | 0 | 541.785173 | 185.440 | 241.105173 |
| Horizontal | Async | 0 | 423.185173 | 66.840 | 241.105173 |
| Grid | Async | 0 | 463.185173 | 106.840 | 241.105173 |
| Vertical | Sync | 0 | 317.037896 | 139.280 | 101.517896 |
| Horizontal | Sync | 0 | 223.037896 | 45.280 | 101.517896 |
| Grid | Sync | 0 | 254.437896 | 76.680 | 101.517896 |
| Vertical | Async | 1 | 523.730268 | 188.520 | 224.090268 |
| Horizontal | Async | 1 | 399.530268 | 64.320 | 224.090268 |
| Grid | Async | 1 | 441.730268 | 106.520 | 224.090268 |
| Vertical | Sync | 1 | 323.437479 | 143.920 | 102.317479 |
| Horizontal | Sync | 1 | 225.237479 | 45.720 | 102.317479 |
| Grid | Sync | 1 | 256.037479 | 76.520 | 102.317479 |

There are 472 logical CNOT calls per case. Async uses 165/155 CNOT waves for
seeds 0/1, with 29.77%/39.37% of its CNOT stage commands shared. Sync uses 118
CNOT waves and shares every CNOT stage command. These counts are unchanged
across the three layouts. They describe component commands, not atom-level
parallelism or execution legality.

The HTML/JSON also report startup latency, finite-batch output rate, per-output
atom-time/storage-area-time, protocol wait, dispatch wait, wave-tail wait and
phase resource wait. Wait totals retain their distinct factory/member-time
bases; they are not additive global elapsed terms. For example, sync seed 0
protocol waits summed over four factories are 314.908/235.508/261.908 ms for
vertical/horizontal/grid. Operation, transport and idle exposure accounting is
retained without modifying acceptance or claiming a decoded error rate.

## Verification and computation cost

- Focused pre-change baseline: 35 fast passed in 6.02 s. New geometry tests first
  failed because layout selection was not accepted by the catalog interface.
- Focused implementation checks: 47 fast passed in 9.92 s. They include N1
  degeneracy, N2 grid aliases, exact N4 geometry, invalid options, common-command
  readout durations 920/320/520 microseconds and invariant 240.5-microsecond CNOT
  controls. A single catalog is reused across real N1/N2 cases, three layouts,
  both policies and raw retry paths, without rebuilding template objects.
- Mapped related checks: **110 fast passed**, 21.54 s pytest / 22.512 s process
  time. No slow/bench, full repository suite or server run was requested or run.
- Ruff format/lint passed for six Python files; scoped strict mypy passed for
  four production/example files using existing config and explicit package bases.
- Independent saved-data audit verifies the same 263/267 event records and
  939/951 invocation identities for seeds 0/1 across all six conditions, along
  with unchanged operation counts, homogeneous waves, nonoverlapping modeled
  AOD intervals and the rejection-inclusive next-round joins.
- All twelve full HTML schedules contain the complete saved traces and 24
  block footprints each. Rendered counts and per-factory time sums match the
  JSON; layout plots in the comparison index use a common coordinate scale.
  The shared inline JavaScript passes Node syntax checking; 27 HTML links,
  58 documentation links and all six configuration files validate.
  No browser screenshot, atomic trajectory or collision validation is claimed.

Every worker loads ten component templates once and processes two seeds. All
template identities are retained and compiler, atom expansion/binding and atom
construction counters are zero. Both policies have identical reuse counts:

| Layout | Lookups per worker | Cache hits | Numeric bindings | Async worker s | Sync worker s |
| --- | ---: | ---: | ---: | ---: | ---: |
| Vertical | 5990 | 5930 | 60 | 4.808 | 4.230 |
| Horizontal | 5990 | 5975 | 15 | 4.688 | 4.706 |
| Grid | 5990 | 5960 | 30 | 5.392 | 4.957 |

Different y levels require different cheap numeric bindings, not component
compilation. Total worker work is 28.781 s, summed case work 26.349 s, and
end-to-end launch time including imports/process startup 46.999 s. The coarse
timings place most worker time in case execution/accounting; no function-level
performance profile was run. Every case completed under the retained 20 s/case,
5 s/wave and 60 s/worker limits. No budget was increased or timeout retried.

## Reproduce and inspect

Six versioned configurations are named
`experiments/msd/layout-d3-n4-{vertical,horizontal,grid2}-{asynchronous,synchronous}.json`.
Use a fresh output directory and stop after the first nonzero return. For example:

```powershell
$msdPython = 'C:\Users\yuyqp\Documents\ChatGPT\NADiT\modules\physical_compiler\.venv\Scripts\python.exe'
$env:PYTHONPATH = "$PWD;$PWD\modules\physical_compiler\src"
& $msdPython -m modules.logical_compiler.examples.factory_objects `
  --config experiments/msd/layout-d3-n4-grid2-synchronous.json `
  --output artifacts/msd-object-local/grid2-sync-reproduction
if ($LASTEXITCODE -ne 0) { throw 'Run failed; stop before later cases' }
& $msdPython -m modules.logical_compiler.examples.factory_schedule `
  --case artifacts/msd-object-local/grid2-sync-reproduction/d3-n4-seed0.json `
  --output artifacts/msd-object-local/grid2-sync-reproduction/complete-schedule.html
```

- [Comparison index, geometry plots and all twelve schedules](../../artifacts/msd-object-local/20261025-layout-d3-n4-comparison/index.html).
- [Representative grid synchronous full schedule, seed 0](../../artifacts/msd-object-local/20261025-layout-d3-n4-grid2-synchronous/d3-n4-seed0-schedule.html).
- [All numeric resource results and cross-layout audit](../../artifacts/msd-object-local/20261025-layout-d3-n4-comparison/comparison.json).
- [Rendering/time-accounting audit](../../artifacts/msd-object-local/20261025-layout-d3-n4-comparison/render-audit.json).
- [Launch timing records](../../artifacts/msd-object-local/20261025-layout-d3-n4-comparison/launch-records.json).

This closes only the requested d3 N4 comparison. d5/d7, N8, constrained device
width/capacity, higher-level factories and non-ideal external consumers remain
outside the completed experiment. Short batches are not steady-state evidence.
