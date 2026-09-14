# 架构文档已拆分：按任务读取

原 V2.1 架构的职责和 M0–M6 路线已整理为按需读取的规范。本文件保留旧路径作为导航，不再承载长篇实施要求。

1. [agent.md](agent.md)：行为准则、程序框架和任务阅读路由。
2. [当前交接状态](instruction/handoff.md)：已完成内容、OPEN 问题、下一步。
3. [instruction 索引](instruction/README.md)：按领域选择物理、状态、运动执行、策略、验收等文档。
4. [里程碑路线](instruction/milestones.md)：原 M0–M6 顺序与当前完成范围。
5. [章节迁移对照](instruction/migration.md)：原 89 章的对应去向和被后续决策替代的要求。
6. [完整原文档案](instruction/references/architecture_v2_original.md)：仅用于历史追溯，原字节保留。

原文中的示例接口、逐测试图片要求及早期身份/配置示例不可直接当作当前实现；阅读新规范中的实际 API、简化边界和审计记录。

最新研究边界与接口见 [compiler_contract](instruction/compiler_contract.md)，物理开关/交接硬逻辑见 [physics](instruction/physics.md)，更新后的 M3 工作包见 [milestones](instruction/milestones.md)。这些是已确认的目标，当前运行时缺口见 [model_audit](instruction/model_audit.md)；原档案不因后续决策改写。
