# Neutral-Atom Execution Refactor — R4 Acceptance

## Phase

R4 — deterministic spatial placement.

## Files changed

- `src/qec_schedule/planner/__init__.py`
- `src/qec_schedule/planner/spatial_planner.py`
- `tests/test_entanglement_placement.py`
- `tests/test_measurement_placement.py`
- `docs/refactor_r4_acceptance.md`

## Architecture change

`SpatialPlanner` now consumes semantic request batches and a read-only
`HardwareState` snapshot. Entanglement placement uses a configured interaction
lane, exact pair distance, inter-pair guard distance, bounds, and capacity.
Measurement placement uses a deterministic row-major grid inside the imaging
FOV. Neither planner reads fixed pair slots or measurement trap sites.

## Tests added

- A six-pair d=3 interaction batch is placed deterministically in bounds.
- Pair distance, guard distance, and minimum spacing are checked.
- Six-pair placement succeeds with all legacy pair slots removed.
- Eight measurements are packed in the imaging FOV.
- Geometry capacity failures return `PlacementError` diagnostics.

## Tests passed

The full suite passes with `77` tests.

## Demo command

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Observed output

```text
six-pair placement: valid
eight-atom imaging placement: valid
Ran 77 tests
OK
```

## Acceptance criterion

R4 passes: a six-pair batch and an eight-atom measurement batch are generated
from dynamic geometry, with explicit validation and no fixed destination
dependency.

## Known simplifications

The first planner uses one configured lane and a row-major imaging grid. It does
not yet perform multi-lane search, obstacle avoidance, or continuous optimal
control. A unified feasibility oracle and scheduler integration follow.

## Commit

Recorded in the R4 phase commit after the full suite passes.
