# Fast logical experiments with calibrated component profiles

Status: Accepted and implemented, 2026-10-24.

Update, 2026-10-24: [ADR 0051](0051-theoretical-factory-acceptance.md) supersedes
the acceptance-model default described below. The corrected full/fast entries
sample the theoretical joint final-MX event with an explicit accepted-input
Z-error parameter; physical no-fault costs are separate diagnostics. The kernel,
scheduler, calibration and accounting decisions in this ADR remain in effect.
The first study and all numbers below are retained as historical **legacy
physical-no-fault-proxy** evidence. Its zero outputs are not theoretical 15-to-1
failures and cannot establish theoretical distillation throughput.

## Context

The factory-array entry preserves protocol decisions, local retries, cohort
barriers and resource ownership while expanding every selected component into
real atom actions. That path provides detailed physical validation and source
projection evidence, but its expansion, whole-world replay and activity-based
cost evaluation are too expensive to repeat for a larger Monte Carlo study.

The new entry must retain the actual recipe operations and stochastic control
flow while avoiding atom movement compilation for each case. It must still
distinguish movement, gate/reset, measurement and waiting costs. A faster timing
model must not inherit a physical-validation claim from its calibration cases.

The fresh pre-change combined baseline is 1085 passing tests in 283.53 seconds.
This ADR records the implementation, acceptance conditions and independently
checked first experiment and final full-suite regression below.

## Decision

### One protocol runtime, two execution kernels

`FactoryProcess` and `CooperativeFactoryRuntime` remain the common protocol and
coordination implementation. A kernel boundary supplies execution receipts and
event-source dependencies. The physical kernel continues to use real components,
atom worlds and its existing physical serialization. The fast kernel uses
calibrated component phases and logical carrier identities, without atom IDs.

The fast kernel must preserve:

- Explicit code/recipe selection and all component calls, including resets,
  canonicalization, conditional S, final measurements and accepted output X.
- Line, factory batch, preparation and attempt identities; the occurrence-keyed
  random sampler remains independent of admission order.
- Local rejection/retry and finite budgets; successful peers hold their state at
  the existing stage barriers, and terminal lines leave the active cohort.
- Carrier ownership and epochs, token readiness, reservation, single consumption,
  discard and offered output holding.
- Distinct action-exit, result-availability and event-release times. Logical
  output-port dependencies replace physical result references in fast records.

The fast path does not create an empty or synthetic AtomProgram to satisfy a
physical interface. It does not invent physical measurement values, physical
result identities, trajectory proofs or a successful physical validator result.
The output identifies itself as a component/timing experiment. Its logical
constraint checks and profile-domain checks are recorded separately; physical
validation is explicitly **not run**.

### Offline calibration and declared coverage

Calibration is a separate, explicit operation. The initial implementation
compresses a frozen serial physical case into reusable profiles: ordered phase
durations, relative patch/role information, resource-busy spans, holder/exposure
information and discrete survival contributions. The calibration retains its
source-case and source-implementation hashes. Runtime results retain the profile
hash, recipe identity, model parameters and their own logical schedule identity.
A calibration-source hash is not evidence that a new fast case has been
physically expanded or validated.

Profiles are selected by the relevant component, parameters, correction class,
signed relative geometry, code/protocol version and device/noise assumptions.
Coverage of possible branches is explicit. Unsupported calls, geometry, noise
settings or classes fail with a domain error; the runtime must not silently
compile a missing profile, interpolate an unrelated case or assume zero cost.
Any code-derived extension to a calibration table needs its own documented rule
and tests.

Logical CNOT counts, calibrated native-operation counts and component-phase work
are separate quantities. In particular, one transversal CNOT component is not
one physical two-qubit gate. Identity corrections have zero physical pulse work
while retaining their protocol identity and feedback dependencies. Other Pauli
corrections keep their calibrated physical pulses and costs; this entry does not
introduce a global software Pauli frame.

### Timing and parallel resource use

