# Schedule-derived noisy raw-A preparation events

Status: implemented for the frozen raw-T plus repeated-SE protocol and explicit
independent `noise/v1` Pauli/readout channels. Conditional output quality and
complete noisy factory/algorithm success are not implemented by this interface.

## Source-dependent entry

After actually expanding the preparation in the current complete physical world:

```python
parameters = {"noise_model": "noise/v1", "noise_params": noise_parameters}
port = backend.preparation_event("raw_t_postselection", source, parameters)
# The logical compiler waits for dependencies and samples one outcome.
quality = backend.preparation_quality_from_event(
    "raw_t_postselection", source, port, selected_values, parameters
)
```

The actual `RawTPostselectionExpansion`, device, full spectator occupancy,
internal gaps and result-ready tail determine the cost model. The estimator
validates the joined physical sequence before deriving activity and noise.
It does not substitute the old isolated seventeen-atom acceptance constant.
The protocol still has seventeen participant roles, while its Pauli-observable
universe includes all occupied atoms. Independent spectator channels have zero
raw-detector signature but remain in the complete cost/loss evidence.

The source hook recognizes `input_z_error` only on its existing ideal-reference
path, as an explicit assumed input-quality parameter. It does not change ideal
preparation class statistics. A noisy request cannot also supply that scalar;
unsupported or mixed parameters raise an error rather than falling back to ideal.

## Exact joint event under the frozen model

The port uses the existing `canonical_preparation` identity and joint fields
`accepted` and `byproduct_class`. Class bits are X1, X2, Z1, Z2, little endian.
There are sixteen accepted outcomes and one rejected outcome with null class.

Let R be the ideal four-bit bulk outcome and F a complete Pauli/readout fault
pattern. The approved encoding isometry makes R uniform on all sixteen values
for an arbitrary center seed. Clifford Pauli covariance gives recorded class
`C = R xor delta(F)`, while the detector parities depend only on F.
Before the unique seed T pulse there is no entangling gate, and the center is
ideally |+>. A pre-T Pauli X^x Z^z is therefore equivalent, on this fixed state,
to Z^z after T up to phase. This is a state-specific identity, not a general
Clifford approximation to T. Independent, state-independent fault probabilities
and these properties imply

`P(accepted, C=c) = P(accepted)/16`.

The accepted mass comes from exact finite XOR convolution of the actual noise
channels, retaining exclusive alternatives within each channel. Source/action
tests verify the sixteen isometry branches and real T seed faults. Other
non-Clifford operations, coherent noise, cross-block ideal interactions or
correlated fault models are rejected; the factorization is not assumed for them.
No individual physical measurement bit is fabricated from the coarse class.

## Why acceptance does not supply a logical input error rate

Even with readout noise only, two flips of the same bulk check, one in each
round, pass the detector rule. The reported class then prompts an incorrect
local Pauli, taking the physical output into a nonzero stabilizer sector.
For independent readout flip probability 0 <= r < 1 and exactly two rounds, the
conditional probability that one bulk class bit is wrong is

`q = r**2 / ((1-r)**2 + r**2)`.

The probability that the ideally applied local correction leaves the standard
code sector is `1-(1-q)**4`. In addition, faults after the final extraction can
pass the open temporal boundary. The actual correction pulses and subsequent
memory time introduce further noise which this preparation segment does not
propagate. Without a declared recovery convention and conditional output channel,
these effects cannot be converted to the factory reference model's iid logical Z
parameter. Rejection probability is not that parameter either.

Consequently the noisy quality result has `status="unsupported"`,
`consumption_parameters=None`, and `logical_success_probability=None`, with its
source port hash and reasons. Callers must treat this as unavailable; passing
None to an API that defaults to ideal would silently change the model.

## Cost and timing scope

- The full world is costed from the first raw action through result readiness.
  Earlier prefix exposure and later storage are explicitly outside this segment.
  Raw resets all participants; this does not erase spectator memory errors or
  imply that earlier physical atom loss is repaired.
- Physical loss is a separate report. The Pauli/readout event is conditioned on
  retained computational atoms; no loss-heralding rejection policy is invented.
- `noise_illustrative.json` remains an example, not a calibration. Its Z override
  gives the seed RZ(T) zero configured gate error. Its T2 channel covers idle and
  configured transport, not gate/reset/measurement busy time. Illuminated CZ
  spectators are busy; with the example's zero spectator Pauli parameters they
  have no configured pulse-time error. These are existing model semantics.
- Source, device, noise parameters, noise report, detector signatures and
  estimator-source hashes accompany the probability port. Actual absolute start,
  exit, result-ready time and all participant/world IDs are retained.
- An unconditional whole-trace no-fault product is a diagnostic, not a logical
  success probability. If a raw rejection has already been sampled, independently
  sampling that same whole trace as fault-free would be inconsistent. A future
  sampled proxy needs an explicit scope and conditioning rule.

The logical compiler owns seeds, retries, actual reset/repreparation calls and
fixed resource ledgers. This interface neither maintains inventory nor implements
a decoder, global frame or complete noisy factory simulation.

An explicitly selected [cost-proxy protocol](cost_proxy.md) can continue action
routing while preserving unsupported actual quality. It uses marked ideal
reference routes and non-overlapping scoped no-fault events; it does not replace
the missing quantum-quality model or silently set its error rate to zero.
