# NADiT worktree snapshots

This index records the publication of eleven local NADiT workspaces on 2026-10-26. Each link opens the exact commit published to QEC-schedule. The source HEAD column identifies the original checkout. Some checkouts also contributed pending changes captured in the published snapshot.

| Workspace | Published QEC-schedule snapshot | Source HEAD | Purpose |
| --- | --- | --- | --- |
| main | [`main@61a3568`](https://github.com/physics-Yu/QEC-schedule/tree/61a3568a86bff89a67fb3024185cb833f591c42a) | `85f5479da14c` | Integrated NADiT workspace, including pending native-component reuse changes. |
| 92db | [`codex/msd-level2-factory@f580179`](https://github.com/physics-Yu/QEC-schedule/tree/f5801799f83c0cd34ab104cc8b9f2617014f11fd) | `88e9a643d2e8` | Two-level object MSD supply and synchronous scan source and reports. |
| d3-smt-architectures | [`feat/d3-smt-architectures@1ad602d`](https://github.com/physics-Yu/QEC-schedule/tree/1ad602d24d391b09b02257998855a89357375677) | `85f5479da14c` | Bounded SMT compiler and free-layout d3 MOVE-depth experiments. |
| e3e1 | [`codex/worktree-e3e1-smt-qec-viewer@306223b`](https://github.com/physics-Yu/QEC-schedule/tree/306223b7980238cf74d0f451d2e7ef3acb00dcca) | `85f5479da14c` | SMT work and QEC replay/viewer annotations. |
| ec0f | [`codex/worktree-ec0f-component-reuse@0fa89aa`](https://github.com/physics-Yu/QEC-schedule/tree/0fa89aa510f5dc9494dc4a1f6dd7145519501335) | `85f5479da14c` | Separate snapshot of pending native-component reuse changes. |
| f4d0 | [`codex/worktree-f4d0-interface-review@a950f24`](https://github.com/physics-Yu/QEC-schedule/tree/a950f242b01b362947d918f344119d600c3b2b94) | `2c55f7edfa8f` | Unified compiler interface boundary review. |
| logical-qasm-frontend | [`codex/logical-qasm-frontend@fd92e1e`](https://github.com/physics-Yu/QEC-schedule/tree/fd92e1e1746d6e8f6665af9f0790f1f7d0eca972) | `852fd7311966` | Logical QASM frontend, shared-resource scheduling and fast estimates. |
| msd-experiment-standard | [`codex/surface-d9-d11-components@0c628bf`](https://github.com/physics-Yu/QEC-schedule/tree/0c628bf5d8e2380737e6be545e850bd8794dd585) | `baba7276e39f` | Raw-T injection, code growth and d9/d11 component bundles. |
| msd-generic-fast | [`codex/generic-fast-factory@ce28191`](https://github.com/physics-Yu/QEC-schedule/tree/ce281914644022d4b2727b69e6c2a051e2706772) | `ebf7d64b4d41` | Generic factory fast profiles and shared-AOD batching. |
| msd-object-scheduler | [`codex/msd-object-scheduler@345a43b`](https://github.com/physics-Yu/QEC-schedule/tree/345a43b6c1aa48c0c8c3f51953a27fb5f58b497b) | `d7723a23ed34` | Object-level single-round factory strategy and layout scans. |
| msd-single-level-fast | [`codex/msd-single-level-fast@bc6d74c`](https://github.com/physics-Yu/QEC-schedule/tree/bc6d74cdd4734d44e73250d0c2d93526921e125e) | `b43db97d64f4` | Center-cost single-level MSD experiment and audited results. |

The 2026-10-26 publication preserved the three research documents on `main` byte for byte: `log.md`, `short-term task.md`, and `Framework (Surface Code).md`.

Scope: tracked files and non-ignored pending source files. Git metadata, ignored virtual environments/caches/build outputs, and the untracked top-level `artifacts/` run deliveries are excluded. Already tracked experimental results remain included. Each branch contains `SNAPSHOT-MANIFEST.json` with source state, file hashes and explicitly excluded untracked artifacts. Local workspaces and their Git indexes are not modified. Snapshot verification checks publication fidelity, not runtime correctness.

## November 4 maintenance

The local cleanup retired two linked QEC-schedule checkouts and three NADiT research checkouts. Their filesystem snapshots and raw experiment files are in the local recovery archive. The published source snapshots above remain available at their original commits.

| Retired branch name | Where its contents are preserved |
| --- | --- |
| `codex/readme-license-ci` | [Merged PR #7](https://github.com/physics-Yu/QEC-schedule/pull/7) brought the README, MIT license and CI workflow into `main`. The [PR head](https://github.com/physics-Yu/QEC-schedule/commit/bc42b30fe696f6075e3e9fcb83dc922ae28dd85d) and [merged commit](https://github.com/physics-Yu/QEC-schedule/commit/75d3911456ed8bac2bef73f41ceccb1bab0ccd67) have identical file trees. |
| `old` | [Legacy QEC revision `6b63287`](https://github.com/physics-Yu/QEC-schedule/tree/6b632876cf30d505052acaad166c1bb839278be9) is an ancestor of both `main` and `develop`. Use this link to inspect its original source. |
