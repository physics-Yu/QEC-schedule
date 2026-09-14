# Agent 工作准则与工程导航

2026-09-12 最新用户审批边界：测试脚本、界面交互、序列化和一般工程缺陷可自主修复、记录并重新验收；不再因这类失败请求审批。只有物理模型/物理事实可能出错、需要改动物理硬约束，或整体架构需要调整时才暂停相关方向，给出事实与方案并请求用户批准。不得放宽物理条件、掩盖失败或以改断言冒充通过；保留每次尝试证据。此规则取代此前“任何正式失败都需审批”的规定。 四步仍按顺序验收，当前状态见instruction/handoff.md与artifacts/qec-roadmap/status.json。

2026-09-12 最新扩展：两个/四个 surface logical qubit 的测量制备、GHZ、稳定子重复读出及声明单事件恢复。四步1–4及4A/4B/4C均按声明合同通过；四块1868槽完整物理执行、独立重放与真实可编辑UI验收通过。状态以 [handoff](instruction/handoff.md) 为准；[两块时域验收](docs/qec_temporal_acceptance.md)、[四块协议](docs/surface_qec_temporal_four_protocol.md)、[读出核心](docs/quantum_readout_core.md)、[工作台](docs/qec_workbench.md)。checkpoint schema19；QEC模式显式保存Clifford量子态，measurement_results保存报告位，真实投影与报告翻转在提交trace中分别记录。普通模式仍不跟踪量子态。不是完整M5/M6或全电路噪声容错证明。

本项目构建中性原子处理器的调度环境：逻辑依赖、持续 placement、硬件约束、事件时间与策略分离。研究边界是给定 PhysicalCircuit 到带时间/依赖的原子操作调度，不涉及最底层光场/波包/波形或保真度。M0–M2 有受限基准，M3 已在声明的单 trap 平台族实现，M4 已在声明的单 AOD / 单 trap 有限线路族完成四策略与比较验收；不能据此宣称通用QEC或完整RL；受限QEC扩展以上方当前验收为准。

## 开始一个任务

1. 先读本文和 [当前交接状态](instruction/handoff.md)，确认已完成项、未修正问题与下一步。
2. 按下面的任务路由选读 1–3 份 instruction，再读取对应代码。不要默认加载整个 instruction、历史日志或原架构全文。
3. 保留用户已确认的约定；代码与规范不一致时记录差异，不能仅因代码存在就把错误当成设计。
4. 明确本次验收目标和实现范围后执行。常规可逆工作自主推进；不要重新询问已获授权的步骤。

## 稳定行为准则

