# M3-B：独立目标任务与串行操作 IR

> M3-C–F 已实现持久状态与 scheduled operations；本页继续说明串行兼容 API，新接口/平台族/恢复见 [M3](milestone3.md)。

默认工作台及其初始条件、线路编辑、物理编译、Executor、VisualRecorder、共用 viewer 管线保持不变。新增目标任务接口可执行无 gate 运输，并把已有通用门程序拆成 prepare/effect/cleanup，在每段执行前按最新已提交状态重新编译和验证。单比特固定 1 μs，回放仍支持最高 32×。

## 接口与语义

代码入口是 `domain/operations.py`、`motion/tasks.py`、`motion/task_validation.py`，类型均为不可变值；`planning.compilers.TaskCompiler` 声明 `compile(intent,state)->CompiledPlan` 协议，原 GateCompiler 保留为兼容基线。

| 类型 / 字段 | 已实现语义 |
| --- | --- |
| `TaskIntent.task_id` | 调用者给出稳定非空 ID；同一执行 trace 内禁止再次执行同 ID |
| `TaskIntent.target` / `TaskTarget` | 终态约束的合取：Q→holder 子集、可选完整 AODConfiguration、可选完整 TrapState；省略字段不作额外目标约束，但始终须满足物理合法性 |
| `atom_ids` | 任务声明的目标原子；effect 的实际门操作数自动纳入 requested 集；终态可额外约束不应改变的旁观原子 |
| `effect_gate_id` | 唯一授权的门效果；仅 effect 阶段可设置。None 表示零 pulse，不能通过 related_gate_id 偷做门 |
| `phase` / `related_gate_id` | transport、prepare、effect、cleanup；related_gate_id 仅用于追溯，不预约或改变对应 DAG 节点 |
| `allowed_atom_ids` / `allowed_site_ids` | 限制真实受影响原子、使用的 SLM 站点，独立 replay 根据实际操作/holder 派生后验证；None 表示不额外限制 |
| `max_duration_us` | 可选有限正数，超过预算拒绝整个候选，未提交任何状态 |
| `Operation.gate_id` | 仅任务的实际脉冲有值，运输/开关/交接操作为 None |
| `Operation.depends_on` | 当前合法 IR 是按执行顺序连接的串行链，校验不得断链/改依赖；稳定操作标识为 `task_id/opNN` |
| `CompiledPlan.operation_intervals` | 每操作的相对 start/end μs、资源 ID 和受影响原子；由独立物理 replay 派生并核对，不能伪造时间或资源 |
| `CompiledPlan.initial_dag` | 原始完整 DAG 的规范 JSON，用于恢复时证明 gateless 任务没有改变任何门、effect 只改变授权门及其后继 |

每个任务必须有目标或门效果，执行程序必须至少含一个有正时长的物理操作。已经满足的零操作目标返回 `TASK_ALREADY_SATISFIED`，不通过添加假 WAIT 或 gate 增加完成计数。没有独立运输需求的空电路仍是空电路。

## 无 gate 运输

```python
from neutral_atom_env.domain.models import HolderRef, HolderType
from neutral_atom_env.domain.operations import TaskIntent, TaskTarget
from neutral_atom_strategies.motion.tasks import TargetTaskCompiler
from neutral_atom_env.simulation import Executor

task = TaskIntent(
    'park-Q000',
    TaskTarget(holders=(('Q000', HolderRef(HolderType.STATIC, 'EZ0')),)),
    atom_ids=frozenset({'Q000'}),
    allowed_atom_ids=frozenset({'Q000'}),
)
plan = TargetTaskCompiler().compile(task, state)
executor = Executor(state)
executor.submit(plan)
executor.run()
```

此处 state 必须包含 Q000 和空的 EZ0，来自明确输入。当前目标路由编译器支持一个 rigid trap、空闲边界、单原子 SLM→SLM，以及空 AOD 关闭后显式定位、终态 mask 切换。每条载原子路径最多尝试 64 个既有 HalfGridPlanner 候选；不修改几何、作用范围或 clearance 来满足目标。目标占据、未知站点、资源/时长约束和路由耗尽都拒绝并保留原因。

`TargetTaskCompiler` 还支持原位 CZ/U3 效果任务。CZ 起态必须已经物理合法，不能隐含准备；1Q 须满足稳定启用 SLM 等资格。loaded 路由和多原子 exact 目标分配已由 M3-C 的 PersistentTargetCompiler 实现；允许终态集合/区域优化仍待 M4；TaskProgram 已允许经过校验的 loaded 起末边界，但这不证明通用路径完备。

## 准备 / 脉冲 / 清理

