# Serial six-patch 15-to-1 factory

Status: code-owned recipe, physical components and reference probability model.
The logical compiler owns execution, resource identities, budgets and exports.
This is a compositional pipeline, not a full circuit-level fault-tolerance claim.

## Frozen protocol

`factory_recipe()` in [factory.py](factory.py) returns the immutable records in
[factory_recipe.py](../../contracts/factory_recipe.py). Its six participants are
W1..W5 and R. Every call uses the complete shared physical world.

1. Prepare canonical `initialize_plus` on W1. Prepare accepted, canonical raw A
   states on W2..W5, each using raw T plus one SE round and twelve detectors.
2. For every triple support in lexicographic order, then the five-body support:
   prepare R until accepted; use the lowest work role as pivot; compute parity
   using CNOT(other, pivot); consume R with CNOT(pivot, R), MZ(R); apply S(pivot)
   for m=1; uncompute in reverse order. S must precede uncomputation.
3. Destructively measure X on W2..W5. Wait for all four logical event dependencies.
   Accept only all-zero ideal logical bits; apply physical logical X on W1.
   The uncorrected accepted output is A-dagger, and X establishes A=T|+>.
4. Publish one uniquely owned output on W1. Ownership transfer does not vacate
   its physical carrier. For the first closure, the consumer may initialize the
   freed W2 and consume W1 there; this does not require a seventh patch.

There are four initially adopted A inputs and eleven subsequently consumed A
inputs. The unoptimized parity implementation uses 48 parity CNOTs plus eleven
consumption CNOTs: 59 factory CNOTs. Preparation/SE and the external consumer are
excluded from that count. This is the five-work-qubit reduction described in
[Litinski, Sec. 3.1](https://arxiv.org/pdf/1808.02892) and the convention in
[Litinski, Sec. 1](https://arxiv.org/html/1905.06903).

## Branch and reset boundaries

| Event | Reset / retry | Preserve |
| --- | --- | --- |
| Initial raw preparation rejects | Only that W2..W5 role; preparation includes reset | Already accepted independent work states |
| R preparation rejects | Only R, before parity computation | All five work states and the completed rotation prefix |
| Consumption m=1 | Execute S, then uncompute; no rejection | Working quantum information |
| Raw attempt budget exhausted | Stop with supply exhaustion; no automatic batch restart | Prefix and all outstanding ownership records |
| Final four-check rejection | No output; next batch redoes all five initial preparations | Physical atoms/layout; no old work quantum state is reusable |
| Final acceptance | Release measured W2..W5 and consumed R; hold W1 | One output token and its occupied carrier |

Consumption becomes irreversible at the injection CNOT. Later missing results
or physical errors cannot be reclassified as pre-interaction raw rejection.
R needs no redundant reset after its final measurement: its next preparation
already resets. A freed or reset carrier never resurrects a consumed token.

## Components and event interfaces

- `make_factory_world(FactoryWorldConfig(...))` constructs a real 102-atom
  device/world with six disjoint bindings. It does not prepare quantum states.
  Its default patch separation is 100 micrometers and its execution mode serial.
- `SurfaceFactoryBackend(device)` in [factory_backend.py](factory_backend.py)
  binds calls to immutable compiled templates. `bind_call` accepts a component
  ID, ordered participant bindings and a tuple of named parameters. Its return
  exposes `result_count` and `expand(context)`, preserving the original single or
  multi-round source object. It owns no clock, world or event sampling state.
- `logical_mz` and `logical_mx` measure all nine data atoms and retain all atoms.
  `measurement_spec` supplies physical ports and ideal logical/check parities.
  `read_ideal_observable` is not a noisy decoder.
- `PreparationCanonicalization` compiles the sixteen possible local Pauli
  preparations. `CorrectionDecision` binds the joint event's identity, port hash,
  class and readiness to the actual preparation. It does not fill physical bits.
- `preparation_port` supplies ideal acceptance/byproduct joint probabilities.
  Class bits follow the existing preparation relation order, little endian.
  Raw's sixteen bulk classes each have probability 1/16; rejection has probability
  zero in this ideal model. Nonideal joint probabilities remain a separate model.
- `factory_mx_port(input_z_error=p)` supplies all sixteen final four-bit joint
  outcomes. Here p means iid Z error on each accepted canonical A input, with
  ideal Clifford operations and storage. It is explicitly assumed, not inferred
  from raw rejection or from the example physical noise profile. Conditional
  output Z-error probability is model metadata, never a sampled feedback bit.
- `correction_decision` and `bind_canonicalization` hide code-specific class and
  source details from the logical compiler. `preparation_quality` and
  `output_quality` return portable resource metadata containing opaque
  `consumption_parameters`; the runner passes these to `resolve_event` without
  reconstructing a density or deriving an error probability itself.

The factory runner executes continuations from `FactoryRecipe` only. Equivalent
steps in `ProbabilityPort.branches` document the same response and must not be
executed again: in particular output X and the consumption S each run once.

For x=1-2p, acceptance is `(1+15*x**8)/16`. The implementation uses finite positive
probability convolution, avoiding cancellation in the small conditional error.
The leading conditional output error is 35p^3. Consumption measurements remain
independent fair bits under this reference model. General correlated or physical
noise can invalidate this factorization and must use another probability model.

Known preparation byproducts are corrected with physical local Pauli actions.
Ideal gates and logical Z input errors stay in the canonical stabilizer sector,
which is the supported S-SE entry here. Arbitrary nonzero physical syndrome
sectors require additional processing; no global frame or decoder is provided.

## Evidence and reserved work

Tests independently enumerate all 2048 consumption branches and compare the
five-qubit quantum state, and enumerate all 32768 input-error patterns for joint
check/quality probabilities. Component tests compare source and actual atom
actions, including all sixteen preparation classes. Shared-world tests validate
every required directed CNOT and single-block operation with all 102 atoms.
These layers do not claim a 102-qubit noisy statevector simulation.

Logical execution must additionally validate the concatenated selected timeline,
result availability, output ownership and rejection paths. Coarse events remain
separate from pending physical readouts. Forced raw failure tests must carry a
test-fixture label; the isolated 17-atom example noise estimate is not a factory
noise estimate. Prefetch, inventory watermarks, parallel supply, age limits and
waiting-SE policies are reserved for task six after human acceptance.

The subsequent [noisy raw preparation extension](noisy_raw_preparation.md) derives
joint rejection/class events from actual source schedules. Its unresolved noisy
output quality does not replace the independent reference-model parameter above.
