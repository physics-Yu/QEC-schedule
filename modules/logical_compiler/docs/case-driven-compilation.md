# Protocol-aware case compilation and factory studies

Date: 2026-10-23.

Status: confirmed design direction from discussion. A bounded coarse-event
consumer and abstract case expansion are implemented as described below.
The later [factory pipeline](factory-pipeline.md) also implements a serial real
component path; general QASM binding and concurrent device scheduling remain open.
See [ADR 0040](../../../docs/decisions/0040-protocol-aware-case-compilation.md).

## Confirmed approach

Use the physical compiler's case-driven approach: a seeded backend supplies
measurement outcomes, the compiler follows the resulting path, and one case
accumulates a complete atom-action and timing record. Multiple cases can
characterize timing and factory production under the chosen model.

A logical T invocation consumes a factory-produced logical T resource state
through a gate-teleportation protocol. Resource readiness, entangling operations,
internal measurements and conditional corrections belong to that protocol.
A T operation, raw-T preparation and factory acceptance are distinct concepts.

## Measurement meaning and sampling

The selected component/protocol specifies measurement meaning and constraints.
Where ideal behavior fixes a distribution, it declares that rule. General
algorithm-data measurements can depend on the quantum state; a protocol alone
does not determine their probabilities. The fake backend uses an explicit
scenario sampling model. A future state-aware backend can instead supply
state-dependent outcomes through the agreed measurement interface.

| Result role | Initial sampling treatment |
| --- | --- |
| Random correction bit in standard ideal T teleportation | A fair 0/1 sample is appropriate; both outcomes can complete T through the required correction |
| A known eigenvalue or deterministic ideal check | Preserve the protocol's specified value |
| Related measurements or derived logical results | Preserve their joint constraints and interpretation |
| Algorithm-data measurement with state-dependent probabilities | Declare the fake scenario assumption; do not infer fair-coin probabilities from a lack of noise |
| Factory acceptance | Apply the protocol's acceptance predicate to the appropriate results |
| Artificial factory rejection in a scheduling study | Use an explicitly declared probabilistic model, distinct from physical error simulation |

Noiseless operation does not imply that every measurement is an independent
fair coin. For standard 15-to-1 distillation, ideal input resource states and
ideal operations satisfy the acceptance checks; random teleportation correction
bits do not by themselves require rejection. Sampling four acceptance checks as
independent coins would instead manufacture a 1/16 acceptance rate.

