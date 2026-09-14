# 原 architecture 章节迁移对照

原文完整归档为 [architecture_v2_original.md](references/architecture_v2_original.md)，SHA-256：

`9862cc2c58f0aba79b255159b8f86b19e5e69e45fd662dda48df63574eb8d869`

迁移覆盖原文 1–89 全部顶层章节；子章节随所属顶层迁移。原文作为历史来源，不再要求每次读取；以下映射不是逐字复制，实际行为以当前规范、用户后续决策和代码审计为准。

## 明确替代或收敛的旧要求

- §7/§66 的 Atom/physical_qubit_id 双身份：统一 Q 编号；原文顶部已有用户修订，拆分后不再保留误导性代码示例。
- §6/§8/§30 的重复 occupancy/position 字段示例：holder 为真值，占据和位置派生，不创建多套可写状态。
- §56 的示例分区方向：使用用户确认的从上到下 storage/entanglement/measurement。
- §65–79 的逐测试图片、默认重复小布局：改为机器断言 + 有区别的代表性场景；M0 与 M1 分别使用实际报告入口。
- §70/§79/§87 提前要求 KEEP/多门图：按原 M2/M3 顺序实现，不将未实现能力放进 M0/M1 验收。
- §28 slot 是规划工具：不能靠 slot ID 代替真实几何/激光冲突验证。
- §33/§34 的 decision/Gym 示例：列为未来接口，不假称当前 `Executor.run()` 等同完整调度循环。
- §67 所有视觉属性配置化：保留为方向；当前 CSS 与 Canvas 装饰仍部分在模板内，不能声称已全部抽离。
- 图形方框/原子字母示例：由当前可视化规范中的等大小 SLM/AOD 圆环、圆点/菱形、统一 Q 标签与图层开关替代。

## 2026-09-10 后续决策的规范落点

保留以下 89 章历史映射和原件字节；最新用户决定补充于维护文档，不反写档案：

- 研究边界收敛到给定 PhysicalCircuit 的调度，不要求底层光场/波形/保真度：见 [compiler_contract](compiler_contract.md)。
- 固定启用集合扩展为 SLM 逐点/AOD 行列动态控制，交接及活动空阱避碰为硬逻辑：见 [physics](physics.md)。原占据模型不能替代 enabled 状态。
- 原动作枚举扩展成目标任务和独立操作依赖；合法持久状态可续接，一个门不等于一个往返计划：见 [planning_rl](planning_rl.md)。
- 一个全局时钟，逻辑完成、分资源释放、含终态的程序完成分清；M3 纳入参数化 1Q 和最小 1Q/运输重叠，M4 全局策略，M5 batch，M6 RL：见 [milestones](milestones.md)。
- 已有实现与已确认待实现严格区分：见 [model_audit](model_audit.md) GAP-001–009。旧说明中的“未实现 KEEP”须按终态执行和通用策略分别理解。

## 逐章去向

