# Surface d=3 event probability producers

This directory supplies code-specific static probability distributions and local
continuation requests through the shared
[event probability contract](../../contracts/event_probability_v1.md).
`ProbabilityPort` owns validation, immutable records, serialization and the
content fingerprint. These producers own the event meaning, input assumptions
and calculation evidence. They do not sample an outcome, assign an occurrence
identity, advance a clock, expand a branch or retry a failed attempt. The logical
compiler owns those operations and binds result availability separately.

The distributions describe joint protocol events, not independently sampled
physical syndrome bits. A detailed syndrome backend, decoder and global frame
manager remain unimplemented. Returning a valid port does not establish that the
corresponding complete physical protocol is available.

The [actual-source noisy raw preparation interface](../protocols/noisy_raw_preparation.md)
adds exact joint acceptance/byproduct events for the complete occupied world.
It explicitly reports unsupported conditional output quality instead of inferring
an iid logical Z error rate from rejection or a physical cost proxy.

The opt-in [factory/consumer cost proxies](../protocols/cost_proxy.md) consume
strictly scoped physical reports. They preserve unknown actual resource quality
and never interpret a no-fault proxy flag as logical success.

## Logical T-consumption branches

The factory integration also provides `preparation_port(preparation)` for ideal
joint acceptance/byproduct classes, and `factory_mx_port(input_z_error=p)` for all
four final checks jointly under an assumed iid accepted-input Z-error model.
Conditional output quality is metadata, not feedback. Raw rejection is a
different event and does not supply p. See the [factory protocol](../protocols/factory.md).

[`t_injection_port`](t_injection.py) describes this precise logical convention:

```text
T = diag(1, exp(i*pi/4)); S = diag(1, i)
magic = T|+>
CNOT(data -> magic); measure magic in Z
m = 0: continue
m = 1: request rotated_surface_d3/logical_s on participant "data", then continue
```

With an independent canonical magic resource, both outcomes have probability
exactly `0.5` for arbitrary data, including data entangled with an external
reference independent of that resource. The unnormalized Kraus operators are
`K0 = T/sqrt(2)` and `K1 = exp(i*pi/4)*T_dagger/sqrt(2)`; consequently
`S*K1 = exp(i*pi/4)*K0`. The correction branch is a declared component request,
not evidence that an S operation has already executed.

```python
from modules.codes.rotated_surface_d3.probabilities.t_injection import (
    injection_probabilities,
    t_injection_port,
)

port = t_injection_port()
assert injection_probabilities() == (0.5, 0.5)
correction = port.branch(port.outcome("m1").branch_id)
assert correction.steps[0].component_id == "rotated_surface_d3/logical_s"
document = port.to_dict()  # Static, JSON-compatible model; no sampled outcome.
```

Both functions optionally accept `data_density=` and `magic_density=` as
independent logical 2x2 density matrices. With `z_data = Tr(rho*Z)` and
`z_magic = Tr(sigma*Z)`, ideal CNOT and readout give

```text
p(m=0) = (1 + z_data*z_magic)/2
p(m=1) = (1 - z_data*z_magic)/2
```

Omitted magic means canonical `T|+>`; omitted data means unknown arbitrary data.
A resource with nonzero Z expectation requires an explicit data density matrix.
Missing information is rejected rather than replaced by a maximally mixed input
or uniform probabilities. Supplied matrices must be finite, Hermitian, unit
trace and positive semidefinite within the declared numerical tolerance. The
producer copies their real and imaginary entries into model provenance and
does not normalize them. Correlated data/resource inputs are unsupported.

```python
biased = t_injection_port(
    data_density=[[1, 0], [0, 0]],
    magic_density=[[0.7, 0], [0, 0.3]],
)
assert abs(biased.outcome("m1").probability - 0.3) < 1e-12
```

`ideal_exact` means exact branch statistics for the stated ideal instrument and
input states. It does not claim an ideal T output channel for a noisy resource.
For example, a maximally mixed resource still gives equal branch probabilities
but dephases the data. The declared S response is unchanged and does not repair
arbitrary resource errors. These ports describe neither T-gate success nor
factory-distillation acceptance. A complete physical T-consumption component
has not been implemented by this estimator.

## Raw-T repeated-SE acceptance

[`raw_t_ideal_port(extra_rounds=1)`](raw_t.py) describes acceptance of the approved complete
`raw_t + k*se_round` sequence, with integer `k >= 1`. Its ideal distribution is
acceptance `1`, rejection `0`; accepted requests `deliver`, rejected requests
`retry`. A retry declaration does not execute cleanup or a new preparation.
The caller must enforce its retry budget and pay for each physical attempt.

The default uses two total rounds, sixteen results and twelve detectors:

- Four first-round boundary checks: `X0`, `X3`, `Z0`, `Z3`.
- Eight adjacent-round XORs, one for every X/Z check.

In general there are `4 + 8*k` detectors and `8*(1+k)` results. Acceptance means
all detectors vanish; it does not require all raw results to be zero. See the
[raw-T protocol](../protocols/raw_t.md) for the physical component sequence,
result availability and local correction relations. The low-level primitive's
four-check acceptance alone does not qualify a resource for use.

This coarse acceptance port does not supply the random first-round bulk signs
or apply their correction relations. Assuming a canonical resource for a later
T-consumption port is an explicit input assumption, not an implemented frame
handoff. The open temporal boundary after the last SE round and undetected seed
errors also prevent acceptance from certifying an error-free logical resource.

### Explicit Pauli/readout model

