# Patch and component scheduling

The common rule is **compatible code-owned execution declarations on disjoint
participants**, followed by space, resource and physical checks. Shared-AOD
lockstep calls require the same code, component, waveform and participant count.
Local pulse families use a separate `local_parallel` mode. The scheduler contains
no surface-code algebra or atom expander. Admission is not permission to skip the
physical validator.

## Interfaces

- `SurfaceFactoryBackend.describe_execution(...)` returns a code-owned
  `ComponentExecutionSpec` without binding, compiling or expanding a component.
- `ComponentScheduler.add(...)` retains explicit dependencies and adds ordering
  only for shared patches. Event/token readiness is separately published.
- `admit(now_us, snapshot_id=...)` returns an immutable selection. Shared
  participants, exclusive resource conflicts and intersecting closed space claims
  prevent batching. Shared AOD claims additionally require compatible row
  trajectories, disjoint column bands and aggregate column/readout capacity.
  Pairwise capacity checks alone are insufficient. A declared multi-patch member
  owns every participant; it is not treated as one synthetic patch.
- `PhysicalContext.invoke_batch(...)` consumes that selection and returns an
  actual `PhysicalBatch`. It preserves original sources and records their
  embedding into the combined action timeline. `batch_for(...)` provides this
  evidence to code-owned source-aware event models.

Shared transport composes equal action phases in lockstep. Members retain their
phase boundaries and durations. Gates are never stretched or split to hide
disagreement. Mismatches fail the transaction without committing a partial world,
binding update or result allocator. Each step contains one merged Load/Move/Store
per AOD, with reversible column-ID mappings and unchanged timing.

The current d3 declarations distinguish:

| Component family | Participants per member | Shared demand per member |
| --- | ---: | --- |
| SE/S/raw/initialization | One patch | 4 rows, 4 columns; up to 8 auxiliary readouts |
| MX or MZ | One patch | 3 rows, 3 columns; 9 data readouts |
| Corresponding horizontal CNOT | Ordered control/target pair | 3 rows, 3 columns; no readout |
| Local Pauli/canonicalization | One patch | Addressed local pulses; no AOD or measurement claim |

CNOT waveform identity includes signed relative displacement and physical
parameters. Both patches, the intervening transport envelope and complete
ordered entry/exit bindings are checked. Different directions or separations do
not share a waveform. Unsupported pairs and arbitrary joint operations remain
exclusive. MX and MZ have different waveform identities, with distinct global
result ranges and causal ready times for every member.

`local_parallel` permits different component names or correction classes within a
code-declared local pulse family. Actual Rotation/LocalU targets, angles, sources
and times remain unchanged. Different lane lengths are allowed only when their
pulse boundaries compose; shorter lanes keep their own exit time. Identity adds
no physical pulse or positive-duration padding. A full-world check still applies,
including to empty members' declared spaces. The wave finishes at its latest
member exit before further admission. Physical correction costs remain present;
no global software Pauli frame is introduced.

The shared AOD must be inactive at the wave entrance. Its actual row trajectories,
column spans, capacities and member actions are checked after expansion. This is
not arbitrary asynchronous use of one grid. Nonparticipating successful patches
remain in SLM; a retry wave activates only its failed members' column bands.
Several AODs remain configurable, but distinct AOD identities are not a condition
for same-component parallelism.

The surface backend uses relative reference implementations for admitted
translations. Pulses and transport remain within each declared envelope;
expansion still checks the entire atom world, including spectators. This is a
physical implementation condition, not the generic logical batching rule.

## Dynamic initial supply

Passing a `ComponentScheduler` to `FactoryExecutor` enables initial-preparation
frontier collection. W1 initialization and W2-W5 raw bodies have independent DAG
nodes. Ready correction work has priority; classical results may be released at
a safe completed-wave boundary after their recorded physical availability.

Each preparation keeps its semantic invocation and attempt number. A rejected
event releases only its carrier, adds its next attempt and executes the existing
raw component's Reset. Accepted resources are canonicalized and held. Future
same-patch consumers are submitted only after this local retry chain resolves.
T feedback gates its declared data and magic participants, including an empty
m0 branch. Whole-batch rejection explicitly gates every retry-work patch.

`FactoryExecutor` collects initial bodies into frontiers; its later calls retain
their recipe order. The separate `examples.factory_array` entry uses resumable
processes and one cooperative runtime to collect calls from all active lines at
each stage. Its cohort barriers preserve successful work while peers retry and
expose matching later CNOT, measurement and correction calls to admission. This
does not claim globally optimal or arbitrary asynchronous scheduling.

## Probability and accounting

Parallel raw event production verifies the participant action projection,
trajectory, measurement identities and actual clock against the committed batch.
For shared transport this includes the original member's portion of each fused
action and the reversible local-to-shared column mapping; members may share an
action index but cannot share atom ownership. The code-owned probability adapter
independently checks this evidence rather than treating the producer's claim as
proof of noise factorization.
It requires independent Pauli/rates noise and zero spectator-Pauli weights.
The code retains the joint acceptance/byproduct table and marks actual quantum
quality unsupported. An isolated projection's loss metadata is never relabeled
as the complete parallel world's loss.

Factory proxy cost excludes the **union** of complete raw attempt horizons. Each
original attempt and its batch identity is saved separately. The single-factory
proxy applies this exclusion to the whole world; the array proxy applies only a
line's own horizons to that line's actual atoms. Other patches within that scope
still lose their storage/operation contribution during excluded raw horizons.
Peer-retry waiting inside a line's evaluated window remains included.

The optional single-factory downstream proxy starts at acceptance and includes
output correction and algorithm T. The array output-hold entry has no such
downstream evaluation: each line's factory window ends at its final-check
evaluation, before later decision-barrier waiting, output correction and output
holding. Logical success remains null; no loss-replacement trajectory is simulated.

Static `case.json`, `experiment.json` and the physical trace retain the component
schedule, effective call/event dependencies, actual admissions, pending results,
retry epochs, S branches and unique resource consumption. `parallel_batches`
contains physical step/action mapping and validation evidence.
The array entry instead exports `array-ledger.json`, with per-line histories and
held outputs. See [ADR 0049](../../../docs/decisions/0049-component-parallel-admission.md)
for the current admission decision.

## Reproduce a same-device comparison

Use a physical Python environment containing the existing Clifford methods and
set `PYTHONPATH` to the intended physical source and this repository. The exact
imported runtime source files are hashed in every experiment.

```powershell
python -m modules.logical_compiler.examples.factory_parallel --config modules/logical_compiler/configs/factory_parallel_reference.json --noise-params modules/physical_compiler/cost_params/noise_illustrative.json --seed 12909 --output modules/logical_compiler/artifacts/factory-shared-aod-verified
```

The configuration explicitly selects code, AOD inventory/allocation and maximum
batch width. Its default is one AOD and up to four members. The command compiles
serial, parallel and a repeated parallel run;
all use the same Device, case identity and seed. It requires initial four-way
overlap, a real initial rejection, completed factory output/T consumption and
byte-identical parallel case replay. The embedded Device inventory and shared
batch mode are checked, and the HTML report displays the actual AOD count.
The seed is a disclosed branch witness,
not an unbiased sample for estimating success rate.

`index.html` compares startup component/patch lanes and links the two full atom
replays. `comparison.json` and `report.md` give startup and complete-case times,
counts and proxy outcomes. Each mode also retains the standard detailed ledger.
