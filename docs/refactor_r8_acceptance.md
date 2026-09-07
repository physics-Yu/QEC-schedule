# Refactor R8 acceptance

R8 makes dynamic zone residency part of the runtime state.  A completed
`RydbergEpoch` leaves its atoms in the entangling region.  Before the next
layer, the scheduler retires only residents not required by the selected
batch; after the last layer it returns data to storage and sends ancillas to
measurement.  Final cleanup returns the measured/reset ancillas to their home
sites.

The acceptance trace shows four six-pair interaction epochs, with at least ten
entangling residents after each layer.  There is no per-CZ return-home stage.
The only return stages are lifecycle-level `RETURN_DATA` and `FINAL_RETURN`.

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_resident_atom_execution -v
```