`raw_t_pauli_port(sequence, device, *, noise_params)` accepts an unobserved
`RawTPostselectionExpansion` and explicit `noise/v1` parameters. The producer
joins its actual actions, checks them against the approved source circuits,
revalidates one complete physical result, and evaluates its noise timeline once.
This avoids double-counting first-round result latency as idle time when the
second round has already begun. The initial profile requires exactly seventeen
atoms and at most twenty detectors (two or three total SE rounds).

```python
from modules.codes.rotated_surface_d3.probabilities.raw_t import raw_t_pauli_port

# sequence and device are the already compiled and bound physical protocol.
# This is a readout-only validation example, not a calibrated device model.
port = raw_t_pauli_port(sequence, device, noise_params={"readout_flip": 0.1})
```

The estimator propagates each detector observable backwards through the actual
actions. At the real center T pulse it requires identity on the seed wire;
this proves that these detector statistics do not depend on replacing the
non-Clifford seed state. It does not replace that state by a Clifford proxy or
relax the physical compiler's rejection of T in its general Stim export.
Measurement/reset consistency and zero ideal detector parity are also checked.

Every Pauli channel contributes a distribution of detector-flip masks, retaining
its mutually exclusive Pauli alternatives. Independent channels combine by
finite XOR convolution; acceptance is the all-zero-mask probability. This is
exact for the declared stochastic model, evaluated in floating point, with no
Monte Carlo shots or statistical confidence interval. For two rounds and
readout-flip probability `p` only, an independent check is
`P(accept) = (1-p)^8 * ((1-p)^2 + p^2)^4`.

The port retains source, device, template, result, noise and estimator
fingerprints, resolved noise parameters and proof evidence. Only explicitly
Pauli gate models are admitted; coherent/native models are rejected instead of
silently twirled. No nonideal hardware model is selected by default. An estimate
is not an unconditional property of code distance or a fault-tolerance claim.

Atom loss remains a separate physical model. A Pauli/readout-only estimate must
not silently include loss, leakage, coherent errors, a decoder or a distillation
factory. Combining these effects requires an explicit joint protocol and noise
model; multiplying an unrelated survival estimate by postselection acceptance
does not establish such a model. All calculation backends in this directory
return static probabilities rather than sampled records or branch executions.

## Export for the logical compiler

Run from the repository root with the existing physical-compiler environment:

```powershell
& modules/physical_compiler/.venv/Scripts/python.exe -m modules.codes.rotated_surface_d3.examples.export_event_probabilities --output modules/physical_compiler/artifacts/event-ports-ideal
```

The exporter writes `raw_t_postselection.json` and `t_injection.json`, printing
each canonical port fingerprint. Both defaults are ideal; it samples no event.
`--extra-rounds` selects additional ordinary SE rounds. Supplying
`--raw-noise-params path/to/explicit-noise.json` compiles the illustrative
nonzoned reference device and estimates raw-T acceptance for that parameter
file. T-consumption still uses the separate ideal logical instrument. Existing
output directories are rejected to preserve previous results.

### Selected first nonideal example

The user selected the existing
[`noise_illustrative.json`](../../../physical_compiler/cost_params/noise_illustrative.json)
on 2026-10-23 as the first nonideal example, explicitly without hardware
calibration. Use the complete file with the default two-round reference protocol:

```powershell
& modules/physical_compiler/.venv/Scripts/python.exe -m modules.codes.rotated_surface_d3.examples.export_event_probabilities --output modules/physical_compiler/artifacts/event-ports-illustrative --raw-noise-params modules/physical_compiler/cost_params/noise_illustrative.json
```

For this fixed action/noise profile, Pauli/readout acceptance is
`0.8538402099976652` and rejection is `0.1461597900023348` across twelve detectors.
These are example model probabilities, not calibrated hardware probabilities or
logical-state fidelity. The separate all-atoms-survive estimate is
`0.9718619126101095`; it is not folded into acceptance. The example explicitly
sets Z-rotation gate noise to zero, including the seed T pulse.

The selected handoff port retains an `example_profile` evidence record with
`calibrated=false`, the parameter-file hash and the original producer-port hash.
This annotation changes the port fingerprint but leaves its probabilities and
branches unchanged. T consumption retains its separate ideal instrument and
canonical-resource assumptions: m0/m1 are each one half, with S requested for m1.
Factory distillation acceptance is outside the user-confirmed scope.

The consumer reads each JSON with `ProbabilityPort.from_dict`, binds its own
occurrence and availability, then records its selected outcome and the unchanged
fingerprint. The code-owned port contains no case seed or synthetic syndrome.

## Evidence and primary sources

- [Bravyi and Kitaev, *Universal quantum computation with ideal Clifford gates
  and noisy ancillas*, Sec. III, Eq. (2)](https://arxiv.org/pdf/quant-ph/0403025)
  gives the `A_theta` injection relation and equal-probability outcomes. The
  producer uses `theta=pi/4` and the explicit CNOT/MZ convention above.
- [Ye et al., arXiv:2305.15972v2, Fig. 1(a), Eq. (1)](https://arxiv.org/pdf/2305.15972v2)
  supports the central-seed rotated-code preparation route. Its hardware results
  are not substituted for this implementation's probability model.
- [Li, *A magic state's fidelity can be superior to the operations that created
  it*, Sec. II](https://arxiv.org/pdf/1410.7808v1) uses two syndrome rounds with
  initial-boundary and inter-round consistency postselection. This motivates
  repeated extraction, without equating its full protocol to this d=3 instance.

The [T-branch tests](../tests/test_event_t_injection.py) independently compare
the formula with full two-qubit evolution, verify both corrected branches with
an entangled reference, and check noisy-resource counterexamples and invalid
inputs. Physical raw-T source/atom-state evidence is documented in the linked
protocol; it is distinct from a noise-model estimate or logical error rate.