```python
from neutral_atom_env.program.tasks import split_gate_program

# full_plan 已由 SingleTrapCompiler 等通用 program 路径编译并验证。
recipes = split_gate_program(full_plan, state, task_prefix='cz-0')
executor = Executor(state)
for recipe in recipes:
    plan = recipe.compile(state)  # 每次用最新状态，不预提交未来旧 fingerprint
    executor.submit(plan)
    executor.run()
```

拆分只发生在完整脉冲之前和之后；不会拆开一个 CZ，也不会截断需要相邻实际交接的 approach/depart 豁免。配方是独立的不可变 TaskProgram，保存显式目标和操作序列，每次仍需 ProgramBuilder、独立 validator、Executor.submit 全链路核对。参数化单比特纯 pulse 程序只产生一个 effect 任务。

prepare 不预约/完成 gate；effect 开始计划时 READY→RESERVED，实际 pulse 开始/完成时 RUNNING→COMPLETED，立即释放逻辑后继；cleanup 不重复完成 gate。终态明确保存全部原子 holder、AOD 轴和 masks。准备完成可以保留 loaded 原子，效果完成后可以先在另一稳定 SLM 原子上执行 READY 的 Raman，再清理；这仍是**串行插入**，没有操作重叠。

## 校验、恢复与观察

任务保留全状态 version/fingerprint、初始几何/支撑/placement、预计终态及独立实际 replay。目标不满足、隐藏/重复 pulse、非 READY 门、非法依赖/时长/资源、禁止的附带原子或站点均在 submit 前拒绝。后端仍检查活动空阱、所有 AOD 轴间距、目标先支撑和结束才提交 holder；失败不部分提交。

checkpoint **schema 13** 保存任务、逐操作 gate/dependency/interval 和起始 DAG；旧 1–12 明确拒绝，须从原 circuit/platform/placement 输入重新编译。恢复校验计划、trace、cursor、唯一下一事件、预约、holder/轴/masks/交接、DAG 与唯一效果一致；运行任务的每个 start/complete 及完成空闲边界均有恢复测试。不得通过重写旧 trace 达成恢复。

事件附 task_id、task_phase、related_gate_id、operation_ref；效果完成附 effect_completed。legacy CZ 同样记录 effect_completed。共用 recorder/viewer 的 /2 格式追加任务元数据，gateless 操作使用空 gate 字段和任务标签，不画虚构门脉冲；cleanup 在 recorder 与 trace 汇总中都归入回程。路径支持任务开始时已 loaded 的原子。

本页 serial TaskProgram 保留整计划预约；M3-D 的 scheduled_program/operation_program 已支持多个活动操作及提前释放资源。工作台新草稿默认 resident，旧无 compiler 字段输入保留 eager 兼容行为；没有新增可调物理参数。

## 复现与证据

```powershell
python examples/run_task_program.py
python examples/run_task_program.py --transport-only --output artifacts/m3-task-transport
python -m pytest tests/test_task_ir.py -q --tb=short
node tests/task_controls.cjs
node tests/raman_controls.cjs artifacts/m3-task-program/index.html
node tests/viewer_speeds.cjs artifacts/m3-task-program/index.html
```

入口继续读取 `configs/workbench/mixed.json` 或 `--input` 指定的工作台导出 JSON，使用同一 build_inputs、真实编译和 VisualRecorder/viewer；`--output` 指定输出目录。保存 input、plans（含 IR）、recording、checkpoint、diagnostics、result 与 index.html，stalled 以非零退出并保存部分结果。`--transport-only` 的 completed 仅代表运输任务完成，result 同时记录该模式与 completed_gate_count，不声称电路完成。

2026-09-11 实际结果：

| 场景 | 门 / 任务 / 操作 / commits | 独立核对数字 |
| --- | --- | --- |
| 6 原子 shuffled seed 7 混合输入 | 4 门 / 6 任务 / 26 操作 / 64 commits | wall 1163.2898987322333 μs，Raman 3 μs，CZ 0.3 μs；3 LOAD/3 OFFLOAD；AOD/原子路程 279.99494936611666/181 μm，和未拆分物理成本一致 |
| 同一输入只搬 Q000 到 EZ0 | 0 完成门 / 1 任务 / 6 操作 / 14 commits | wall 338.2842712474619 μs；1 LOAD/1 OFFLOAD；AOD/原子路程 69.14213562373095/55 μm，原 DAG 不变 |

Node 是 DOM/Canvas 替身控制检查；本次 CUA 仍 `nodeRepl.fetch request failed`，没有真实浏览器视觉 PASS。完整测试结果及下一步见 [本次日志](../instruction/logs/2026-09-11-m3-task-ir.md)。M3-B 的串行 IR 验收不等于 M3-C 持久平台族、M3-D 并行、M3-E 双 compiler 与失败契约或 M3-F 大规模验收完成。
