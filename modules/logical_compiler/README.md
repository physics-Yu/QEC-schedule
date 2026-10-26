# Logical Compiler

Status: workspace and responsibility boundaries accepted on 2026-10-23.
The code-selected QASM frontend, initialization simplifier, logical dependency
graph and coarse probability-driven abstract cases are implemented. A separate
[factory pipeline](docs/factory-pipeline.md) now composes real code-owned components
in one physical context. Code-declared synchronous component waves are supported;
general QASM-to-component execution and asynchronous device scheduling remain open.

Start with the [QASM translation reference](docs/qasm-translation.md) for the
explicit code entry, supported syntax, approximation budget and command line.

For the initial two-level object estimate, use `examples.factory_level2` with
[`level2-d3-n1-b1.json`](../../experiments/msd/level2-d3-n1-b1.json).
It runs one producer and one consumer with B=1, progressive four-plus-eleven
input supply and three costed whole-block moves per handoff. It reuses the
existing object runtime and fake probability ports, without atom work. The
[acceptance report](../../docs/experiments/msd-object-level2-d3-20261025.md)
contains the command, bounded configuration, metrics and full HTML location.
The entry now exposes `distance` (recorded 3/5/7/9/11), positive integer
`level1_factories`, and `placement` (`vertical`, `horizontal`, or `grid` with
explicit `columns`). These reuse existing whole-factory placement and costs.
L2 is one same-distance factory below the L1 array; B remains one. Setting
`level2_distance` to a different distance fails explicitly. `strategy` selects
L1 asynchronous/synchronous behavior; L2 remains an independent asynchronous
consumer. No cross-level stage barrier is introduced.

The [two-producer comparison](../../docs/experiments/msd-object-level2-n2-20261025.md)
uses d3, N1=2, N2=B=1, seed 0 and one attempted L2 round. All five distances and
three layouts have geometry-interface checks; complete L2 production acceptance
currently covers d3 with N1=1/2 only, not every configurable combination.

The [next scan preparation](../../docs/experiments/msd-level2-sync-scan-preparation.md)
freezes synchronous L1 only and one L2 across 270 cells / 27000 shots, with
89 single-thread workers and a 30-second shot / 3060-second cell budget.
Its [JSON record](../../experiments/msd/level2-sync-scan-preparation.json) is not
accepted by the current runners. Three consumer-position variants and scan
adaptation remain pending; do not run or implement this campaign before the
user approves it. Historical asynchronous code and reports remain available.

The user subsequently approved this scan. The executable configuration is
[`level2-sync-server-scan.json`](../../experiments/msd/level2-sync-server-scan.json),
used by `python -m experiments.msd.scan_objects --config CONFIG --output FRESH_RUN`.
Set `NADIT_SOURCE_COMMIT` to the frozen archive commit before full dispatch.
`--cell ID --one-shot` is a separately labeled bounded control, never a full scan.
The 30-second shot cap includes metrics and selected trace serialization. Full
completion requires all 270 cells and 27000 valid shots; no resume is performed.

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

## Object production rounds

`examples.factory_objects` supports `production_basis="production_rounds"`:
`cycles_per_factory` counts attempted factory rounds, including final rejection.
Both async and sync configurations must select that basis for paired comparison.
`synchronous/v2` delivers success immediately, counts rejection as no output,
then joins every factory at the next production round. Raw-resource retry waits
and conditional S+SE joins remain. `synchronous/v1` is rejected as superseded.
The asynchronous default retains legacy `accepted_outputs` semantics.

Snapshots separate all `production_rounds` from accepted `production_cycles`.
Zero-output runs are valid, with null startup/per-output costs. Actual external
injection costs remain excluded by the ideal sink. This object-only path does
not compile or expand atoms. See [ADR 0053](../../docs/decisions/0053-factory-strategy-boundaries.md)
and the paired `experiments/msd/factory-objects-rounds-d{3,5,7,9,11}.json` and
`factory-objects-sync-d{3,5,7,9,11}.json` configurations.

Complete numeric object inputs now cover d=3/5/7/9/11. The d9/d11 inputs are
projected from existing saved stage templates and exact-XOR probability caches,
with no new physical build. The loader validates exact probability evidence
without inventing sampled counts; d3/d5/d7 files are unchanged. The explicit
offline `experiments/msd/extract_d9_d11_objects.py` converter is never called by
the estimator. See the [migration and acceptance report](../../docs/experiments/msd-object-d911-20261025.md).

## Whole-factory placement in object estimates

The Python object entry and catalogs accept `placement="vertical"` (default),
`"horizontal"`, or `"grid"` with positive `columns`. JSON configurations use
`"placement": {"kind": "grid", "columns": 2}`. Non-grid choices reject columns;
grid reports both requested and effective columns when N is smaller. All layouts
reuse `GridFactoryPlacement`, code-owned block footprints and the original
internal role order. No component cost records or probability ports are rebuilt.

Reports retain placement fingerprints, storage width/depth/bounding area,
summed block area, resource use, and separate command/member timing and shared
stage counts. Complete schedules draw saved block geometry without code expansion.
The [d3 N4 study](../../docs/experiments/msd-object-layout-d3-n4-20261025.md)
contains six reproducible configurations and all twelve complete schedules.
Unbounded horizontal capacity is explicit; readout/device total area is unavailable.