The common scheduler continues to admit declared shared-AOD and local component
families, checking participants, spaces, row/column demand and readout capacity.
The fast kernel applies the calibrated phase structure to that admission rather
than constructing atom trajectories. Local members can retain different exit
times; the shared writer still advances to the wave's last exit before admitting
another wave.

Result availability is derived from the calibrated measurement-phase endpoint
and latency, together with any required component exit. It is not generally
`component duration + readout latency`: real components can transport atoms after
measurement. A ready event is released only when the common runtime can process
it, including its completed-wave policy. No latency tail is charged twice.

Ordered phase durations are retained where needed for reproducible timing. Full
and compact schedules may differ slightly because of floating-point accumulation
or deliberately compressed phases. Validation reports absolute time errors and
an explicit tolerance; it does not promise byte-identical full/fast timestamps.
Tolerance must not hide a missing dependency or an operation starting before its
required feedback or resource becomes ready.

### Cost quantities and units

The report keeps these quantities distinct:

| Quantity | Meaning |
| --- | --- |
| Operation counts | Recipe/component counts and calibrated native gate, reset, transfer and measurement counts, labeled by level |
| Component-category work, in microseconds | Sum over members of their occupied phase spans for movement, gates/reset and measurement exposure |
| Resource busy time, in microseconds | Union of occupied intervals for each shared AOD, readout or local-control resource |
| Exposure work, if reported | Time weighted by a declared role/atom multiplicity, with units such as atom-microseconds |
| Makespan, in microseconds | The scheduled case horizon, including feedback gaps and cohort/resource waiting |
| Compilation wall time | The software time needed to produce the abstract case, reported separately from model time |

Member work adds across parallel calls. Shared transport busy time counts the
combined wave once. Busy intervals on different resources may overlap and cannot
be summed as elapsed time. Component-category spans can also overlap; a sum of
movement, gate and measurement work is not automatically the makespan.

Measurement exposure and classical result latency are separate. Per-line
`waiting_peers`, `waiting_feedback` and `waiting_resources` describe runtime
states, not extra physical operations. Waiting summed over lines is not global
idle time. The report preserves this distinction even when a shorter or identity
member remains inside an admitted wave until its peers finish.

### Probability and exposure estimates

Raw preparation retains the joint acceptance/byproduct distribution. T
consumption retains its declared conditional branches. An accepted scalar raw
probability does not determine the correction class, and unsupported output
quality must not fall back to an invented input error probability.

The fast cost path combines calibrated discrete contributions with exposure and
idle segments from the current abstract schedule, clipped to the same declared
raw-exclusion and final-check scopes. It uses the selected `noise/v1` formulas
where supported, but the result is labeled a **profile estimate**, because its
activity is reconstructed from calibration rather than a newly validated atom
program. Discrete loss/gate factors must not be charged again through an idle
term. Profile or partition uncertainty is separate from Monte Carlo uncertainty.

A component's scalar no-fault probability must not simply be exponentiated by
new duration and presented as an exact `noise/v1` evaluation. In particular, T2
identity probabilities depend on the exposure partition; multiplying estimates
for split intervals need not equal evaluation on the unsplit interval. Calibration
records its partition/holder assumptions, and the comparison reports probability
errors against covered physical references.

Factory estimates select each line's roles and its own evaluation window. Only
that line's raw-horizon union is excluded. Peer-retry waiting inside the evaluated
window remains included. The inherited whole-line raw exclusion still omits
exposure of that line's other patches during its raw horizons. Each factory
window ends at its own final-check evaluation; later final-decision waiting,
output correction and output holding remain outside that estimate unless a
separately declared downstream assessment is added.

Shared-control common-mode noise, unsupported cross-line interactions, decoded
logical success and concrete loss/replacement trajectories are not inferred.
The physical no-fault estimate is not logical fidelity. Actual accepted-state
quality and `logical_success` remain unknown.

## Initial scaling experiment

The first planned line counts are **1, 2, 4, 8 and 16**. The normal seed set starts
at **0 through 15**. Any extension, such as 64 seeds, is frozen as a separate
recorded experiment plan before its aggregate results are reported. The selected
witness **1167024** is a separate golden comparison and is excluded from normal
statistics.

