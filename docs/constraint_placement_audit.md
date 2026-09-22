# Constraint 判定与 placement 接入审计

2026-09-22，针对当前源码的结构审计。**此文记录现状和后续方案，没有完成约束系统重构。** 交互 IR 的新增实现见 [interaction_ir](interaction_ir.md)，全局框架见 [general_framework_summary](general_framework_summary.md)。

## 当前如何判定

目前主要是“策略提出具体候选 → 私有状态预测并检查 → 拒绝非法候选 → 审核完整计划 → 环境提交执行”。不是将所有问题一次性编码到全局 SMT。

| 阶段 | 现有检查 | 主要入口 |
|---|---|---|
| 状态与落点 | holder 唯一、区域/占用、支撑、EZ 四邻预约、作用对 | `env/world`、`hardware/ez_neighbors.py`、`zoned/placement.py` |
| 装卸与 AOD 批次 | 行列容量、顺序、共享坐标、完整活动交点捕获集合、显式选择性装卸能力 | `motion/ordered_primitives.py`、`hardware/partial_transfer.py` 等硬件模块 |
| 连续移动 | 原子间最小距离、移动/静态原子、空活动 AOD 交点扫掠、SLM 排斥区和交接豁免 | `hardware/row_column_aod.py`、`rigid_aod.py`、`dynamic_traps.py`、`slm_clearance.py` |
| 门和读出 | 静止支撑、全部实际 CZ 对与声明集合一致、单比特门类型/间距、MZ 读出能力 | 硬件 backend 与操作 transition |
| 完整程序 | DAG、资源区间、时长、每门效果、授权范围和终态 | `program/builder.py`、`simulation/operation_program.py` |
| 提交与事件 | 状态版本/指纹、事件/计划一致性、checkpoint 和运行状态 | `simulation/executor.py`、`simulation/runtime_validation.py` |

上述路径相对 `src/neutral_atom_env/`，`motion/`、`zoned/` 路径相对 `src/neutral_atom_strategies/`。确切文件导航以源码为准。

```text
ProgramBuilder.add → apply_operation / backend → 私有下一状态
ProgramBuilder.finish → audit → exact_validate → validate_program → audit
Executor.submit → exact_validate
PLAN_STARTED → validate_program
Executor.step → validate_runtime(old) → transition → validate_runtime(next) → 提交
```

整计划审核存在重复，但运行时已有有限的前缀重建缓存，不能说每个事件必然从头审计所有动作。独立重放不调用策略重新规划，底层仍使用同一物理 backend；它不是第二套独立物理模型。

## Placement 的三个含义

1. **初态优化**：策略包 `placement/` 在创建环境之前搜索 `qubit → 合法 SLM`；应用层 `placement_execution.py` 对候选完整编译、执行与重放。自由布局覆盖已配置合法站点，可以改变占据形状，不是连续空间任意生成 trap。
2. **动态落点**：`MoveToInteraction` 只表达原子对与交互区；`zoned/interaction.py` 调用 resolver，生成含角色、site、坐标的 `ResolvedInteraction / LayerPlacement`，再交 `PhysicalCodegen` 展开 AOD 操作。QMAP 原生输出已经做过落点决策，兼容层保留作者目标。
3. **运行态 placement**：环境内 atom → holder 的事实记录，由 Executor 提交；它不是优化器。CZ 后落地与测量落点还分别由 `zoned/landing.py`、`ReadoutPlacementPolicy` 等入口决定，尚未共享统一动态落点接口。

## 需要重构的边界

- **分开物理能力、实验合同和搜索限制。** 完整捕获闭包/连续碰撞是当前模型约束；EZ 四邻停车保护是可配置实验规则；整片入区、每批归还、2.5 μm 路由网格和候选预算属于策略选择。有限搜索失败不能当作物理无解。
- **明确预约所有权。** `hardware/ez_neighbors.py` 当前通过扫描未来 CZ 推导允许的伙伴；后续建议由上层提供显式 reservation，环境只强制检查。迁移须保持现有 guard 行为，不能偷偷停用。
- **按失败阶段指导修复。** 当前 `ConstraintViolation` 主要保存 code/message/atoms/holder/position；后续增加 scope、phase、retry kind，区分目标不合法、批次不合法、具体路线失败和预算耗尽，避免对同一坏落点反复寻路。
- **复用审核结论需要可靠绑定。** 相同不可变计划、起态和硬件配置的完整审核可以研究证书复用；外部输入仍完整检查，运行时继续验证事件与状态。尚未实现或测得这部分加速。

建议逐步提供 `check_intent → check_target → check_transfer → check_motion → check_program → check_runtime_binding`，保留环境作为物理判据所有者。部分候选的“信息不足”、明确非法、有限搜索未找到必须分开报告。

## 后续验收

先固定合法/非法计划语料，验证重构前后判定和失败码等价；再统计各层调用次数、耗时和拒绝原因。提前剪枝应减少无效路线尝试，不能通过减少必要的连续检查取得速度。实现、性能实验与 GUI 验收均仍待后续任务。
