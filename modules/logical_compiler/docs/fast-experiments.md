# Fast logical factory experiments

The generic surface profile entry is
`modules.logical_compiler.examples.surface_factory_fast`. It reuses the same
kernel and factory coordinator with code-owned distance/position coverage, fixed
d3 injection and accepted-only growth. See
[joint single-AOD schedules](../../../experiments/msd/JOINT_FAST_FACTORY.md) and
[ADR 0057](../../../docs/decisions/0057-joint-factory-profile-admission.md).
Joint profiles extend `shared_aod_lockstep` through exact group calibration and
preserve single-AOD cohort barriers. Missing group coverage raises explicitly;
it never substitutes singleton serialization. Multi-AOD independent progression
is paused. The previous generic exclusive-AOD results are withdrawn as parallel
acceptance and retained only as historical controls.
The d3 horizontal profile API documented below remains supported separately;
its waveform/co-batching assumptions are not silently reused for vertical arrays.

`examples.factory_fast` executes the d3 factory recipe using an explicitly loaded
component profile. It reuses `FactoryProcess`, `CooperativeFactoryRuntime`, the
frontier scheduler, seeded events and carrier/token ledger. Each experiment
retains preparation attempts, corrections, transversal CNOTs, T-consumption
feedback, S calls, final postselection and output holding. It does not compile
atom movements for that experiment.

The logical input may now include a separately generated `PlacementPlan`.
Placement is lightweight geometry and does not require a physical case first.
Execution still needs applicable saved component costs; loading or looking up
those costs never implicitly compiles missing atom work. The supported logical
program remains the code-owned factory recipe and its resource protocol. This
entry does not add arbitrary QASM lowering or automatic inventory production.

The execution representation is `logical_estimate`. Logical carriers have no
atom identities. Receipts carry logical interface result IDs and estimated
ready times; physical validation is `not_run`, `physical_validation_ok` is null,
and decoded `logical_success` remains null. A successful protocol trajectory
means the modeled factory issued an output token, not that its quantum state was
decoded or simulated.

A raw preparation's physical rounds are compressed into one component receipt.
Their result timing and aggregate phase work remain represented, but physical
sub-expansion identities are not reproduced as logical receipt identities.
Comparisons flatten the corresponding dependency results and compare their ready
times explicitly.

## Entries and calibration

Run commands from the repository root with the configured physical-compiler
Python environment and this checkout on `PYTHONPATH`. `run` and `sweep` require
an explicit code and profile. Their default acceptance model is `theory`, which
also requires `--input-z-error`; the confirmed reference study uses 0.01:

```powershell
python -m modules.logical_compiler.examples.factory_fast run `
  --code rotated_surface_d3 --profile artifacts/fast-profile.json `
  --input-z-error 0.01 `
  --factories 2 --seed 1167024 --sampling-role witness `
  --output artifacts/fast-witness

python -m modules.logical_compiler.examples.factory_fast sweep `
  --code rotated_surface_d3 --profile artifacts/fast-profile.json `
  --input-z-error 0.01 `
  --factories 1,2,4,8,16 --seeds 0..15 `
  --output artifacts/fast-sweep
```

Output directories must be new. The scheduler always fills compatible ready
batches under the actual AOD and readout budgets; no serial-mode or artificial
batch-width option exists. `--detailed` adds complete case exports for every
sweep point; normal sweep records retain per-line outcomes, counts, modeled
costs and timing summaries.

The old acceptance behavior is an explicit separate experiment mode:

```powershell
python -m modules.logical_compiler.examples.factory_fast run `
  --code rotated_surface_d3 --profile artifacts/fast-profile.json `
  --acceptance-model physical_no_fault_proxy `
  --factories 2 --seed 0 --output artifacts/legacy-proxy-seed-0
```

Proxy mode rejects `--input-z-error`. Theory mode never infers a missing p from
raw rejection or physical noise parameters. Use the same explicit model and p
with `examples.factory_array` for a full physical comparison.

Calibration is a separate, deliberately slower operation. It reads a stable,
validated physical factory case with the required component/event coverage and
compiles the finite missing correction classes. Shared waves retain validated
member projections, so calibration does not require a separately serialized run:

```powershell
python -m modules.logical_compiler.examples.factory_fast calibrate `
  --artifact modules/logical_compiler/artifacts/factory-array-theory-seed-0 `
  --output artifacts/fast-profile.json
