# ADR 0039: Code-selected logical QASM translation

Status: implemented frontend and logical dependencies. Atom-component execution
and resource scheduling remain open.

## Context

The user approved explicit code entry selection, general QASM gate translation,
Clifford+T synthesis and exact redundant-pattern elimination. Initialization
must use the component names initialize_0 and initialize_plus so a known-state
H can be absorbed into initialization.

The physical frontend already separates normalization, basis translation and
dependency construction. Its public loader returns PhysicalDAG and its
conditions use physical IR types; logical translation must not relabel that
output or inherit its physical gate basis.

## Decision

Add independent source-checkout Python entry points under modules/logical_compiler/.
Concrete d3 and d5 providers live in their respective modules/codes/ directories.
The registry requires an explicit code and resolves the chosen scheme before
parsing. The code entry owns operation-to-component identities. Both entries
currently select the shared surface-code Clifford+T scheme; declaring a logical
operation does not assert its atom component is implemented.

Use the existing locked Qiskit 2.6.0 environment and its parser, BasisTranslator
and Ross-Selinger RZ synthesis. No physical-compiler code, dependency declaration
or lockfile is changed. Source normalization uses independent logical records.

Normalize finite for loops and fixed bit/register-equality branches, retaining
nested predicates and immutable measurement identities. Branch measurements and
unbounded control flow require future runtime/merge semantics and are rejected.
Only standard includes are accepted.

Insert initialize_0 for zero-state inputs and lower reset to the same logical
overwrite operation. Offer explicit external-state input for subcircuits.
Fold an eligible H into initialize_plus (or back into initialize_0). Apply exact
dependency-local inverse and phase reductions before and after gate synthesis.
Preserve guards and global phases; barriers and wire interactions constrain
rewrites. No optimization samples measurement outcomes.

Translate exactly to Clifford+RZ+T and CX, then synthesize non-exact RZ angles
under an explicit circuit-level error budget. Numerically verify each generated
matrix, including global phase. Sum the local errors across all occurrences,
including alternate branches, and reject unmet budgets or output limits.
This synthesis tolerance is separate from QEC and physical-error budgets.

Return logical operations, intended component references, dependency edges,
source identities and synthesis evidence in nadit.logical_translation/1.
Mark execution_ready=false. Frontier resource checks, physical binding, SE
insertion, factories, frame tracking and atom-action emission are not implemented
by this frontend.

Rename the reserved preparation workspace to initialize_0 and initialize_plus
in both concrete codes. Their atom circuits and layouts remain undecided.

## Alternatives

- Changing only the physical GateSet cannot supply the missing approximate
  synthesis stage for generic angles.
- Reusing PhysicalDAG as Logical DAG would conflate source meaning and physical
  operations and make the code library depend on physical IR.
- A fixed rotation table would limit otherwise valid gate-level inputs.
- Approximation without an explicit budget or independent matrix check would
  hide algorithmic changes.
- Treating all valid QASM 3 as a finite DAG would discard runtime semantics.

## Consequences

General gate circuits within the documented source profile can now be translated
for either code entry. Explicit initialization enables cheaper state preparation.
Unsupported language features, precision and expansion limits remain visible.
The code library remains responsible for future concrete component algorithms.

The implementation is usable from the repository source tree through Python and
python -m modules.logical_compiler. Standalone packaging is a separate decision.
See the [caller reference](../../modules/logical_compiler/docs/qasm-translation.md)
for supported syntax, operation semantics and verification commands.

## Verification

- Existing physical frontend baseline: 78 passed; post-change regression:
  78 passed. No physical-compiler source or dependency files changed.
- Logical frontend: 59 passed, including exact unitary equivalence, initialized
  state evolution, general-angle error bounds, all four nested branch outcomes,
  repeated measurement identities, finite loops and CLI serialization.
- The initial tests failed on the absent API. A later independent matrix
  counterexample exposed loss of a small rotation when summing large angles;
  exact-representability checks fixed it without weakening the assertion.
- Ruff formatting/lint and strict mypy checks cover the new code.
- The d5 feedback example translated with 183 T/T-dagger operations and a
  checked synthesis bound of 1.10748726775807e-6 against a requested 1e-5.
  This is translation evidence, not an executed QEC or atom program.