| 原章节 | 标题 | 主去向 | 处理 |
| --- | --- | --- | --- |
| 1 | V2.0 重新定义问题 | [architecture](architecture.md) | 按现有模块与未来接口区分整理 |
| 2 | V2.0 设计原则 | [agent](../agent.md) | 保留职责与不变量；执行状态见具体模块 |
| 3 | 总体架构 | [architecture](architecture.md) | 按现有模块与未来接口区分整理 |
| 4 | 一次决策到底发生什么 | [architecture](architecture.md) | 按现有模块与未来接口区分整理 |
| 5 | Circuit 层：Dynamic Gate DAG | [state_circuit](state_circuit.md) | 保留；身份/重复状态字段以统一 Q 与 holder 真值替代 |
| 6 | World 层：持续演化的物理世界 | [state_circuit](state_circuit.md) | 保留；身份/重复状态字段以统一 Q 与 holder 真值替代 |
| 7 | Atom 模型 | [state_circuit](state_circuit.md) | 保留；身份/重复状态字段以统一 Q 与 holder 真值替代 |
| 8 | Placement 模型 | [state_circuit](state_circuit.md) | 保留；身份/重复状态字段以统一 Q 与 holder 真值替代 |
| 9 | Hardware 层 | [physics](physics.md) | 保留物理意图；补充连续坐标及简化边界 |
| 10 | AOD Backend | [physics](physics.md) | 保留物理意图；补充连续坐标及简化边界 |
| 11 | Capture Closure | [physics](physics.md) | 保留物理意图；补充连续坐标及简化边界 |
| 12 | Motion 层重新划分 | [motion_execution](motion_execution.md) | 保留；标明当前实际 API 和未实现能力 |
| 13 | High-Level Intent | [motion_execution](motion_execution.md) | 保留；标明当前实际 API 和未实现能力 |
| 14 | EndDisposition | [motion_execution](motion_execution.md) | 保留；标明当前实际 API 和未实现能力 |
| 15 | Motion Compiler | [motion_execution](motion_execution.md) | 保留；标明当前实际 API 和未实现能力 |
| 16 | CompiledPlan | [motion_execution](motion_execution.md) | 保留；标明当前实际 API 和未实现能力 |
| 17 | Operation 层 | [motion_execution](motion_execution.md) | 保留；标明当前实际 API 和未实现能力 |
| 18 | AOD Motion 的 V2.0 表达 | [motion_execution](motion_execution.md) | 保留；标明当前实际 API 和未实现能力 |
| 19 | 为什么不要固定“移动回来” | [planning_rl](planning_rl.md) | 保留为分阶段设计；除 eager 外尚未实现 |
| 20 | Return Decision 的正确所属层 | [planning_rl](planning_rl.md) | 保留为分阶段设计；除 eager 外尚未实现 |
| 21 | Planning 层 | [planning_rl](planning_rl.md) | 保留为分阶段设计；除 eager 外尚未实现 |
| 22 | Candidate 不等于 Gate | [planning_rl](planning_rl.md) | 保留为分阶段设计；除 eager 外尚未实现 |
| 23 | Candidate Generator | [planning_rl](planning_rl.md) | 保留为分阶段设计；除 eager 外尚未实现 |
| 24 | Candidate 数量必须受控 | [planning_rl](planning_rl.md) | 保留为分阶段设计；除 eager 外尚未实现 |
| 25 | Gate Batch | [planning_rl](planning_rl.md) | 保留为分阶段设计；除 eager 外尚未实现 |
| 26 | Entanglement Zone | [physics](physics.md) | 保留物理意图；补充连续坐标及简化边界 |
| 27 | 2Q Laser Effect | [physics](physics.md) | 保留物理意图；补充连续坐标及简化边界 |
| 28 | Interaction Placement | [physics](physics.md) | 保留物理意图；补充连续坐标及简化边界 |
| 29 | Simulation 层 | [motion_execution](motion_execution.md) | 保留；标明当前实际 API 和未实现能力 |
| 30 | SimulationState | [state_circuit](state_circuit.md) | 保留；身份/重复状态字段以统一 Q 与 holder 真值替代 |
| 31 | State Version | [state_circuit](state_circuit.md) | 保留；身份/重复状态字段以统一 Q 与 holder 真值替代 |
| 32 | Event-driven Execution | [motion_execution](motion_execution.md) | 保留；标明当前实际 API 和未实现能力 |
| 33 | Decision Point | [motion_execution](motion_execution.md) | 保留；标明当前实际 API 和未实现能力 |
| 34 | Environment Step | [motion_execution](motion_execution.md) | 保留；标明当前实际 API 和未实现能力 |
| 35 | 三种 Scheduler 基线 | [planning_rl](planning_rl.md) | 保留为分阶段设计；除 eager 外尚未实现 |
| 36 | Return Cost Feature | [planning_rl](planning_rl.md) | 保留为分阶段设计；除 eager 外尚未实现 |
| 37 | RL Action Space | [planning_rl](planning_rl.md) | 保留为分阶段设计；除 eager 外尚未实现 |
| 38 | 分层 RL 的未来接口 | [planning_rl](planning_rl.md) | 保留为分阶段设计；除 eager 外尚未实现 |
| 39 | Observation | [planning_rl](planning_rl.md) | 保留为分阶段设计；除 eager 外尚未实现 |
| 40 | 为什么 Candidate-based Observation 更合适 | [planning_rl](planning_rl.md) | 保留为分阶段设计；除 eager 外尚未实现 |
| 41 | Reward | [planning_rl](planning_rl.md) | 保留为分阶段设计；除 eager 外尚未实现 |
| 42 | 不要直接奖励 KEEP | [planning_rl](planning_rl.md) | 保留为分阶段设计；除 eager 外尚未实现 |
| 43 | Resource Model | [motion_execution](motion_execution.md) | 保留；标明当前实际 API 和未实现能力 |
| 44 | Reservation | [motion_execution](motion_execution.md) | 保留；标明当前实际 API 和未实现能力 |
| 45 | Concurrency | [motion_execution](motion_execution.md) | 保留；标明当前实际 API 和未实现能力 |
| 46 | 冲突检测重新定位 | [motion_execution](motion_execution.md) | 保留；标明当前实际 API 和未实现能力 |
| 47 | Hardware Validation | [physics](physics.md) | 保留物理意图；补充连续坐标及简化边界 |
| 48 | Exact Validation | [motion_execution](motion_execution.md) | 保留；标明当前实际 API 和未实现能力 |
| 49 | Deadlock | [motion_execution](motion_execution.md) | 保留；标明当前实际 API 和未实现能力 |
| 50 | Trace | [motion_execution](motion_execution.md) | 保留 trace/metrics；明确当前口径与 future 字段 |
| 51 | Visualization | [visualization](visualization.md) | 合并到现有自动生成规范；当前符号与开关优先 |
| 52 | V2.0 推荐目录 | [architecture](architecture.md) | 按现有模块与未来接口区分整理 |
| 53 | 目录依赖规则 | [architecture](architecture.md) | 按现有模块与未来接口区分整理 |
| 54 | Config 与 State | [architecture](architecture.md) | 按现有模块与未来接口区分整理 |
| 55 | 推荐配置 | [architecture](architecture.md) | 按现有模块与未来接口区分整理 |
| 56 | 示例配置 | [architecture](architecture.md) | 按现有模块与未来接口区分整理 |
| 57 | Milestone 0：架构骨架 | [milestones](milestones.md) | M0–M6 原顺序保留；多门/KEEP 演示回到对应阶段 |
| 58 | Milestone 1：单 Gate Eager Baseline | [milestones](milestones.md) | M0–M6 原顺序保留；多门/KEEP 演示回到对应阶段 |
| 59 | Milestone 2：连续 Circuit | [milestones](milestones.md) | M0–M6 原顺序保留；多门/KEEP 演示回到对应阶段 |
| 60 | Milestone 3：Dynamic Placement | [milestones](milestones.md) | M0–M6 原顺序保留；多门/KEEP 演示回到对应阶段 |
| 61 | Milestone 4：Lookahead / Greedy | [milestones](milestones.md) | M0–M6 原顺序保留；多门/KEEP 演示回到对应阶段 |
| 62 | Milestone 5：Batch Gate | [milestones](milestones.md) | M0–M6 原顺序保留；多门/KEEP 演示回到对应阶段 |
| 63 | Milestone 6：RL | [milestones](milestones.md) | M0–M6 原顺序保留；多门/KEEP 演示回到对应阶段 |
| 64 | 第一版明确不做的事情 | [milestones](milestones.md) | M0–M6 原顺序保留；多门/KEEP 演示回到对应阶段 |
| 65 | 测试与验收策略：Visual-First Acceptance | [validation](validation.md) | 保留有证据验收；逐测试套图与未实现功能验收要求被替代 |
| 66 | Visual Test Renderer | [visualization](visualization.md) | 合并到现有自动生成规范；当前符号与开关优先 |
| 67 | VisualTheme：允许快速调整美术资源 | [visualization](visualization.md) | 合并到现有自动生成规范；当前符号与开关优先 |
| 68 | Visual Acceptance Mode | [validation](validation.md) | 保留有证据验收；逐测试套图与未实现功能验收要求被替代 |
| 69 | 单元测试验收模板 | [validation](validation.md) | 保留有证据验收；逐测试套图与未实现功能验收要求被替代 |
| 70 | 必须覆盖的 Visual Unit Tests | [validation](validation.md) | 保留有证据验收；逐测试套图与未实现功能验收要求被替代 |
| 71 | 场景测试：优先动画验收 | [validation](validation.md) | 保留有证据验收；逐测试套图与未实现功能验收要求被替代 |
| 72 | Visual Regression Test | [validation](validation.md) | 保留有证据验收；逐测试套图与未实现功能验收要求被替代 |
| 73 | Failure Visualization | [validation](validation.md) | 保留有证据验收；逐测试套图与未实现功能验收要求被替代 |
| 74 | Test Report 首页 | [validation](validation.md) | 保留有证据验收；逐测试套图与未实现功能验收要求被替代 |
| 75 | 新的验收定义 | [validation](validation.md) | 保留有证据验收；逐测试套图与未实现功能验收要求被替代 |
| 76 | Milestone 验收方式调整 | [milestones](milestones.md) | M0–M6 原顺序保留；多门/KEEP 演示回到对应阶段 |
| 77 | 开发循环 | [workflow](workflow.md) | 整理为可交接工作循环 |
| 78 | Codex 的新增验收要求 | [validation](validation.md) | 保留有证据验收；逐测试套图与未实现功能验收要求被替代 |
| 79 | 最小 Visual Acceptance Demo | [milestones](milestones.md) | M0–M6 原顺序保留；多门/KEEP 演示回到对应阶段 |
| 80 | Metrics | [motion_execution](motion_execution.md) | 保留 trace/metrics；明确当前口径与 future 字段 |
| 81 | Debugging 输出 | [motion_execution](motion_execution.md) | 保留 trace/metrics；明确当前口径与 future 字段 |
| 82 | Candidate 编译失败也要记录 | [planning_rl](planning_rl.md) | 保留为分阶段设计；除 eager 外尚未实现 |
| 83 | 对旧设计的关键调整 | [agent](../agent.md) | 保留职责与不变量；执行状态见具体模块 |
| 84 | 关键接口总览 | [architecture](architecture.md) | 按现有模块与未来接口区分整理 |
| 85 | 工程不变量 | [agent](../agent.md) | 保留职责与不变量；执行状态见具体模块 |
| 86 | Codex 实现要求 | [agent](../agent.md) | 保留职责与不变量；执行状态见具体模块 |
| 87 | 最小可运行 Demo | [milestones](milestones.md) | M0–M6 原顺序保留；多门/KEEP 演示回到对应阶段 |
| 88 | 最终执行模型 | [architecture](architecture.md) | 按现有模块与未来接口区分整理 |
| 89 | 最终架构判断 | [architecture](architecture.md) | 按现有模块与未来接口区分整理 |
