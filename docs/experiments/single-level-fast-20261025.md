# Single-level fast MSD: assumptions and coverage

Status: complete. All 192 production trajectories are recorded and audited;
failed line outcomes are retained explicitly.

## Final results

All **192 production trajectories** (12 cells, 16 seeds per cell) are saved.
Every trajectory covers its requested observation horizon. **183 windows**
meet the original failure-free primary criterion; **9** contain an in-window
line budget stop and remain in the secondary observed-window statistics.
All 12 pilots, the bounded smoke and all production no-atom guards passed.
The independent auditor checked all 192 records and deeply read 13 cases with
no findings. Runtime source was frozen at commit `733c81a`, with pooled
orchestration committed in `537bc74`; the source identity is recorded in the
[manifest](../../experiments/msd/results/single-level-fast-20261025/manifest.json).

The following **observed rates include line budget stops** and pool accepted
outputs over all fully observed fixed windows (states per second). They are
finite-window model estimates; no asymptotic steady-state claim is made.

| d | N=1 | N=2 | N=4 | N=8 |
| --- | ---: | ---: | ---: | ---: |
| 3 | 8.092 | 11.781 | 14.475 | 15.065 |
| 5 | 3.392 | 4.213 | 4.405 | 3.935 |
| 7 | 2.559 | 3.084 | 3.103 | 2.737 |

Pooled allocated atom-time per accepted output, using the same inclusive
observed-window denominator (atom-seconds per state):

| d | N=1 | N=2 | N=4 | N=8 |
| --- | ---: | ---: | ---: | ---: |
| 3 | 12.60 | 17.32 | 28.19 | 54.17 |
| 5 | 86.66 | 139.56 | 266.99 | 597.64 |
| 7 | 227.44 | 377.44 | 750.18 | 1701.19 |

Mean first-deliverable latency across all 16 seeds per cell (milliseconds).
A later line budget stop does not erase an already observed first delivery.
These values are calculated directly from the seed ledger; the primary
conditional statistics remain separately available in the JSON report.

| d | N=1 | N=2 | N=4 | N=8 |
| --- | ---: | ---: | ---: | ---: |
| 3 | 109.28 | 138.74 | 190.31 | 311.32 |
| 5 | 259.30 | 391.64 | 646.00 | 1242.55 |
| 7 | 344.03 | 537.20 | 912.58 | 1795.20 |

In this fixed vertical layout, throughput is not proportional to pipeline
count. N=8 gives a small additional rate at d3, but lower point estimates than
N=4 at d5/d7. The reserved readout translation grows with the installed array,
while cohort waits and rejection retries remain explicit. These are results for
this policy and center-cost model, not a proof of an optimal factory count or
code distance. A distance choice would also need an output-quality model.

The 12 paired half-window rate-difference confidence intervals all include zero.
This diagnostic did not detect a half-window rate difference at its stated
95% level; it does not establish asymptotic stationarity. Confidence intervals
cover production-seed variation only, excluding calibration uncertainty and
center-model discrepancy.

Full-case totals, **including warmup and drained work after the window**:

- Raw preparation attempts: **286,579**.
- Raw rejections: **63,319**.
- Factory batch attempts: **14,884**.
- Rejected factory batches: **2,123**.
- Conditional S calls: **81,708**.
- Added standalone SE calls: **4,086,940**.
- Accepted and delivered output resources: **12,761**.

There are **11,619 accepted/delivered outputs inside the observation windows**.
The complete cases contain **5,822,432 logical component calls**. This explains
why keeping full DAGs, interface results and event ledgers is appreciable
software work even without atom compilation. Software worker time is separate
from all modeled production-time and throughput quantities.

The nine terminal line stops occur at N=8, for seeds 5, 11 and 13 at each
reported distance. Each is `distillation_rejected` after four rejected batches;
no unexpected protocol failure was found. Earlier outputs from a line that
later stops remain counted, and peer lines continue through the window.

## Published files

- [Summary and all interval statistics](../../experiments/msd/results/single-level-fast-20261025/summary.json).
- [192 seed ledgers](../../experiments/msd/results/single-level-fast-20261025/seed-ledger.csv).
- [720 line ledgers, including batch decisions and failures](../../experiments/msd/results/single-level-fast-20261025/line-ledger.csv).
- [192 cost records, geometry, transport, idle and operation exposure](../../experiments/msd/results/single-level-fast-20261025/costs.csv).
- [Scaling figure](../../experiments/msd/results/single-level-fast-20261025/scaling.png): its primary panels condition on eligible failure-free windows; the inclusive rates above are separate.
- [Independent final audit](../../experiments/msd/results/single-level-fast-20261025/independent-audit.json).
- [Bounded acceptance and replay evidence](../../experiments/msd/results/single-level-fast-20261025/small-acceptance.json).

