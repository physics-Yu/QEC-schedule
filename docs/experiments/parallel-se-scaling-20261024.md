# Joint SE scaling: completed fixed-standard experiment

Date: 2026-10-24. Branch: `codex/msd-parallel-se`.
Runtime source commit: `dbff6e9637f2bb8f9cfe601b77b56a198ce1fcb7`.
Source fingerprint: `3bb88c358293dc3132b3aed0383ba6db4e273462dbecbc1c45c2865f6b4f13eb`.

## Result

All 39 actual schedules completed successfully, covering nine d,N configurations
with joint, serial and every-position solo controls. The complete campaign took
241.875 host seconds. For all nine configurations:

`Tjoint = max(Tsolo_i)` and `Tserial = sum(Tsolo_i)` within numerical tolerance.

The SE instances are actually jointly scheduled. Whole-round latency grows with
N because the farthest factory is farther from readout. There was no additional
serialized transport-batch overhead in this matched set of configurations.
The entire observed position effect is readout MOVE time; every other phase is
unchanged. These are measurements of this scheduler and unlimited line-count
profile, not a proof that shared AOD hardware never creates contention.

## Scope and unchanged inputs

- Each factory contributes one complete SE on W1: N simultaneous SE instances.
  The other five patches per factory remain physically present as spectators.
- One complete world, one global physical clock, one unchanged flexible AOD.
  Source-local barriers preserve independence; no cross-factory DAG edges exist
  in the joint case. The existing `ReadyScheduler` selects gates across all N
  copies, and `NonZonedStrategy` lowers their joint CZ/readout layers.
- Measurement 100 us, result processing 0 us, LOAD/STORE each 100 us. Other
  reference capabilities and timing remain unchanged.
- Factories remain stacked downward below y=0; readout remains y>=50 um. All
  controls use exactly the same Device, positions and complete atom inventory
  for their d,N configuration. Only which source calls are submitted and whether
  serial-control barriers exist differ.
- The standard already has no row/column-count or simultaneous-readout-count
  limit. This was retained, not introduced to obtain the result. Physical line
  ordering, spacing, capture closure, occupancy and pulse constraints remain.

## Completed matrix

Times below include readout return and all result availability. Speedup compares
actual serialized execution with actual joint execution on identical hardware.

| d | N | Joint round (ms) | Serial round (ms) | Position cost (us) | Joint residual (us) | Serial/joint |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 3 | 1 | 3.128817 | 3.128817 | 0 | 0 | 1.000 |
| 3 | 2 | 3.328817 | 6.457635 | 200 | 0 | 1.940 |
| 3 | 4 | 3.728817 | 13.715270 | 600 | 0 | 3.678 |
| 5 | 1 | 3.208817 | 3.208817 | 0 | 0 | 1.000 |
| 5 | 2 | 3.488817 | 6.697635 | 280 | 0 | 1.920 |
| 5 | 4 | 4.048817 | 14.515270 | 840 | 0 | 3.585 |
| 7 | 1 | 3.288817 | 3.288817 | 0 | 0 | 1.000 |
| 7 | 2 | 3.648817 | 6.937635 | 360 | 0 | 1.901 |
| 7 | 4 | 4.368817 | 15.315270 | 1080 | 0 | 3.506 |

Define the slowest solo index i* from total duration, then use that same index
for every exclusive phase:

`G = Tsolo_i* - Tsolo_top`, `J = Tjoint - Tsolo_i*`.

The identity `Tjoint = Tsolo_top + G + J` holds in every case. G is the isolated
position effect; J is the signed net joint-execution effect. J is zero here,
including its complete phase partition. In general J can include contention,
batching gains, changed destination geometry and scheduling decisions; it is
not defined as a pure contention estimator and is never clamped nonnegative.

## Readout distance versus shared AOD behavior

Every joint and solo case uses four CZ pulses, twelve CZ transport episodes
(each LOAD through release STORE) and one readout episode. Each joint episode
serves all N factory instances. The serial controls use four-N CZ pulses,
twelve-N CZ transport episodes and N readout episodes. Source IDs identify the
actual gate participants; ambient spectator illumination is excluded from
concurrency counts.

