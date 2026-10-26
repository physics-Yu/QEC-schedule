# Code-selected factory execution

This implementation covers the first five agreed tasks: protocol/resource
interfaces, resource lifecycles, dynamic execution, one shared physical context,
and one factory output consumed by one algorithm T injection. Supply is on
demand and physical calls are serial. Task six is not implemented: no prefetch,
watermarks, in-flight production policy, age policy, periodic waiting SE or
supply optimization. Finite preparation, batch and call bounds prevent runaway
execution; they are correctness limits rather than inventory policies.

## Ownership and entry points

`modules.logical_compiler.factory` exposes `FactoryExecutor`, `FactoryLimits`
and `FactoryCase`. The caller supplies an explicit code ID, the code-owned
`FactoryRecipe`, its backend, a `PhysicalContext`, and role-to-block bindings.
The code ID must match the recipe. The QASM frontend remains a separate entry;
this change does not automatically connect arbitrary QASM to a physical factory.

Code supplies gate order, participant roles, pivots, preparation/canonicalization,
joint event distributions, acceptance and output quality. Logical compilation
owns clocks, identities, tokens, dependencies, selected continuations and retry
scope. Physical validation owns action legality. No d3 support matrix, Pauli
list, distillation equation or probability estimator is defined in the generic
executor. The example explicitly chooses the d3 implementation.

For this frozen recipe, four accepted and locally corrected raw inputs become
work states. Eleven later resources are prepared individually on R. The code
recipe requests parity computation, consumption CX, logical MZ, the selected
correction and parity uncomputation. Only recipe calls are executed;
`ProbabilityPort.branches.steps` remains evidence and cannot cause a second S or X.

The factory core uses six real 17-atom patches in one 102-atom world. After
success, the example initializes algorithm data on the measured W2 carrier.
W1 holds the resource until the algorithm's irreversible consumption CX. This
specific single-output demonstration needs no hidden seventh data patch.
An application with existing algorithm data must provide its actual carrier.

## Resource and retry semantics

`ResourceLedger` records immutable carrier epochs and token snapshots, plus an
append-only transition audit. It checks disjoint atom identities and exact token
ownership. Token readiness, physical exit and ownership release are separate.

- `begin_preparation` starts a new epoch only on a released, physically safe carrier.
- `offer` records code-supplied kind, canonicalization, quality and provenance.
- `reserve` transfers ownership after result readiness and compatibility checks.
- `consume` happens once at the irreversible CX start. `adopt` marks an input
  becoming a retained work state, without claiming physical measurement.
- `complete_use` releases a carrier only after its declared safe exit and only
  when no available/reserved output token protects it.

Initial raw rejection retries only that input carrier; other accepted inputs
remain owned. A later R rejection repeats only R preparation and leaves completed
work prefixes intact. Every new raw attempt runs the full code-owned preparation,
including its reset. It does not insert a second initializer/reset beforehand.

Once consumption CX commits, later measurement, correction or physical failures
stop the case. They do not return the token or repeat the T injection. The
`algorithm_consumed_token_id` records this irreversible fact even if the
subsequent algorithm measurement fails; `algorithm_t_complete` separately marks
successful completion.

Final rejection starts a new batch only if budget remains. Every work carrier is
released and re-prepared; the history and physical world are retained. Final
budget exhaustion or local supply exhaustion preserves the current prefix and
owned state for inspection. It never silently starts an extra attempt.

Statuses are `complete`, `input_supply_exhausted`, `distillation_rejected`,
`expansion_budget_exhausted`, `unsupported_resource_quality`, `physical_failure`
and `protocol_failure`.
`complete` refers to the declared goal: `factory_output` or `factory_output_to_t`.
An executor runs once. A fresh executor cannot attach a fresh ledger to an
already-used physical context and forget live resource ownership.

## Events and the physical timeline

`EventJournal` binds the existing seeded sampler to actual component result IDs,
their availability and relevant component exits. A continuation waits for all
of them before using an event. An event retains the complete probability port
fingerprint, joint values and dependencies. Repeated reads cannot change the
binding or expose the result before its recorded release.

`PhysicalContext` serially invokes code-owned expanders under one complete world,
including spectators. It retains actual exit bindings, unique physical result
ranges and global time. Waits become real Atom IR `Wait` actions. Each invocation
is expanded and checked before its world/clock/identity changes are committed.

Whole-program assembly maps local component wires to fixed global atom wires,
renumbers native operations and action source IDs, and preserves the separate
global measurement IDs. Each mapping retains invocation/local-ID provenance.
The flattened program is replayed and validated for motion, coverage, pulses,
addressing and timing against its selected native DAG.

