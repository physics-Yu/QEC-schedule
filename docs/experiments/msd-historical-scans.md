# Historical object-factory scans

Use this index to read the saved object-model studies with their original
code and inputs. The current [two-level supply method](../../experiments/msd/README.md#choose-when-l1-may-prepare-the-next-magic-states)
charges capacity until consumption. In the archived two-level model, delivery
to L2 freed an upstream inventory position. A comparison of rates must account
for that difference.

| Study | Executed source and frozen configuration | Published record and saved output |
| --- | --- | --- |
| One-level object factory, 180 cells and 18,000 one-round shots | `12816435bfa0599a4c44c937a02b969b3a1e4438`, `experiments/msd/server-scan-d3-d11-n1-n10-100seeds.json` | Report revision `d7723a23ed34ee0461e97d60efd2e8219028907a`, `docs/experiments/msd-object-server-scan-20261025.md`. In the original object-scheduler worktree, open `artifacts/msd-object-server/20261025-scan-1281643/report-v3/index.html`. |
| Two-level synchronous object supply, 270 cells and 27,000 shots | `d00a937dbff011b9cf03c4031604f739ff8cb823`, `experiments/msd/level2-sync-server-continuation.json`. The continuation reused 1,251 completed shots from `5c21201` and ran 25,749. | Report revision `88e9a643d2e8bdb66f40bf799ba7bc23ea5cf1a7`, `docs/experiments/msd-level2-sync-results-20261026.md`. In the original level2 worktree, open `artifacts/msd-object-server/20261026-level2-sync-continuation/delivery/report/index.html`. |

Read the reports from the local Git history with

```console
git show d7723a2:docs/experiments/msd-object-server-scan-20261025.md
git show 88e9a64:docs/experiments/msd-level2-sync-results-20261026.md
git show d00a937:experiments/msd/level2-sync-server-continuation.json
```

The dataset archives live beside the corresponding saved reports. Compare
their SHA-256 values before using data from another copy.

| Archive | SHA-256 |
| --- | --- |
| One-level `compact-results.tar.gz` | `26f069e59b5df4fcf0f0bbdcc73662fcd811de930b1df2635299a3958663af03` |
| One-level `representatives.tar.gz` | `5bab8547ce59e62ba5279992abe5f2bcf7736902ec5f0e77353acb6896c5ca8b` |
| Two-level `verified-delivery.tar.gz` | `e0dba4beff423a54c8165438fd5f8f8c757a3dc242ccc2063becd67a3d67df89` |

The separately published [single-level center-distance study](single-level-fast-20261025.md)
uses its own cost model, frozen trajectories and eligibility rules.
