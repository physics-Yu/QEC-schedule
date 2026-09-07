# R12 acceptance: resource parameter sweep

The sweep now accepts the resource controls named in the refactor contract:

- AOD X/Y tone budgets, X/Y speed, and axis execution mode;
- entanglement maximum atoms, maximum parallel pairs, pair distance guard,
  and interaction geometry parameters;
- measurement maximum parallel atoms and field of view;
- the runtime Rydberg parallel-pair limit.

The default hardware configuration leaves the entanglement geometry's
`max_parallel_pairs` and `max_atoms`, and the measurement geometry's
`max_parallel_atoms`, unset (`null`).  The explicit 12-atom entangling and
8-atom measurement zone capacities remain as physical occupancy safety limits.

Each row records the effective configuration, epoch-centric timing and
concurrency metrics, device/tone/working-zone utilization, and structured
diagnostic counts.  Each case also writes its complete trace and metrics JSON,
so the sweep is a resource-estimation report rather than only a wall-clock
benchmark.

The default experiments demonstrate predictable degradation.  With the
default d=3 configuration the observed baseline is 30 AOD epochs, 4 Rydberg
epochs of 6 pairs, and 1 imaging epoch of 8 atoms.  Limiting AOD to one tone
per axis increases movement to 67 epochs; limiting Rydberg or entanglement to
three pairs produces 8 Rydberg epochs; limiting imaging to four atoms produces
2 imaging epochs.

Acceptance command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_parameter_sweep -v
```
