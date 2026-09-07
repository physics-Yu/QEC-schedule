# R11 acceptance: epoch timeline and metrics

R11 makes the execution report explicitly epoch-centric.  The runtime trace
publishes the same metrics consumed by `simulation.run_cycle`, and every
dispatch decision records ready requests, selected requests, successful batch
count, batch size, and structured rejection entries.

The report includes:

- cycle, movement, Rydberg, imaging, preparation/reset, and idle time;
- mean and maximum AOD batch size, Rydberg pair count, and imaging batch size;
- device utilization for AOD, local 1Q, Rydberg, imaging, and preparation;
- X/Y tone utilization plus entanglement and measurement occupancy;
- diagnostic counts derived from the scheduler's structured rejections.

The default d=3 cycle reports a maximum of 7 atoms per AOD epoch, 6 CZ pairs
per Rydberg epoch, and 8 atoms per imaging epoch.  The timeline renders shared
device custody above per-atom epoch participation, so overlapping bars expose
actual hardware concurrency from the trace rather than a second schedule.

Acceptance command:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_epoch_metrics -v
```