Complete compressed case and ledger files are retained locally under
`modules/logical_compiler/artifacts/msd-single-level-fast/production-20261025-optimized/cells/dD-nN/seed-SSSS/attempt-0001/`.
Each completion record lists their byte hashes. CSV completion paths resolve
from the repository root. The full corpus is ignored by Git; compact reports,
configuration, reference costs and source are committed.

## Frozen configuration

The [configuration](../../experiments/msd/single-level-fast-20261025.json)
requests d=3/5/7, N=1/2/4/8, seeds 0 through 15: 12 cells and 192 trajectories.
The S cost hypothesis is one simultaneous 1 us pulse per data atom, with
independent X/Y/Z probabilities of 0.0001 each. S has no measurement result or
transport. These values are explicit experiment assumptions, not hardware
measurements or a surface-code gate proof.

After each complete parity rotation, all five work patches receive d additional
SE rounds, with each round exposed for batching. Initialization, three-round d3
raw injection, accepted-only growth and local retries are retained. A
`preparation_only` control is also selectable. Conditional S finishes before
uncompute. EC executes on both correction branches and waits for all results.

The existing p=0.01 independent accepted-input Z-error model controls the
ideal-Clifford 15-to-1 final checks. It is independent of raw supply rejection.
The configured ideal output sink excludes external transport, external
consumption and external reset. Subsequent factory preparation remains counted.

## Pure fast boundary

The same logical scheduler, factory process, seeded event backend, and resource
ledger execute without atom program generation or execution. A runtime guard
fails before known physical compiler, component expansion, native replay,
validation, activity reconstruction, or calibration entrypoints can run.
Every worker needs its own guard; the current instrument is thread-local.

The center-model API is:

```python
from pathlib import Path
from experiments.msd.fast_guard import no_atom_execution
from modules.codes.rotated_surface.assumed_s_profile import AssumedSProfile
from modules.codes.rotated_surface.center_costs import load_center_references
from modules.codes.rotated_surface.center_profile import CenterSurfaceFactoryProfile
from modules.codes.rotated_surface.factory_assumptions import (
    ECPolicy, TransversalSAssumption, assumed_factory_recipe,
)
from modules.logical_compiler.examples.surface_factory_fast import run_surface_factory

s = TransversalSAssumption((0.0001, 0.0001, 0.0001), duration_us=1.0)
ec = ECPolicy("after_rotation", "distance")
references = load_center_references(Path("experiments/msd/center-reference-costs.json"))
base = CenterSurfaceFactoryProfile(references, distance=3, count=2)
profile = AssumedSProfile(base, s)
recipe = assumed_factory_recipe(profile.distance, s=s, ec=ec)
with no_atom_execution() as audit:
    result = run_surface_factory(profile, seed=0, input_z_error=0.01, recipe=recipe)
evidence = audit.to_dict()
```

The S overlay can also wrap an exact profile. That exact provider must supply
every other component and joint frontier; it never silently changes to the
center model when calibration is missing.

With the repository's Python 3.12 environment and physical compiler source on
`PYTHONPATH`, the reproducible sequence is:

```text
python -m experiments.msd.single_fast smoke --config experiments/msd/single-level-fast-20261025.json --output <new-campaign-directory>
python -m experiments.analysis.single_fast_pool --config experiments/msd/single-level-fast-20261025.json --output <same-campaign-directory> --workers 4
python -m experiments.analysis.single_fast_report --campaign <same-campaign-directory> --output <new-report-directory>
```

Software workers process independent seeds. Every simulated trajectory still
uses one shared AOD. Resume verifies frozen source/configuration/reference
identity, task parameters and artifact hashes. Full cases and ledgers are stored
as deterministic gzip JSON; summaries remain directly readable JSON and CSV.

## Exact cache inventory

An instrumented read of the available historical joint profiles found:

| Distances | N | Existing profile | Missing static coverage |
| --- | --- | --- | --- |
| 3, 5, 7 | 1 | present | 5 work-patch SE contracts and complete final-MX frontier |
| 3, 5, 7 | 2 | present | 10 work-patch SE contracts and complete final-MX frontier |
| 3, 5, 7 | 4 | present | 20 work-patch SE contracts and complete final-MX frontier |
| 3, 5, 7 | 8 | absent | full profile |

This is only a static inventory. Old source applicability and all dynamically
encountered retry frontiers still require validation. These old records cannot
be treated as current-model production results. This initial cache inventory
executed no production trajectories. The selected center-cost campaign is a
separate, subsequently frozen run.

Run the read-only inventory with:

```text
python -m experiments.analysis.msd_single_fast_preflight --config experiments/msd/single-level-fast-20261025.json --profiles <historical-joint-profile-root> --output <new-report.json>
```

The user selected a geometric model: retain intrinsic component costs, and
replace readout and CNOT travel by center-to-target distance times 1 us/um.
`center-reference-costs.json` contains hash-checked compact references for
d3/5/7, extracted read-only from existing standard/2 summaries. No native
program is decoded or replayed. Local SE motion, transfers, gate/reset/readout
times and the original readout batch counts are retained.

