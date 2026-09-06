# Neutral-Atom Execution Refactor — R5 Acceptance

## Phase

R5 — explicit AOD program planning.

## Files changed

- `src/qec_schedule/hardware/aod.py`
- `src/qec_schedule/hardware/config.py`
- `src/qec_schedule/hardware/__init__.py`
- `src/qec_schedule/lowering/movement_planner.py` (explicit legacy adapter)
- `src/qec_schedule/lowering/__init__.py`
- `configs/hardware_default.yaml`
- `tests/test_aod_multi_atom_parallelism.py`
- `tests/test_aod_axis_trajectory.py`
- `tests/test_aod_tone_budget.py`
- `tests/test_aod_compatibility.py`
- `docs/refactor_r5_acceptance.md`

## Architecture change

The runtime AOD model now constructs explicit x/y tone bindings and axis
trajectories. Feasibility checks cover bounds, duplicate atoms/endpoints, tone
budgets, tone spacing, ordering, and configurable axis execution. Movement
duration follows the simultaneous or sequential axis formulas from the spec.

The equal-displacement predicate is available only as
`legacy_compatible` for the named migration planner. New `AODPlanner` calls
`build_program` and accepts distinct 2-D displacement vectors.

## Tests added

- Twelve movements with unequal vectors fit one program under 12/12 tone budgets.
- Simultaneous, x-then-y, and y-then-x timing is verified.
- X and Y tone budgets fail independently.
- Crossing/order constraints reject only the conservative ordering case.

## Tests passed

The full suite passes with `83` tests.

## Demo command

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Observed output

```text
12 unequal-vector movements -> 1 AODProgram
Ran 83 tests
OK
```

## Acceptance criterion

R5 passes: multi-atom AOD feasibility is represented by explicit x/y programs,
not equal 2-D displacement vectors, with deterministic diagnostics and speed-
based duration.

## Known simplifications

Tone IDs are deterministic logical controller channels, and crossing is
conservatively modeled by preserving source-axis order. No acoustic waveform or
continuous collision optimization is simulated.

## Commit

Recorded in the R5 phase commit after the full suite passes.
