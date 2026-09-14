# 2026-09-10 · 调度研究边界与物理契约更新

- 状态：COMPLETED（本轮文档任务完成；M3 未完成）。
- 用户目标：实现前，先将 milestone、物理和接口 instruction 按已确认方向和文献核对结果写清并同步。
- 开始基线：schema 9；single_trap/legacy_eager 编译接口、通用 Program 和 KEEP_LOADED 终态底座；仍仅 CZ 串行执行。
- 本轮范围：更新/新增 27 份 Markdown（含入口、规范、案例范围说明及本日志/索引）。不修改源码、测试、配置、历史日志正文或原始参考资料，不提交或发布。

## 完成内容

| 维护范围 | 本轮同步内容 |
| --- | --- |
| [compiler_contract](../compiler_contract.md)（新增） | 研究边界；目标状态/约束与局部候选；任务/操作/gate 分离；单一时钟、资源释放、终止条件、失败与条件保证 |
| [physics](../physics.md)、[state_circuit](../state_circuit.md) | 动态 SLM/AOD 开关、完整活动交点、格点交接支撑、空阱硬避碰、参数化 U3/别名与 SLM 1Q 临时规则 |
| [milestones](../milestones.md)、[planning_rl](../planning_rl.md) | M3-A 至 F 施工依赖；最小 1Q/运输重叠不拖到 M5；M4 全局成本与 M5/M6 范围 |
| [architecture](../architecture.md)、[motion_execution](../motion_execution.md)、[motion_planning](../motion_planning.md) | 现有 API 与目标 API 分列，持续起态、操作区间、指纹/轨迹/并发恢复需要一起扩展 |
| [aod_backends](../aod_backends.md)、[aam](../aam.md) | rigid 几何与可变启用分离；保持轴身份/顺序/间距；原占据规则不替代 enabled 和交接语义 |
| [research](../research.md) | 补 R2/R4/R5 的证据边界，新增 R9 DPQA 与 R10 Weaver；项目决定与实验事实对照 |
| [model_audit](../model_audit.md)、[validation](../validation.md) | A-004 从可沿用简化改 OPEN；新增 GAP-001–009 与具体正反例；没有关闭实现缺口 |
| [visualization](../visualization.md) 及 docs 五份说明 | 真正启用/交接/并行记录的目标；固定资源/类别 schedule 保留时序；旧数字与显示规模检查限定范围 |
| agent、README、旧架构导航、instruction 索引、migration、handoff、日志索引 | 统一路由与下一任务，保留 89 章历史映射和原件 |

AGENTS.md 继续只作发现入口，workflow.md 的一般工作规则无需改动。历史报告配置与数值保留，仅对维护中的案例说明补充当前适用范围。

## 文献核对与明确取舍

- R2 Methods 支持 AOD/SLM 原子局域 1Q，采用独立 Raman 资源；暂限稳定 SLM 和默认单局域通道是项目选择，不能说 AOD 物理上做不了 1Q。
- R2 转移采用对齐与阱深 ramp，并非普遍二值 SLM 关灯协议。SLM 逐点开关与完成事件提交 holder 是用户指定的调度抽象；预设交接时间含稳定余量。
- R4 支持移动光势影响原子的背景；活动空 AOD 对静态原子硬避让来自用户要求，不宣称论文证明所有穿越必然失稳。
- R5 CZ/U3、行列交点与复用提供输入和架构参考；装卸次数不是跨策略常量，scheduler 主目标是含相同终态要求的总完成时间。
- R9 的有条件逐门构造不证明任意有限分区布局可行；需要声明和验证自己的平台族。
- R10 的独立物理原语提供 IR 参考，但其顺序 annotations 与门关联；本项目进一步采用独立目标任务，不声称直接移植现成接口。

来源 URL、版本和定位统一保存在 research.md，不把本文当第二份物理规范。没有改变演示硬件参数或复制文献数值为默认成本。

## 验证

命令：`python artifacts/instruction-update/check_docs.py`。

- 检查 29 份入口/维护文档及本轮日志/索引的相对文件链接和 Markdown 标题锚点，无失效项；具体数量见生成报告。
- 与开始时 SHA-256 清单比较，114 个保护文件均未改变（源码、测试、配置、原件及既有日志正文；日志索引允许更新）。
- 原 architecture 档案 SHA-256 仍为 `9862cc2c58f0aba79b255159b8f86b19e5e69e45fd662dda48df63574eb8d869`。
- 逐项检查新增要求与当前代码的分界：GateCompiler 仍接受 ExecuteGateBatchIntent；PhysicalGate 尚无角度字段；SLM enabled 仍为静态属性；单 plan 执行和原 schema 9 没有变化。
- 人工检查残留旧结论，修正根 README/AAM 的“全 SZ 准备未实现”、路线文档“当前 schema 7”、KEEP 终态与通用策略混淆，以及把空 AOD sweep 缺失当永久简化的表述。
- 不运行物理功能/浏览器测试：本轮没有代码、输入参数或视觉生成模块变化。历史 202 passed 和七组 Node PASS 仅保留其原实现日志，不用于证明新契约。

检查脚本与 before/docs-before 哈希清单、最终 report.json 位于 artifacts/instruction-update/；这些生成文件可能不随版本库交接，因此本日志保留关键结果与原件哈希。

## 未完成与下一步

GAP-001–009 全部 OPEN。本轮只完成规范，不生成符合新规则的原子动画，也不声明支持任意门集/任意布局。下次先做 M3-A：动态 masks、交接支撑与活动空阱 sweep/enable 校验，同步 Executor/checkpoint/observer，再把 single_trap 编译成真实开关操作。之后按 M3-B 至 F 接任务 IR、持久起态、参数化 1Q、最小并行、替换与端到端验收。
