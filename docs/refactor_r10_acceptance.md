# Refactor R10 acceptance

Animation and timeline rendering now consume the epoch-centric trace directly.
The browser player interpolates AOD source/target positions, draws every active
Rydberg pair in a batch, highlights imaging epochs, and exposes active devices,
tone counts, pair counts, ready requests, and zone occupancy.  The Matplotlib
adapter and timeline use the same `epochs` records and timestamps.

The visualizer intentionally remains trace-only: it does not call the scheduler
or produce a second layout/schedule.  AOD paths are endpoint-interpolated and
the configured conservative ordering rule remains visible in the trace model.

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_epoch_visualization -v
```
