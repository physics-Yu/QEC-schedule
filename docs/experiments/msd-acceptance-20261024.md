# MSD preparation and component calibration acceptance

Date: 2026-10-24. Source branch: `codex/msd-experiment-standard`.

Follow-up: the [actual joint-SE scaling experiment](parallel-se-scaling-20261024.md)
now measures all N W1 SE instances together with matched same-world controls.
The original results below remain single-component position calibrations.

## Delivered scope

1. A versioned physical experiment standard and explicit top-to-bottom factory
   layouts, with independent distance/pipeline axes and a first-level experiment
   plan. Second-level sizing remains conditional on first-level arrival traces.
2. A source-grounded interface audit and compact component calibration adapter
   that reuses the existing nonzoned compiler, validation, replay and activity
   APIs. The active logical compiler checkout was inspected read-only.
3. Odd-distance surface-code definitions and concrete components, including the
   actual S/Sdag construction, plus readout destination selection fixes.

The standard is measurement 100 us, result processing 0 us, LOAD and STORE each
100 us. Other reference values remain CZ 0.5 us, rotation 1 us, reset 5 us and
linear movement 1 us/um. Storage/gates occupy the lower half-plane y<=0; readout
occupies y>=50 um. Finite execution windows are generated per geometry and do
not impose a fixed area budget on the mathematical model.

## Verification

- Readout focused baseline: 58 passed. After four new regressions: 62 passed.
  Direct consumers: 158 passed. Full physical compiler suite: **1763 passed**.
- Original d3 plus the initial generic suite: **468 passed**. After two final
  metadata/compatibility checks, the generic suite alone: **69 passed**. The
  unchanged original d3 suite contributes 401 of the combined baseline tests.
- Experiment geometry/accounting/provenance/CLI checks: **33 passed** across the
  final focused runs. Ruff formatting/lint and strict scoped mypy passed.
- d5/d7 templates compile, bind and expand against complete six-patch occupied
  worlds. Source and actual Clifford action, retained measurements, role exits,
  physical validation and replay are checked. H includes real carrier rotation.
- Independent raw deterministic-condition rank checks cover odd d=3..15;
  correction-column checks cover odd d=3..11. This does not establish noisy
  circuit-level fault distance or a decoded logical error rate.
- d5,N4 bottom-row SE and S were repeated with padding 20 and 1020 um. All actual
  targets, trajectories, times and illuminated atom identities agree. Only empty
  extensions of symbolic CZ coverage rectangles differ. Both complete physical
  validations and exact return-home checks pass.

## What the calibration measures

Every cell executes one actual component at the bottom factory row, with all
`6*N*(2*d*d-1)` atoms present. Other factories are idle spectators. The matrix
therefore measures distance, world size and physical location dependence. It is
not a parallel-factory throughput measurement. `raw_t` is the primitive; its
required extra SE/postselection composition is tested separately in the code
library. Preparation correction metadata is not charged as an executed action.

`compile_wall_s` is host time for the physical backend call only; world creation,
frontend parsing, validation and serialization are outside it. Modelled device
time, interval-union transport time, summed action time and cumulative atom idle
time are reported separately. Busy plus idle independently conserves whole-world
atom-time. Action exposure includes all actual CZ spectators, not only gate pairs.
The benchmark does not run a noise model or infer quality from exposure.

## Completed calibration matrix

All **72/72 cells passed**, with no failed, timed-out or atom-budget-censored cells.
Coverage: d=3/5/7, N=1/2/4, eight operations. End-to-end campaign host time was
356.672 s; this is not a device production time or a controlled host-speed comparison.
Independent endpoint verification passed **1623 assertions**; the complete retained
d3 S trace was separately revalidated and replayed, with metrics independently
recomputed from typed action intervals. The other 71 schedules were validated
during their runs but were not retained for a second independent replay.
Every cell used source commit `323533d8e7f7a3e9ac8f25223eb5aec0984eb130` and runtime source fingerprint
`6b85d35ced74baa3ea892a98b8a32c51fc79e343cf71dce2da3015ff2b909dcb`. All retained accepted-output and logical-error fields are null.

