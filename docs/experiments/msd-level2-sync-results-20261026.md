# Two-level MSD synchronous scan results

Date: 2026-10-26 (Asia/Shanghai). Status: complete; data audit passed.
Source: `d00a937dbff011b9cf03c4031604f739ff8cb823`.
Protocol and budgets: [continuation record](msd-level2-sync-continuation-20261026.md).
The 270 cells contain all seeds 0..99: 27000 shots, including 1251 unchanged
imported records and 25749 newly executed shots. No new timeout occurred.

## Delivery and verification

Local delivery: `artifacts/msd-object-server/20261026-level2-sync-continuation/delivery/`.
Open `report/index.html` for statistics, 22 chart figures and a filterable table;
`report/schedules/index.html` links 14 complete seed-0 schedules from saved traces.
All 270 full representative traces remain on the server; 14 are included locally.
`cell-summary-with-layout.csv` includes unique cell IDs and all L2 positions.
The frozen HTML export is preserved separately; publication adjustments only
correct budget metadata, add provenance and disambiguate CSV layout columns.

Audit: 27000-shot coverage, 60395 common production-round signatures, conservation,
catalog reuse and frozen runtime/accounting hashes passed. Imported records match
their originals exactly. Compile, atom expansion and atom construction counts are
all zero. No factory was rerun for plotting or schedule export.
The downloaded archive SHA256 is
`e0dba4beff423a54c8165438fd5f8f8c757a3dc242ccc2063becd67a3d67df89`.
All 1173 member hashes match. Static checks passed for 16 HTML files, 66 links,
270 table/CSV cells and 22 PNG figures. The rate figure was visually inspected.
Browser policy blocked automatic `file:` navigation; interactive browser and
user visual acceptance remain unverified. No alternate browser route was used.

## Highest observed accepted-output rate per distance

All listed configurations use N1=10, N2=B=1 and L2 below-center.

| d | L1 rows x columns | Accepted outputs/s | Approximate 95% CI | L2 input wait, ms | Atoms |
| --- | --- | --- | --- | --- | --- |
| 3 | 2 x 5 | 2.4663 | 2.4283–2.5044 | 290.419 | 1122 |
| 5 | 1 x 10 | 1.0632 | 1.0473–1.0792 | 700.585 | 3234 |
| 7 | 1 x 10 | 0.8149 | 0.8032–0.8266 | 910.264 | 6402 |
| 9 | 1 x 10 | 0.6334 | 0.6241–0.6428 | 1175.643 | 10626 |
| 11 | 1 x 10 | 0.4948 | 0.4874–0.5021 | 1520.069 | 15906 |

At d3, versus the highest-rate N1=1 layout, N1=10 reduces mean L2 input wait
80.08% (1458.102 to 290.419 ms) and raises observed rate 3.765x. Allocated atoms
rise from 204 to 1122; atom-time/output rises 46.08% (311.421 to 454.930 atom s).
At N1=2, the best-rate layout has 278.103 atom s/output. More supply capacity
therefore improves this rate comparison but does not minimize resource cost.

## Runtime and limits

Continuation server wall time: 6232.050 s (103.87 min), up to 89 workers.
New shot wall time: median 16.774 s, mean 16.840 s, maximum 42.166 s; peak worker
RSS 1486628 KiB. New work reused 193561345 catalog lookups, with 193545755 hits
and 15590 numeric bindings (99.99195% hits). Each cell worker loads ten templates.
No function-level profile was taken; execution versus serialization cost is not
quantified. The original failure location alone does not establish the bottleneck.
These are finite independent-shot restart estimates, not continuous steady-state
throughput, physical schedules, decoded LER or output-quality-matched optima.
The per-distance maxima are observed selections, not significance-tested winners.