The default resource budget is fixed at **one AOD, four rows, 48 columns and 96
simultaneous readout atoms**. Increasing line count does not automatically increase
these capacities or an explicit `max_parallel` bound. The required placement area,
shared/readout regions and AOD workspace extent may grow and are reported
separately. This is a fixed count-capacity study with an enlarged modeled layout,
not a claim that calibrated hardware field of view scales without cost.

Each independent seed produces one complete array trajectory. Lines within a
trajectory share barriers and resources, so they are not interchangeable with
independent shots. Aggregates report the per-seed output count, makespan, work,
busy times, retries and terminal statuses. Expected rejection/exhaustion cases
remain in the sample; conditioning on successful runs would bias production
metrics.

The definition of throughput is explicit. For repeated complete trajectories,
the ratio of total output count to total simulated duration differs from the
mean of per-trajectory ratios. Uncertainty calculations resample or otherwise
treat independent seeds as the statistical unit. Zero observed outputs do not
establish zero success probability; a degenerate bootstrap interval must not be
reported as certainty. A separately labeled model expectation from conditional
acceptance probabilities may be useful, but never replaces sampled output and
resource records.

## Acceptance and failure tests

1. **No physical execution path:** poison component compilation, bound expansion,
   physical invocation/finalization, atom validation and physical activity/cost
   construction during a fast run. A valid calibrated run must complete without
   reaching them. Missing calibration must fail rather than trigger a fallback.
2. **Shared control semantics:** exercise local retry, successful-peer holding,
   terminal cohort departure, empty/conditional corrections, safe exits and token
   single use through the common process/runtime implementation.
3. **Covered golden comparison:** use the frozen full serial/parallel cases with
   the same recipe, seed, noise settings and capacity policy. Compare complete
   event identities/uniforms, calls, admissions, barriers, readiness, resource
   lifecycle and timing errors. Report probability/model differences; do not
   force full/fast byte equality or substitute saved outcomes for sampling.
4. **Accounting checks:** verify retry costs are included, identity work is zero,
   shared busy intervals are unioned, result latency is distinct from measurement
   exposure and summed line waiting is not relabeled as makespan.
5. **Domain and evidence checks:** reject mismatched hashes/versions and unsupported
   geometry or model parameters. Fast output must not claim current physical
   validation, atom trajectories, physical result bits or decoded logical success.
6. **Scaling checks:** fixed capacities constrain wider cohorts; seed replay is
   stable, profile reuse does not grow into per-case compilation, and statistical
   records preserve every normal seed and distinguish witnesses.

Software runtime is measured for the reported scaling matrix, with profile load
and export timed separately. Peak process memory was not measured in this study;
logical carrier counts and profile size are not substitutes for that measurement.
Unit tests avoid unstable wall-clock speed thresholds. Logical validity,
physical-reference agreement, approximation error and software speed are separate
acceptance results.

## First experiment acceptance, 2026-10-24

The [independent audit](../../modules/logical_compiler/artifacts/fast-logical-verified/independent-audit.md)
reads the three detailed witness/control exports and all 80 scaling summaries.
These local experiment files are ignored artifacts, not unit-test dependencies.
No compilation or physical simulation was rerun by that audit.

All three detailed runs retain the same 85 runtime/code source hashes at start
and finish, matching current files. Their profile SHA-256 is
`bdb0ef1cd8381f507cd1d9fbc2d340b577bcfc119893280a4ae36c76ed1d00a8`.
The offline reference-case and manifest hashes verify independently.

For selected witness seed 1167024, the parallel and serial modeled durations are
77218.59058432898 and 138097.33773164128 microseconds. All 222 call start/end
times, 59 event availability/release times, admission member groups and 87 stage
barriers match the corresponding full physical references with zero observed
timing difference. The maximum observed absolute factory-probability difference
is 8.966785647324116e-15; this is evidence for the covered witness and control,
not an accuracy guarantee for every larger layout.

