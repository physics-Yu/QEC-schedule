# MSD experiment interface audit

Status: source inspection on 2026-10-24. The initial external-interface audit was
read-only; subsequent local adapter checks are described below.
The experiment baseline is `8edea9a1ab55e00fceb71325a8001444a09397fb`.
The separately active logical compiler checkout was inspected read-only at
`C:/Users/yuyqp/.codex/worktrees/logical-qasm-frontend/NADiT`, with committed HEAD
`5160fe37d3bf47193d6e6899065b6522f3edc337` and additional uncommitted component
admission changes. These working files are evidence of an interface under
development, not an accepted dependency of the experiment baseline.

## Existing component and physical seams

| Responsibility | Existing entry and contract |
| --- | --- |
| Physical lowering | `modules/physical_compiler/src/nadit_physical_compiler/compiler.py:compile_physical(dag, device, strategy=..., entry_state=...)` returns `CompilationResult`. |
| Code-owned templates | `modules/codes/_support/atom_template.py:compile_template` uses `NonZonedStrategy`, explicit home sites, physical validation and immutable relative actions. |
| Invocation binding | `modules/codes/contracts/component.py:ComponentBinding(block_id, origin, atom_ids, aod_id, site_ids=())`; `InvocationContext(invocation_id, start_us, result_id_base, device, world_state)` includes the complete occupied world. |
| Expansion | `ComponentTemplate.bind(binding).expand(context)` returns `ComponentExpansion`, including Atom IR, exit world/bindings, result identities and availability. `action_end_us` and `results_ready_us` are distinct. |
| Existing factory cache | `modules/codes/rotated_surface_d3/protocols/factory_backend.py:SurfaceFactoryBackend(device).bind_call(component_id, participant_bindings, parameters=())` caches single, raw, CNOT and correction templates for that concrete device. |
| Real logical S | `modules/codes/rotated_surface_d3/components/phase.py:PhaseComponent`; retain this implemented S/SE construction, not a transversal-S timing substitution. |

Templates already avoid recompilation during expansion. They still validate a
binding against the full world; their timing profile includes transfer, gate,
readout and result-latency values. A template compiled before the timing change
cannot silently be reused afterward. Geometry, spectators, AOD availability,
participant exits and measurement identities remain invocation-specific.

## Timing and geometry configuration

The baseline reference is
`modules/codes/rotated_surface_d3/configs/nonzoned_cnot_reference.json`.
Its `shared/v1` architecture document supplies the following concrete paths:

| Parameter path | Baseline | Experiment override |
| --- | ---: | ---: |
| `params.measurement.readout.duration_us` | 10 | 100 |
| `params.measurement.readout.latency_us` | 500 | 0 |
| `params.timing.load_us` | 10 | 100 |
| `params.timing.store_us` | 10 | 100 |
| `params.cz.duration_us` | 0.5 | unchanged |
| `params.local.rotation_us` | 1 | unchanged |
| `params.local.reset_us` | 5 | unchanged |
| `params.timing.move_us_per_um` | 1 | unchanged |

The confirmed Cartesian layout is readout at `y >= 50 um`, nonzoned storage/gates
at `y <= 0`, and a 50-micrometer intervening gap, with factory index increasing
downward. `device.py:Region` currently requires finite bounds. The implementation
must therefore distinguish the unlimited-area experimental policy from a finite
compilation window enclosing all requested sites and trajectories, or explicitly
extend that public geometry contract. No literal JSON Infinity is supported.
Measure occupied layout/trajectory footprint separately from provisioned region
area; unbounded region area is not a useful resource-cost denominator.

## Active logical compiler integration boundary

The inspected external working source contains:

- `examples/factory_array.py:load_configuration(document)` with schema
  `nadit.factory_array_configuration/1`. Exact top-level keys are `schema`, `code`,
  `world`, `limits`, `max_parallel`, and `coordination_policy`. It currently requires
  `code = rotated_surface_d3` and `coordination_policy = cohort_stage_barriers`.
- `examples/factory_array.py:run_array(seed, noise_params, output, *, configuration,
  sampling_role="individual_seed")`. It constructs one `PhysicalContext`, one
  `ComponentScheduler`, and `FactoryProcess` instances under
  `CooperativeFactoryRuntime`. The example hardcodes `distance=3`.
- `src/protocols/physical.py:PhysicalContext(device, entry_world, bindings)` owns
  the only clock, current world, result allocator and committed actions. Reuse
  this ownership boundary when the fast interface becomes available.
- `src/protocols/cost.py:evaluate_physical_cost(bundle, noise_params)` adapts a
  validated `PhysicalBundle` with unobserved physical measurements to `noise/v1`.
  Participant/time-restricted evaluation is in `participant_cost.py` and
  `evaluate_physical_cost_intervals`; it is not a logical-error estimator.

The active entry always exports the complete case, Atom IR, replay, HTML ledger
and proxy evidence. No statistics-only lowering API was found in the inspected
source. A fast backend is a pending external dependency, not delivered by this
audit. Do not replace it with an independent scheduling or probability engine.

