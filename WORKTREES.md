# NADiT worktree snapshots

Updated 2026-10-26 (Asia/Shanghai). Each branch preserves a separate local workspace, including its pending source changes. These snapshots do not merge the experimental branches or certify uncommitted changes.

| Workspace | Published branch | Source HEAD | Purpose |
| --- | --- | --- | --- |
| main | [main](https://github.com/physics-Yu/QEC-schedule/tree/main) | `85f5479da14c` | Integrated NADiT workspace, including pending native-component reuse changes. |
| 92db | [codex/msd-level2-factory](https://github.com/physics-Yu/QEC-schedule/tree/codex/msd-level2-factory) | `88e9a643d2e8` | Two-level object MSD supply and synchronous scan source and reports. |
| d3-smt-architectures | [feat/d3-smt-architectures](https://github.com/physics-Yu/QEC-schedule/tree/feat/d3-smt-architectures) | `85f5479da14c` | Bounded SMT compiler and free-layout d3 MOVE-depth experiments. |
| e3e1 | [codex/worktree-e3e1-smt-qec-viewer](https://github.com/physics-Yu/QEC-schedule/tree/codex/worktree-e3e1-smt-qec-viewer) | `85f5479da14c` | SMT work and QEC replay/viewer annotations. |
| ec0f | [codex/worktree-ec0f-component-reuse](https://github.com/physics-Yu/QEC-schedule/tree/codex/worktree-ec0f-component-reuse) | `85f5479da14c` | Separate snapshot of pending native-component reuse changes. |
| f4d0 | [codex/worktree-f4d0-interface-review](https://github.com/physics-Yu/QEC-schedule/tree/codex/worktree-f4d0-interface-review) | `2c55f7edfa8f` | Unified compiler interface boundary review. |
| logical-qasm-frontend | [codex/logical-qasm-frontend](https://github.com/physics-Yu/QEC-schedule/tree/codex/logical-qasm-frontend) | `852fd7311966` | Logical QASM frontend, shared-resource scheduling and fast estimates. |
| msd-experiment-standard | [codex/surface-d9-d11-components](https://github.com/physics-Yu/QEC-schedule/tree/codex/surface-d9-d11-components) | `baba7276e39f` | Raw-T injection, code growth and d9/d11 component bundles. |
| msd-generic-fast | [codex/generic-fast-factory](https://github.com/physics-Yu/QEC-schedule/tree/codex/generic-fast-factory) | `ebf7d64b4d41` | Generic factory fast profiles and shared-AOD batching. |
| msd-object-scheduler | [codex/msd-object-scheduler](https://github.com/physics-Yu/QEC-schedule/tree/codex/msd-object-scheduler) | `d7723a23ed34` | Object-level single-round factory strategy and layout scans. |
| msd-single-level-fast | [codex/msd-single-level-fast](https://github.com/physics-Yu/QEC-schedule/tree/codex/msd-single-level-fast) | `b43db97d64f4` | Center-cost single-level MSD experiment and audited results. |

The three existing main documents (`log.md`, `short-term task.md`, and `Framework (Surface Code).md`) are preserved byte for byte. Other pre-existing remote branches are retained.

Scope: tracked files and non-ignored pending source files. Git metadata, ignored virtual environments/caches/build outputs, and the untracked top-level `artifacts/` run deliveries are excluded. Already tracked experimental results remain included. Each branch contains `SNAPSHOT-MANIFEST.json` with source state, file hashes and explicitly excluded untracked artifacts. Local workspaces and their Git indexes are not modified. Snapshot verification checks publication fidelity, not runtime correctness.
