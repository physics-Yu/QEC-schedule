# Neutral-Atom Execution Refactor — R1 Acceptance

## Phase

R1 — freeze Steps 1–3 with invariant tests.

## Files changed

- `tests/test_surface_slot_parallelism.py`
- `docs/refactor_r1_acceptance.md`

## Architecture change

No production architecture was changed. The new tests make the upstream QEC
parallelism contract executable before the hardware execution refactor begins.

## Tests added

- The default rotated surface code has four interaction slots.
- Each slot contains six CZ interactions and six CNOT interactions.
- No interaction slot reuses a physical qubit.
- `PhysicalCircuitDAG` can expose all six interactions in each slot as READY
  together after their prerequisites complete.

## Tests passed

The full suite passes with `64` tests, including the two R1 tests.

## Demo command

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Observed output

```text
Ran 64 tests
OK
```

The invariant assertion is `slot sizes = [6, 6, 6, 6]` for both supported
primitive forms (`CZ` and `CNOT`).

## Acceptance criterion

R1 passes: QEC-level parallelism exists upstream of hardware lowering, with no
hardware changes required to expose the four disjoint six-interaction layers.

## Known simplifications

This phase intentionally does not change fixed hardware slots, lowering,
scheduling, trace schema, or visualization. Those are later refactor phases.

## Commit

Recorded in the R1 phase commit after the full suite passes.