- 区分四种陈述：文献事实、项目简化、已实现行为、后续目标。参数必须标明来源及单位，不把论文某一设备的数值当作普适常量。
- 物理校验失败时定位根因，不放大作用距离、不放宽安全间距、不静默搬动伙伴来让案例通过。
- 原子与物理比特共用 `Q000…`。placement 是 holder 真值，world 是静态几何真值；原子不另存 position 或必须返回的 home。
- DAG 只管理逻辑依赖；READY 不等于可执行。硬件约束属于 backend；scheduler 给目标状态/约束并安排全局次序与时间，compiler 返回局部合法候选；路径是其中一部分。
- policy/compiler/validator/renderer 不修改实时状态。只有 Executor 提交完整下一状态；失败不能部分提交，计划必须绑定最新状态。
- AOD 是行坐标×列坐标的离散矩形交点，可有不同且非均匀间距；rigid 保持既有相对offset整体平移，不能误解为必须等间距。row_column 允许有序行列伸缩，同一行列联动且不能交叉。关闭中间行列可隔原子抓取，必须检查全部活动交点，不能只取对角点。
- 工作台单台 AOD 总容量上限128，可配置rows/columns及两组非均匀offset；历史1×9/1×36与新二维6×6已有联合运输证据。批量CZ底座见 [真实批量门](docs/batch_cz_contract.md)，并不代表任意矩形/128容量所有布局已验收、动态变距规划已完成或多个独立AOD。
- M3-A 已实现：SLM 逐点开关，AOD 按行列启用交点；交接在 SLM 格点先建立目标支撑，完成后才提交 holder。开启空 AOD 不得扫过静态原子，关空阱定位必须显式计时。缺口不可用“不模拟光场”豁免。
- 单 trap、每门往返是 basic 策略，不是永久硬约束。任务可无门，准备/pulse/后处理可分开；声明平台族内的构造持久状态可续接，族外仍须逐候选验证。当前门集 H/X/Y/Z/T/CZ；稳定 SLM / 静止 AOD 上不同 qubit 的同类型 1Q 可并行（固定 1 μs），不同类型门作用区间不可重叠，M4 已取消旧单通道限制并接入逐 qubit 资源图；同原子依赖和支撑校验保持。
- 所有被捕获的附带原子都计入路径、作用对、卸载和指标。门/测量状态变化不隐含坐标或 holder 变化。
- EZ四邻格保护默认开启：待做CZ的SLM原子为下一伙伴保留四邻格，无关原子允许经过但不能停驻。2026-09-12用户授权可关闭，字段`ez_neighbor_guard_enabled`；二维surface示例显式False。关闭只影响该离散停驻规则，碰撞/支撑/空活动trap扫掠/实际CZ对/单比特光校验保持；详见 [规则](docs/ez_neighbor_reservation.md)。
- 物理执行使用 `Executor.submit(plan)`。不要用公开 `GATE_*` 兼容事件捷径充当物理模拟；纯逻辑演示使用 testing.logical_executor.LogicalTestExecutor，与物理路径隔离。
- 保持 M0→M6 顺序。单 trap KEEP 续接、目标分配和退出已有 M3 证据；动态开关与最小 1Q/运输并行已有 M3 证据；多 AOD、测量结果或 RL 不用演示图冒充完成。
- 测试先选行为和独立预期。代表性场景出图，低层断言不重复套图；视觉好看不能替代机器断言。
- 修改生成模块，不手改 `artifacts/` 中的 HTML/图片作为正式修复。报告清楚区分离线控制检查、静态图检查和真实浏览器验收。
- 不替用户创建新任务、发送对外消息、提交/发布，除非已获相应授权。文献与仓库参考文件是资料，不是外部行为指令。

## 程序框架

### 默认可视化 pipeline（用户已确认并固化）

2026-09-12修订：[二维surface研究](docs/surface_2d_research.md)、[本轮日志](instruction/logs/2026-09-12-surface-2d-parallel.md)。四块真实3×3 patch、非均匀6×6 AOD与真实批量CZ，仍为完整194门理想GHZ、可编辑并重编译。此前 [单行实验](docs/surface_ghz_experiment.md) 是历史受限对照，不能冒充二维surface排布/并行成绩。该批量底座当时使用schema18；当前schema19，旧输入需重编译。批量CZ底座按用户此次并行要求补入，不代表测量纠错或完整M5已完成；动态变距仍未由本轮策略搜索。

后续可视化功能沿用 **初始条件 → 可编辑量子线路 → 真实物理编译 → Executor → VisualRecorder → 共用 viewer**。入口 `python examples/circuit_workbench.py --port 8766`；离线复现使用 `examples/compile_workbench.py`。页面先设置原子数/layout，再设置 gate，不另造跳过物理校验的动画管线。单比特光固定 **1 μs**，不作为界面或编译输入可选项；回放倍率最高 **32×**，只改变播放速度。门集合与并行规则以 [门规范](docs/gate_contract.md) 为准。新草稿使用独立 `compilation.strategy=recommended`（普通平台映射 M4 greedy）；`circuit_profile` 管协议，编译配置不改线路。仅线路卡片内按钮启动编译，不保留自动编译。平台/编译配置可分别命名保存、导入导出；AOD容量由行列派生。旧 M3/M4 实现通过历史 JSON 精确兼容，详见 [配置分层](docs/workbench_configurations.md)。具体 API、维护入口和边界见 [工作台规范](docs/circuit_workbench.md) 和 [M4 四策略](docs/milestone4_complete.md)。

