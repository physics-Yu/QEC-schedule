# Neutral-Atom Execution Refactor — R3 Acceptance

## Phase

R3 — semantic request layer.

## Files changed

- `src/qec_schedule/compiler/semantic_requests.py`
- `src/qec_schedule/compiler/__init__.py`
- `src/qec_schedule/lowering/gate_lowering.py`
- `src/qec_schedule/lowering/__init__.py`
- `src/qec_schedule/simulation.py`
- compatibility examples/tests renamed to `LegacyGateLowerer`
- `tests/test_semantic_requests.py`
- `docs/refactor_r3_acceptance.md`

## Architecture change

`GateLowerer` now emits immutable `SemanticRequestPlan` records. A request
contains only the physical gate identity, atom handles, dependencies, and
semantic operation data. It does not contain pair slots, measurement sites,
coordinates, or movement actions. Runtime-state lookup is read-only and only
translates qubit handles to atom IDs.

The old destination-based implementation remains available under the explicit
name `LegacyGateLowerer` solely while later scheduler phases migrate.

## Tests added

- One d=3 round emits 24 `EntangleRequest` values and one request per physical gate.
- Measurement, preparation, reset, and single-qubit request types are preserved.
- Serialized requests contain no compile-time placement or transport fields.
- Physical dependencies and state immutability are preserved.

## Tests passed

The full suite passes with `72` tests.

## Demo command

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Observed output

```text
EntangleRequest count = 24
Ran 72 tests
OK
```

## Acceptance criterion

R3 passes: physical gates can be lowered into semantic requests without
choosing a pair slot, measurement site, target coordinate, or transport action.

## Known simplifications

The legacy action IR is still exercised by explicitly named migration tests;
R4–R8 replace its use in the runtime path with dynamic placement and epochs.

## Commit

Recorded in the R3 phase commit after the full suite passes.
