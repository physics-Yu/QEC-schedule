# 2026-10-04 · 编码 Shor 初始化前缀的并行物理编译

- 状态：COMPLETED
- 用户目标：将巨大编码 native 电路中的可并行模块交给真实编译器，显示按码块放置、共同门脉冲和真实原子运动；统一计算区域，保留 MZ，并在右侧配置独立 magic AOD。
- 本轮范围：首 24 个初始化 / canonical-check functions（2,988 native gates）加首资源函数的 17 RESET / H，共 3,006 门的可追溯并行 DAG；固定 5 μm SLM 候选格点；实际 Executor / VisualRecorder；双 AOD 的限定非交叉工作域、资源和恢复合同。
- 基线：公开分支 codex/d3-shor15-stages，fd7abf38c2a3bde007950283588057d4530b1730。原工作区 HEAD / 其他 dirty 保留。
- 相关规范：[factory](../qec_factory_pipeline.md)、[physics](../physics.md)、[AOD](../aod_backends.md)、[compiler](../compiler_contract.md)、[visualization](../visualization.md)。

## 用户决策与物理假设

- 用户明确取消的是逻辑最近邻限制；任意逻辑配对仍须通过真实移动进入有限 CZ 作用距离，所有旁观原子的额外作用对必须核验。不得改为任意距离直接作用或 pair-addressed 豁免。
- 一个共享 compute 区域（沿用内部 ENTANGLEMENT 能力标签），另有 MZ；无独立 SZ / EZ 分区。
- 5 μm 是 SLM 候选格点间距，并非全部站点都必须占据。6 μm 全局 CZ 半径下密集占据会出现额外 SLM–SLM 对，因此采用格点的稀疏子集放置各码块。
- 新设备是实际 state / holder / operation / resources / trajectory 的扩展；不得用仅画出的第二组轴代替真实独立 AOD。
- 首轮只执行可跟踪 Clifford 前缀；右侧资源的 Clifford 准备 / 运输可验证设备能力，不能称完整 magic-state 工厂或 T 生产。

## 开始时已确认的证据

- 母 native manifest SHA256：16d12bb97b28d49c07b8a28d7a94ea81cf58d1c6fe7e3ee21f2a68fb350adac7。
- 首 2,988 门 raw SHA256：45a3210053ef7f2d9ea497d77e3c828cf861727d6fa672eb4be90fa2ee4c4601。
- 396 投影 raw SHA256：bfdfcd1c3c82c838d59b5f3bc6b29392bd26823119b4c9371038f42e5fcda861。
- 独立理想重排审计：204 physical roles，串行 / per-qubit DAG 重排后全部 canonical stabilizers 相同，396 raw 报告与母包逐项一致。该审计尚非物理编译验收。

## 完成内容

源/template adapter、码块调度器和双设备全局 Executor 已实现。CSS 有向 CNOT 门序与 canonical phase barriers 保留，只去掉独立码块的导出序列化；source native ID、投影报告和 resource Q204..220 身份保持。平台统一 COMPUTE + MZ、固定5 μm候选格点 / 10 μm稀疏占据、每块持久 home holders，3列×4行算法 AOD 与右侧分离资源 AOD；全活动空交点、支撑、连续扫掠及有限6 μm全局 CZ pair 判据保持。

多设备状态、holder、operation、scheduled resources、各设备 transfers、public observation、schema20及恢复完整绑定；LOAD/MOVE/OFFLOAD 能实际同钟并行。RESET/MEASURE/globalSLM switch/CZ 保守全局同步。legacy primary API/schema19保持，实际旧HEAD与新版本分别执行7操作，16events/17snapshots、883.4621125123532 μs；plan、trace、每份snapshot逐字节一致。旧ZZ/XX原始initial快照字节也相同，未冒称重跑其完整长终态。

共用 VisualRecorder/viewer 显示实际已提交世界、13块身份、两设备行列、holder、时间与脉冲。report添加初始放置、29RESET、72H、12对CZ、12MZ读出、两台带载运输、终态七个入口；必须全部producer checks/replay true，且recording SHA与独立audit相同才能生成。母流1.14MB审核packet包含首25完整functions、3245native/429投影，实际只选3006/413，止于首T；省略的母流后缀不称完整交付。Git属性保存packet原始字节。

## 验证

| 检查 | 本轮结果 |
| --- | --- |
| 完整12patch真实切片 | 3006门=1777H/816CZ/96MEASURE/317RESET，413投影，221原子，2AOD，196plans，所有effect恰一次 / DAG完成 / 队列空 / code与logical/aux检查通过 |
| 总模型时间 | 69927.72585501682 μs，包含最终归还；不是实验室标定或全Shor加速比 |
| 原初态重放 | 全部196个实际计划重新提交，完整canonical snapshot bytes相同；非仅比较选定字段 |
| 独立Stim / 几何 | 204算法态约束、全部source/committed413投影一致；68全局CZ脉冲816对、413真实MZ位置、1777H分离、221完整有限坐标；sourceID/kind/trace时刻精确绑定，9401条依赖时序通过 |
| 专项 / 回归 | 54新+180旧=234不同pytest通过；旧3项历史artifact缺失skip另计。peer230等重叠结果不累加，历史215/913不累加 |
| 架构 | 263 modules（59 ENV / 85 strategies / 101 experiments / 18 app），0违规 |
| 浏览器 | 最终12patch实际页七个入口、双带载12+17、RESET/H/CZ/M、终态与合批表通过，console无error，390px无横向溢出；截图和详细命令见小摘要 |
| 单patch / 双patch预览 | 单patch249门/33投影/195plans及双patch资源516门/83投影/196plans全部原初态replay和独立审计通过；不合并计入完整12patch数量 |

