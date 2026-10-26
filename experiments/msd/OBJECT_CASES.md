# MSD component-object local acceptance

Both named policies are available: `asynchronous/v1` and `synchronous/v1`.
The [paired local comparison](../../docs/experiments/msd-object-synchronous-20261025.md)
uses unchanged cost/probability inputs and links all complete schedules. Select
`"strategy": "synchronous"` or use the saved `factory-objects-sync-d{3,5,7}.json`
configurations; asynchronous remains the default.

The existing policy is now named `asynchronous/v1`; configuration may select
`"strategy": "asynchronous"` explicitly. The [strategy boundary and synchronous
draft](../../docs/decisions/0053-factory-strategy-boundaries.md) distinguish policy
parameters from distance-specific cost coverage. Positive N is not limited to
1/2; missing distance inputs still fail without a compiler fallback. Recorded
full-factory catalogs are now available for d=3/5/7; see the
[distance migration report](../../docs/experiments/msd-object-d357-20261025.md)
and [d5](factory-objects-d5.json) / [d7](factory-objects-d7.json) configurations.

The subsequent batching correction and authorized final server rerun are recorded
in [the server comparison report](../../docs/experiments/msd-object-parallel-fix-20261025.md),
including the complete standalone HTML schedules and saved-trace rendering command.

For the subsequent complete d3 recipe with the precomputed-probability fake
backend, see [the full-factory report](../../docs/experiments/msd-object-factory-d3-20261025.md)
and [factory-objects-d3.json](factory-objects-d3.json). The cases below retain
their original, narrower control-test scope.

This is the first implementation milestone, not a complete factory campaign.
It implements same-component waves on one AOD through the existing logical
compiler. Different component types never overlap. No physical compiler, atom
binding, atom expansion or atom construction may enter the combination loop.

The source migration record is
[`msd-object-migration.json`](../../docs/experiments/msd-object-migration.json).
The design and task-specific test scope are recorded in
[ADR 0052](../../docs/decisions/0052-msd-object-waves.md).

## Reproduce locally

Use the existing Python 3.12 environment. In this Windows workspace:

```powershell
$msdPython = 'C:\Users\yuyqp\Documents\ChatGPT\NADiT\modules\physical_compiler\.venv\Scripts\python.exe'
$env:PYTHONPATH = "$PWD;$PWD\modules\physical_compiler\src"
& $msdPython -m modules.logical_compiler.examples.object_cases `
  --config experiments/msd/object-cases.json `
  --output artifacts/msd-object-local/local-acceptance
```

Choose a fresh output directory for every run. Existing output directories are
never overwritten. The outer worker budget is 45 seconds. The retry fixture's
runtime budget is 10 seconds and each stage-planning wave has a 5-second budget.
A timeout returns an error (outer timeout exit code 124), terminates the worker,
and retains `error.json`, last progress and stdout/stderr. A failed case stops the
run; there is no background retry, server submission or automatic fallback.

Run focused fast tests with a bounded process invocation in the same environment:

```powershell
& $msdPython -c "import subprocess,sys; sys.exit(subprocess.run([sys.executable,'-m','tools.testing.run','fast','--area','logical.objects'],timeout=60).returncode)"
```

Changes to shared interfaces additionally require the mapped related fast
consumers. The initial implementation's related selection is:

```text
python -m tools.testing.run fast --changed
  modules/codes/contracts/parallel.py
  modules/codes/contracts/factory_recipe.py
  modules/logical_compiler/src/estimation/kernel.py
  modules/logical_compiler/src/protocols/factory_process.py
  modules/logical_compiler/src/protocols/cooperative.py
  modules/codes/rotated_surface/object_readout.py
```

These tests are run under a 90-second subprocess deadline. Bench and unrelated
slow suites are not part of this task. A deliberate 0.1-second sleeping-worker
test verifies timeout termination; it is an expected negative test, not a failed
MSD experiment.

## What the cases establish

| Case | Model | Expected evidence |
| --- | --- | --- |
| Synchronous | d3 logical MZ on two vertically placed factories | Shared Load/Move/readout/return/Store; 520 us |
| Resource conflict | Second factory shifted 20 um in x, outside the common-band certificate | Single AOD queues the second readout; 840 us, including its 320 us wait |
| Retry offset | Explicit two-work-block control-flow fixture | Only failed preparation retries; independent cohort proceeds; resets recur next cycle; output tokens consumed once |

For the synchronous case the data rows are (-50,-30,-10) and
(-150,-130,-110) um. A shared +200 um translation reaches the readout domain.
The relative stages are Load [0,10), outbound [10,210), measure [210,310),
return [310,510), Store [510,520). Measurement results are available at 310 us;
safe exit is 520 us. These are modeled times, not validated atom actions.

The catalog stores one readout topology per d=3/5/7. Its instances share those
objects across N=1/2/4/8. The separate fixture catalog has three synthetic
component types and is reused across seeds and retry counts. The runner reports
template builds, lookups, preserved object identities, guarded forbidden-call
counts and wall time by stage. A forbidden call increments its counter and
aborts; zero counts are observed instrumentation results, not assumed constants.

## Outputs and limits

- `summary.json`: scope, configuration, timing sources, reuse counters, runtime,
  and explicitly labeled single-MZ-wave d/N scaling.
- `synchronous.json`, `resource_conflict.json`: logical layout, component receipts,
  per-stage resource schedule and waits.
- `postselection_retry_offset.json`: full existing factory-runtime/ledger evidence
  for the scripted control-flow fixture.
- `schedule.html`: representative absolute time tables for all three cases.
- `source-hashes.json`: exact runtime/code files used by the run.
- `progress.json`, `worker.stdout.log`, `worker.stderr.log`: progress and diagnostics.
- `error.json`: failure/timeout only; partial artifacts never imply success.

Model parameters retain Load=Store=10 us, measurement=100 us, processing=0 us,
movement=1 us/um, a 50 um gap, and unbounded zone capacities. Actual allocated
atoms and finite storage footprints are reported. The readout transport model
uses compressed row/column bands, not atom lists. It currently supports only
standard-orientation MZ; unsupported components fail explicitly.

The migrated generic recipe retains all 59 logical CNOTs, actual conditional S,
15 raw inputs and accepted-only growth. Its complete object cost catalog and
schedule-dependent raw acceptance adapter are **not yet implemented**. The
scripted fixture does not provide those missing data. Full-factory throughput,
steady state, physical loss recovery and actual output LER remain unreported.
No physical validation, animation or server run is performed by this entry point.
