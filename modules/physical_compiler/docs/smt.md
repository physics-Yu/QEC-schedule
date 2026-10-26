# Bounded SMT compiler

Install the optional `smt` extra (`z3-solver==4.16.0.0`). Other compilers do not
import Z3. The `smt` registration appears in `nadit describe` and the job schema.

```json
{
  "kind": "smt",
  "xs": [0, 2, 10],
  "ys": [0],
  "horizon": 5,
  "timeout_s": 60,
  "time_quantum_us": 0.001
}
```

| Field | Default | Meaning |
| --- | --- | --- |
| xs, ys | required | Strictly increasing coordinate alphabets, in micrometers |
| horizon | required | Maximum synchronous Atom IR steps; empty suffix allowed |
| timeout_s | 60 | Total Z3 check budget; model construction is recorded separately |
| time_quantum_us | 0.001 | Upward rounding for integer optimization bounds |

Use `entry.kind="explicit"` with SLM homes and no initially active AOD lines.
Only the selected AOD is modeled. Device determines capacities, row/column
spacing, workspace, fixed SLM traps, motion model, operation zones, holder
permissions, readout capacity and all action durations. Capacity `null` remains
unlimited; the coordinate alphabet is a separate declared discretization.

Supported native operations are rx/ry/rz/u/cz/reset/measure and metadata
barrier/global_phase. Measurements retain their identities and result latency.
Conditional operations and GlobalRY are not admitted by this static profile.
The current control profile illuminates all CZ-capable regions together; it
does not optimize locally addressed CZ coverage. LOAD/MOVE/STORE include all
active lines, including empty lines. Partial stores and retention across gates
are allowed. The final state returns every atom to its original SLM home.

Independent local gates can overlap transport on other atoms. A moving atom
cannot cross concurrent CZ illumination. Every geometrically coupled pair must
match a scheduled CZ. The objective includes completion of the Atom IR and
availability of all measurement records. Actual emitted durations use Device,
without rounding; the solver objective uses the stated time quantum.

Use ordinary `nadit compile JOB.json` for a complete schedule. For evidence:

```python
from nadit_physical_compiler.smt.solver import solve
solved = solve(context, options, measurement_backend, seed=None)
# context is the existing ProgramContext; result uses ordinary CompilationResult.
# solved.evidence records SAT/UNSAT/UNKNOWN, bounds, domain and input hashes.
```

An optional `seed` is a `Plan` carrying an independently checked upper bound.
Checking a fully fixed seed is recorded as `fixed_witness_membership`, not an
unrestricted search. Phase preferences do not constrain the search. Entirely
empty NONE steps are canonicalized to a suffix in the search model, eliminating
idle-position symmetry without changing attainable costs. Caller-provided seeds
must already have that form. Ordinary compilation raises `SearchExhausted` when
no schedule is found. `SMTCompiler.last_evidence` retains the evidence in-process;
the research harness saves it as a hash-linked sidecar.

`optimal_in_domain` means a feasible upper bound meets a proved lower bound in
the declared alphabet/horizon/control model. `feasible_unknown` means a valid
program exists but the search did not prove optimality; `unsat_in_domain` does
not mean physical hardware infeasibility. A larger coordinate alphabet or
horizon can change the answer. Report constructive and solver-found schedules
separately, and never infer architecture dominance from unequal heuristic bounds.

The d3 harness is `python -m experiments.surface_smt.run`: prepare frozen inputs,
run each of four cases once, then summarize and export the shared viewer. It uses
one extraction round, fixed N/Z per-wire order, common homes and unlimited AOD
capacity. It checks ideal extraction and hook orientation; it is not a noisy
memory or circuit fault-distance experiment. See
[ADR 0058](../../../docs/decisions/0058-bounded-smt-surface-architecture.md).
