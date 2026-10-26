# Two-level synchronous scan: stop and authorized continuation

Date: 2026-10-26 (Asia/Shanghai).
Status: complete; independent saved-data and provenance audits passed.
See the [result and delivery record](msd-level2-sync-results-20261026.md).

## Original attempt

Source `5c212010d4616e85627195ea6fc4f30ab4edd617` ran on
`yyq@10.133.24.178`, reached through ZeroTier network `166359304ed7c7a5`.
The d11/N1=10 vertical pilot completed in 26.983 s with 996404 KiB peak RSS.
The 89-worker matrix stopped after 171.431 s: cell
`d03-n01-c01-synchronous-below_center`, seed 8, exceeded its 30 s shot budget.
The exception was raised during `json.dumps` in `protocols/cooperative.py:871`.
The last recorded model time was 1725860.672 us; this is not wall time.
The stack locates the interruption, not the duration of each processing stage.
No physical compilation occurred. No function-level profiling was performed.

The independent stop audit found zero active owned processes, 89 started cells,
zero complete cells, and 1251 complete JSONL shot records without partial lines.
These records alone are not a completed statistical experiment.
Evidence is preserved under `artifacts/msd-object-server/20261026-level2-sync/`.
The downloaded `stopped-evidence.tar.gz` SHA256 is
`ddb45f4580f3c0820ece2cfc61335628a92c8f7fc70163a3294daddc9c5e35bb`.

## Authorized continuation

The user requested a larger budget, remaining configurations and periodic checks.
[Continuation config](../../experiments/msd/level2-sync-server-continuation.json)
uses 120 s per shot and 12060 s per cell; 89 workers and the 24 h batch cap remain.
All scientific parameters, seeds 0..99, 270 cells and the 27000-shot target remain.
Synchronous L1, one L2, B=1, single AOD and the original fake backend are unchanged.

A fresh output directory imports only exact completed seed prefixes, preserving
their original metrics and wall timings. It validates the prior source commit,
configuration, runtime source hashes and metric/motion hashes before dispatch.
Each worker verifies the frozen prefix hash, copies retained representative
traces and executes only missing seeds. The original errors and data remain.
Reuse counters and worker wall time describe newly executed work; imported shot
timings retain their original budget. A new timeout/error still stops the batch;
there is no automatic budget increase, seed replacement or repeated restart.

## Verification and follow-up

Related baseline: 165 fast tests passed. Continuation runner suite: 21 passed,
including duplicate/gap/source-change rejection and actual missing-seed execution.
Ruff passes. Scoped mypy with imported modules excluded passes; unrestricted
dependency analysis reports 17 errors including existing third-party typing and
package-resolution issues. No slow or bench suite ran.
Check the unique continuation run every 15 minutes using this thread's heartbeat.
On completion, audit all seeds, conservation and common event signatures before
publishing statistics or HTML. On failure, retain evidence and report the cause.
