# Neutral-Atom Execution Refactor — R6 Acceptance

## Phase

R6 — epoch-level hardware operations.

## Files changed

- `src/qec_schedule/execution/__init__.py`
- `src/qec_schedule/execution/epoch.py`
- `tests/test_aod_epoch.py`
- `tests/test_rydberg_epoch.py`
- `tests/test_imaging_epoch.py`
- `docs/refactor_r6_acceptance.md`

## Architecture change

The execution layer now has an epoch IR. AOD movement, Rydberg interaction,
and imaging are represented as multi-atom epochs with one shared device
requirement and one per-atom lock for the whole epoch. Specialized payloads
retain AOD programs, pair placements, measurement placements, and keys.

## Tests added

- AOD epochs carry one `device/aod` requirement plus atom locks.
- Six disjoint entanglement requests become one `RydbergEpoch`.
- Eight measurement requests become one `ImagingEpoch`.
- Epoch payloads round-trip through JSON-compatible dictionaries.

## Tests passed

The full suite passes with `87` tests.

## Demo command

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Observed output

```text
6 requests -> 1 RydbergEpoch
8 requests -> 1 ImagingEpoch
Ran 87 tests
OK
```

## Acceptance criterion

R6 passes: shared devices are acquired at epoch granularity and batches retain
atom-level detail without creating one device action per atom or pair.

## Known simplifications

Epoch construction is currently invoked directly by tests/planning helpers;
the event-driven RESST integration and runtime state updates are implemented in
R7–R9.

## Commit

Recorded in the R6 phase commit after the full suite passes.