The audit independently reproduces all 59 seeded joint decisions, verifies 862
unique logical result IDs and 814 dependency references, and checks 30 single-use
raw tokens and one offered output. Each detailed run has 33 raw attempts, three
rejections and six S calls equal to six m1 requests. Thirty-three raw invocations
compress two physical round parts into one logical receipt; flattened result
dependencies match, while physical sub-expansion identity is deliberately not
reproduced. Four deterministic production/replay files are byte-identical;
software-time metadata is not claimed byte-identical.

The prespecified sweep completes 16 seeds at each of five sizes, holding one AOD,
four rows, 48 columns and 96 readout atoms fixed while explicitly growing area:

| Factories | Mean modeled duration (us) | Mean software time (s) | Observed outputs |
| ---: | ---: | ---: | ---: |
| 1 | 74980.185487 | 0.226324 | 0 |
| 2 | 81980.909205 | 0.464966 | 0 |
| 4 | 91778.631993 | 0.948067 | 0 |
| 8 | 99605.321266 | 2.066698 | 0 |
| 16 | 138934.732230 | 4.925887 | 0 |

The 80 run summaries and aggregate statistics pass 320 independent checks. The
recorded software time totals 138.1110648001195 seconds. Across 496 coupled line
executions, there are 8,620 raw attempts, 1,180 rejections, 7,440 accepted raw
resources and 2,708 S calls. Every sampled final factory proxy rejects. Per size,
the any-output Wilson 95% interval is [0, 0.1936076805344365]; zero observed output
does not imply zero probability. There are 16 independent seed trajectories per
size, not 496 independent lines or 80 independent trials for one probability.
The separately selected witness is excluded from these statistics.

The complete event/dependency audit covers the three detailed cases; the sweep
retains summaries rather than all full trajectories. Fast outputs remain logical
estimates with no physical validation or decoded logical-success claim. The final
peer barrier, output X and output hold remain outside factory acceptance cost.
Independent tests cover forbidden physical entry points, real-recipe retries,
missing coverage, immutable calibration, and tampered feedback evidence.

The final combined regression passes **1159 tests in 275.72 seconds**, compared
with the same-command baseline of 1085 in 283.53 seconds. There are no failures,
skips or xfails. The audit independently reads and hashes the
[final log](../../modules/logical_compiler/artifacts/fast-logical-verified/tests.log)
and [baseline log](../../modules/logical_compiler/artifacts/fast-logical-baseline.log).
The coordinating agent also records Ruff check/format passing for all 29 changed
Python files and strict mypy passing for all 18 production files. The readback
audit does not rerun those commands or the full suite.

Both regression runs use the logical worktree as their current directory:

```powershell
$env:PYTHONPATH='C:/Users/yuyqp/Documents/ChatGPT/NADiT/modules/physical_compiler/src;C:/Users/yuyqp/.codex/worktrees/logical-qasm-frontend/NADiT'
& 'C:/Users/yuyqp/Documents/ChatGPT/NADiT/modules/physical_compiler/.venv/Scripts/python.exe' -X faulthandler -m pytest modules/logical_compiler/tests modules/codes -q
```

The quality commands are `ruff check` and `ruff format --check` on the 29 changed
Python files, and `mypy --strict --explicit-package-bases --follow-imports=silent`
on the 18 production files, with `MYPYPATH=PYTHONPATH`.

## Alternatives and consequences

Repeated full atom compilation remains the reference path for physical validation,
but is not the scalable experiment entry. Overlaid independent line timelines
would lose the shared scheduler and barriers. A second hand-written factory state
machine would risk divergent retry and ownership semantics. Reusing only whole-case
durations or scalar success probabilities would discard the requested operation,
postselection and cost accounting. These alternatives are not selected.

The kernel boundary adds a second execution representation while keeping the
protocol implementation common. It requires explicit calibration coverage and
honest estimate labels, and cannot certify a new atom layout by itself. The
physical entry and its serialization remain available for validation at selected
points. General QASM execution, asynchronous scheduling, inventory maintenance and
new error-correction physics are outside this change.

See [ADR 0048](0048-synchronized-factory-resource-ledger.md) for synchronization and
resource history, and [ADR 0049](0049-component-parallel-admission.md) for declared
component parallelism.