The current `FactoryArrayConfig` generates horizontal six-patch factory tiles,
all at the same y origin. `protocols/parallel.py:supports_local_profile` requires
`binding.origin.y == reference.y`; its readout strip is tied to `origin.y + 90`.
Shared claims encode the row origin, and
`src/scheduling/compatibility.py:_shared_capacity` requires matching row
trajectories and disjoint column envelopes. Consequently, a vertical array with
a common upper readout half-plane is not admitted as equivalent by that profile.
Serial fallback is possible; shared-AOD vertical admission requires an explicit
new supported geometry/profile and validation. Infinite area does not imply
infinite AOD rows, columns, readout throughput, or simultaneous control capacity.

## Metrics and reproducible execution to reuse

- `metrics.py:program_metrics(program, duration_us=...)` and `collect_metrics`
  provide duration, action counts, CZ pairs/pulse, transfer counts and load sizes.
  `transport_duration_us` sums Load/Move/Store action durations including parallel
  actions; it is not elapsed transport time. `max_parallel_atoms` is the largest
  individual Move target count, not a count of all simultaneous hardware work.
- `activity.py:derive_activity(document)` derives complete per-atom busy/idle
  intervals, movement distances, action exposure and actual pulse coverage.
  `cost.prepare(document)` is the validated entry for a serialized physical result;
  `cost.model_for(...).evaluate(activity, document, params)` reuses that activity.
- `experiments/spec.py:load_spec` and `runner.py:run_experiment` already provide
  snapshotted configuration, content-based IDs, enforced per-cell timeouts,
  resumable JSONL, source-change checks and worker thread limits. The existing
  worker accepts physical QASM jobs; a component/factory adapter is needed.
- `experiments/costs.py:evaluate_models` shares activity across models;
  `reevaluate` reuses retained results. `store="none"` avoids retained successful
  result files but still performs full compilation, validation and serialization.

Use full validated representative component/schedule witnesses to qualify
compact parameter records. Record source, device, code-distance, component,
layout, scheduling-policy and cost-model identities in any cache key. Startup,
steady-state accepted-output throughput, retry amortization and two-level
buffering require production-event evidence; component duration sums alone do
not establish those quantities.

## External source fingerprints

SHA-256 values below freeze the inspected working files independently of the
external checkout's dirty HEAD. Paths are relative to that checkout.

| Path | SHA-256 |
| --- | --- |
| `modules/logical_compiler/examples/factory_array.py` | `2e2e94af53716a6396d3757385e35ae84a7433ddebd7adcd520b94d4f98b1a7d` |
| `modules/codes/rotated_surface_d3/protocols/factory_array.py` | `f9fb9d6096d9d756daad093ae78dddfd78d04c58c563a52c9347d30c0621eee3` |
| `modules/codes/rotated_surface_d3/protocols/parallel.py` | `1c015c598bc2f197ae2f0450ddeeb1250bcd327d21be9b8e5c9b5d95f6c7e26c` |
| `modules/logical_compiler/src/scheduling/compatibility.py` | `8b031805ed6281f4157c448d405e25eb278d9aa434bc3b409095c9555caf9113` |
| `modules/logical_compiler/src/protocols/parallel_physical.py` | `3ce27d20fe6ef211a5a011099d849f4af65dd0c1bccc021e6150f554127e40be` |

Open integration work: distance-selected factory backend, vertical/common-readout
parallel profile, the external compact-output API, sustained multi-batch
production, and two-level handoff. These are separate from the checked geometry
and component-generation work of the present experiment task.

## Local adapter added by this task

`experiments/msd/standard.py:build_world(ExperimentSpec(distance, pipelines))`
constructs the complete vertical world using the new
`modules.codes.rotated_surface` definitions. `calibrate.py:calibrate` lowers one
explicitly allowed component with all factory atoms present, validates the
result, and returns a compact metrics record plus its complete physical witness.
This saves a compact record; it still performs complete physical lowering.

The source-only calibration allowlist deliberately excludes `logical_h`: its
full component also rotates the physical carriers, which is not expressed by
its QASM source alone. The complete H template must be used to measure H cost.
No preparation or S timing shortcut is substituted.

`calibrate.py:source_snapshot` fingerprints local compiler, code and experiment
Python sources plus the actual reference-device JSON. It rejects importing the
physical compiler from another checkout. `survey.py` records this identity,
checks it before and after each child and before final export, and applies
explicit atom and host-time budgets. Model execution time and host compilation
time remain separate fields. Failed or limited cells remain in the journal.

`plot.py` reads the saved representative world rather than rebuilding it with a
possibly newer generator. Its figures describe component calibration and layout;
they do not claim production throughput or output-error scaling.

Independent hand-built accounting fixtures check overlapping transport intervals,
feedback tails, spectator atom-time and trajectory footprint. Source-identity
regressions cover reference JSON changes and a compiler imported from the wrong
checkout. CLI regressions reject nonfinite budgets, repeated cells and unsupported
H calibration, and ensure a last-child source change cannot produce a completed
summary. A synthetic plotting smoke check was rendered and visually inspected;
its values are not experiment results. Concrete benchmark outcomes belong in the
campaign artifacts and acceptance report, not this interface audit.
