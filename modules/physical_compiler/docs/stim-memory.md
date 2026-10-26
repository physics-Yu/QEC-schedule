# Atom-action Stim method and surface memory

`stim/v1` is a NADiT result method. It consumes a validated `nadit.result/2`, calls
`noise/v1` once with explicit noise parameters, and produces a Stim circuit plus
`nadit.stim/1` metadata. It is independent of the physical compiler. Inspect its
contract with `nadit describe` under `methods`.

Install from this module directory:

```powershell
uv sync --locked --extra simulation
```

The optional extra pins Stim 1.16.0 and PyMatching 2.3.1. Ordinary compilation,
cost evaluation and viewing do not import these packages.

## Translate a saved result

```powershell
uv run --locked --extra simulation nadit method stim/v1 result.json --params cost_params/noise_illustrative.json --annotations annotations.json -o memory.stim
```

This writes `memory.stim` and `memory.json`. Use `--report` to change the report
path. Neither operation compiles QASM or samples FakeBackend results. Omitted
`--params` selects the zero-noise defaults; existing attached cost reports are
not selected implicitly. Parameters use the existing `noise/v1` schema.

Python API:

```python
from nadit_physical_compiler.methods import run_method
from nadit_physical_compiler.methods.memory import sample_memory

exported = run_method(
    "stim/v1", result_document,
    noise_params=noise_parameters,
    annotations=measurement_annotations,
)
stats = sample_memory(exported, shots=1000, seed=17)
```

`StimExport.circuit` is the circuit text. `StimExport.report` includes result and
circuit hashes, AtomStep times, atom-to-wire and measurement-to-record mappings,
the complete noise report, annotations and simulation scope. Probabilities are
serialized with binary64 round-trip precision.

## Translation semantics

| Atom action / effect | Stim representation |
| --- | --- |
| Clifford Rotation / GlobalRY / LocalU | Equivalent Clifford operations, ignoring global phase |
| CZPulse | CZ on the actual illuminated interaction pairs established by semantic validation |
| Reset | R, then configured reset error |
| Measure | M with its own readout-flip probability; records identified by source measurement ID |
| Load / Move / Store | No ideal quantum gate; configured Pauli channel after completion |
| Idle / selected transfer exposure | Z_ERROR from the measured duration and configured T2 |
| AtomStep | One TICK after the step; TICK itself has no duration |
| Physical loss / leakage | Separate report; no automatic Pauli or heralded-erasure substitution |

`transport.load_pauli`, `store_pauli` and `move_pauli` are `[pX,pY,pZ]`, defaulting
to zero. Existing transfer-loss probabilities and lifetime hazards stay separate.
Gate-model channels retain their before/after placement. Distinct-duration actions
are ordered at their own completion; idle channels end before the next operation
on the same atom. Tail exposure through final measurement availability is retained.
Moving an atom never changes its Stim wire.

The geometry-only entry layout contains no quantum state. A standalone export
uses Stim's initial all-zero state; memory workloads explicitly prepare/reset
their data and ancillas. Exporting a component does not recover an unknown or
entangled state inherited from a previous component.

General non-Clifford gates are rejected. Conditional DAGs are rejected by default:
the physical result contains one preselected branch, not a dynamic program.
`--allow-fixed-case` exports that branch explicitly. Memory sampling rejects such
exports; fake bits are never inserted as Stim measurement outcomes.

## Detector annotations

Atom actions do not determine which checks define a code's logical memory.
The workload supplies `nadit.stim.annotations/1` with:

- `qasm_sha256`: exact source file bytes used by the physical frontend;
- `measurement_ids`: all source measurement IDs;
- `detectors`: parity records with `measurement_ids` and optional `coordinates`;
- `observables`: parity records with `measurement_ids` and logical `index`;
- optional `workload`: identifying metadata.

The translator maps identities to the actual compiled measurement order. It emits
DETECTOR and OBSERVABLE_INCLUDE after all measurements with the corresponding
negative `rec` offsets. Detector time coordinates preserve the workload's round
index; physical timing remains separately available in the export report.

