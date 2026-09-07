# Refactor R7 acceptance

R7 integrates semantic requests, deterministic batch construction, a unified
hardware feasibility oracle, epoch-level resource locks, and an event-driven
runtime scheduler.  The legacy action scheduler remains available during the
migration; the new entry point is `qec_schedule.scheduler.RuntimeScheduler`.

## Default d=3 result

```text
requests: 104
Rydberg epochs: 4
Rydberg pairs per epoch: [6, 6, 6, 6]
Imaging epochs: 1 (8 atoms)
multi-atom AOD epochs: present
final mapped atoms: 17 in storage; 4 reservoir atoms retained
```

The runtime keeps atoms in the entangling region between interaction layers.
It retires only the residents that are not required by the next selected
batch, and returns data/ancillas at the lifecycle boundary.  AOD ordering is
still conservatively enforced by `ordering_rule=preserve_order`; incompatible
movement sets are split greedily into smaller multi-atom epochs.

## Resource degradation

```text
rydberg_parallel_pairs=3 -> 8 Rydberg epochs of 3 pairs
measurement max_parallel_atoms=4 -> 2 imaging epochs of 4 atoms
```

The scheduler records every rejected candidate as `{family, request_ids,
reason, diagnostics}`.  A zero-capacity entangling region produces a
`RuntimeSchedulingError(reason="DEADLOCK", ...)` with the `ZONE_CAPACITY`
rejections still attached.

## Verification

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The R7 tests are `test_scheduler_max_feasible_batch.py`,
`test_scheduler_resource_degradation.py`, and
`test_scheduler_deadlock_diagnostics.py`.
