# NADiT architecture

NADiT models neutral-atom compilation from circuits and code-owned components
to schedules and atom actions. To change a module, start with the artifact
its caller supplies and the result that caller consumes. The
[method guide](docs/methods.md) lists runnable entry points. The
[engineering guide](agent.md) defines how a change reaches human acceptance.

## Module ownership

| Owner | Input and decision | Output consumed downstream |
| --- | --- | --- |
| [Code library](modules/codes/README.md) | A code, distance, operation and participants determine the block geometry, component implementation, event ports and local protocol. A factory recipe specifies the roles and operations it needs. | Geometry for placement, component templates for binding, and recipes for the logical runtime. Cross-code interactions require an [explicit protocol](modules/codes/protocols/README.md). |
| [Logical compiler](modules/logical_compiler/README.md) | The frontend translates supported logical QASM using a selected code. A separate recipe entry places blocks, schedules ready component invocations and tracks ownership, results and retries. | The frontend returns a Logical DAG. The recipe runtime produces a factory case through its physical or fast backend. |
| [Physical compiler](modules/physical_compiler/README.md) | Native operations and dependencies, a Device, an entry layout and a strategy determine which gates can run together and how their atoms move. | A case-specific Atom IR program, timeline, result records and exit layout. The saved result can be replayed and validated. |
| [Experiment methods](docs/methods.md) | A method consumes a circuit, saved result, calibration profile or declared cost model. Its inputs determine which calculation or sampling procedure applies. | A method-specific artifact such as a histogram, fixed-schedule cost estimate or resource ledger. The receipt identifies the model and evidence for that result. |

## Circuit IR and physical compilation

The physical QASM frontend translates gates into the selected native basis
and builds a device-independent `PhysicalDAG`. It preserves source measurement
identities, conditions and dependencies. Geometry and timing enter when a
strategy maps the DAG to a Device and an entry state. An omitted strategy kind
selects Search Smarter. The nonzoned and bounded SMT backends have their own
admission rules. The SMT backend handles static circuits within its declared
coordinate and horizon bounds. [Frontend and IR](docs/decisions/0008-native-frontend-and-module-contracts.md) · [Compiler interface](docs/decisions/0032-unified-compiler-interface.md) · [SMT evidence](docs/decisions/0061-smt-evidence-integration.md)

The strategy groups gates, places their participants, plans transport batches
and emits AtomSteps. Device geometry, holder state, AOD capacity and motion
rules constrain each move. Source measurement references survive lowering.
The compiler resolves one measurement case using its result provider and
schedules conditional operations after the corresponding result is available.
Native controlled phase requires Device support and a compatible scheduler.
The emitted `CPhasePulse` carries the source angle.
[Device model](modules/physical_compiler/docs/device-and-zones.md) · [Case compilation](docs/decisions/0005-case-driven-physical-compilation.md) · [Native CPhase](docs/decisions/0062-native-controlled-phase.md)

The independent validator reconstructs timing and physical interactions from
the emitted actions and compares them with the source DAG and recorded case.
A saved `nadit.result/2` contains the inputs needed for this replay. The viewer
displays the recorded case. Physical validation establishes legality under the
configured Device and compiler model. [Result and validation contract](docs/decisions/0023-semantic-validation-and-self-contained-results.md)

## Small-circuit sampling

The ideal sampler accepts supported QASM or the serialized `PhysicalDAG`,
uses Born probabilities for each shot and follows the measured feedback bits.
The Small Shor L2 path for N=15 and N=21 compiles a fixed-slot schedule or
loads a saved result. It samples fresh measurements on that physical timeline,
uses reported bits for feedback and reports surviving-shot counts and losses.
These are separate outputs from the seeded case used during compilation.
[Inputs, commands and output-bit convention](experiments/small_circuit/README.md)

## Components, placement and factories

The logical frontend currently ends at the Logical DAG. Binding arbitrary
logical QASM to executable component invocations remains open. Factory
execution starts from a supported recipe. A code provider supplies block
footprints and component behavior. Placement returns a validated
`PlacementPlan` with block poses and a layout fingerprint. The scheduler
admits compatible ready work against shared resources. [Logical translation](modules/logical_compiler/docs/qasm-translation.md) · [Placement contract](modules/logical_compiler/docs/placement.md) · [Factory runtime](modules/logical_compiler/docs/factory-pipeline.md)

- **Physical factory.** The d3 adapter binds code-owned components to atoms in
  a shared device model. Inspect the emitted actions and their validation for
  the selected case. [Physical factory entry](modules/logical_compiler/examples/factory_array.py)
- **Fast factory.** The runtime consumes profile costs and declared event
  probabilities to estimate time, resource use and acceptance. The
  distance-parameterized surface entry requires matching recipe and profile
  coverage. The single-level center-distance study uses an explicit cost
  model with assumed acceptance. Each result carries the assumptions of its
  own path. [Profile-driven entry](modules/logical_compiler/examples/surface_factory_fast.py) · [Center-distance model](docs/experiments/single-level-fast-20261025.md)
- **Calibration reuse.** Compare the applicability key for the component and
  its declared surroundings. Adding a distant factory can preserve a local
  record. A joint action schedule depends on the actual shared frontier and
  Device. A cache miss identifies the calibration needed. [Factory-addition example](docs/calibration-reuse-guide.md) · [Component and joint scheduling](experiments/msd/COMPONENT_REUSE.md)
- **Two-level MSD.** Under synchronized consumption, the next supply round
  waits for the last L2 consumer in its cohort to finish consuming its input,
  including feedback and correction. AOD admission controls when transport
  can use the device. [Supply modes and hardware assumptions](experiments/msd/README.md)

## Scope of results

A retiming study keeps the saved schedule fixed while changing its timing
parameters. The Stim memory workflow decodes sampled Clifford-memory shots under
its Pauli and readout model and reports loss and leakage separately. General
leakage-to-erasure conversion with carrier replacement, state-aware noisy
full-factory simulation and decoded factory output quality remain open.
[Fixed-schedule retiming](experiments/se_tradeoff/README.md) · [Stim memory](modules/physical_compiler/docs/stim-memory.md)

When changing a boundary, follow one input into the owning module and inspect
one downstream artifact through a supported entry point. Keep detailed APIs
and command examples with their owner. [Design decisions](docs/decisions/)
record the rationale and historical scope of individual implementations.