The following times are per component in the bottom row, with all factory atoms present:

| d | N | Total atoms | SE (us) | Actual S (us) | W1-to-W2 CNOT (us) |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 3 | 1 | 102 | 3128.817 | 4548.291 | 608.500 |
| 3 | 4 | 408 | 3728.817 | 5148.291 | 608.500 |
| 5 | 1 | 294 | 3208.817 | 8313.876 | 688.500 |
| 5 | 4 | 1176 | 4048.817 | 9153.876 | 688.500 |
| 7 | 1 | 582 | 3288.817 | 14799.576 | 768.500 |
| 7 | 4 | 2328 | 4368.817 | 15879.576 | 768.500 |

The N dependence in measured components comes from the bottom-row distance to
readout. These CNOT cells contain no readout and their times coincide across N;
their whole-world atom-time and spectator illumination still grow with N.
The real S construction is substantially more expensive than one ordinary SE
under this transport strategy, motivating separate measurement of its fold routes.

- [Compact checked-in results](../../experiments/msd/results/20261024-component-calibration.json)
- [Independent endpoint verification](../../experiments/msd/results/20261024-independent-verification.json)
- [Frozen source hashes](../../experiments/msd/results/20261024-source-snapshot.json)
- [Scaling plot](../../modules/physical_compiler/artifacts/msd-standard-20261024/component-scaling.png)
- [Representative vertical layout](../../modules/physical_compiler/artifacts/msd-standard-20261024/vertical-layout.png)
- [Offline d3 S replay](../../modules/physical_compiler/artifacts/msd-standard-20261024/d3-s-replay.html)

The replay contains 102 atoms, 86 steps, 4548.291397 us and zero structural viewer
observations. It is a single S-component witness, not a whole factory schedule.
Plot layout was rendered and visually inspected; human acceptance remains pending.

## Bottlenecks and next integration steps

- A shared upper readout half-plane gives lower factory rows longer journeys.
  Infinite readout area does not remove that transport cost or AOD order rules.
- Under the retained reference pulse semantics, every shared-zone atom is
  illuminated by global CZ pulses. Increasing N increases spectator exposure.
  A more local illumination model would be a distinct hardware configuration.
- The current logical compiler's parallel declarations assume horizontal tiles
  with equal row trajectories. A vertical/common-readout profile must explicitly
  validate shared AOD behavior. Do not overlay independently compiled timelines.
- The new component library supplies ideal symbolic corrections, local raw
  postselection and physical interfaces. Larger-distance correction execution,
  event probability ports and the factory backend adapter remain unimplemented.
  The fast logical compiler must consume these interfaces before full production
  runs can produce accepted-output statistics.
- Freeze inter-operation/waiting EC policy, output delivery/release, retries and
  buffer aging in that runner. Then measure startup and steady state under the
  observation windows in the plan. Preserve output-error fields as null until a
  supported quantum quality model exists.
- Only after first-level accepted-arrival traces exist, size second-level supply
  and buffers; compare central, surrounding and grouped layouts under matched
  physical budgets. Mixed-distance transfer needs an explicit protocol.

## Reproducible entry points

- [Experiment plan](../../experiments/msd/level1_plan.json)
- [Configuration and commands](../../experiments/msd/README.md)
- [Component API and evidence](../../modules/codes/rotated_surface/README.md)
- [Concrete integration audit](msd-interface-audit.md)

No changes were made to the separately active logical compiler worktree. The
original checkout's existing `agent.md` modification was preserved. No push was
performed. Human acceptance of the delivered layouts and traces remains pending.

## Commits

- `53bf87f`: free geometry-derived readout destination selection.
- `323533d`: odd-distance components and frozen experiment standard.
- The final documentation/results commit contains this report and compact verified data.