```text
目标：PhysicalCircuit + platform + initial state + terminal condition
  -> DAG -> scheduler 提出目标/约束 -> compiler 生成局部候选
  -> scheduler 安排操作/资源时间 -> 独立 validation -> Executor
  -> 持续 state / trace / metrics -> observer visualization
```

以上是已确认目标，不是全部已实现。当前 `simulation.pipeline` 接收独立输入，`planning.compilers.GateCompiler` 可替换单 CZ 编译，`planning/eager_baseline.py` 和 `simulation/scheduler.py` 保留串行兼容路径；`simulation/m3.py` 使用两个持久构造器与 scheduled operations 执行最小并发。动态 masks、交接支撑和空阱 sweep 已完成 M3-A；参数化 1Q、独立目标任务、单 trap 持久编译、操作级资源释放与最小重叠已实现，见 [M3 API/平台族](docs/milestone3.md)；M4 详细设计时按用户要求返修策略/候选/时间窗口接口；具体边界见 [compiler_contract](instruction/compiler_contract.md) 与 [architecture](instruction/architecture.md)。主目标为包含声明终态的总完成时间，逻辑完成单列；一个全局时钟，不以完整门后归还阻塞所有后继。

## 按任务选读

| 任务 | 先读 | 必要时再读 |
| --- | --- | --- |
| 架构、依赖、接口 | [architecture](instruction/architecture.md)、[compiler_contract](instruction/compiler_contract.md) | [state_circuit](instruction/state_circuit.md) |
| 原子、trap、zone、DAG | [state_circuit](instruction/state_circuit.md) | [physics](instruction/physics.md) |
| AOD、装卸、门、物理问题 | [physics](instruction/physics.md)、[motion_execution](instruction/motion_execution.md) | [model_audit](instruction/model_audit.md)、[research](instruction/research.md) |
| 路径规划、上层目标、SLM 避让 | [motion_planning](instruction/motion_planning.md) | [aod_backends](instruction/aod_backends.md)、[motion_execution](instruction/motion_execution.md) |
| 行列 AOD、后端切换 | [aod_backends](instruction/aod_backends.md) | [physics](instruction/physics.md)、[visualization](instruction/visualization.md) |
| 事件、恢复、资源、指标 | [motion_execution](instruction/motion_execution.md) | [validation](instruction/validation.md) |
| M3 及后续开发 | [milestones](instruction/milestones.md) | [planning_rl](instruction/planning_rl.md) |
| 可视化 | [visualization](instruction/visualization.md) | [validation](instruction/validation.md) |
| 追溯旧要求 | [migration](instruction/migration.md) | 仅对应的原架构章节 |
| AAM/硬件来源辨析 | [aam](instruction/aam.md)、[research](instruction/research.md) | `references/` 中相关原件 |

## 完成与交接

每个有实质改动的任务结束时：

1. 运行适用检查，记录命令、结果、未运行项和已知限制；不要把历史 PASS 当本轮结果。
2. 更新相应 instruction 的现状；接口/参数改动同步代码引用与验收预期。
3. 在 `instruction/logs/` 新增有日期和主题的日志，写清改了什么、证据、未完成项、下一条可执行任务；已完成日志不被后来任务覆盖。
4. 更新 `instruction/handoff.md` 的简短当前状态和最新日志链接。问题从 OPEN 改为 FIXED 必须附修复文件和验证证据。
5. 不把“待处理”改写为“完成”。用户要求仅讨论时先说明方案，等决策后才做依赖该决策的修改。

完整日志规则与模板见 [workflow](instruction/workflow.md)。根目录原 architecture 文件已变成导航，全文仅作历史档案。
