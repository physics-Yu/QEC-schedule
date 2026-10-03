# QEC 并发组件：本批交付与集成边界

用户让另一 agent 执行任务 A；本批不修改 A 的 canonical、baseline 或其测试，也不修改硬件、环境、共享策略和旧工作。采用独立模块并发实现，读取 A 当前接口做组合验证。

| 组件 | 已实现 | 独立验证 | 范围 |
|---|---|---|---|
| [logical Pauli](qec_logical_pauli.md) | exact Clifford+T → signed rotations、residual Clifford、global phase；inverse frame 避免重复扫描历史 | 12 项，含随机酉矩阵与长电路 | 持续数据 unitary frontend，未做严格 BSS 消元 |
| [backend contract](qec_backend_contract.md) | 耦合层、H-CZ-H DAG、生命周期、能力/actual pairs/AOD矩形审查 | 12 项 | 请求与预检查，没有执行新并行运输 |
| [logical gadgets](qec_logical_gadgets.md) | 同朝向 d3 transversal CNOT，显式朝向变化的 H | 5 项，stabilizer group 与 logical maps | 未插入 QEC/decoder 或声称 FT |
| [magic injection](qec_magic_injection.md) | T/Tdg 资源请求、消费、测量和 S/Sdg 分支校正 | 3 项，Kraus、两分支、纠缠参考 | logical instrument，默认质量未知，没有工厂 |
| [noise bridge](qec_noise_bridge.md) | 显式 Pauli 曝光、native Clifford→Stim、detectors、MWPM、Wilson区间 | 5 项与实际 Monte Carlo | synthetic 参数；不支持loss/nonPauli/带噪条件pulse |
| [Shor frontend](qec_shor_frontend.md) | 精确 7-T Toffoli、固定来源 N21 模幂→logical Pauli | 最终8项与1024指数真值 | 没有QFT、反馈读出或physical Shor |

## 实际组合结果

`examples/run_shor_pauli_frontend.py` 读取 SHA256 固定的作者 N21 原件：15 logical wires，73 X、10 H、191 CX、369 CCX。展开为1476 T、1107 Tdg，共2583 rotations；最终Clifford含3226 gates。全部1024个指数符合 `pow(2,e,21)`，控制寄存器恢复；没有使用周期或因子。T count 不是同时需要的magic patches，峰值缓存/物理原子数仍未知。

`examples/run_qec_parallel_integration.py` 使用 A 当时的3-round canonical memory，通过新 backend contract 与 Stim bridge：每basis12 coupling layers、72 CNOT-equivalent interactions、24 detectors、1 observable；native gates X332/Z314。各1000 ideal shots的detectors/observables全零。这不包括原子运动或Executor执行。

人工 `one_qubit=two_qubit=readout=0.005`，每basis20000 shots、seed17、Stim1.15.0/PyMatching2.3.1：native X869 failures（4.345%，95% Wilson约4.071–4.636%），Z605（3.025%，约2.797–3.272%）。官方generated reference另得X184/Z165；电路分解与噪声位置不同，不能按数字评硬件优劣。实际trace自动曝光分段、相关decoder与loss生命周期仍待接入。

证据：`artifacts/qec-parallel-2026-10-02/{shor-prefix,canonical-bridge}` 与 `artifacts/qec-noise-reference-2026-10-02`。canonical-bridge报告保留源文件hash；重新组合前核对 A 是否更新。

## 验证和开放问题

- 本批组件＋既有PBC/稀疏physical/读出/算术/环境边界联合378项通过；随后最终算术值快照改动及新增用例，与Pauli/injection联合23项复验通过。
- 补充Z3后旧ordered comparison6项通过。包边界172模块、0 violations。一次旧Pauli测试收到pytest10 iterator弃用提示，不影响通过。
- 广泛`test_qec*.py`首次427pass/6fail：其中3项缺Z3已经补依赖并复验；另外3项旧工作流差异保留：joint/persistent预期旧装卸节省200us，当前实际30us；geometry的9-pair密集CZ八个候选均被`PATCH_PULSE_PAIRS`拒绝。没有改断言或放宽物理条件。诊断见`artifacts/qec-parallel-2026-10-02/legacy-regression-diagnostics.json`。
- 严格BSS、一般/Y logical PPM、surgery、资源态蒸馏与CCZ工厂、实际闭环loss恢复和完整Shor继续作为后续任务。M5/M6未因此完成。

## 可复现入口

使用 Python3.12 和 [固定依赖](../examples/requirements-qec-components.txt)；当前本机可复用`.venv-qec-noise-modern/Scripts/python.exe`。默认PATH的Python3.7不能运行本项目。测试必须使用独立basetemp，避免并发agent互删目录。

```powershell
$env:PYTHONPATH='src'
& '.venv-qec-noise-modern/Scripts/python.exe' examples/run_qec_parallel_integration.py --output artifacts/qec-parallel-2026-10-02/canonical-bridge --shots 20000 --seed 17
& '.venv-qec-noise-modern/Scripts/python.exe' examples/run_shor_pauli_frontend.py --qasm artifacts/shor-greedy-2026-09-15/circuits/gidney-factor21.qasm --output artifacts/qec-parallel-2026-10-02/shor-prefix
```

后续先把 A 最终protocol/hash接入，再让策略消费请求生成真实并行计划，经原环境和Executor核验；逻辑rotation→容错PPM需单独实现。工作区内本批测试venv不是交付源码，不应上传。未提交或推送本批更改。