实际脉冲批次：{"RESET": 25, "H": 103, "CZ": 68, "MEASURE": 8}。最大同批：{"RESET": 29, "H": 72, "CZ": 12, "MEASURE": 12}。执行767.549507s；summary.wall_seconds=1351.654208699998s，采样在重放和最终检查之后、导出之前，差值不叫纯replay时间，完整导出另确认。

## 保留的失败与修复

- single-patch-attempt1：生成过位于计算/MZ间隙的注册SLM，初始化拒绝，0 committed门；仅注册实际home supports修正，没有放宽区域。
- single-patch-attempt2：新多设备origin registry未完整codec绑定，首plan被PLAN_TAMPERED:aod拒绝，0 committed门；完整origin/terminal registry绑定修正。
- full12-dual-attempt1：新增Platform.aods后附加tuple误用位置参数，SimulationState初始化dict报TypeError；改用aods映射与additional_aods显式关键字。输出目录为空，仅console，0 plans/gates。
- full12-dual-attempt2：大量永远disabled的SLM序列化过慢，26plans/318门后主动停止；无最终checkpoint/replay验收。固定5μm候选格点仍保留，仅实例化永远使用的221home supports；其他候选点不启用、不卸载。
- four-preview：已有完整双patch预览后停止重复CPU任务，70plans/294门，无replay验收。
- 初版静止时序算术把observer浮点尾差约7.28e−12 μs当作运动重叠；改为既有ENV时间容差1e−8 μs，不改距离、扫掠或作用资格。缺Stim依赖和默认GBK读取的工程检查失败均用已有只读依赖/UTF8修正。
- 独立审计的extra H/H、伪wait CZ、观测timestamp/缺旁观原子孔已用反例关闭；报告拒绝跳过replay及stale recording。连续轨迹由真实Executor及完整replay验收，独立工具不声称另一套连续路径证明。
- 首次浏览器聚焦后resize/fullPage把画布420变650像素，旧相机pixel pan未随投影尺寸更新，顶部一排被裁切。fit现按当前CSS尺寸计算并在resize重新聚焦，手工缩放/拖动解除锁定；真实full12 Node与浏览器420/650、390/320及CZ中点通过，物理recording字节不变。失败与最终截图均保留。

所有尝试保留于 `artifacts/qec-parallel-prefix-2026-10-04`，失败/停止记录不记为成功。问题ID与当前边界见[model audit](../model_audit.md)。

## 复现与边界

入口：[源码/复现](../../docs/qec_native_parallel_prefix.md)、[多设备合同](../../docs/multi_aod_contract.md)、[可移植小摘要](../../references/qec_pbc_validation/native_parallel_physical_2026_10_04.json)。从checked-in packet运行CLI→独立audit→serve，命令均在摘要与文档。完整run `full12-dual-sparse-slm-attempt1`，source mother SHA `16d12bb97b28d49c07b8a28d7a94ea81cf58d1c6fe7e3ee21f2a68fb350adac7`；Python3.12.14/NumPy2.5.3/Stim1.15.0/pytest8.4.2。大型plans/trace/snapshot及运行失败档案留本地ignored；Git保存实现、原始小packet、摘要与RAG。

这是已完成的 bounded ideal Clifford physical 编译/可视化阶段。首T前资源为一个未编码物理+及16零载体，没有magic库存或工厂输出；未实现完整physical Shor、tracked T/Born、噪声/decoder/FT，未承诺一般cross-envelope路由。下一主线保持factory-first F1：真实15-to-1生产、accept/reject/cleanup/replenish、同载态唯一库存与单T完整channel参考闭环，再接tracked Executor、逐周期噪声、MSC与完整算法。

实施仅在attached managed worktree `C:/Users/yuyqp/.codex/worktrees/d3-shor15-stage/QEC-schedule 2`；原工作区HEAD仍9e28b2e、36个tracked dirty字节不变。本轮涉及这些原有dirty核心文件，因此交付于该隔离checkout，不全文件回写原目录。阶段发布沿用draft PR#3，无merge；独立fetch/tree/blob发布回执待追加。

## 发布回执

能力提交[2b6a763](https://github.com/physics-Yu/QEC-schedule/commit/2b6a76391f33b20bc2ca76fa20a4a71bbbacc6c8)已发布；独立Git fetch核对parent/tree、全部60个blob与staged bytes精确相同。工作树已匹配新commit并干净。PR#3已更新最终描述，仍draft/open/unmerged；pushurl=DISABLED保持，使用connector Git-data。最终RAG64/52/140、58/58检索和11/11换行可移植通过，3旧artifact skip不记PASS。详见[可移植发布回执](../../references/qec_pbc_validation/native_parallel_publication_2026_10_04.json)。

收尾更正：原目录另一任务在发布期间追加了单工厂到单T设计交接；早先36dirty全字节相同是当时捕获值，最后重验其余35文件与HEAD仍相同。该handoff并行更新完整保留，本任务没有回写任何原目录tracked文件。当前实现仍全部在managed worktree；工厂设计说明不新增F1/F2运行PASS。
