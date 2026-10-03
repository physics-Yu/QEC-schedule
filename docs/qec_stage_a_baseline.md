# 阶段 A：canonical d=3 surface-code memory 物理基线

本基线把标准四层 CSS syndrome 协议完整交给既有中性原子 Executor，分别执行 Z/X memory，并保存真实操作时间、测量结果、独立重放及受限 native circuit-fault 验收。默认从已经排好 working placement 的 EZ 初态开始计时；上游布局准备的时间未测量，不计入本基线。它为后续 logical Pauli measurement 与 magic-state 协议提供可复现的 QEC 底座；不代表完整 M5/M6、Shor、逻辑 PPM 容错或 fidelity 模拟已完成。

## 执行链与协议约定

```text
canonical.py：几何推导的四层 CSS memory + detector/observable
  → lower_to_physical：显式 H(target)–CZ–H(target)、MEASURE、RESET
  → qec_baseline：固定源行与共同位移分组
  → 既有物理编译、约束校验与 Executor
  → VisualRecorder → 共用 NeutralAtomViewer + 只读报告
```

入口为 `canonical_memory_program(basis='Z', rounds=3)`，basis 也可选择 `'X'`。`rounds` 是全部 syndrome 轮数，即 r1、r2、r3；首轮已经包含在三轮之内。每个 patch 使用 9 data 与 8 syndrome ancillas，四个交互层各有六对不共享原子的 CNOT，共 24 对/轮。每层显式展开目标 H、CZ、目标 H 恢复三个阶段，阶段与轮次之间保留依赖屏障。X ancillas 在交互前后各有一次 H；每轮八个 ancillas 测量后复位，下一轮等待全部复位。最终全部 data 按相应 memory 基测量。

