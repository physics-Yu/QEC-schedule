# 源码职责边界

交互意图位于 `neutral_atom_strategies/ir/`：上层 Move/Apply 不指定 trap；`zoned/interaction.py` 对接可替换落点 resolver 与实际 AOD lowering，控制器输出意图/落点/物理计划三层记录。见[接口说明](../docs/interaction_ir.md)。环境物理 Operation 继续保存具体坐标，viewer 只读真实执行。

自由初态优化在 `neutral_atom_strategies/placement/free.py`，实际执行适配 `neutral_atom_app/placement_execution.py::optimize_free_layout`；编辑与对照界面由 app 的 `placement_workbench.py` 和 `visualization/placement*` 组装，复用原 viewer。该入口可改变原子占据形状，见[完整说明](../docs/free_initial_placement.md)。

| 包 | 拥有的职责 | 不允许依赖 |
| --- | --- | --- |
| `neutral_atom_env` | 物理模拟、显式操作审核、事件提交、恢复和只读观测 | 其余三个包 |
| `neutral_atom_strategies` | 路径、目标选择、候选排序、调度控制 | app、experiments |
| `neutral_atom_experiments` | 电路/布局配方、协议合同、测试场景和验收 | app |
| `neutral_atom_app` | 用户输入、控制程序、策略组装、作业服务与编辑器 | 无反向注入环境 |

新增算法放 `neutral_atom_strategies`，通过 `NeutralAtomEnv` 控制模拟；不要把算法、默认电路或工作台配置放回环境。只有 Executor 提交真实状态。

初态优化和动态落点接口位于 `neutral_atom_strategies/placement/`；自定义布局编译入口 `neutral_atom_app/placement.py`，非可视化对照 `neutral_atom_experiments/initial_placement.py`。估计映射与实际执行结果严格分离，见 [初态放置合同](../docs/initial_placement.md)。

固定用户 layout 的实际编译反馈搜索：`placement/verified.py`（通用搜索）和 `neutral_atom_app/placement_execution.py`（普通有序编译执行/独立重放适配），见[通用初态优化](../docs/compiler_initial_placement.md)。

完整接口与迁移说明见 [环境与策略边界](../docs/environment_strategy_boundary.md)。

当前有序 QEC 的 CZ 候选、measurement target 和 movement 入口见 [版本导航](../docs/current_version.md)。研究策略由专用实验组装，不自动暴露为旧通用工作台的能力。