Physical measurement values remain `None`; coarse byproduct/MZ/factory events
never populate a syndrome trace. The existing validator internally needs bit
records for unconditioned source measurements; temporary placeholders are used
only there and discarded. They are absent from the case, trace and feedback.
Validation is explicitly `selected_actions_unobserved_measurements`, with
`measurement_values_verified=false` and `logical_branch_semantics_verified=false`.
Those flags describe this physical validator's scope, not the separate code-side
ideal circuit/branch checks.

## Quantum-model scope and cascading boundary

The principal case uses ideal preparations and gates, a proven joint local
byproduct event, and explicit physical preparation corrections. Factory final
checks come from the code-owned joint four-bit model. An optional nonzero
`input_z_error` is an assumed iid accepted-input reference model with ideal
Clifford, readout and storage; it is not extracted from raw rejection or from a
shared-device physical-noise calculation.

Prepared input quality and conditional factory-output quality are returned by
code. Their `consumption_parameters` are passed unchanged to the next T-event
model. This preserves a noisy reference resource's phase-flip mixture instead
of silently replacing it with a pure magic state. Quality estimates and hidden
error information are never exposed as observed feedback bits.

The same token representation describes raw and factory outputs. Keeping an
output token supports a later consumer contract, including a higher-level
factory. This delivery does not implement a multi-level factory orchestrator,
distance conversion, state transfer, global frame propagation or decoder.
Transferring a token alone never moves its physical quantum state. The current
public executor starts a fresh finite case; future continuation across executor
instances must explicitly retain its ledger and physical context.

## Running and reviewing

Use the existing physical-compiler Python environment. When working in an
isolated checkout, point `PYTHONPATH` at that checkout's physical `src` and repo
root so an editable environment does not silently import another checkout.

```powershell
$env:PYTHONPATH = "$PWD/modules/physical_compiler/src;$PWD"
& modules/physical_compiler/.venv/Scripts/python.exe -m modules.logical_compiler.examples.factory_to_t --scenario ideal --output modules/logical_compiler/artifacts/factory-to-t/ideal
```

The example requires a fresh output directory. It exports the static case, real
AtomProgram, action trace, viewer and a compact manifest with hashes and counts.
Protocol calls, primitive component parts, AtomSteps and atom actions are distinct
counts. Raw preparation contains two primitive SE-related parts.

The acceptance scenarios include ideal success, startup raw retry, R retry after
a completed rotation, local supply exhaustion, whole-batch rejection/retry,
terminal batch rejection, consumption-stage failure and held-output protection.
Forced raw rejection and an injected binding failure are explicitly `test_fixture`
scenarios. Their actual compiled actions establish control/physical continuity,
not the quantum probability of those injected events. Batch rejection uses the
code-owned parameterized reference model.

Unit fixtures test generic control independently. Real integration tests use the
surface backend and the complete six-patch world. Independent code-side checks
cover ideal preparation branches, every intermediate injection-bit combination,
the final state convention and the reference distillation probabilities.

## Cost-driven preparation experiments

The separate `examples.factory_noise` entry calls the source-aware code backend
after each actual raw preparation. It passes explicit `noise/v1` parameters and
the complete occupied world. The code returns one joint acceptance/byproduct
event; the seeded backend samples that event once. Rejection repeats the full
raw component, including its reset, on the same carrier and advances its epoch.
The previous attempt's actions, results and rejection remain in the static case.

The repository's `noise_illustrative.json` is an uncalibrated example. Its raw
event covers Pauli/readout detector rejection conditional on retained atoms;
physical loss is reported separately. It does not determine the quality of an
accepted resource. A noisy resource with unsupported or missing consumption
parameters remains protected and stops the case before adopt or injection CX.
There is no fallback to an ideal input or to `input_z_error=1-P(accept)`.

The default cohort fixes case identity, parameters, sources and seeds 0..15.
It records the actually imported physical package source tree, including when
an editable environment points to another checkout. Source changes stop the
cohort and invalidate comparison. Use a physical installation containing the
existing `methods.clifford` dependency; the exporter does not replace it.

```powershell
python -m modules.logical_compiler.examples.factory_noise --noise-params modules/physical_compiler/cost_params/noise_illustrative.json --output modules/logical_compiler/artifacts/factory-cost-noise-v1
```