本前端保留既有 data/check/logical 编号，借助 x 反射映射到官方 Stim 几何；当前 logical X 代表与 Stim 的选择相差一个 stabilizer 乘积。来源固定为 [Stim v1.15.0 generator](https://github.com/quantumlib/Stim/blob/42e0b9e099180e8570407c33f87b4683cac00d81/src/stim/gen/gen_surface_code.cc)，commit `42e0b9e099180e8570407c33f87b4683cac00d81`；具体坐标、四层耦合、CNOT 方向及 native CZ ID 均保存于 `canonical.json`。

首轮仅同基的四个 checks 有已知正本征值。异基的首轮 syndrome 可以随机，此后无故障时保持原有符号；本协议不执行初态纠正或 frame normalization。closing 验收比较各 stabilizer 的实际本征值与已报告 syndrome 的符号，不要求全部为 +1。bit 0 表示本征值 +1。三轮共 24 detectors：4 个首轮已知边界、16 个相邻轮 XOR、4 个最终 data parity 与 closing syndrome 的终端边界；logical observable 单独记录。

## 物理范围与本轮结果

平台仍有 34 个真实原子，17 个角色参与该 memory，其余原子作为 spectators 继续参与捕获、碰撞、寻址和 CZ 配对校验。working placement 只选择现有 EZ traps；整数几何单位映射为 10 μm，data 相邻间距为 20 μm。平台容量、几何、作用距离、装卸和门时长、最小安全间距及环境约束保持原要求。

`canonical_native_inputs(..., initial_placement='prearranged')` 与 `execute_canonical_memory` 默认在创建环境之前声明完整初态：17 个活跃角色位于 `baseline_destinations` 指定的现有 EZ traps，17 个 spectators 保持原 SZ holders，仅占用的 SLM 支撑初始启用，其他 SLM 支撑关闭。AOD 初始配置、trap 集合和坐标、hardware 与电路保持原配置。t=0 已经处于该布局，执行不包含一般 SZ 初始重排，也不插入零时间 MOVE。布局准备的上游时间记录为 `upstream_layout_preparation_time_us: null`，不记为零。

预排的是原子位置，不是编码量子态。原始 RESET、X memory 的 data H、syndrome extraction、全部 MEASURE 与 ancilla RESET 仍由 Executor 执行。终态恢复的 original holders/supports 是本次已准备好的 EZ/SZ 初态；从 MZ 读出后的归还仍真实计时。需要复现旧初态运输时，显式使用 `initial_placement='storage'` / `--initial-placement storage`，其历史数字单列为 legacy storage。

CZ 服务只把 caller 声明的 syndrome ancillas 作为 mobile operands；按相同源行和相同位移固定分组，使用硬件声明的 `interaction_offset`。分组不比较估计成本；候选拒绝时保留诊断，按固定顺序尝试单例。运行中测量往返与终态归还仍包含 data 等角色的真实运输。四层是协议分组，不等于四个物理 pulse。

| 项目 | Z memory | X memory |
| --- | ---: | ---: |
| 总 syndrome rounds | 3 | 3 |
| 活跃角色 / 平台原子 | 17 / 34 | 17 / 34 |
| Native primitives | 314 | 332 |
| Native H / CZ | 168 / 72 | 186 / 72 |
| 单原子 MEASURE / RESET | 33 / 41 | 33 / 41 |
| 实际 CZ pulses / 最大并行 pair 数 | 48 / 3 | 48 / 3 |
| Detectors / logical observable | 24 / 1 | 24 / 1 |
| 默认 prearranged 逻辑任务完成时间，μs | 61983.261277 | 61985.261277 |
| 默认 prearranged 包含归还的时间，μs | 62539.043703 | 62541.043703 |
| Accepted plans / committed events | 101 / 3274 | 103 / 3314 |
| 枚举 native 单故障机制 | 1658 | 1712 |

时间由既有物理执行事件得到，包含起点之后本项目声明的运输、装卸、门、测量和复位成本，不是实验测得的设备性能。逻辑完成与终态归还分别报告，不把 final data readout 后的运输省略。上游布局准备未测量；不能将它描述为零成本，也不能将下面 legacy storage 的时间当作默认 prearranged 结果。实际并行数与 pulse 区间来自提交的操作，而不是从六对逻辑 CNOT 推断。

默认 prearranged 正式证据目录为 `artifacts/qec-baseline-2026-10-03/prearranged-memory-z-verified` 与 `prearranged-memory-x-verified`。两份 `result.json` 均为 completed，含 `prearranged_initial_holders_verified`、`no_general_layout_staging`、量子参考和 independent plan replay 全部通过；实际48 CZ pulses、最大3对。初态边界修订后127项针对性测试通过，架构检查176模块、0 violations。真实浏览器两份32×连续播放至314/332门全部完成，终点62539.04/62541.04μs；Z真实三对CZ定位与t=0的EZ holder核对通过，浏览器error日志为空。记录见证据根目录 `prearranged-browser-acceptance.json`，初态截图 `prearranged-ez-start.jpg`。

历史 **legacy storage** 模式从 SZ 开始并包含初始 staging 与归还到 SZ；原证据保留于同一根目录的 `memory-z-verified` / `memory-x-verified`：

| legacy storage 历史计时，μs | Z memory | X memory |
| --- | ---: | ---: |
| 逻辑任务完成 | 73825.986672 | 73827.986672 |
| 包含 original holders/supports 归还 | 86801.606074 | 86803.606074 |

该历史轮次 1093 个不同专项/回归测试最终通过：首轮 1080 项通过，10 项测试配置失败经修复后定向复验，并额外核对 3 项 Enola 参数兼容测试；架构检查 172 个模块、0 violations；两份历史 storage 浏览器 32× 连续播放到全部门终点。这些证据不替代修订后的 prearranged 验收。两种模式的输入placement与terminal不同，时间差不作为调度优化收益。

## 独立验收与受限故障模型

物理验收检查 DAG、效果各执行一次、依赖时间、资源区间、测量与 reset projection 完整性、closing syndrome 符号、logical observable、spectators、最终支撑，以及从不可变初态重新提交全部 accepted plans 后的快照一致性。另一个量子参考按实际 native 顺序、报告位与 reset projection 独立重放，避免仅用最终 detector=0 判断正确。

Stim 审计加载隔离的 `stim==1.15.0`，核对官方 reference 与当前完整 native 顺序，包含 H–CZ–H 展开中的每一个 H。枚举模型为：每个 native 1Q 后的 X/Y/Z、每个 CZ 后的 15 种非平凡两比特 Pauli 产品、每个 RESET 的错误 |1〉制备，以及每个 MEASURE 的报告位翻转。报告翻转不改变真实投影；两比特产品算一个 faulty CZ operation。

Z/X 分别枚举 1658/1712 个单故障机制。零或一个故障的 detector 签名不得对应不同 logical flip；双故障组合没有无 detector 的 logical flip，并有三个最终报告翻转的距离三 witness。因此距离 3 结论仅适用于这组离散 native fault mechanisms。字典 decoder 只保证零或一个故障正确；多故障也可能产生字典中的已知签名并导致误纠正，测试保留两故障失败实例。它不是任意电路噪声或通用时域 decoder。

此审计不赋予 idle、transport、原子丢失、leakage 或相关环境过程噪声，不拟合逻辑错误率、coherence、fidelity 或 Shor 成功率。理想物理执行与离线故障审计分别留证，不把后者描述为真实带噪硬件执行。

## 复现

在仓库根目录使用 Python ≥3.10。只把独立审计依赖安装到指定目录，环境内核和普通前端不导入 Stim：

```powershell
python -m pip install --target artifacts/qec-baseline-deps -r requirements-qec-baseline.txt
python examples/run_qec_baseline.py --basis Z --rounds 3 --seed 0 --initial-placement prearranged --audit-deps artifacts/qec-baseline-deps --output artifacts/qec-baseline-reproduce/prearranged-memory-z
python examples/run_qec_baseline.py --basis X --rounds 3 --seed 0 --initial-placement prearranged --audit-deps artifacts/qec-baseline-deps --output artifacts/qec-baseline-reproduce/prearranged-memory-x
```

`--initial-placement` 默认是 `prearranged`，命令显式写出以固定计时边界；改为 `storage` 可复现旧 staging 起点，建议配套使用独立的 `storage-memory-*` 输出目录。`--output` 选择新复现目录。若目标已存在，输出分配器保留原文件并另建目录；以脚本返回的 `output_directory` 为准。`--wall-budget` 控制编译墙钟预算，与仿真 μs 区分。

每次运行保存：

- `canonical.json`（`qec-canonical-memory/1`）：protocol program、phase、coupling、角色坐标和固定来源；phase 的 `gate_ids` 是 protocol IDs，`native_gate_ids` 是真实 lowering IDs。
- `compiled.json`（`qec-pbc-compiled/1`）、`physical_circuit.json`：全部原语、native dependencies、raw→semantic measurement bindings、detectors 和 observable。
- `platform.json`、`working_destinations.json`、`initial_placement.json`、`initial.json`、`run_metadata.json`：平台、既有 trap 落点、完整34原子初始 placement、不可变初态、seed、解释器、预算和生产源码 SHA256 指纹。metadata/evidence 明确 `initial_placement`、`layout_preparation_time_included` 和未测量的 `upstream_layout_preparation_time_us: null`。
- `plans.json`、`trace.jsonl`、`schedule.json`、`gate_schedule.json`、`phase_schedule.json`：accepted physical plans、实际事件、时间、资源和各协议阶段关联的真实 pulse。
- `fault_audit.json`、`native_reference.stim`、`official_reference.stim`：受限故障模型、reference 对照、decoder 与距离证据。
- `result.json` / `evidence.json`、`checkpoint.json`、`recording.json`、`animation.html`、`index.html`：机器验收、完整终态、原始回放及只读报告。报告数据 schema 为 `qec-canonical-baseline-report/1`；缺失执行记录显示未知，不推断完成。

## 浏览器核对

现有本机服务以 `artifacts/qec-baseline-2026-10-03` 为根目录，默认入口为 [prearranged Z 报告](http://127.0.0.1:8831/prearranged-memory-z-verified/index.html) 与 [prearranged X 报告](http://127.0.0.1:8831/prearranged-memory-x-verified/index.html)。旧 `memory-*-verified` 链接仅是 legacy storage 历史回放。需要自行启动时，在仓库根目录执行：

```powershell
python -m http.server 8831 --bind 127.0.0.1 --directory artifacts/qec-baseline-2026-10-03
```

先 seek 到 t=0，确认17活跃角色已在EZ、17spectators留SZ，页面声明上游布局准备未计时；不应先播放一般SZ初始重排。再选择 round/layer，核对每层六对与本轮 24 对；点击真实 CZ batch 的“定位”查看实际 pulse 中点。展开全部 native gates，选择 MEASURE 或 RESET，核对条数、角色、时刻与 applied 状态，并定位到共用 viewer。Detectors 分别筛选 `temporal` 与 `destructive_readout`，查看 XOR 与终端边界；measurement sidecar 保留 raw、semantic 与实际读出时间。最后拖动共用 viewer 到终点，核对逻辑完成后仍发生了归还至本次初态holders/supports，并结合机器验收中的终态、独立量子 reference 和 exact plan replay 结果查看。

源码指纹覆盖整组 env/strategies/qec_pbc Python 文件，比 baseline 导入路径更宽；每次运行的指纹原样保存，不用当前源码哈希覆盖旧证据。本轮运行期间并行任务改变了 `logical_pauli.py`、`lowering.py`、`magic_injection.py`、`visual_report.py`；当前重新编译的完整canonical/compiled输入和完整初始快照与两份正式产物逐字相等，其余baseline执行、环境、策略和fault-audit源码指纹保持。核对见 `prearranged-verification.json`。历史 storage 运行后的无关 `shor_frontend.py`、`stim_bridge.py` 变更核对保留在旧 `final-verification.json`；该核对不充当新的 prearranged 证据。浏览器记录和截图位于对应证据根目录。
