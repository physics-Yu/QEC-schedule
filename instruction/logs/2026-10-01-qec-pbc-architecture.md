# 2026-10-01 · QEC / PBC 上游编译架构

- 状态：COMPLETED（本轮架构、增量编译原型与声明范围验收完成；完整容错/Shor系统未实现）
- 用户目标：基于参考对话建立 QEC 与 Pauli-based computation 的新架构，以 rotated surface code d=3 接入既有中性原子物理电路。
- 本轮范围：架构合同、增量 IR/编译原型、d=3 memory 与逻辑 Pauli 测量、独立语义验证及原生 PhysicalCircuit 导出；不修改既有物理核或硬件参数。
- 基线：M0–M4 与受限 QEC；已有 dirty 修改保持。用户已明确授权此次新架构，PBC 全称已确认。
- instruction：architecture.md、compiler_contract.md、workflow.md。

## 完成内容

- `docs/qec_pbc_architecture.md`：两种 PBC 语义、分层数据流、code 与测量合同、实施阶段和可复现入口。
- `src/neutral_atom_experiments/qec_pbc/`：`pauli.py` 的有符号 Hermitian 代数；`ir.py` 的 role、Pauli measurement、primitive、AND/XOR经典表达和显式 memory decoding contract；`surface.py` 的固定 d=3 memory/check/logical representatives；`lowering.py` 的 native X/Z parity gadget、结果符号和 provenance；`validation.py` 的理想验证与 encoded Bell；`neutral_atom.py` 的既有34原子平台适配。
- `examples/compile_qec_pbc.py`：memory X/Z 与 logical PBC Bell bundles。17-role memory Z/X 为416/434槽、各96CZ/41测量/32detectors；r0制备加3存储轮。35-role Bell为517槽/108CZ/34测量，无噪声 codespace 与 XX/ZZ 均通过。
- `examples/run_qec_pbc_physical_smoke.py`：全零输入的单Z0Z3 check，34个物理原子保留所有spectators；输出已接受计划、trace、checkpoint、共用viewer动画与独立重放。重复命令保留旧证据并另建attempt目录。
- `tests/test_qec_pbc{,_pauli,_instrument}.py`：独立Pauli矩阵、projector两分支、纠缠spectator、码距/秩、全部54单data fault、frame、依赖/符号/edited contract/能力拒绝及native adapter。
- 更新 `instruction/architecture.md`、`compiler_contract.md` 和 `handoff.md`；保留既有dirty工作，未提交/推送。

## 验证

使用本机 bundled Python 3.12：`C:/Users/yuyqp/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe`。pytest 8.4.2 隔离在 `artifacts/qec-pbc-test-deps`，未修改全局Anaconda。

| 命令/检查 | 本轮结果 | 证据 |
| --- | --- | --- |
| `examples/compile_qec_pbc.py --output artifacts/qec-pbc-2026-10-01 --rounds 3` | PASS，三例各seed0/1/7 | `artifacts/qec-pbc-2026-10-01/verification.json`及各case bundle/verification；含源码SHA256 |
| `examples/run_qec_pbc_physical_smoke.py --output artifacts/qec-pbc-2026-10-01/physical-smoke` | 两次均PASS；7门/2CZ/8计划/150事件，3221.711190μs | `physical-smoke/result.json`和`physical-smoke-attempt2/result.json`；各自accepted plans、trace/checkpoint和动画 |
| smoke独立accepted-plan resubmission | 快照完全一致；effects exactly once、raw parity0、ancilla Z=+1、DAG/terminal完成且无pending | 两份result的audit |
| 三个新增测试文件 + `test_environment_boundary` + `test_surface_qec_protocol` + `test_stabilizer_quantum` + `test_quantum_readout` | **274 passed in 8.20s** | 本轮工具输出；其中独立密集instrument8例、Pauli代数93例 |
| `tools/check_architecture.py --output artifacts/qec-pbc-2026-10-01/architecture-audit.json` | PASS，零依赖违规 | env58/strategies41/experiments48/app9模块 |
| 本轮文档链接、Python语法与差异检查 | PASS | 结束检查工具输出；LF/CRLF提示不是空白错误 |

测试复现（先运行 export/smoke 的普通命令亦可）：