For N factory rows with pitch `20*d + 40`, every source row translates by
`50 + 20*d + (N-1)*(20*d+40)` um into disjoint readout rows, preserving order.
CNOT uses the signed participant geometry for batching and the center distance
for travel; the configured zero target offset is a cost reference, not a
physical docking instruction. Intrinsic gate work is not rescaled with N.

Raw supply acceptance is held at its archived reference: 0.7817840576171875
for d3 and 0.7775421142578125 for d5/d7. New geometric waiting and movement
exposure is counted, but detector acceptance is not re-simulated. This is
separate from the accepted-input quality p=0.01 and final theory check.

Macro category partitions preserve component duration, primitive counts,
movement distance and addressed busy-atom integrals. They are not a native
action-order timeline; partial-window exposure uses an explicit uniform
aggregate approximation. Shared resource times use interval unions.
Across complete seeds, primary cost/output is pooled total cost divided by
accepted outputs, including costs of zero-output windows. Failed/truncated
windows retain their incurred costs in a separate diagnostic total.

## Omitted or unknown quantities

- Startup begins with all allocated atoms at the declared home positions.
  Initial array assembly and replacing physically lost atoms are excluded;
  the retained SLM/AOD load and store costs are ordinary transport transfers.
- Raw supply is on demand and the output sink is always ready. Inventory,
  prefetch, output-consumer backpressure and multi-level delivery are excluded.
- The model retains homogeneous component batches and cohort barriers. It
  does not establish an optimal schedule or an atomic route for mixed waves.
- The hypothetical S is not an independently verified logical gate.
- Supplementary SE syndromes are not sampled or decoded; waiting-period
  maintenance and actual noisy logical correction are omitted.
- Generic preparation uses a one-Pauli-layer correction-cost envelope.
- The final theory model does not include physical factory-gate, storage or
  growth error as decoded output LER.
- External output delivery/consumption/reset are excluded by the explicit sink.
- Dynamic occupied-area-time and atom exposure unavailable from summaries
  remain unknown. They must not be reconstructed by adding singleton costs
  across shared-AOD waves.

## Verification scope

Actual-reference d3/N2 bounded acceptance, two completed production cycles per
line, gave the following complete-case counts:

| Seed | Raw attempts | Raw rejections | Conditional S | Added SE calls | Delivered outputs |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0 | 82 | 22 | 20 | 660 | 4 |
| 1 | 111 | 21 | 41 | 990 | 4 |

Seed 0 placed all eight initial raw calls in one wave. Both W4 preparations
rejected once and retried locally; the other six accepted patches were not
reprepared. Later supply paths differed between the two lines. Exact seed-0
case and ledger replay matched, and seed 1 produced a different event history.
Every consumed resource passed ready-time/epoch checks, each S preceded
uncompute, and every added EC round joined its five work patches and result
availability. The no-atom guard passed. These finite cases establish the
protocol path; sustained rates come from the separate production campaign.

The structural fixture exercises the full 4+11 protocol, independent retries,
conditional assumed S, added EC, multiple production cycles and unique output
consumption under the no-atom guard. Fixture timing is deliberately synthetic
and is not a performance result. Exact-cache missing-data behavior is checked
separately.

Related fast baseline initially reported nine reference-hash failures caused by
CRLF checkout of `nonzoned_cnot_reference.json`. Restoring that file's existing
Git LF bytes, with no content diff, made all nine checks pass. No assertion or
expected hash was changed. Runtime checks remain focused; no full fast+slow or
bench run was started for this phase.

The mapped implementation/consumer fast run passed 1,818 tests (767 slow and
22 bench tests not selected). After the scheduler optimization, the affected
fast run passed 1,432 tests (190 slow and 9 bench tests not selected). These
overlapping selections are separate checks, not an additive unique-test count.
The runner fix passed 19 focused tests. Changed production files passed the
applicable Ruff and strict mypy checks; the standalone report was checked by
syntax/lint, representative arithmetic, artifact verification and figure review.
Final publication edits use documentation/link and report checks only.

Local ignored evidence is retained under
`modules/logical_compiler/artifacts/msd-single-level-fast/`: baseline log,
reference recheck, exact cache inventory, and bounded acceptance artifacts.

The first large pilots exposed repeated full-history DAG validation on each
append. Their completed pilot records and interrupted seed attempts remain in
the earlier run directory. The scheduler now validates only new nodes against
the already-valid immutable history, and scans only unstarted frontier nodes.
No dependency, batching, epoch, random event or timing rule changed. Differential
tests preserve admission hashes and snapshots; the actual d3/N2/seed0 case and
ledger are byte-equivalent to the pre-optimization reference. Production is
restarted under a new frozen source identity rather than relabeling old runs.
