# 环境、策略、控制应用与实验的包边界

2026-09-14。用户授权本轮大规模分离。此文描述已落地接口；不宣称候选流水线、RL、通用二维联合落点或新物理模型已完成。

## 目录与依赖

```text
src/
  neutral_atom_env/           纯模拟平台：物理状态、规则、事件执行、验证、恢复、观测
    environment.py           NeutralAtomEnv / Observation
    platform.py              外部平台和电路输入、初态建立
    domain/ circuit/ world/  值对象、逻辑依赖、静态几何与 holder
    hardware/ quantum/       物理动作与声明量子模型
    program/                 显式操作构建、状态绑定、独立计划审核
    simulation/              Executor、事件队列、物理 reducer、运行校验
    replay/ statistics/      保存、恢复、逐原子统计
    visualization/           无策略依赖的 recorder 和通用 viewer
  neutral_atom_strategies/    外部算法：选门、选位置、寻路、复用、排序、调度
    api.py                   Strategy / FunctionStrategy / make_strategy
    planning/                编译插件协议与 eager 选择
    motion/                  A*、落点与运输算法、各类局部 compiler
    scheduling/              M3/M4、row/patch、通用 QEC 运输运行循环
  neutral_atom_experiments/   电路生成、实验布局、协议合同、fixtures 与验收工具
    runners/                 两/四逻辑时域 QEC 的特定历史 guard 适配器
    testing/ fixtures/       测试替身、场景与实验报告；不属于物理环境
  neutral_atom_app/           完整控制应用：组装策略、配置、作业、编辑器与 HTTP
    control.py               ControlProgram / configured_strategy
    pipeline.py              run_circuit：外部输入到受策略控制的环境运行
    visualization/           workbench/studio 配置、前端与作业服务
```

允许依赖：策略 → 环境；实验 → 策略/环境；应用 → 实验/策略/环境。环境不能反向导入后三者；策略不能导入应用和实验。特定实验的 syndrome ID/guard 因此保留在实验包，不放进通用策略。物理环境中的 visualization 只读提交记录，不包括编辑器、作业、预设或算法派发。

`program` 保留的是“如何表达并验证一份已明确指定的操作程序”，不是“选择什么操作”。原混合 `motion/compiler.py` 拆为环境 `program/binding.py` 与外部 `strategies/motion/compiler.py`；原 `motion/tasks.py` 拆开显式 TaskProgram 与目标寻路算法；原 `simulation/pipeline.py` 拆为 `env/platform.py` 和 `app/pipeline.py`。

## 环境是实验平台，不是默认调度器

```python
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_strategies import make_strategy
from neutral_atom_app.control import ControlProgram

env = NeutralAtomEnv.create(circuit, platform, placement, seed=7)
controller = ControlProgram(make_strategy("greedy", adaptive_sites=True))
result = controller.run(env, on_event=recorder.observe)
checkpoint = env.snapshot()
```

更换控制程序无需修改环境：实现带 `id` 和 `run(env, *, on_event=None)` 的对象即可，不要求继承基类、不要求修改硬件注册表。程序化 `run_circuit(..., strategy=对象或通用策略名)` 同样支持；旧 compiler/policy 参数仍保留，但三者不能同时指定。工作台固定目录保持输入校验，不允许 JSON 动态导入任意 Python。

| 环境接口 | 合同 |
| --- | --- |
| `create(circuit, platform, placement, seed=...)` | 从独立输入建立环境，不选择策略或注入 demo |
| `observe()` | 返回冻结的观测：位置/holder、READY 门、已报告测量位、光阱掩码、时间和事件数量；不包含量子态/RNG/trace |
| `validate(plan)` | 对当前版本执行精确计划校验，无实时状态提交 |
| `submit(plan)` | 经唯一 Executor 验证和入队；拒绝过期/损坏计划，不搜索路线 |
| `step()` | 提交下一事件；不自动挑选后续门 |
| `run(on_event=None)` | 只排空已经提交的操作；不等于整个电路或终态已经完成 |
| `fork()` | 分离顶层运行状态，共享持久不可变子结构；用于私有预测 |
| `snapshot()` / `restore(checkpoint)` | 保留 schema19 的完整恢复合同 |

所有生产策略运行循环通过环境提交与推进，不再直接构造 Executor。物理 Executor、运行验证器与低层测试仍在环境内直接使用。

`env.state` 是为现有物理编译器保留的**特权只读规划/核验视图**，包含旧 SimulationState 全部字段；冻结 dataclass 不等于不可信代码沙箱。它尚未实现“所有算法只能读取去私有信息的 PlanningView”。新 Observation 不暴露量子态/RNG；未来 RL 应使用它及经审查的候选特征，不能把本次改包宣称为完整信息隔离。

## 迁移与兼容

- 保留 `examples/circuit_workbench.py`、`examples/compile_workbench.py` 等 CLI 路径、输入 JSON、配置目录、门/操作 ID、执行顺序和 checkpoint schema19。
- Python 算法旧导入路径已迁移；**不在环境包留下反向导入策略的兼容壳**。仓库内 tests/examples/tools 已同步。
- 主要路径：`env.motion.greedy` → `strategies.motion.greedy`；`env.simulation.m4` → `strategies.scheduling.m4`；`env.visualization.workbench` → `app.visualization.workbench`；`env.experiments.*` → `neutral_atom_experiments.*`。以上前缀 `env/strategies/app` 分别指完整 `neutral_atom_*` 包名。
- 旧 runner 函数仍接受 SimulationState，内部通过 `as_environment` 适配；新 Strategy/ControlProgram 接口要求 NeutralAtomEnv。
- 已运行的 Python 服务不会因文件迁移自动刷新模块；使用重新启动的新服务实例加载新包。旧 trace/checkpoint 不需要重编。
- 原策略中的布局限制、预算、终态、QEC 声明范围保持；“策略可替换”是接口能力，不是任意策略兼容任意平台/协议的保证。

## 验证与后续

架构约束在 `tests/test_environment_boundary.py` 中检查：静态依赖方向、运行时屏蔽全部外部包后的环境独立执行、冻结观测、非法/过期计划原子拒绝、fork/中途恢复、用户自定义策略注入，以及六种内置策略同接口执行。

迁移前保存六种策略同一 H/CZ/T 输入的完整快照，迁移后比较 SHA256。整体测试状态与本轮证据见 [交接日志](../instruction/logs/2026-09-14-environment-strategy-separation.md)。不能以成功 import 代替物理行为验收。

后续再实施统一 Frontier → Intent → 联合落点/Move Realizer → AOD batch → 有界合法候选 → Policy。当前各策略仍拥有自己的内部控制循环，本轮统一了它们操作的环境接口和外部调用接口，没有重写候选搜索算法。
