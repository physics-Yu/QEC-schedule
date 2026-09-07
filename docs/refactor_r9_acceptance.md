# Refactor R9 acceptance

`qec_schedule.simulation.run_cycle` now uses the refactored path:

```text
PhysicalCircuit -> SemanticRequestPlan -> RuntimeScheduler -> epoch trace
```

The default d=3 cycle emits 104 semantic requests.  Its epoch trace contains
four six-pair Rydberg epochs, one eight-atom imaging epoch, multi-atom AOD
movement, dynamic entangling residency, final valid home placement, resource
spans, decision diagnostics, and immutable state snapshots.

Trace validation, replay, metrics, animation, and timeline code are required
to consume this same epoch list.  The old action scheduler remains available
through `run_legacy_cycle` for migration callers, but is not the public cycle
path.

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_surface_cycle_parallel_execution -v
```