The [surface-code distillation reference](https://arxiv.org/html/1808.02892)
separates teleportation corrections from the final acceptance checks in
Section 3.3. A future chosen factory protocol remains authoritative for its own
sign conventions, predicates and cleanup.

Initial studies may use two distinct model settings:

- An ideal protocol model with valid deterministic and random outcomes.
- A scheduling stress model with configured rejection behavior.

These are study directions, not selected numerical probabilities. The latter
does not establish a physical output error or a logical failure rate.

The sampling boundary must be explicit. Physical readout records and derived
logical/protocol outcomes must not be sampled independently as if unrelated.
A coarse protocol-outcome model must identify that abstraction; it must not
invent a contradictory physical measurement trace. The coarse event interface is
defined by the shared [probability contract](../../codes/contracts/event_probability_v1.md).
Detailed physical measurement and decoder interfaces remain open.

## One case

A case maintains a shared clock, complete device layout, block/atom bindings,
resource occupancy, measurement records, pending results and protocol progress.

1. Select ready component work and arrange its physical actions.
2. At a measurement occurrence, produce one result and record its availability.
3. Only after that result is available may it drive a correction, acceptance
   decision, rejection or retry.
4. Commit the resulting exit state, release resources when actually available,
   and introduce subsequent component invocations.
5. Continue the same case record through successful outputs and failed attempts.

Offline sampling may compute a bit before its simulated availability. That
knowledge must not change scheduling decisions before the feedback is available.
Pending results survive component boundaries. A physical action ending, an AOD
becoming free and a measurement result becoming available are separate events.

The initial timing convention follows the physical compiler: availability is
measurement completion plus the configured readout/feedback latency. Future
classical processing costs must be represented explicitly when included.

## Reproducible measurement occurrences

Results belong to invocation instances. A conceptual occurrence identity includes
the line, batch/attempt, component invocation and local measurement position,
within the case's identity/seed. The implemented occurrence is
`(case_id, invocation_id, attempt, port_id)`; a line can be encoded in the stable
invocation ID. The binding also fixes the full port hash and availability time.

Repeated reads of one occurrence return the same bit. A retry creates new
occurrence identities rather than reusing the failed attempt's results.
Parallel lines must not accidentally share template-local measurement IDs.

The current physical FakeBackend derives bits from seed plus measurement ID.
A global occurrence mapping is therefore required before reusing that mechanism
across components. Sequential random-stream order alone should not cause a
scheduler ordering change to assign different bits to the same logical occurrence.

Compiled templates may be reused when their conditions remain valid. Cached
templates must not carry case measurements, acceptance decisions or attempt state.

## Device resources and parallel lines

One AOD is the first study assumption, not a compiler invariant. AOD inventory,
identity, motion capabilities and capacity belong to the Device/resource model.
Code and component interfaces must not hardcode one global AOD or equate a
transport role with a permanent device-specific identifier.

Reserve a resource interface through which components declare requirements,
binding selects concrete resources, and scheduling checks availability and
joint legality. Its exact schema and multi-AOD algorithms require later design.
The first implementation may explicitly support only the one-AOD configuration.

Adding AODs is not simply multiplying throughput. Multiple AODs may still share
workspace, laser/readout channels or other constraints. Both per-resource limits
and cross-resource conflicts must be represented and enforced before claiming
multi-AOD scheduling support. Device data expressing several AODs is not evidence
that a compiler can schedule them jointly.

All lines share the same device state and timeline under the selected resource
configuration. Independently compiled action tables cannot simply be overlaid.

In the one-AOD study, lines compete for compatible transport batches. They need
not wait for each other at every factory-round boundary. While one line awaits
feedback, another may use a free AOD. If the first line still holds it during
readout, that resource is not available to the other line.

The existing AtomStep convention synchronizes actions within a step and starts
the next step after the longest action completes. It does not require all
factory batches to advance in lockstep.

## Rejection, retry and storage

A rejected batch does not deliver its candidate resource state to algorithm
data. Rejection does not automatically mean physical atom loss or global
factory shutdown.

The selected factory protocol specifies which states are discarded, which
carriers can be reset/reused, what cleanup or transport is necessary, and when a
new attempt can start. Other lines and previously accepted resources retain
their actual state unless a declared dependency requires otherwise.

Cleanup, reinitialization and retry compete for device resources in the same
case. Storage and protocol-required SE for waiting data or buffered outputs must
be included in the timing/resource model. Retries are new component invocations;
this direction does not add unrestricted QASM while-loop support.

## Proposed study outputs

Useful quantities include accepted outputs ready for use per unit simulated time,
delivered outputs if delivery has a separate cost, first-output latency,
inter-output time distributions, resource utilization, waiting time by cause,
failed attempts, cleanup/retry cost and output-buffer residence time.

Before running a study, specify the code and component versions, factory and
sampling model, Device/resource configuration, timing model, seeds/sample count,
initial state, stopping rule and treatment of startup and unfinished attempts.
A fixed horizon and a fixed target output count answer different questions.
Study parameters and execution will be agreed separately.

An accepted output means it passed the modeled protocol predicate. Its actual
quantum-state quality is not verified by a fake backend. Production statistics
are conditional on the declared sampling and device model; neither physical
loss estimates nor scheduling success establish corrected logical failure rates.
Fake scenario frequencies are not automatically the true path probabilities of
an arbitrary input quantum circuit.

## Implementation boundary and open work

At logical-frontend commit e36889f, QASM measurements, immutable result references,
guards and DAG dependencies exist. The frontend does not sample measurements,
execute T teleportation, supply factory states or schedule multiple lines.

The physical compiler has a seeded bit provider and availability-aware
conditions, but each compile_physical call creates fresh time and result state.
Passing only an exit layout to another independent call does not implement the
shared case described above.

The shared coarse-event contract now fixes joint distributions, occurrence IDs,
model fingerprints and continuation declarations. The abstract engine implements
bounded retries. Open decisions include physical pending-result ownership,
resource requirement/binding contracts, multi-AOD admission and scheduling, the
first complete factory and atom-level T-consumption protocols, detailed
syndrome/decoder integration and statistical study definitions.

## Implemented abstract case API

`modules.logical_compiler.compile_case` is separate from `load_qasm`/`loads_qasm`.
Its input is an explicit root DAG of `Invocation` objects and a catalog of
`AbstractComponent` bodies. The QASM-to-component adapter is not implemented.
Codes supply `ProbabilityPort` from the shared contract; the compiler imports
that contract and defines no alternative probability schema.

Each abstract body declares ordered participant roles, an exit-time offset and,
if it has an event, a result-ready offset. Both offsets are measured from body
start. The caller includes all modeled readout/classical delays in result-ready
time. These are declared timings, not inferred atom-level durations.

For each attempt, the engine samples one joint outcome at
`max(body_exit, result_available)`, expands only its selected ordered branch
steps, then applies `continue`, `deliver` or `retry`. A step's parent roles are
mapped positionally to the child component's declared roles. Each step completes
its own nested event/continuation before the following step begins. A retry
executes declared cleanup first and starts a fresh attempt of the original body.
The body's initialization is part of its declared work; it is not skipped.

`Invocation.max_attempts` includes the initial attempt and is inherited as a
per-invocation bound by nested steps. `CaseLimits.max_expansions` independently
bounds all body starts, including recursive continuations. Exhaustion returns
`budget_exhausted`; missing selected components and invalid bindings return
`failed`. These partial artifacts retain events and unresolved invocation IDs.
Malformed input DAGs and unsupported modes raise an error before expansion.
An unselected branch does not require an executable component in the catalog.

The seeded backend hashes a versioned domain, integer seed and stable occurrence
identity. Root input/frontier ordering does not reassign outcomes. Repeated reads
reuse the same result; changed model hashes or availability under the same
identity are rejected. This is a reproducible coarse probability backend, not a
quantum-state simulator. Detailed syndrome/decoder mode is explicitly unsupported.

The exported schema is `nadit.abstract_case/1`, with `artifact_kind=abstract_case`
and `execution_ready=false`. `CaseResult.to_json()` emits deterministic JSON and
`to_dict()` returns a fresh copy. The artifact retains:

- Selected body calls, their participant bindings, attempts and `after_calls`
  dependencies, plus event/result-ready times and chosen branch continuations.
- Full catalog probability documents keyed by `content_sha256`, used only as
  evidence. Their alternative branches are provenance, not unresolved work in
  the selected call graph.
- Delivery records, finite budgets, partial-failure details and unresolved IDs.
- `physical_validation=not_run`, `resource_scheduling=not_performed`, and
  `frame_status=unresolved`. No fabricated syndrome or AtomProgram is produced.

`status=complete` means every selected abstract invocation finished. It does not
mean that frame handling, quantum-state verification or physical execution finished.

`after_calls` refers to body-call dependencies. `exit_at_us` is the body exit;
`invocation_completed_at_us` additionally includes selected nested steps and
feedback waits. For example, a T body can exit at 5, release its result at 12,
run S during [12,15], and complete the whole T invocation at 15. S is a child
of that invocation; it does not wait until the whole parent completes.
Root successors wait for all predecessor invocations to complete. Event
`released_at_us` records the feedback barrier separately from body edges.

Independent roots may overlap abstractly. The caller must express required
participant/protocol ordering; this engine does not validate physical resources
or block exclusivity. AOD inventory is intentionally outside this API. A future
device adapter must bind resource requirements to configured resource identities,
check individual capacities and shared conflicts, and reject unsupported device
configurations. There is no hardcoded single-AOD slot or implemented multi-AOD
scheduler in the abstract engine. Its durations cannot estimate factory throughput.

For partial cases, `processed_until_us` is the last processed event time.
`duration_us` also covers the declared exit/readiness of bodies already started;
it is not a claim that unfinished work or delivery succeeded.

### Reproducible example

From the repository root, run the following with the physical compiler's existing
Python environment. The fixture is copied from the real code-side producer;
its provenance file records the source commit and hash. Timings below are
deliberately synthetic. The invocation ID and case ID are part of the seed input.

```python
import json
from pathlib import Path
from modules.codes.contracts.event_probability import ProbabilityPort
from modules.logical_compiler import AbstractComponent, Invocation, compile_case

fixture = Path(
    "modules/logical_compiler/tests/fixtures/event_probability/t_injection.ideal.json"
)
port = ProbabilityPort.from_dict(json.loads(fixture.read_text(encoding="utf-8")))
components = (
    AbstractComponent("rotated_surface_d3/t_injection", ("data", "magic"), 5, port, 12),
    AbstractComponent("rotated_surface_d3/logical_s", ("patch",), 3),
)
roots = (
    Invocation(
        "inject-t", "rotated_surface_d3/t_injection", (("data", "D"), ("magic", "M"))
    ),
)
for seed in (1, 0):  # m0, then m1 -> S, for these exact occurrence identities
    case = compile_case(
        roots, components=components, case_id="producer-t-injection", seed=seed
    )
    print(case.to_json())
```

`tests/test_producer_cases.py` validates both T branches, both readiness/exit
orderings and ideal raw-T acceptance using frozen real producer documents.
Synthetic `test_fixture` models separately test rejection, cleanup, retry success,
budget exhaustion and recursive expansion. A second real raw-T producer fixture
uses an explicit readout-flip probability of 0.1 with other modeled faults zero,
only as a validation example. With case `producer-raw-t-retry`, invocation
`prepare-raw-t`, seed 3 and two allowed attempts, it selects rejection then
acceptance. This is not a selected production noise profile or calibration.
Raw-T acceptance does not resolve bulk frame signs, and this API does not connect
that accepted resource to a certified canonical T input. The T model's canonical
resource assumption remains explicit in its probability evidence.

### Selected illustrative raw-T model

The user selected the repository's complete `noise/v1` illustrative parameters
for the first nonideal raw-T example. The source is
[noise_illustrative.json](../../physical_compiler/cost_params/noise_illustrative.json).
Its two-round, twelve-detector port declares acceptance 0.8538402099976652 and
rejection 0.1461597900023348. This is Pauli/readout-only detector acceptance,
conditioned on retained atoms. Loss evidence stays separate; these numbers do
not represent calibrated hardware success probabilities or logical fidelity.

The annotated input port has `example_profile.user_selected_as_example=true`
and `calibrated=false`. Its complete `content_sha256` is
`6cfaa93f6bf28db092e51e9e182ed1ebad650f15124b232ee3179f912d144ac5`.
The original producer fingerprint retained inside that evidence is
`021ab428f860b0e1e8be5dc0bde01409ab01c896fa8cda2d39ec10facb79125c`;
event bindings use the complete annotated document's fingerprint.

Two cases were exported with the unchanged engine at commit `57a74f0`:

| Seed | Selected outcomes | Attempts | Abstract delivery time |
| --- | --- | --- | --- |
| 0 | accepted | 1 | 13 us |
| 7 | rejected, accepted | 2 | 26 us |

Both use case ID `producer-raw-t-illustrative`, invocation ID `prepare-raw-t`,
component `rotated_surface_d3/raw_t_postselection`, binding `magic=M`, and
`max_attempts=2`. Body exit and result-ready offsets are 11 and 13 us. These
synthetic offsets are unrelated to the producer's physical activity duration;
they only exercise causal feedback and retries.

Local outputs are in `modules/logical_compiler/artifacts/event-probability-v1/illustrative-noise-v1/`:

- `raw_t.illustrative.accepted.abstract_case.json`
- `raw_t.illustrative.retry_then_accept.abstract_case.json`
- `manifest.json`, recording inputs, hashes, seeds, outcomes and verification.
- `raw_t_postselection.illustrative.json`, the unmodified source-port snapshot.

These generated files are ignored by Git. Each case embeds the complete model
snapshot, preserves its example/calibration labels, and retains
`execution_ready=false`, `frame_status=unresolved`, and unverified delivery quality.
Validation checked fixed-seed replay, fresh retry identities, readiness barriers,
JSON readback and full model fingerprints. It did not rerun the producer's
scientific calculation or change backend behavior.

T injection remains the separate T-consumption measurement-branch model with an
independent canonical T resource and ideal logical instrument. This raw-T example
does not establish corrected frames or connect raw acceptance to that canonical
input. QASM wiring, atom expansion and decoding remain outside this integration.

See [architecture](architecture.md), [frontend scope](qasm-translation.md),
[physical backend](../../physical_compiler/src/nadit_physical_compiler/execution.py)
and [physical case controller](../../physical_compiler/src/nadit_physical_compiler/compiler.py).