## Prepare a standard single-block workload

```powershell
uv run --locked --extra simulation nadit memory prepare --distance 3 --basis z -o artifacts/memory-d3-z
```

Supported distances are 3, 5, 7 and 9; rounds default to distance. `--rounds`
overrides the round count and `--basis x` selects X memory. The command creates:

- `reference.stim`: noiseless standard rotated-memory circuit from pinned Stim;
- `circuit.qasm3`: the corresponding physical circuit, preserving layer barriers;
- `annotations.json`: source-bound detector and final logical-readout parities;
- `nonzoned.job.json`: explicit standard homes and existing ENOLA-inspired routing;
- `qec.job.json`: the same standard home coordinates and Search Smarter QEC return.

The benchmark includes preparation, d SE rounds and final data readout. It uses
`2*d*d-1` atoms and `d*(d*d-1)+d*d` measurements when rounds=d. The code's standard
coordinates are scaled uniformly; no initial-placement optimizer is run.
This is a benchmark generator, not an implementation of the code-library or
logical-compiler component interfaces.

Both jobs use flexible unbounded-capacity AOD, 2 um gate-pair separation, 4.6 um CZ
radius and 8 um home-coordinate pitch. The QEC gate array has 6 um row spacing.
`--pitch-um` controls home pitch (must exceed 6.6 um for isolated shared cells).
Job files contain the complete editable Device architecture and strategy options.
These are software-test defaults, not a calibrated experimental device or a claim
that the two architectures are hardware-equivalent.

## Compile once, evaluate and sample

```powershell
uv run --locked --extra simulation nadit compile artifacts/memory-d3-z/nonzoned.job.json --validate -o artifacts/memory-d3-z/result.json
uv run --locked --extra simulation nadit method stim/v1 artifacts/memory-d3-z/result.json --annotations artifacts/memory-d3-z/annotations.json --params cost_params/noise_illustrative.json -o artifacts/memory-d3-z/memory.stim
uv run --locked --extra simulation nadit memory sample artifacts/memory-d3-z/memory.json --shots 1000 --seed 17 -o artifacts/memory-d3-z/samples.json
```

Replace the job with `qec.job.json` for the other backend and use distinct output
names. Changing noise parameters requires translation again, not recompilation.
Changing shot count or seed requires sampling only. Moving the circuit and export
JSON together preserves their relative link.

Sampling returns shots, failures, logical failure rate, a Wilson 95% interval,
detector-event count, decoder/package versions, workload and result/noise hashes.
It compares MWPM predictions against sampled logical observable flips; raw logical
flips alone are not counted as decoder failures. Memory sampling is batched, with
batch size and seed recorded for reproducibility on the same software/platform.

Stim samples the Pauli channels as specified. Decoder construction uses
`decompose_errors=True, approximate_disjoint_errors=True`: mutually exclusive
Pauli branches are approximated as independent DEM mechanisms for decoder weights.
Undecomposable faults cause an error instead of being dropped.

The reported logical rate covers **Pauli/readout noise only**. The export retains
physical loss, computational leakage and native upstream records, but these are
not propagated through this memory simulator. A zero-failure sample is not a zero
logical-error estimate; inspect its confidence interval.

## Verification scope

Run `uv run --locked --extra simulation pytest -q tests_simulation` for generated
inputs, exact channel/order checks, CLI round trips and d3 compiled X/Z memory on
both backends. Run the physical compiler suite for shared-interface changes.
The full d3/d5/d7/d9 statistical experiment campaign is a separate task.

Verification on 2026-10-23: 1,807 tests passed (1,759 existing core tests,
31 simulation tests and 17 optional hsim tests). Ruff checks and strict mypy
passed for source/tests/examples. A built wheel, installed into an isolated
directory and invoked outside the checkout, completed both d3 Z-memory CLI
pipelines with 512 shots each. Each exported 17 wires, 33 measurements,
24 detectors and one logical observable. These are functional checks, not
a statistical comparison or a completed distance scan.