The factory-row pitch is `20*d + 40` um. In the checked schedules, the farthest
factory's additional readout round trip is therefore
`2*(N-1)*(20*d+40)` um, at the unchanged 1 us/um motion model. This exactly matches
G in the table. Reset, rotations, CZ pulses, gate transport, readout transfers
and 100 us exposure do not contribute to G.

For d=7,N=4, the actual joint transport requires up to **32 AOD rows and 8
columns**. The readout positions and critical distances are:

| Factory, top to bottom | Readout y range (um) | Maximum one-way distance (um) | Common Move duration (us) |
| ---: | ---: | ---: | ---: |
| 0 | 170 to 205 | 310 | 730 |
| 1 | 130 to 165 | 450 | 730 |
| 2 | 90 to 125 | 590 | 730 |
| 3 | 50 to 85 | 730 | 730 |

Joint placement preserves source row order, so the upper factories' destinations
differ from their solo destinations. Nearer factories still wait for the shared
Move's critical distance; they do not finish at their own solo time. Nevertheless
the complete batch costs no more than the farthest solo in these cases. Finite
line-count limits, incompatible concurrent stages, other layouts or competing
workloads can change that result and require separate measured configurations.

Each global CZ pulse in this example illuminates all 2328 world atoms. Of these,
1940 atoms belong to the five inactive patches per factory; their exposure is
retained in cost accounting and does not count as actively scheduled concurrency.

## Verification and artifacts

The unchanged physical compiler was reused, so the validation scope was the new
experiment adapters and their actual physical integration. All **86 experiment
tests passed** (previous suite 33), with Ruff format/lint and strict scoped mypy
passing. Tests cover independent sources/measurements, arbitrary logical input
states and syndrome sectors, exact N=1 control equality, actual multi-owner CZ,
complete return-home/replay, signed decomposition and missing/invalid controls.
The observation wrapper produces exactly the same `CompilationResult` as the
unwrapped strategy in its regression test.

Every successful run was semantically validated against its source DAG and
Device and returned the complete world exactly to its entry arrangement. Full
result and layer/transport records are retained for **all 39 cases**, rather
than retaining only a representative trace. An independent causal audit parsed
the saved result and scheduling JSON and checked phase/movement/control equality
for the completed endpoint.

A second independent endpoint pass revalidated and replayed **all 39 complete
results**, reconstructed action-time integrals and ready frontiers, and checked
all nine comparisons: **156396 invariant checks, zero errors**. This includes
source-based participant concurrency, readout destinations, AOD occupancy
episode boundaries, and the distinction between measurement-ready and final
return-home times. These are deterministic invariant checks, not statistical
samples or logical-noise evidence.

- [Frozen plan](../../experiments/msd/parallel_se_plan.json)
- [Commands and metric definitions](../../experiments/msd/PARALLEL_SE.md)
- [Compact results](../../experiments/msd/results/20261024-parallel-se.json)
- [Source hashes](../../experiments/msd/results/20261024-parallel-se-source-snapshot.json)
- [Independent causal/geometry audit](../../experiments/msd/results/20261024-parallel-se-causal-verification.json)
- [Independent full-trace verification](../../experiments/msd/results/20261024-parallel-se-independent-verification.json)
- [Scaling plot](../../modules/physical_compiler/artifacts/msd-parallel-se-20261024/parallel-se-scaling.png)
- [Actual joint timeline](../../modules/physical_compiler/artifacts/msd-parallel-se-20261024/parallel-se-timeline.png)
- [Offline joint d3,N4 replay](../../modules/physical_compiler/artifacts/msd-parallel-se-20261024/joint-se-replay.html)

The representative replay has 408 atoms, 66 steps, 3728.817490 us and no viewer
structural observations. Figures were rendered and visually inspected; this is
not human visual acceptance or physical hardware execution. Compiler measurement
bits remain case fixtures; no noisy quantum or complete distillation yield is
claimed. The active logical compiler checkout and original user changes remain
untouched. No push was performed.

The implementation commit is `dbff6e9` (`feat(msd): benchmark jointly scheduled
SE with matched controls`). The following results/report commit changes no
runtime source used by the frozen campaign.
