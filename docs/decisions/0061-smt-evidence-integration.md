# 0061: Optional SMT integration and independent evidence

Status: implementation integrated for acceptance on 2026-10-27.

Keep the existing ProgramCompiler, PhysicalDAG, Device, CompilationResult and
Atom IR contracts. SMT is opt-in, requires explicit SLM homes, and rejects
conditional feedback. Z3 remains an optional pinned extra; ordinary compiler
discovery and existing backends do not import it.

Separate three outcomes: a valid executable schedule, solver feasibility status,
and an optimality claim within a finite domain. BoundedSearchFailure preserves
UNSAT versus UNKNOWN. Existing heuristic SearchExhausted semantics remain intact.
Successful/failed solver evidence is persisted independently of the executable
result schema, with a canonical result hash whenever a result exists.

An isolated worker enforces the solver wall deadline, including construction and
child validation. Incumbents are validated and atomically checkpointed before
further queries. Parent-side preparation/final verification are measured
separately. The caller's measurement provider runs only in the parent after a
plan is recovered. Low-level in-process solve is explicitly not wall-bounded.

Generic conformance tests use per-compiler examples and declared entry/feedback
capabilities. Original backends retain their existing unsupported-device checks;
SMT gets actual missing-control cases and positive rigid admission coverage.
Optional-dependency absence must not break ordinary compiler discovery.

Keep the d3 fixed-stage MOVE-depth solver under experiments. Compact historical
certificates retain source model bytes, input hashes, solver answers and the
exact subdomain argument used to transfer lower bounds. Rechecking a SAT witness
does not independently establish the historical UNSAT responses. Readout and
minimum elapsed-time claims remain outside this depth study.

QEC viewer metadata is an independent presentation feature. Explicit wire-to-atom
binding permits different physical layouts without changing saved results or
inferring topology from labels. Use the shared template for experiment exports.

Existing pending MSD component-reuse edits are preserved outside the integration
commit. Fix only the demonstrated reference-file newline issue: pin the raw-byte
hashed JSON to LF, retaining all expected geometry hashes and assertions.
