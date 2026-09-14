# 按需读取的工程规范

开始任务只读 [agent.md](../agent.md) 和 [handoff.md](handoff.md)，然后从下表选与本次任务有关的文档。不要默认读取全部 instruction、日志或原文档案。

## 任务路由

| 文档 | 回答的问题 | 何时读取 |
| --- | --- | --- |
| [compiler_contract](compiler_contract.md) | 已确认的 circuit→任务→局部编译→调度→原子操作契约是什么？ | M3 接口、职责与并发设计 |
| [motion_planning](motion_planning.md) | 路线候选、扫掠和搜索边界是什么？ | 改局部路径 |
| [architecture](architecture.md) | 有哪些实际模块、接口和依赖边界？ | 改架构或定位代码 |
| [state_circuit](state_circuit.md) | Q 身份、holder、坐标、DAG、快照谁是真值？ | 改数据模型/电路/恢复 |
| [physics](physics.md) | 装载、运输、作用、测量究竟发生什么？哪些是假设？ | 改任何物理语义 |
| [aod_backends](aod_backends.md) | rigid / row_column 如何选择，行列伸缩有哪些约束？ | 改 AOD 几何、计时、捕获、轨迹或后端 |
| [motion_execution](motion_execution.md) | 怎样编译计划、提交事件、预约资源、计算指标？ | 改 compiler/executor 或 M2 |
| [planning_rl](planning_rl.md) | 候选与策略如何分层，KEEP/奖励如何设计？ | M2–M6 策略扩展 |
| [milestones](milestones.md) | 原 M0–M6 要做什么、下一步如何验收？ | 开始下一阶段 |
| [validation](validation.md) | 哪些检查证明什么，如何记录失败？ | 设计验收或解释测试结果 |
| [visualization](visualization.md) | 页面如何自动生成、符号和交互如何统一？ | 改 UI/报告 |
| [model_audit](model_audit.md) | 哪些是简化、限制，哪些是真正 OPEN 缺口？ | 判断模型正确性/开工前排雷 |
| [research](research.md) | 一手资料支持哪些结论，哪些不能照搬？ | 追溯来源或扩展物理能力 |
| [aam](aam.md) | AAM/QN 原抽象怎样映射到当前连续坐标？ | 使用本地硬件资料 |
| [workflow](workflow.md) | 如何记日志、更新状态、跨任务交接？ | 开始/结束实质任务 |
| [migration](migration.md) | 原 architecture 89 章去了哪里？ | 追溯旧要求 |

## 当前状态与历史

- [当前交接摘要](handoff.md)：只放现状、关键证据、OPEN 问题、下一任务。
- [2026-09-11 项目总览快照](../docs/project_status_2026-09-11.md)：集中查阅已实现能力、用户决策、源码入口、历史验收、限制和跨机器复现；不替代各领域规范。
- [日志索引](logs/README.md)：详细历史与可复现审计。
- [独立任务 API](../docs/task_program.md)：M3-B TaskIntent/TaskProgram、零门运输、拆分执行、schema 13 与复现。
- [M3 完成说明](../docs/milestone3.md)：持久构造、操作并行、平台族、两种 compiler、256 原子与 M4 返修点。
- [M2 实例](../docs/milestone2.md)：支持的电路族、多周期独立预期、恢复与运行入口。
- [M1 实例](../docs/milestone1.md)：保留具体案例参数、独立指标与运行命令，不复制成第二份规范。
- [原 architecture 档案](references/architecture_v2_original.md)、[AAM 原文](references/aam_original.md)、[Qiuniu ISA PDF](references/isa-qiuniu-near-self-contained.pdf)：原件保留，只有追溯来源时才读取。

## 如何解读

用户当前指令和已确认约定优先。文献事实、项目简化、当前实现、未来设计必须分开；代码是现状证据，不是把错误合法化的理由。`model_audit` 中 OPEN 不等于已修复，枚举/目录建议不等于已有可执行功能。

通用约定只维护一份：目标接口在 compiler_contract，视觉在 visualization，物理在 physics，当前问题在 model_audit，阶段与验收顺序在 milestones。日志引用它们，不复制整篇。

产物放 `artifacts/`，不纳入规范目录；原件放 references，不修改原文来掩盖差异。改名后检查链接，实质任务结束更新 handoff 和新增日志。
