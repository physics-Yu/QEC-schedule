# Logical T/Tdg resource-state injection

`qec_pbc.magic_injection.make_magic_injection` constructs a logical instrument
contract with data/resource wires, explicit resource provenance, a CX from
data to resource, destructive resource Z measurement, and outcome-dependent
S/Sdg correction. Measurement IDs connect the correction to its required
classical result. The consumed resource cannot be treated as an output wire.

For sign s=+1 (T) or -1 (Tdg), the ideal reference state is
`(|0> + exp(s*i*pi/4)|1>)/sqrt(2)`. Branch zero has Kraus operator
`T_s/sqrt(2)`; branch one has
`exp(s*i*pi/4)*T_s†/sqrt(2)`. The S_s correction on branch one yields
the desired T_s up to a branch global phase. Each branch has probability 1/2
for any input, including entanglement with a reference.

```python
from neutral_atom_experiments.qec_pbc.magic_injection import make_magic_injection
contract = make_magic_injection(
    "T", "data", "resource", measurement_id="injection_0",
    provenance="factory-output-17",  # actual quality has not been characterized
)
payload = contract.to_dict()
```

Resource quality defaults to `unknown`. `ideal_reference` may be selected
explicitly for mathematical tests; it does not assert physical preparation
fidelity. Exact branch/channel identities here assume this ideal vector.
An unknown or noisy resource requires a separate calibrated noise model.

This is not surface-code physical compilation or a fault-tolerance proof.
Logical CX, Z readout and especially logical S/Sdg still need encoded protocol
implementations, detectors and decoding. No physical gate capability,
duration, factory acceptance rate or distillation protocol is inferred.

Independent NumPy tests derive both two-qubit branch Kraus operators directly
from a dense CX and verify completeness, equal probabilities, corrected
data-reference channels and explicit three-qubit branch vectors for T/Tdg.
