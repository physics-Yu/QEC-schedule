# Logical QASM translation

Status: implemented logical frontend and dependency graph. Atom-component
execution, frontier resource scheduling and physical lowering remain open.

## Explicit code entry

The caller must select `rotated_surface_d3` or `rotated_surface_d5`; there is
no default code. Each code's `entry.py` supplies its scheme, target gates and
intended component identities. Both currently choose `clifford_t`. The
compiler does not infer cross-code compatibility.

The source-checkout API is:

```python
from modules.logical_compiler import load_qasm, loads_qasm

result = load_qasm(
    "circuit.qasm3",
    code="rotated_surface_d3",
    scheme="clifford_t",
    error_budget=1e-6,
    input_state="zero",
    max_operations=100_000,
)
document = result.to_dict()
```

Run from the repository root with the existing physical-compiler locked
environment (Qiskit 2.6.0). No dependency or physical-compiler source changes
are needed:

```text
uv run --project modules/physical_compiler --locked python -m modules.logical_compiler modules/logical_compiler/examples/logical_feedback.qasm3 --code rotated_surface_d3 --error-budget 1e-5 -o logical-result.json
```

The command also prints JSON. It returns 0 on success and 2 on input,
translation, budget or output errors. `--code` is required. Output cannot
overwrite the QASM input. This is a repository-source entry point; no separately
installed wheel or public physical-compiler CLI command is introduced.

## Source profile

Supported:

- OpenQASM 2.0 and 3.0 gate-level circuit sources with their standard include.
- Standard gates and custom gate definitions in the same file, with bound
  finite numeric parameters; supported control/inverse modifiers are expanded.
- General rotations and standard multi-qubit gates with a Qiskit basis
  decomposition; no fixed circuit, qubit count or rotation-angle table.
- Measurement, reset and barriers.
- Finite integer for loops, including loop parameters in gate angles.
- Bit/register equality branches and nested branches accepted by the importer.
  Initial classical bits are zero; subsequent reads refer to immutable
  measurement occurrences. An else branch retains the complementary predicate.

The source does not need to start in the target gate set. The general quantum
gate pipeline is exact decomposition to Clifford+RZ+T, followed by approximate
synthesis of non-exact RZ rotations.

Full OpenQASM 3 language support is not claimed. Runtime while loops,
break/continue, conditional measurements, general classical expressions or
assignments, opaque gates, extern calls, pulse/timing constructs, physical-qubit
addressing, unbound inputs and nonstandard includes are outside this profile.
They are rejected rather than silently discarded. Some unsupported constructs
are rejected by the pinned QASM importer before normalization.

The expansion limit counts source visits and emitted operations. It is not a
hard subprocess time or memory limit on the upstream parser or decomposer.

## Target operations and initialization

The quantum gate vocabulary is:

```text
x y z h s sdg t tdg cx
initialize_0 initialize_plus measure
```

`barrier` and `global_phase` are retained metadata. `measure` refers to logical
Z readout. The code entry maps `cx` to its chosen `trans_cnot` identity and
`measure` to `measure_z`; this choice lives in the code library, not the
generic component contract. T/T-dagger references are distinct from raw-T
resource preparation.

With `input_state="zero"`, each source quantum wire starts with
`initialize_0`. A source reset also becomes `initialize_0`, with overwrite
semantics on that logical wire. With `input_state="external"`, implicit
initializers are omitted for arbitrary-state subcircuits; explicit resets remain.

An unconditional H directly following initialization on that wire toggles
`initialize_0` and `initialize_plus`. It need not be adjacent in the serialized
list if intervening operations touch only other wires. This saves the separate
H component without assuming arbitrary data qubits start in a known state.

Other exact reductions include adjacent-on-wire inverse H/Pauli/CX operations,
S/S-dagger and T/T-dagger cancellation, phase-gate composition, equal-axis
rotation composition when the sum is exactly representable, and removal of
identity operations. Known-zero classical
predicates can be simplified without measurement sampling. Incompatible guards,
measurements, barriers and intervening interactions block the relevant rewrites.
No general nonlocal commutation or optimal T-count claim is made.

## Synthesis accuracy

RZ angles represented exactly as multiples of pi/4 in the numerical input take
an exact Clifford+T path, retaining their global phase. Other RZ rotations use
Qiskit's Ross-Selinger implementation. The total requested synthesis budget is
divided across all such occurrences, including mutually exclusive branches.
Repeated angles reuse their compiled sequence within the call, but each
occurrence contributes separately to the bound.

Each generated one-qubit circuit is checked by computing the spectral norm of
its matrix difference from RZ, including global phase. The synthesis request uses
a tighter internal tolerance; a measured error exceeding the allocated budget
is rejected. The supported per-rotation budget floor is 1e-12. Insufficient
precision or excessive output size produces an explicit error, not a coarser
successful result.

`synthesis_error_bound` sums the numerically checked local errors. For unitary
paths this is a conservative composition bound, subject to floating-point
verification. It is not a rigorous interval-arithmetic certificate, a physical
noise estimate, a logical failure probability or a bound on renormalized
postselected states. Exact decomposition and numerical roundoff are checked
separately by the semantic tests.

## Results and ownership

A `nadit.logical_translation/1` document records:

- Code/scheme, target operations, input-state convention and Qiskit version.
- The SHA-256 of the imported source string.
- Logical operations and intended component identities.
- Quantum/classical register names and their flattened wire indices.
- Original normalized source identities, guards and stable measurement IDs.
- Quantum-wire, classical-write and measurement-to-condition DAG edges.
- Requested synthesis budget and each rotation's measured error and gate count.

Source IDs are assigned after custom-gate expansion and loop unrolling, before
gate translation. They are occurrence identities, not source line numbers.
Merged operations retain contributing IDs; identities removed by optimization
need not appear as output nodes. Output node identity is its list index.

The output is marked `stage="logical_translation"` and
`execution_ready=false`. Component references identify required implementations;
they do not certify that those atom-level implementations already exist.
The compiler neither samples measurement outcomes nor chooses a feedback branch.

## Verification

From the repository root:

```text
uv run --project modules/physical_compiler --locked python -m pytest -c modules/logical_compiler/pytest.ini modules/logical_compiler/tests
```

The tests compare exact full unitaries, approximate operator norms and initialized
state evolution independently with Qiskit. They cover both code entries,
measurement rebinding, nested branch outcomes, loop expansion, safe rewrites,
precision failures and the command-line round trip.

See [ADR 0039](../../../docs/decisions/0039-logical-qasm-translation.md).
