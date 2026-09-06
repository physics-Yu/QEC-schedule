# Neutral-Atom Execution Refactor — R2 Acceptance

## Phase

R2 — dynamic zone geometry.

## Files changed

- `src/qec_schedule/hardware/zones.py`
- `src/qec_schedule/hardware/config.py`
- `src/qec_schedule/hardware/__init__.py`
- `src/qec_schedule/visualization/layout.py`
- `configs/hardware_default.yaml`
- `tests/test_dynamic_zone_geometry.py`
- `tests/test_hardware_model.py`
- `tests/test_layout_visualization.py`
- `docs/refactor_r2_acceptance.md`

## Architecture change

Entangling and measurement zones now expose validated dynamic working-region
capabilities. The default schema is version 2 and describes interaction lanes,
pair spacing/guard distance, dynamic atom capacity, imaging bounds, and batch
capacity. Memory and reservoir remain discrete trap-site zones.

Legacy `PairSlot` records remain in the default YAML only as a migration aid for
the pre-refactor lowering path. The new geometry model does not require pair
slots or measurement sites; the new planner will consume geometry directly.

## Tests added

- Six dynamic entangling pairs fit the configured capacity (`12` atoms).
- Eight ancillas fit the configured measurement/imaging capacity.
- Entangling and measurement zones can be constructed with no sites or slots.
- Geometry bounds, FOV containment, and capacity constraints are validated.
- Static layout renders dynamic lanes/FOV rather than reserved pair lines.

## Tests passed

The full suite passes with `68` tests.

## Demo command

```powershell
.\.venv\Scripts\python.exe examples\demo_hardware_layout.py --output-dir results\refactor_r2\layout
```

## Observed output

```text
entangling geometry: max_parallel_pairs=6, max_atoms=12
measurement geometry: max_parallel_atoms=8
Ran 68 tests
OK
```

## Acceptance criterion

R2 passes: the hardware configuration can represent six dynamically placed
pairs and eight dynamically placed measurement atoms without making fixed
destinations part of the geometry contract.

## Known simplifications

The legacy lowering/scheduler still exists during this migration phase and can
read legacy slots. It is replaced by semantic requests and runtime planning in
R3 and later; the new dynamic geometry is already available to those phases.

## Commit

Recorded in the R2 phase commit after the full suite passes.