Each run exports its selected AtomProgram, pending physical results, event/model
snapshots, noise parameters, physical cost report and viewer. The cost adapter
generates and round-trip checks static QASM from the selected physical DAG; its
hash describes that new text, not an invented original QASM input. Internal
structural measurement placeholders are never returned as observations.

`experiment.json` is automatically written by the common exporter. The cohort
also writes a JSONL/CSV ledger using `nadit.factory_experiment_ledger/2`; the
historical v1 audit snapshot has a different shape and cannot be mixed into it.
Counts distinguish factory/algorithm S calls, requested corrections, raw attempts
and accepted canonical resources. Final batch checks, output readiness, physical
validation and overall completion remain separate. An unreached check is null.

The `factory_noise` path stops at `unsupported_resource_quality` after an
accepted, locally corrected raw resource. Complete noisy factory propagation,
recovery/decoding and algorithm correctness are not supplied by this experiment.
The report's unconditional physical no-fault product is a diagnostic, not a
logical-success bit or an independently resampled success event after rejection.

## Explicit physical no-fault proxy experiment

The separate `examples.factory_proxy` entry implements the user-selected cost
experiment. It uses the same real raw rejection/reset/retry model and actual
six-patch factory body. A code-owned, explicit reference-routing marker permits
ideal T-feedback branches while preserving `actual_quality.status=unsupported`.
The marker comes from the returned resource quality; it is never substituted
with an empty object or an assumed `input_z_error=0`.

```powershell
python -m modules.logical_compiler.examples.factory_proxy --noise-params modules/physical_compiler/cost_params/noise_illustrative.json --output modules/logical_compiler/artifacts/factory-cost-proxy-v1
```

The default cohort freezes seeds 0..15, case ID `factory-cost-proxy-v1`, an
eight-attempt budget per raw input, and a two-batch factory budget. Each run
compiles its selected corrections, rejected attempts, resets, waits and accepted
output consumption. Changing the seed can change these actions and their costs.
Opening an exported case or viewer does not resample it.

Three explicitly scoped model decisions are retained:

| Stage | Evidence and decision |
| --- | --- |
| Raw preparation | Actual joint detector/byproduct event, conditional on retained atoms; rejection retries that input. Loss remains separate source evidence. |
| Factory batch | Physical no-fault proxy on the batch window minus every complete raw attempt horizon, including result waiting. Proxy rejection starts another whole batch within budget. |
| Output delivery and algorithm T | Separate terminal no-fault proxy from the accepted factory decision through output X, data initialization, injection and final result readiness. It does not change the compiled path. |

Factory proxy events do not synthesize the four physical MX values. Physical
measurements stay unobserved. `complete` means the selected actions compiled and
validated; `proxy_success` is the terminal cost-model sample; `logical_success`
remains null in every record.

The interval adapter validates and prepares the complete physical bundle first,
then intersects its original atom activity with the selected absolute intervals.
It recomputes `noise/v1` on that activity. Discrete actions must belong wholly to
one selected interval; waits and continuous exposure are clipped. Overlaps and
ambiguous zero-duration boundary actions are rejected. Selected event indices,
source/activity hashes and exact interval boundaries are saved. Included and raw
excluded intervals must cover the entire declared stage window without gaps.

The probability already includes configured physical loss on selected intervals.
It is not multiplied by survival again. Raw horizons are excluded for the entire
world, so storage errors of other working patches during those horizons are also
outside this proxy. Splitting a T2 channel changes the product of identity
probabilities; the recorded partition is part of the experiment and no equality
with an unconditional whole-trace product is claimed. No joint whole-pipeline
no-fault probability or decoded logical success is inferred.

A failed proxy is not a sampled fault location or a lost-atom realization.
Retries compile reset/re-preparation in the declared retained-atom world. They
do not simulate atom replacement or loss-recovery costs, even though the proxy
probability includes loss factors. `physical_execution` remains false.

Every case adds `proxy-costs.json` and `evaluation.json` to the usual physical
artifacts. `experiment.json` and the JSONL/CSV ledger retain the full factory
event/port and terminal evaluation in metadata. The original cohort is never
filtered for desirable outcomes. Optional `--witness-seeds` go into separate
directories and a separate ledger; selected branch witnesses must disclose their
selection method and must not enter an unbiased success-rate estimate.

See [case model](case-driven-compilation.md),
[shared recipe](../../codes/contracts/factory_recipe.py),
[surface backend](../../codes/rotated_surface_d3/protocols/factory_backend.py),
[runtime](../src/protocols/factory.py) and
[integration tests](../tests/test_factory_integration.py).
