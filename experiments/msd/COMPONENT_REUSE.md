# Component reuse and shared scheduling

Status: initial MSD integration implemented; server parameter scans remain paused
for review. This is not a claim that all physical scheduling has become cheap.

## Existing interfaces and the integration problem

- `CalibrationCache` in the logical compiler's `estimation/calibration.py` stores
  applicability-keyed cost/model records. It neither stores Atom IR nor compiles
  a miss. `CalibrationContext` can describe local influence or whole-world scope.
- `AtomComponentTemplate` in `modules/codes/_support/atom_template.py` rebinds a
  validated relative atom program, with strict timing, home-site and complete-world
  admission. Its transport and readout paths are already selected. Arbitrary
  concurrent frontiers cannot safely reuse those paths or a singleton total time.
- MSD uses `_CachedProfile` -> `JointSurfaceFactoryProfile` ->
  `JointCalibrationCache.lookup`. Missing exact world/frontier coverage becomes an
  explicit `msd.calibrate` dependency. It is not a hidden compile inside lookup.
- Before this change, `get_or_create` action misses called `compile_joint_actions`,
  which reconstructed all member sources, concatenated QASM, lowered every member
  to native gates, and ran `compile_physical` over the whole world. The whole-world
  action key correctly includes the frontier, actual bindings, spectators and
  device. Changing a retry frontier therefore repeated internal lowering too.
- Action hits avoid both lowering and shared scheduling. Probability-only misses
  reevaluate the stored actual trace, without compiling actions. Existing
  `factory_component_source` memoization is process-local, so separate calibration
  worker processes do not share that memoization.

## New boundary

`component_reuse.py` persists device-independent native operations, their dependency
edges, local source/result identities and resource requirements under
`cache/components/<key>/operations.json`. The key includes component, distance,
source QASM, wire/measurement contract, frontend/native ABI and dependency versions.
It excludes seed, attempt number, member identities, N, absolute position, noise,
device timing and the current frontier. Those quantities cannot alter the cached
native gate definition; they still affect subsequent scheduling and accounting.

On an action miss, the existing offline calibration worker loads those templates,
rebinds wire/node/result identities, and composes independent DAGs. It then invokes
the existing nonzoned shared-device scheduler on the actual complete world. This
retains single-AOD queueing, transport, readout placement, collision constraints,
and full physical validation. Noise is evaluated from that resulting trace, with
actual transport and spectator waiting. No fixed component duration is substituted.
Small-d injection, three postselected d3 rounds, accepted-only growth and actual S
sources are unchanged.

The first absent component/source/native-ABI key explicitly records
`component_source_or_native_abi_key_not_present`. A corrupt record raises, and a
concurrent writer defers. Neither silently causes repeated compilation. New
source/protocol/distance/native ABI values are legitimate new keys. Changed noise
or readout geometry requires probability or scheduling work, not internal native
lowering. Native block relocation remains a separately scheduled world-dependent
goal, with no claimed reusable transport trajectory.

Counters distinguish `internal_compiles`, `memory_hits`, `disk_hits`, component
requests and `shared_schedule_calls`. Whole-frontier cache hits bypass component
lookup entirely and must be counted separately. `software_seconds` reports
component lookup/lowering and shared scheduling separately; they overlap other
aggregate stage timers and must not be added twice.

Remaining costs include source provenance construction, QASM assembly, shared
atom-action scheduling, validation and actual noise evaluation. This change does
not make a novel frontier a constant-time lookup, nor reuse a whole component's
precompiled transport waveform. It removes repeated native decomposition and DAG
construction from that frontier's offline calibration.

## Small acceptance

Run from the root with the physical environment and root on `PYTHONPATH`:

```powershell
python -m experiments.analysis.msd_reuse_acceptance --output <new-output-directory>
```

This is an explicitly requested, bounded physical comparison, not a parameter
scan or a repository bench suite. It uses d3, two vertically arranged factories,
one AOD, load/store 10 us, measurement 100 us, zero classical processing, and the
unchanged illustrative noise configuration.

| Controlled case | Reference and reuse completion |
| --- | ---: |
| Synchronous raw postselection frontiers | 2974.452471 us |
| One peer retries twice while the other holds | 7723.357414 us |
| Joint logical-Z readout conflict | 520.000000 us |

The retry outcomes are deliberately scripted scheduling witnesses, not measured
acceptance statistics or an end-to-end factory seed campaign. All cases compare
Atom programs, entry/exit worlds, constraints, resource intervals, primitive
counts, exposure and recomputed noise channels. The readout case independently
checks that the two singleton plans compete for nine identical destinations.
The joint physical validator then checks their conflict-free combined schedule.

The first run builds two component keys. A new singleton retry combination uses
the disk template with zero internal recompiles. Two repeated frontiers hit the
whole-action cache. Nine further seed-labelled requests hit saved schedules, with
no new action or component compilation. Native-DAG tests additionally compare
raw preparation, accepted growth/canonicalization, S and CNOT at d3/d5/d7 to the
full combined-QASM frontend. This is stronger than counting cache files, but does
not establish end-to-end high-N throughput or a decoded output error rate.

Inspect `summary.json` for cold/hit counts and software timings. The initial local
run measured about 1.48 s for the new retry frontier including noise calibration,
versus 0.07--0.08 s for already cached frontiers. These are software wall times,
not physical completion times, and are not a like-for-like speedup comparison
against the reference's action-only timing.

Server restart is separate from these local witnesses: old completed results,
failed generations and in-flight output receipts remain intact. Changed execution
and cache source identities must be frozen explicitly before resuming; do not
rewrite old manifests or silently resume the paused old executables.
