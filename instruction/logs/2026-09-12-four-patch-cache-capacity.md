# 2026-09-12 — Bounded four-patch cache capacity mitigation

Read-only assessment while 4C attempt1 was running found a deterministic
sequential-scan cliff in `replay.trace._event_data`'s 4096-entry LRU. The 4B
baseline had 3658 trace records and never exercised that boundary. The copied
4C sample had 1784 records; a smaller 512-entry cache demonstrated the same
cyclic topology with zero second-scan hits. Actual 4096-cache warm scan took
0.001 s while the scaled overflowing scan took 1.02 s. Later live checkpoint
version was 2680 with 736/1868 slots, making the existing limit a serious
remaining-run performance risk. No physical failure was observed or inferred.

Root made the controlled-stop/restart decision and owns the attempt ledger.
This subtask did not interrupt the worker. Assessment evidence and caveats are
in `artifacts/qec-roadmap/snapshot-cache-assessment/assessment.md`, with both
microbenchmark scripts/results and the one copied checkpoint.

After explicit root coordination lifted the freeze, changed only:

- `replay/trace.py`: parser LRU capacity 4096 → 8192 entries.
- `replay/snapshot_encoding.py`: default encoded-trace prefix budget
  256 → 768 MiB. Allocation remains lazy and actual byte accounting unchanged.

No canonical serializer, checkpoint field, hash bytes, RNG/readout behavior,
physical model or validation was changed. Compressed cache alternatives and
different history access APIs remain unimplemented. This is a bounded policy
for the declared four-patch run on the 16 GiB host, not a universal history-cache
solution: event count must stay below 8192 to avoid the same LRU access-pattern
boundary, and memory must be monitored. The encoding cache remains independently
limited by bytes and 16384 entries; overflow is correct but may be slower.

Command:

```text
C:/python312/python.exe -m pytest -q -p no:faulthandler --basetemp=artifacts/qec-roadmap/cache-limits-tests tests/test_trace_event_cache.py tests/test_snapshot_encoding.py tests/test_readout_flip.py tests/test_quantum_readout.py tests/test_batch_raman.py
```

Result: **67 passed in 12.61 s**, no failures/skips. New tests cover 4097 exact
raw records with three subsequent full scans and no extra misses; cached deep
immutability; distinct raw strings with identical event values; and lazy byte
budgets. Old formal schema19 baseline and 4B checkpoints still restore and match
original canonical strings and SHA256.

Bounded copied-4C checkpoint benchmark:

```text
C:/python312/python.exe examples/benchmark_snapshot_encoding.py --checkpoint artifacts/qec-roadmap/snapshot-cache-assessment/copied-checkpoint.json --output artifacts/qec-roadmap/cache-limits-benchmark/result.json
```

PASS: 132,556,536 bytes, 1784 records; unchanged SHA256
`345b45b3aff08329688eb80943f412160212715e836d4877f1b777261fba7d18`.
Restore with existing audits 4.2875 s; reference canonical 0.8522 s; cold snapshot
0.7718 s; warm snapshot 0.1085 s; complete warm stream hash 0.3937 s. Actual
encoded-cache accounting is 236,222,246 bytes under 805,306,368 bytes maximum.
This sample already fit the old limit; timing differences from older samples
are not attributed to the capacity change. No full compiler was run by this
subtask. Root owns 4C attempt2, its verification/UI and shared handoff updates.

Source changes frozen and handed to root immediately after these checks passed.
