# Logical Clifford+T to signed Pauli rotations

`src/neutral_atom_experiments/qec_pbc/logical_pauli.py` implements an exact
unitary frontend, independently of surface-code protocols and hardware.
It reuses the existing `PauliProduct` with signed Hermitian observables.

```python
from neutral_atom_experiments.qec_pbc.logical_pauli import (
    LogicalGate, compile_logical_pauli,
)

program = compile_logical_pauli([
    LogicalGate("H", ("a",)),
    LogicalGate("CX", ("a", "b")),
    LogicalGate("T", ("b",)),
], wires=("a", "b"))
payload = program.to_dict()
```

## Exact convention and execution order

Input and residual gates are in chronological order. Output rotations are also
chronological; apply all rotations first, then the residual Clifford circuit.
With `quarter_turns=k`, a rotation is
`R_P(k*pi/4) = exp(-i*k*pi*P/8)`. The program includes a global phase
`exp(i*pi*global_phase_eighth_turns/8)` modulo 16. Thus its exact matrix is
`phase * C * R_last * ... * R_first`, including the conventional T/Tdg phase.

At each T/Tdg gate the preceding Clifford is propagated into its signed
observable as `C† Z C`. The compiler maintains the inverse images of 2n X/Z
generators, updating only the acted-on generators after each Clifford using
a snapshot. T/Tdg requires one image lookup. This avoids quadratic traversal
of the gate history; per-gate Pauli algebra still depends on support size.
H, S, Sdg, X, Y, Z, CX and CZ remain in the residual
Clifford. No noncommuting rotations are reordered, combined or removed.
Each rotation records its original source index. Explicit wire order may
include untouched wires and defines the input/output register order.

The equality holds for arbitrary input states, including entanglement with
external reference systems. It is not a BSS compiler that discards stabilizer
registers while preserving a terminal classical output distribution. It is
also not yet a Pauli-measurement/injection protocol: these rotations require
separate resource-state and encoded-operation lowering.

## Scope

Supported gate names are exactly H/S/Sdg/X/Y/Z/CX/CZ/T/Tdg. Measurements,
reset, conditions, parameterized rotations and CCX are rejected at this
boundary. Such circuits need an explicit instrument frontend or upstream
decomposition; no measurement is silently discarded. The result does not
claim fault tolerance, physical timings, resource-state quality or QEC rounds.

## Independent checks

`tests/test_qec_logical_pauli.py` uses dense NumPy matrices, independently of
the symbolic algebra. It checks all signed two-wire Pauli products under
forward/inverse Clifford conjugation, 60 seeded random three-wire circuits,
exact global phases, source order, untouched wires and an entangled probe.
Rejecting invalid gates/wires and nonunitary boundaries is also checked.

Validated on Python 3.12.14 with NumPy 2.5.3 and pytest 9.1.1: 11 tests
passed initially; the incremental frame revision passes 12 tests, including
a 400-gate comparison against history conjugation and independent dense
matrices. The exhaustive conjugation cases include both signed identities and
all Y-containing two-wire products; randomized comparisons check full
unitaries rather than only computational-basis probabilities.

A local synthetic 15-wire benchmark (single samples, not hardware timing)
compiled 3,000/6,000/12,000 mixed gates containing 1,000/2,000/4,000 rotations
in 0.0532/0.1075/0.2138 seconds on this host.
