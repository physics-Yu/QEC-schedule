# 2026-10-02 · QEC/PBC 上传 GitHub

- 状态：IN_PROGRESS
- 用户授权：将上一轮 QEC/PBC 架构部分上传到 GitHub QEC-schedule。
- 目标仓库：`physics-Yu/QEC-schedule`，默认分支 main。
- 范围：QEC/PBC 新代码、测试、示例、架构文档、2026-10-01 日志与相关导航插入；不发布其他本地未提交研究或硬件变更。
- 基线：本地主分支9e28b2e，GitHub main04dc69b；将在最新远端基线上构建独立发布快照，保留原本地工作区。
- 相关规范：agent.md、instruction/handoff.md、instruction/workflow.md。

## 发布与验证

发布前验证完成，GitHub提交及远端ref核验仍进行中。

- 远端父提交：`04dc69b416da5d35fd3e16739075a543643ef42e`，tree `2e96c2a8a33212a82bfb57ca6d11de0f7566f892`。
- 只选18文件：7个qec_pbc模块、2个examples、3个tests、架构文档、10月1日/2日日志，以及architecture/compiler_contract/handoff的QEC/PBC增补。共享导航基于最新远端正文插入；没有覆盖较新的QMAP/placement/RL/交互IR等内容。
- 从远端commit执行`git archive`构建清洁快照，仅复制上述文件；原本地主分支不checkout/reset/stash，不动原Git index。24个其他tracked dirty文件以SHA256守护；未收录其他untracked研究文件或artifacts。

| 检查 | 本轮结果 | 证据 |
| --- | --- | --- |
| 三个新test文件 + environment_boundary / surface_qec_protocol / stabilizer_quantum / quantum_readout | **274 passed in 8.68s** | 清洁快照执行输出 |
| `tools/check_architecture.py` | PASS，223模块，零反向依赖 | `artifacts/qec-pbc-publication-2026-10-02/validation/architecture-audit.json` |
| `examples/compile_qec_pbc.py --rounds 3` | 三例seed0/1/7 PASS；17-role memory416/434槽、Bell35-role517槽 | `validation/compiled/verification.json`及各case源码指纹/bundle |
| `examples/run_qec_pbc_physical_smoke.py` | PASS，7门/2CZ/8计划/**158事件、3726.6μs**；logical completion2906.6μs | `validation/physical-smoke/result.json`及accepted plans/trace/checkpoint |
| 单check quantum/terminal/effect/独立replay | 全部PASS，raw parity0、ancilla Z=+1、效果各一次、DAG完成、快照一致 | 同上audit |

验证使用Python3.12与隔离pytest8.4.2，在清洁快照根目录运行，PYTHONPATH指向该快照src。新增代码未依赖未发布Enola/ZAC/Shor源码；现有pyproject自动发现包，无需上传其本地package-data修改。

## 发布结果

待GitHub connector建立commit并以`force=false`推进main后记录提交SHA、远端文件核验与本地守护结果。

## 已知边界

本地 origin 的 pushurl=DISABLED，发布采用已连接 GitHub connector，不更改该配置。QEC/PBC 依旧是声明范围的理想语义原型和单check物理验收，非完整容错/Shor系统。

10月1日本地3221.711190μs/150事件使用未发布Enola默认参数。此次clean main底座为3726.6μs/158事件，硬件/底座不同不作性能比较；原历史证据追加说明但不覆盖。完整memory/Bell尚未物理验收，Y/容错PPM/标准Clifford+T→PBC/magic-state/noise fidelity边界保持。
