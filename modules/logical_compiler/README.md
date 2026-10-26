# Logical Compiler

Status: workspace and responsibility boundaries accepted on 2026-10-23.
The code-selected QASM frontend, initialization simplifier, logical dependency
graph and coarse probability-driven abstract cases are implemented. A separate
[factory pipeline](docs/factory-pipeline.md) now composes real code-owned components
in one physical context. Code-declared synchronous component waves are supported;
general QASM-to-component execution and asynchronous device scheduling remain open.

Start with the [QASM translation reference](docs/qasm-translation.md) for the
explicit code entry, supported syntax, approximation budget and command line.

The [component scheduler](docs/component-scheduling.md) uses code declarations,
participant dependencies, spaces and device resources. Its d3 factory integration
supports matching SE/S, initialization, raw preparation and MX/MZ waves,
corresponding translated transversal CNOT pairs, and physical local-correction
families. Actual composition retains whole-world physical validation. A same-device
serial comparison and component/atom timelines are exported by
`examples.factory_parallel`; synchronized multi-line production uses
`examples.factory_array`.

The [fast factory entry](docs/fast-experiments.md), `examples.factory_fast`, reuses
the same protocol runtime with calibrated logical component receipts. Its explicit
`--code`, `--profile` and `--input-z-error` inputs support repeated seed and
factory-count experiments
without compiling atom movements for each case. It separates member work, shared
resource busy time, makespan and software wall time. Component timing and physical
costs are profile estimates; theoretical joint final-MX checks control output acceptance.
The user-confirmed reference study uses `--input-z-error 0.01`. Raw rejection and
retry retain their separate supply model, while complete-window physical
no-fault costs are independent diagnostics. Physical validation is not run on
the fast path and decoded logical success remains unknown. The old cost-driven
acceptance mode requires `--acceptance-model physical_no_fault_proxy`; see
[ADR 0051](../../docs/decisions/0051-theoretical-factory-acceptance.md).

The [case-compilation design](docs/case-driven-compilation.md) records the agreed
direction for protocol-aware fake measurements, factory retries and shared
device scheduling. One AOD is an initial study configuration; resource interfaces
must allow other configurations. Its [implemented subset](docs/case-driven-compilation.md#implemented-abstract-case-api)
expands selected protocol events with finite retries and causal timing. The
separate factory entry supplies physical expansion and resource ownership;
hardware execution remains outside this module.

The intended pipeline translates a logical circuit into operations supplied by
the [code library](../codes/README.md), constructs a Logical DAG, checks frontier
constraints and binds component invocations into atom-level work. Concrete
code definitions and gate implementations remain in the code library.

## Layout

```text
logical_compiler/
  src/
    frontend/
    translation/
    dag/
    cases/
    protocols/
    scheduling/
    estimation/
    expansion/
    state/
  examples/
  configs/
  tests/
  docs/
```

The [source responsibilities](src/README.md) describe these work areas.
The [architecture note](docs/architecture.md) records the accepted flow and
remaining design questions. Empty folders contain only .gitkeep files.

## Intended responsibility

1. Read a logical circuit using an approved source profile.
2. Translate gates using implementations supplied by selected codes/protocols.
3. Construct component invocations and their quantum/classical dependencies.
4. Check frontier dependencies and declared logical constraints to select
   candidates that may advance together.
5. Bind participants, atom roles, coordinates and measurement identities, and
   expand the selected components through their interfaces.
6. Accumulate the case's atom program, results and updated block state through
   the physical-compilation handoff.

Logical admission does not establish device-level concurrency. Actual geometry,
AOD transport, pulse coverage and readout capacity must be resolved against the
complete device state. Component identity must survive that handoff.

## Current delivery

The source-checkout Python API and CLI translate QASM using the d3/d5 code
entries. Outputs include intended component references, guards, dependencies and
numerically checked Clifford+T synthesis evidence. They are not executable atom
programs. Automatic component binding and resource scheduling for general QASM
output, and standalone packaging remain open. Existing physical compiler code
and dependencies are unchanged.

`compile_case` separately accepts explicitly bound abstract components and shared
code-owned probability ports. It exports one reproducible static abstract case,
including selected corrections, retry attempts, event provenance and timing.
It is not yet wired to the QASM result or a physical component loader. The d3
producer fixtures exercise raw-T acceptance and both T-injection branches; their
abstract timing values are synthetic and do not establish device throughput.

The explicit `modules.logical_compiler.factory` entry runs a code-owned factory
recipe with real component timing, local preparation corrections, single-use
resources and finite retries. The six-patch example reuses measured W2 for
algorithm data and consumes the factory output on W1 once. Its physical case is
validated as selected Atom IR while individual physical results remain pending;
logical events use declared coarse reference models. Prefetch, watermarks,
resource aging and periodic waiting-SE policies are not implemented.

The factory path carries each component's actual exit binding, pending results
and time through its shared context. General frame handling, state-aware noisy
simulation and decoder integration remain open.

The factory component scheduler supports synchronous waves using shared rows and
disjoint column bands on one AOD. Corresponding CNOT pairs require matching signed
relative geometry and ownership of both patches; being transversal alone does
not allow batching. MX/MZ reserve nine result identities per member. Local Pauli
and canonicalization families preserve actual pulses and their costs without
introducing a global Pauli frame. Admission checks aggregate capacity before
expansion, and the combined physical program is validated afterward. Initial raw
preparation retries affect only failed patches. See
[component scheduling](docs/component-scheduling.md) and
[ADR 0049](../../docs/decisions/0049-component-parallel-admission.md).

The `examples.factory_array` entry adds resumable multi-factory production with
one shared scheduler and resource ledger. Its default two-line policy waits for
cohort peers at protocol stages, keeps successful raw resources while peers retry,
and holds accepted factory outputs. Actual enlarged Device geometry, per-line
cost ownership and interactive resource-history replay are documented in
[factory arrays](docs/factory-array.md). A configuration with `max_parallel=1`
provides the serial control through the same entry, code and Device.
Its final checks use the same theoretical reference backend as the fast entry,
with an explicit `--input-z-error` and separately reported physical cost diagnostics.

The legacy explicit `examples.factory_proxy` entry provides fixed-seed cost experiments:
real noisy raw rejection/reset/retry, batch no-fault proxy acceptance, and a
separate terminal algorithm proxy. Every run exports its physical case and a
fixed ledger of attempts, S corrections, scoped probabilities and sampled
outcomes. Actual accepted-state quality and logical success remain unknown;
see the [proxy scope](docs/factory-pipeline.md#explicit-physical-no-fault-proxy-experiment).

See [ADR 0037](../../docs/decisions/0037-code-library-and-logical-compiler-workspaces.md)
and the root [engineering standards](../../agent.md).