```powershell
$taskPython = 'C:\Users\yuyqp\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $taskPython -c "import os,sys;from pathlib import Path;os.environ['PYTHONPATH']=str(Path('src').resolve());sys.path.insert(0,'artifacts/qec-pbc-test-deps');import pytest;raise SystemExit(pytest.main(['-q','-p','no:cacheprovider','--basetemp=artifacts/qec-pbc-pytest','tests/test_qec_pbc.py','tests/test_qec_pbc_pauli.py','tests/test_qec_pbc_instrument.py','tests/test_environment_boundary.py','tests/test_surface_qec_protocol.py','tests/test_stabilizer_quantum.py','tests/test_quantum_readout.py']))"
```

## 失败与修正证据

- 默认 `python` 为旧Anaconda3.7/pytest3.8，首次Pauli tests在collection前失败；bundled Python初次缺pytest。改用Python3.12并隔离安装pytest，不修改物理规则。随后Pauli93例通过。
- 第一轮组合测试 **186 passed / 1 failed**：environment boundary 的子进程没有继承pytest配置中的src路径，报 `ModuleNotFoundError: neutral_atom_env`。设置本次进程 `PYTHONPATH=绝对src` 后273例通过；新增adapter负例后最终274例通过。未修改该历史测试或放宽断言。
- 独立审查发现prototype decoder按observable名字猜basis会受patch名中`.logical_X`干扰；改为显式`MemoryContract`，追加负例。复制合同后修改check符号也可能错解，追加八个positive d3 closing checks及basis observable精确验证，不匹配则拒绝。
- 空条件条目在校验前索引导致IndexError，调整验证顺序并验证ValueError。重叠gadget使用完整role生命周期依赖是保守协议策略；审查者进一步核对后确认原wire顺序本身已保留理想量子语义，没有把它误报为既有物理核错误。

## 决策与物理假设

- 区分标准算法 PBC 化简与保留 QEC 语义的 physical Pauli-measurement IR。
- 单裸 ancilla 的逻辑 Pauli measurement 只承诺理想 projector 语义，不承诺容错。
- d=3 check、logical representative 与 coupling order 复用已有约定；不修改物理参数。
- 参考文献：Bravyi–Smith–Smolin `https://arxiv.org/html/1506.01396` 的PBC/Clifford化简；Nature `https://www.nature.com/articles/s41586-025-09848-5` 的hook ordering和逐物理指令噪声。工程推论/项目简化与文献事实在架构文档分别说明。
- memory preparation通过真实报告位lookup修正，不用hidden physical truth；closing lookup仅完美读出单data Pauli，不等于通用decoder。逻辑Y代表元保留精确相位，但物理Y测量缺S/Sdg已验证能力，首版fail closed。
- 单check执行复用已有默认rigid平台/Enola参数，总时间包含真实运输、读出和最终归还。没有改变EZ/间距/作用半径等限制。

## 未完成与风险

- 通用 Clifford+T→PBC、magic state、通用时域 decoder 与噪声统计不属于本轮已实现结果。
- 完整17-role memory尚未真实物理执行；当前adapter可建立34原子含spectators的输入，不能视作17原子新平台验收。35-role Bell需要额外已验证bus平台，当前既有34原子适配器明确拒绝。
- 当前check逐个串行、前后reset均保守保留；不宣称routing/门数最优，gate slots含条件分支声明，不等于每次都执行。
- 裸ancilla Logical PPM、重复syndrome不构成容错性证明；未采样noisy circuits、loss/leakage或coherence/fidelity。export报告的time/fidelity为null；物理smoke time仅属单check。
- 共用viewer动画已生成，但本轮没有真实浏览器验收，也未完成新工作台输入/自适应控制流/经典延迟/保护插入。

## 下一步

1. 用 `memory_program` / `build_native_qec_inputs` 接入完整memory执行，先验收原生测量sidecar、真实计划、terminal和独立replay；若另建17原子平台，逐候选保留原物理核验证。
2. 选择实际容错Logical PPM协议并增加backend，定义故障模型，完成hooks/错误传播/时域decoder验证后才开放FT能力。
3. 再补Logical Clifford+T→PBC、Y能力与magic-state接口；最后连接timeline噪声、标定库与Shor运行。

## 2026-10-02 发布补充

本日志的3221.711190μs/150事件是10月1日本地Enola默认参数工作树的历史证据；不是仅上传QEC/PBC后的远端默认硬件结果。10月2日在最新GitHub main04dc69b的干净基线上加本轮QEC/PBC文件，重新得到3726.6μs/158事件，仍为7门/2CZ/8计划，完整物理/测量/终态/独立replay通过；274项回归亦通过。此次不发布本地未提交硬件/Enola变更，详情见[发布日志](2026-10-02-qec-pbc-publication.md)。原验收数字保留，不用于跨硬件排名。