```

The source artifact must be available locally and pass the calibration's source,
member-projection and model checks. Before writing a profile, calibration requires
every factory recipe branch, including conditional S, output X and each signed
CNOT geometry in the fixed 100-micrometer layout. Missing ordinary components or
preparation/consumption events produce explicit incomplete-calibration errors.
All 32 preparation-correction variants are supplemented and checked separately.
Theoretical T-injection joint ports retain their source identities, parameters
and probabilities in `theory_consumption_ports`; the runtime evaluates its own
code-owned theory port at the explicitly requested p. An explicit proxy-routing
port is recorded separately in `consumption_port` only when the source contains
one. A theory-only profile cannot silently supply proxy routing and fails if
requested for that mode without the required reference port.
Calibration records its source hashes, physical reference,
component coverage and noise parameters. It is never invoked automatically by
`run`, `sweep` or a profile lookup. Missing geometry, correction class, component,
event distribution or supported parameter values cause an explicit failure;
there is no physical-compilation fallback or zero-cost default.

The current profile domain is the horizontal d3 six-patch factory with calibrated
100-micrometer patch spacing and three total raw SE rounds: the unchanged raw-T
primitive contains the first round, followed by two ordinary SE rounds. Signed CNOT geometry,
local correction classes and fixed device/noise assumptions select variants.
Changing line count permits reuse only when the applicable participant, Device,
readout and spectator context still matches. A new code or materially different
layout/model needs separately established coverage.

Profiles use `nadit.fast_surface_factory_profile/2`. The required `raw_t_protocol`
identity records protocol version 2, distance 3, `round_policy="distance"`,
`total_rounds=3` and `extra_rounds=2`. Calibration checks the source call
parameters, three physical parts, 24 result identities and the matching joint
canonical-preparation port. Its compact cache preserves the port's round
metadata. Old version-1 profiles, two-round tables and explicit historical
controls are rejected; they cannot be relabeled or reused as normal profiles.
Regenerate a complete physical reference using the shared batching runtime,
then calibrate a new profile from its validated member projections.
The fast factory remains d3-only; generic d5/d7 acceptance ports are not a
substitute for calibrated timing and joint canonicalization coverage.

Calibration preserves the consumption port from the source's declared experiment
model. Theory references retain `t_injection.logical_z` with their explicit p,
including raw inputs and the declared distilled output quality. Each port is
checked against its model and retained separately from proxy-routing events.
Fast theory runs continue to resolve T feedback from their current explicit p.
A theory-only consumption cache cannot supply the separate proxy routing mode.

`ResourcePreparation.parameters` carries code-owned invocation parameters.
Single-factory and array execution use the shared cooperative runtime to pass
them unchanged to each `ComponentCall`, including retries, and record them in
the call ledger. The d3
recipe explicitly requests `extra_rounds=2`. Probability-model parameters remain
separate, so changing a noise model cannot silently change physical round count.

## Placement input and applicability

The Python `run_fast` API accepts `placement_plan=plan` and optional declared
shared/readout bounds. `layout_from_plan` associates the plan with logical
carriers and resource capacities without moving, regenerating or compiling its
positions. If an explicit factory count is also supplied, it must agree with
the plan. Exported cases retain the placement document for inspection.

The historical default layout is now produced by an explicit-plan adapter.
`make_fast_layout` remains a compatibility entry that delegates to that adapter;
`FastProfile` supplies costs and execution declarations rather than deciding
where blocks belong. The default horizontal coordinates and budgets remain the
same. Supplying a vertical MSD plan does not turn the old horizontal/readout
profile into a valid vertical profile.

`CalibrationContext` records placed participants, component identity/version/
fingerprint, parameters and correction selection, code/distance/orientation,
Device control/transport/readout, and the model's spectator scope. Saved records
and lookups must share that context. A profile created without applicability
metadata is not silently considered valid for arbitrary placements; production
lookup returns an explicit missing-calibration result.

World scope includes every spectator. Local scope requires an influence envelope
and versioned provider evidence; spectator footprints intersecting that envelope
are included. Global operations require world scope. The global plan fingerprint
and N remain provenance instead of forcing all entries to expire: adding a remote
factory can preserve a local key, while changing a relevant neighbor or readout
region changes it. The validity of a locality declaration still needs physical
evidence.

This permits an explicit server workflow: generate a plan, query applicable
records, list misses, run separate authorized calibration jobs, then execute
logical scans. There is no on-demand physical compiler hidden in placement,
profile lookup or `run_fast`. New vertical shared-AOD logical batching and full
vertical factory throughput are not established by generating a placement plan.
See [logical placement](placement.md) and
[ADR 0056](../../../docs/decisions/0056-logical-placement-and-calibration-context.md).

## Timing and accounting

Measurements become available at their calibrated measurement-phase endpoint
plus readout latency. Return transport may finish before or after that time.
Feedback waits for both its source exits and results; an event's release time
also includes any delay until the common coordinator processes it. The scheduler
retains stage barriers, successful-peer holding and independent retry attempts.
Both full and fast execution use the same deterministic, inclusion-maximal
frontier policy. Every ready member that can join the chosen group under all
declared constraints is included; this does not claim global schedule optimality.

The exported `accounting` keeps distinct quantities:

| Quantity | Meaning |
| --- | --- |
| `work_by_category_us` | Sum of each component member's category interval union; parallel members each contribute work |
| `resource_busy_us` | Union of intervals occupying each named shared resource |
| `category_busy_us` | Union of intervals in one category across all members |
| `global_busy_union_us` | Union of all recorded work intervals, counted once |
| `explicit_global_wait_us` | Union of intervals where the global execution clock explicitly waits |
| `makespan_us` | Total modeled experiment duration |
| Line `waiting_us` | Per-line feedback, resource or peer waiting; different lines can overlap |
| `wall_seconds` | Software time for layout, scheduling, events, cost evaluation and ledger projection |

Category or resource totals can overlap and must not be summed as elapsed time.
Member work is not atom-microseconds. Measurement exposure is not result latency.
Identity corrections retain protocol identity but add no pulse work. Other local
Pauli corrections retain their calibrated pulse cost; there is no global software
Pauli frame. Profile loading and export time are separate from `wall_seconds`.

## Probability scope

Raw preparation uses a frozen joint acceptance/byproduct distribution. A retry
draw gets its own line, batch, preparation and attempt identity; a correction
uses the already selected class. No second independent class draw is introduced.

The `theory` mode selects the existing code-owned `factory_mx_port`. One seeded
joint outcome supplies all four final MX bits and the acceptance decision; only
four zero bits accept. There is no independently sampled final success flag.
The assumed inputs are 15 independent accepted, locally canonicalized A states,
each with logical Z-error probability p. Factory Clifford gates, storage and
readout are ideal in this reference model.

For x = 1 - 2p, acceptance is `(1 + 15*x**8)/16`. The user-confirmed p=0.01 gives
acceptance **0.860090333670424** and conditional output Z-error probability
**3.60876839653233e-05**. The latter is reference-quality metadata after acceptance
and output X, not a sampled error bit available to the controller. These values
do not establish a noisy d3 logical error rate or fault tolerance. Changing p
does not change the separately configured raw acceptance distribution.

Physical cost is an independent **profile estimate** of `noise/v1`, combining
frozen discrete contributions with holder and idle intervals reconstructed from
the current logical schedule. Original interval partitions matter for the T2
formula; the result is not a product of scalar component success probabilities.

Theory runs use `full_line_diagnostic`: all six patches and 102 carrier roles
are included from that line's first batch work through its own final-check
evaluation. Raw attempts and loss, resets, and successful patches' storage while
other patches retry remain included. Raw horizons are recorded without excluding
them. Coverage records include per-patch role-time, SLM/AOD residence and overlap
with raw windows. The final peer barrier, accepted output X and subsequent output
holding are outside this diagnostic window.

The physical no-fault number describes modeled channels on the selected actions
and timeline. It is not a success probability conditioned on already observed raw
postselection outcomes. It is not multiplied by raw or factory acceptance and
does not influence theoretical decisions. No actual physical loss event is drawn
and no atom-removal/replacement trajectory is simulated. Common-mode shared-AOD
noise and actual accepted-state quality remain outside this reference model.

The explicit `physical_no_fault_proxy` mode retains `legacy_raw_excluded_proxy`:
its own raw-time union is excluded from every carrier on that line. This omits
raw physical loss and successful-patch storage during those intervals. That mode
preserves historical comparisons and is not a complete physical diagnostic or
theoretical 15-to-1 acceptance model.

Seed and occurrence identity preserve each random draw across scheduling choices.
Under the same theory p, final joint probabilities do not depend on modeled
waiting time; the physical diagnostic does. Different probability models can
select different outcomes even with the same seed. A full/fast comparison reports
event/control agreement, timing error and physical diagnostic error separately.

## Scaling and evidence

The default sweep is 1, 2, 4, 8 and 16 factories with seeds 0 through 15. The
default capacity remains **one AOD, four rows, 48 columns and 96 simultaneous
readout atoms** at every size. `--aod-rows`, `--aod-columns` and
`--readout-atoms` explicitly change that budget. Patch placement and modeled
shared/readout area grow with line count and are reported separately.

Each independent seed trajectory is one statistical sample. Lines sharing
resources and stage barriers are not treated as independent trials. Summaries
report a Wilson interval for any output per seed and a bounded Hoeffding interval
for output fraction. Zero observed outputs do not establish zero probability.
Throughput is total observed outputs divided by total modeled trajectory time,
not the mean of individual trajectory ratios. Unexpected execution errors remain
visible and invalidate that size's statistical summary. Witness runs are labeled
separately from the prespecified sweep.

Each selected run exports the case, dynamic ledger, model and cost reports,
summary and resource audit. The profile hash and runtime source hashes distinguish
calibration evidence from this experiment. The component report is a logical
timeline; it supplies no atom trajectories or current physical-validation proof.
Physical spot checks and approximation errors require separately recorded full
compilations. See [ADR 0050](../../../docs/decisions/0050-fast-logical-experiments.md)
for the kernel design and
[ADR 0051](../../../docs/decisions/0051-theoretical-factory-acceptance.md) for the
current probability contract. Corrected theory acceptance artifacts are recorded
separately under `artifacts/theoretical-factory-verified/{fast,replay,full,scaling}`.

## Verified theory study

The following evidence belongs to the earlier frozen implementation recorded
below; it is not a timing claim for subsequent scheduler changes.

The completed p=0.01 seed-0 full/fast comparison has 35 raw attempts, five raw
rejections, six conditional S calls and two offered outputs. Its eight initial
raw calls share one wave; only `factory0/W5` initially rejects and retries while
the other seven accepted resources remain retained. Both final joint checks
are 0000.

The 225 calls, 61 coarse events and 116 admitted waves agree in control flow,
resource lifecycle and timing, with zero observed timing or event-probability
difference. The physical case passes motion, coverage, replay, pulse, addressing
and timing validation. The fast case remains a logical estimate and replays its
deterministic exports exactly. The two full/fast no-fault diagnostic relative
differences are approximately 4.414e-12 and 3.622e-12.

All 80 prespecified cases finish. Accepted outputs are 11/16, 24/32, 50/64,
102/128 and 220/256 line executions for 1, 2, 4, 8 and 16 factories respectively.
Each size has 16 independent seed trajectories; the same seed set is reused
across sizes. Do not treat the combined 496 lines as independent trials, or count
the detailed seed-0 case again. Software wall times were recorded during
concurrent validation and are not a controlled speed benchmark.

The final regression records 1213 passing tests against a fresh 1159-test
baseline. Independent readback performs 7821 checks with zero failures. See the
[validation record](../artifacts/theoretical-factory-verified/validation.md) and
[ADR 0051](../../../docs/decisions/0051-theoretical-factory-acceptance.md) for source
provenance, quality checks and limits. Full's stable source snapshot has one
recorded subsequent wording-only difference in a fast renderer it did not execute;
its original bytes are preserved. New physical or quantum-state claims do not
follow from these bounded comparisons.

## Historical proxy study

The following frozen study used `physical_no_fault_proxy`, before theory became
the default. Its zero outputs are not theoretical 15-to-1 failures and cannot be
used as theoretical distillation-throughput measurements. The original files,
model labels and statistics remain preserved for reproducibility.

The first frozen study completes the default 80-run matrix. Mean software time
is 0.226324, 0.464966, 0.948067, 2.066698 and 4.925887 seconds for 1, 2, 4, 8 and
16 factories respectively. These times exclude profile loading and export.
Peak process memory was not measured.

All 80 samples reach valid terminal states and observe zero accepted proxy
outputs. All 496 line executions obtained 15 accepted raw inputs, then rejected
at the final physical-no-fault proxy event. Per size, 16 independent seeds give an
any-output Wilson 95% interval
of [0, 0.1936076805344365]; the observation does not establish probability zero.
The separately selected two-line witness produces one output and is excluded
from that sweep. Its recorded call and event times match the corresponding
full physical references exactly in the exported numbers; the largest observed
absolute proxy-probability difference is 8.966785647324116e-15. This bounded
comparison does not validate all larger atom worlds.

See the [independent readback](../artifacts/fast-logical-verified/independent-audit.md)
for hashes, per-size statistics, complete scope limits and the distinction between
logical receipt and physical sub-expansion identities. Those local ignored
artifacts are not required by the ordinary test suite.
