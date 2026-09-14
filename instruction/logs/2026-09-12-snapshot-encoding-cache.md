# 2026-09-12 — Exact schema19 trace encoding cache

Parent authorized engineering optimization after 4B compile/replay/UI passed.
Changed only snapshot encoding in `simulation/state.py`, the new
`replay/snapshot_encoding.py`, and `motion/compiler.py` fingerprint generation.
The original canonical serializer, physics and validation/audit paths are intact.
Added focused tests and `examples/benchmark_snapshot_encoding.py`.

Complete design/limits: `docs/snapshot_encoding_cache.md`.
Machine benchmark evidence and exact source hashes:
`artifacts/qec-roadmap/snapshot-cache-benchmark/result.json`.

First regression command:
`C:/python312/python.exe -m pytest -q tests/test_snapshot_encoding.py tests/test_readout_flip.py tests/test_quantum_readout.py tests/test_batch_raman.py`
completed **64 passed in 19.61 s**, with no skips/failures. Both saved formal
baseline and 4B schema19 checkpoints match original JSON strings and SHA256.
After conservative accounting adjustment, the five small tests passed in
0.15 s; after replacing the SLM payload example with a valid spare-trap state
variant, they passed in 0.20 s. No physical model or expectation was relaxed.

4B saved checkpoint microbenchmark: reference canonical 1.1823 s; new cold
snapshot 1.2065 s; warm snapshot 0.1126 s; full warm streaming hash 0.5554 s.
Persistent cached record data accounts for 239,848,712 bytes (limit 256 MiB).
All cold/warm strings and hashes match. No complete compiler or new physical
experiment was run. Other concurrent work means these are local sample timings,
not an isolated compiler performance comparison. Cache is process-local and
absent from checkpoints; restoration uses unchanged schema19.

Handoff: ready for parent integration. For larger 4C traces above the retained
prefix budget, excess suffix encoding remains uncached; do not remove history,
weaken checks or change SHA256 to compensate. Parent maintains shared handoff.
