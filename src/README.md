# 源码职责边界

| 包 | 拥有的职责 | 不允许依赖 |
| --- | --- | --- |
| `neutral_atom_env` | 物理模拟、显式操作审核、事件提交、恢复和只读观测 | 其余三个包 |
| `neutral_atom_strategies` | 路径、目标选择、候选排序、调度控制 | app、experiments |
| `neutral_atom_experiments` | 电路/布局配方、协议合同、测试场景和验收 | app |
| `neutral_atom_app` | 用户输入、控制程序、策略组装、作业服务与编辑器 | 无反向注入环境 |

新增算法放 `neutral_atom_strategies`，通过 `NeutralAtomEnv` 控制模拟；不要把算法、默认电路或工作台配置放回环境。只有 Executor 提交真实状态。

完整接口与迁移说明见 [环境与策略边界](../docs/environment_strategy_boundary.md)。

当前有序 QEC 的 CZ 候选、measurement target 和 movement 入口见 [版本导航](../docs/current_version.md#分层与所有权)。研究策略由专用实验组装，不自动暴露为旧通用工作台的能力。
