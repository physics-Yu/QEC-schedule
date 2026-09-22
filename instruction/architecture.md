# 工程框架与模块边界

2026-09-22：[constraint 与 placement 审计](../docs/constraint_placement_audit.md)记录当前检查链、初态/动态落点/运行态的不同职责，以及尚未实施的显式预约、分层检查和拒绝原因重构。新交互 IR 不等于约束系统已经统一。

2026-09-22：[程序框架系统总结](../docs/general_framework_summary.md)按当前源码汇总四包职责、旧有序/zoned/QMAP等实际入口、可复用模块、认识演进和验证边界。下文按日期增补的旧状态不代表各新分支都相同；特别区分统一Env操作接口与尚未统一的内部调度、初态evaluator及应用入口。

2026-09-22：[交互意图 IR](../docs/interaction_ir.md)新增 `strategies/ir`，MoveToInteraction/ApplyInteraction 不含 trap/坐标；`zoned/interaction` 将请求解析为绑定状态的 LayerPlacement，再由 PhysicalCodegen 生成物理计划。`run_zoned` 已走该入口；native 已解析 NAViz 保持原适配层，旧策略未宣称全迁移。Env 和 viewer 职责不变。

2026-09-21：[分层驻留编译器](../docs/zoned_compiler.md) 已接入原 Studio 和并行 placement worker。新 `strategies/zoned` 将 schedule/reuse/placement/routing/landing/codegen/controller 分开；几何假设使用轻量 PlacementView，不能提交为环境状态。只有所选方案进入 program 校验和 env.submit/run。旧 greedy/SMT 不改语义。

2026-09-21最新：`placement/verified.py` 是独立于 demo 和具体下游编译器的初态优化循环；`app/placement_execution.py` 组装有序编译器及真实执行/重放 evaluator。layout 几何、电路、平台和共同终态固定，初态 mapping 可变；不在 env 中注入搜索，不修改运行态。详见[合同](../docs/compiler_initial_placement.md)。

2026-09-21：`neutral_atom_strategies/placement` 独立容纳初态优化、成本估计、统一结果与动态落点接口；自定义输入/Platform适配在app，物理对照在experiments。代理布局不修改env；初态在创建环境前提供，中途重排必须编译真实运输。动态新算法未因建立接口而完成，详见[初态合同](../docs/initial_placement.md)。

2026-09-14新增受限实验：[SMT 联合批次对照](../docs/smt_batch_experiment.md)。`strategies/scheduling/smt_batch.py` 提供符号提案，`experiments/smt_comparison.py` 实验执行/核验，`app/smt_experiment.py` 独立进程与编辑界面；底层仍由 env 验证/执行。是固定 EZ、规则 rigid 轴、恢复式批次的实验插件，不代表通用候选接口、任意二维规划或 RL 已完成。原生产工作台没有默认切换到 SMT。

2026-09-14。本文是当前维护导航，详细接口见[环境/策略边界](../docs/environment_strategy_boundary.md)，当前验收结果见[handoff](handoff.md)。历史架构方案与演进路线仍可参考，但不能将建议接口当成已实现功能。

## 1. 当前边界

研究对象是给定 PhysicalCircuit 到可验证的原子操作执行。环境模拟项目声明的几何、支撑、门作用、事件时间和受限QEC Clifford状态；没有模拟最底层光场、波包、波形或完整保真度。

```text
neutral_atom_app          配置、控制程序、策略组装、HTTP作业、线路编辑器
       │
       ├── neutral_atom_experiments  电路/实验布局、协议、专用历史guard、验收工具
       │                │
       └── neutral_atom_strategies  选门、落点、寻路、批次、调度与排序
                        │
                 NeutralAtomEnv    提交、推进、观测、预测分支、恢复
                        │
                  唯一 Executor    提交真实状态与事件
```

依赖方向：app → experiments/strategies/env；experiments → strategies/env；strategies → env。env不导入后三者。生产策略通过env执行，不直接构造Executor。底层物理验证与测试可以直接使用Executor。

## 2. 源码归属

