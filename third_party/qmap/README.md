# QMAP source provenance

Upstream: https://github.com/munich-quantum-toolkit/qmap (MIT).
Source review snapshot: `e2988b773a36665fd6e5a5e1228fc1df7c4e1ef1`.
The three upstream files are copied unchanged; LICENSE is retained.

| File | SHA256 |
|---|---|
| eval_ids_relaxed_routing.py | 182310f913c8a1ef9a3f4e403d0229529c77a123344eb2e522e4467eae2f0865 |
| square_architecture.json | efb930eeedfc49dc3822b99a4ba44720b8973de0171ec7f5bb485fceeaf8084f |
| LICENSE | 42c32f77c8dcde761998d41ff3c05384dc468dee388866c5876a94966a5f9236 |

Execution uses the released native wheel **mqt.qmap 3.5.0**, not a build of
the reviewed main commit. The author evaluation pins mqt.bench 2.1.0.
The Windows/Python 3.12 dependency lock additionally resolves dependencies
with cutoff 2025-12-16T12:59:59Z (Qiskit 2.2.3, mqt.core 3.3.3).
The local glue is original code under `src/neutral_atom_strategies/qmap_native`.

`tools/setup_qmap_native.py` installs an isolated runtime. No replacement of
the main project's Qiskit installation is required. See `docs/qmap_native.md`
for supported physical translation, experiments, and limitations.
