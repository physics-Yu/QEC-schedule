# Exact checkpoint encoding cache

This is an engineering optimization of schema19 snapshot encoding. It changes
neither the checkpoint fields/shape nor the SHA256 input bytes. It does not
change physical validation, scheduling, quantum projection, reported readout,
RNG consumption, or restored-state audit rules.

`SimulationState.snapshot_data()` freshly reads every snapshot field and builds
current metrics on each call. `snapshot()` encodes that payload.
`motion.compiler.fingerprint()` streams the same complete canonical fragments
into SHA256, avoiding allocation of one combined UTF-8 checkpoint. The unchanged
`replay.serializer.canonical_json()` remains the independent reference.

The specialized encoder emits sorted top-level keys structurally. All non-trace
values use the original canonical serializer. The trace remains a JSON array
of **escaped JSON string literals**, exactly as before; it is not an array of
raw event objects. There is no sentinel replacement or abbreviated hash.

Only an exact `tuple` containing exact immutable `str` entries enters the
cache. One active prefix stores original strings and their canonical string
literals. Every call compares the prefix, truncates at the first differing
entry, then encodes new records. Appending, shortening, restoring an older
branch, replacing a history and sharing equal immutable records are safe.
Other trace shapes use the reference encoder. A lock protects cache updates;
encoded fragments returned to each caller are immutable.

The retained prefix has two limits: 1536 MiB and 16384 records. The byte counter
conservatively includes both retained strings, entry tuples, integer sizes and
list allocation shares. It excludes small fixed cache/lock overhead. Records
beyond either limit are encoded without retention; encountering a divergent
branch releases the prior suffix. No full trace tuple or state object is kept
alive by this cache. This bounds persistent cache data, **not** total working
memory: the live state, fresh non-trace serialization and requested complete
snapshot string still require memory. The cache can be cleared explicitly.

Caching a complete state by `(id, version)` would be incorrect: scheduling can
change its event queue without incrementing the committed-event version, and
pure predicted states may share versions. No such cache is used. Frozen outer
dataclasses are not assumed to make arbitrary nested objects immutable.

## Verification and measured scope

Command:

```text
C:/python312/python.exe -m pytest -q tests/test_snapshot_encoding.py tests/test_readout_flip.py tests/test_quantum_readout.py tests/test_batch_raman.py
```

Result: **64 passed in 19.61 s**. The new seven tests cover Unicode/quotes/control
characters, numeric representation, fallback values, append/fork/replacement,
byte/entry limits, mutable non-trace data, scheduling at unchanged version,
RNG/measurement/SLM changes and restoration. Both saved formal schema19
checkpoints were restored using existing audits and checked against the original
canonical string and SHA256: the historical 29,104,811-byte GHZ2 baseline and
the 132,888,888-byte 4B checkpoint. After tightening conservative cache accounting
and strengthening the valid SLM-state fixture, the five small tests passed again
(0.20 s); the final core source is also exercised by the benchmark below.

```text
C:/python312/python.exe examples/benchmark_snapshot_encoding.py --checkpoint artifacts/qec-roadmap/step4B-attempt1/checkpoint.json --output artifacts/qec-roadmap/snapshot-cache-benchmark/result.json
```

The saved 4B checkpoint has 3658 trace records. Its unchanged SHA256 is
`9919d73c918e5a2da0d859b4fa8d69fc35fb47edbbc31ac153364d6d471a77bc`.

| Phase | Seconds |
| --- | ---: |
| Restore with existing audits | 7.8666 |
| Fresh payload | 0.0009 |
| Reference primitive conversion | 0.0479 |
| Reference JSON encoding | 1.2804 |
| Reference UTF-8 conversion | 0.0393 |
| Reference SHA256 | 0.4650 |
| Separate reference canonical total | 1.1823 |
| New cold snapshot | 1.2065 |
| New warm snapshot | 0.1126 |
| New warm snapshot UTF-8 | 0.0387 |
| New warm snapshot SHA256 | 0.4452 |
| New warm streaming hash, including fresh encoding | 0.5554 |
| New cold streaming hash, including fresh encoding | 1.5369 |

Cache retained-data accounting: 239,848,712 bytes (228.7 MiB), within the
then-current 268,435,456-byte limit. Exact strings and hashes passed for cold and warm paths.
The result JSON records source fingerprints, Python/platform and all phases.
This is one local checkpoint microbenchmark with other agents potentially active;
the separately sampled timings need not add up exactly. No full compiler was
rerun, so no end-to-end compiler speedup is claimed. Full snapshot output and
SHA256 remain linear in output bytes; cold encoding and cache overflow can limit
the benefit. Checkpoint/trace file sizes are unchanged.

## Bounded four-patch capacity policy

After the read-only 4C assessment identified sequential-scan LRU thrashing,
`replay.trace._event_data` capacity was raised from 4096 to 8192 entries, and
the encoding prefix default from 256 to 768 MiB. These are lazy upper limits;
the 4B sample's existing retained records do not grow merely because the limit
is larger. The 16 GiB host had about 4.7 GiB available during the assessment.
The parser entry limit is not a byte bound or a universal solution for arbitrary
trace length. Actual final event count and worker memory must still be checked
for the declared 4C run.

67 regression tests passed in 12.61 s, including an actual 4097-distinct-record
parser scan followed by three scans with zero additional misses, exact raw-key
distinction, deep immutability, lazy allocation and all previous snapshot,
readout and batch-Raman tests. The copied 4C checkpoint (132,556,536 bytes;
1784 records) restored and matched original canonical strings and hashes on
all paths. It retained 236,222,246 cache bytes under the new 805,306,368-byte
limit. Evidence: `artifacts/qec-roadmap/cache-limits-benchmark/result.json` and
`artifacts/qec-roadmap/cache-limits-tests/result.json`. These checks do not claim
a full 4C compile has completed. Assessment alternatives, including compressed
representations, were not implemented by this minimal capacity change.


The subsequent attempt2 reached its 3600-second budget at 1604 slots (7568 events, below 8192). The saved 1588-slot checkpoint has 7564 records and 533,176,568 bytes. Restoring it in the validated continuation measured 956,574,284 retained encoding bytes, above the old 768 MiB bound. The next lazy limits are 16384 parsed events and 1536 MiB encoded-prefix data. 77 focused checks passed in 20.96 s; exact resume boundaries and source deltas are recorded in the resume contract. This repairs engineering working-set limits without changing the physical trace. Full 515-plan replay subsequently passed with exact final snapshot and all 8360 event records.