| 包/模块 | 职责 |
| --- | --- |
| env/environment.py | NeutralAtomEnv与去除私有仿真信息的Observation |
| env/platform.py | 独立平台/电路/placement输入与初态建立 |
| env/domain、world、circuit | 不可变值、静态几何、holder、逻辑依赖 |
| env/hardware、quantum | 几何/捕获/交接/作用/读出规则及声明量子模型 |
| env/program | 显式操作表达、状态绑定、完整计划独立校验；不选择落点或路线 |
| env/simulation | Executor、事件队列、物理reducer、runtime校验 |
| env/replay、statistics、visualization | schema19保存恢复、逐原子统计、无策略依赖的recording/viewer |
| strategies/planning、motion、scheduling | 编译插件、路线与落点算法、M3/M4/row/patch/QEC控制循环 |
| experiments | 电路生成、布局、协议、fixtures、验收工具；runners存特定时域历史guard |
| app/control.py、pipeline.py、visualization | 策略组装与控制、端到端输入执行、工作台/作业/配置/前端 |

表中env/strategies/experiments/app分别指完整的neutral_atom_*包名。具体新需求先按[src职责表](../src/README.md)选择归属，不能为方便import把实验或控制程序移回环境。

## 3. 实验平台控制接口

```python
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_strategies import make_strategy
from neutral_atom_app.control import ControlProgram

env = NeutralAtomEnv.create(circuit, platform, placement, seed=7)
controller = ControlProgram(make_strategy("greedy", adaptive_sites=True))
result = controller.run(env)
saved = env.snapshot()
restored = NeutralAtomEnv.restore(saved)
```

- Strategy协议为 `id` 与 `run(env, *, on_event=None)`。实现该协议即可注入ControlProgram或app.pipeline.run_circuit，不要求继承环境。
- `env.validate(plan)`独立验证；`submit(plan)`通过Executor审核入队；`step()`提交下一事件；`run()`只清空已提交队列。空队列不等于电路或声明终态完成。
- `CompiledPlan`绑定版本及完整状态fingerprint。非法/过期计划不能部分提交；审核失败使用结构化ValidationError。
- backend构建的推演状态和env.fork拥有的预测分支不能安装到实时环境；最终仍通过submit和唯一Executor提交。
- `observe()`返回冻结的已提交观测，不暴露quantum_state、RNG、trace。`env.state`仍是旧编译器的特权冻结规划/核验视图，包含上述字段；本轮没有实现完整PlanningView或不可信策略沙箱。
- Python旧算法导入路径已经迁移，没有环境反向引用策略的兼容壳。仓库内CLI与输入JSON保持，checkpoint为schema19。

## 4. 不可破坏的物理和状态职责

- placement是holder真值；world是静态几何真值；atom不另存position或永久home。
- DAG只处理逻辑依赖，READY不等于物理可执行；不得在DAG中查询路线、zone或AOD。
- 策略、编译器、validator和renderer不改实时状态。只有Executor提交完整下一状态；successor根据真实门效果完成释放。
- AOD活动trap是开行×开列的全部交点；非均匀间距、附带捕获、空交点扫掠与行列联动必须按物理合同处理。
- 资源占用、动作时间、作用集合与支撑由环境核验，策略不能以收益或reward替代硬约束。
- 当前门集、同类并行、光照间距、EZ四邻停驻、测量/反馈约束以[physics](physics.md)及其合同链接为准。本轮包分离没有修改这些规则。
- 通用recording/viewer读取已提交记录；编辑器、预设、算法派发、HTTP作业属于app。

## 5. 配置与实验隔离

平台Config描述几何/能力与声明参数；runtime保存SLM/AOD启用、当前holder、时间和已报告测量位。初始配置不能替代运行态变化。

工作台目录在configs/studio：完整demo锁定配套配置，电路示例只填gates，用户自定义策略仅显示通用能力。AOD容量和绝对坐标从行列及相对偏移派生。环境不读取demo目录、不隐式选择默认线路或算法。

完整输入/编译流程见[配置归属](../docs/studio_configuration_layers.md)、[工作台合同](../docs/workbench_configurations.md)。

## 6. 验收与下一阶段

修改包边界后运行：

```powershell
python tools/check_architecture.py
python -m pytest -q tests/test_environment_boundary.py
```

还需按实际受影响行为执行相关回归；不能以import成功替代物理行为相同。本轮保留迁移前六策略完整checkpoint，迁移后逐字比较；具体结果见[本轮日志](logs/2026-09-14-environment-strategy-separation.md)。

[架构演进A0–A8](../docs/architecture_evolution_backlog.md)中的状态/历史拆分、统一候选决策循环、缓存和规划优化尚未因本次分包完成。下一步可在策略内部建立Frontier→Intent→Move/AOD batch→有限合法候选→Policy；本轮没有通用CandidateGenerator、RL策略或通用二维动态变距规划。

策略可替换指接口独立，不保证任意策略适用所有平台和QEC协议。硬件模型或整体架构的进一步变更按用户审批边界处理；普通工程修复自主记录和重验。
