# 当前交接状态

截至 2026-09-22，当前源码在 `main`。本轮整理的主变更 `8cb547b` 已推送 GitHub并核对远端 SHA，发布验证与确认补录见 [本轮日志](logs/2026-09-22-repository-release.md)。[发布前交接原文](handoff-2026-09-22-archive.md) 按原字节保留；其中旧端口/PID、默认算法、未推送表述只对应当时快照。

## 当前入口与已实现能力

- 当前自定义默认 `qmap_native`：作者 QMAP 3.5.0 原生内核 → 本地显式成对 SLM / AOD 适配 → Env 执行与共用回放。先运行 `python tools/setup_qmap_native.py`，再 `python demo/launch.py --port 0`。普通 H/X/Y/Z/T/CZ 已接入，测量/反馈 QEC 保持旧协议。
- 同工作台保留本地 `zoned_ids`、`ordered_greedy`、`smt_ordered`；锁定 demo 不自动迁移。各策略的几何、终态和候选族不同，不能直接排名。详见 [当前版本](../docs/current_version.md)。
- 初态 `placement/` 支持合法 SLM 域的站点/占据形状搜索、真实编译反馈、并行评估。工作台默认关闭搜索；本地三策略可选，QMAP 使用作者映射。当前默认 pool256 / evaluations16 / workers4 / stable；stable 与 fixed 终态必须分开比较。
- Parking 朴素版保留已匹配轴、跳过无目标行/列；兼容优化及方向选择已实现，最优范围是声明模板中的抓取批数。离线分享模板与真实 Env 执行的证据分开。
- 交互 IR 已接本地 zoned：Move/Apply 不携带具体 trap，resolver 选择落点，lowerer 展开物理计划；准备不打门、显式 pulse、状态/前缀绑定。仍为完整事务提交，未统一迁移所有策略。见 [IR](../docs/interaction_ir.md)、[实现日志](logs/2026-09-22-interaction-ir.md)。
- 发布审查修复 IR-001（IDS 部分前沿阻断缩小批次回退）及实验 RL 摘要的 NumPy ABI 依赖；最终229项不同专项用例通过，216模块架构、134文件bundle与11项HTTP检查通过。完整1889项压力套件未跑完，717通过/1失败的初次记录及失败修复分别保留；发布总验收见本轮日志，不能宣称全量通过。
- ZAC 固定/SA × reuse、QMAP/Enola 原生规模实验、隔离 RL 源码一并收录；来源、依赖、失败和验证边界在专题报告。模型权重/完整运行 artifacts 不上传。独立 `QEC-scheduler-next` 实现在仓库外，本仓库仅保留 [迁移日志](logs/2026-09-22-qec-next-bootstrap.md)。

## 必须保留的边界

环境只拥有状态、硬件判据和执行，不导入策略；只有 Executor 提交真实下一状态。策略控制完整活动行×列、附带捕获、空阱扫掠和连续轨迹，不得以可行性为由放宽物理。单比特门固定 1 μs；EZ 四邻停车保护是可配置实验合同。

本地 Env 重放、原生离散指令审计、Parking 浏览器模板和 RL 离散见证是不同验证范围。大型历史结果与本轮源码回归分别记账；原生编译时间不等于本地适配/审核/回放耗时。QEC 当前是声明 Clifford 协议及有限故障验收，不是一般噪声阈值证明。

## OPEN 与下一步

1. **Constraint 重构未实施。** 当前检查分散于落点、捕获、运动、完整计划与 runtime；EZ reservation 仍在 env 扫描下一 CZ。建议显式上层预约、阶段化错误、寻路前目标预筛、可靠绑定下复用审核结论。先冻结合法/非法语料和 profile，再做等价改造。见 [本次审计](../docs/constraint_placement_audit.md)。
2. 动态 placement 尚未统一：初态优化、zoned CZ 落地、readout、ZAC 各有入口。完整服务仍多为串行，任意 AOD 跨批带载续接/统一全局调度未完成。
3. `zoned_ids` QEC 性能退化仍 OPEN（历史 17→81 CZ 批次、约 3.57 倍物理时间），不替换旧 QEC。原生 QMAP 未迁移测量/反馈，同几何公平比较与本地执行性能仍待优化。
4. Enola/QMAP 2000/5000 三正则图双方在 300 s 预算内失败；QMAP 5000 GHZ 链成功仅为原生离散验收，不能代替高并行图或连续物理验收。
5. RL 尚无稳定超越启发式的结论；自由初态优化有成功与无收益案例，不能假定 surface QEC 普遍获益。
6. 当前发布补齐依赖提示；ZAC/Enola 等研究工具尚非跨平台一键安装。物理模型或整体架构需变更时请用户确认，普通工程修复自主执行并保留失败证据。

## 证据导航

- [框架总览](../docs/general_framework_summary.md) · [源码职责](../src/README.md) · [环境/策略边界](../docs/environment_strategy_boundary.md)
- [QMAP 与本地执行](../docs/qmap_native.md) · [运动修正](logs/2026-09-22-qmap-motion.md) · [Enola scaling](../docs/enola_scaling_benchmark.md)
- [初态搜索](../docs/compiler_initial_placement.md) · [统一编译流程](../docs/unified_compilation_workflow.md) · [Parking](../docs/parking_compatibility.md)
- [ZAC 复用](../docs/zac_reuse.md) · [ZAC SA](../docs/zac_initial_placement.md) · [RL 初态](../docs/rl_initial_placement.md)
- [QEC 有序对照](../docs/qec_ordered_smt_comparison.md) · [历史发布](logs/2026-09-15-stable-release.md)
