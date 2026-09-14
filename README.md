# Neutral Atom Environment — Circuit Scheduling

**[可编辑量子线路工作台](docs/circuit_workbench.md)**：配置原子数、初始 layout 与 AOD，编辑 H/X/Y/Z/T/CZ 电路，手动启动真实物理编译并回放动画。QEC 模式另支持 MEASURE/RESET 与报告位反馈，T 在当前 Clifford QEC 模式中明确拒绝。

```powershell
python examples/circuit_workbench.py --port 8766
```

打开 `http://127.0.0.1:8766`。默认 pipeline 已固化为“初始条件 → 线路编辑 → 真实编译 → Executor → 动画回放”，单比特光固定 1 μs、回放最高 32×。支持随机载入可编辑线路、撤销/重做、导入/导出和编译取消；仅线路卡片中的按钮启动编译，没有自动编译。平台、编译策略与具体电路分开配置，详见 [配置说明](docs/workbench_configurations.md)。

当前以 [handoff](instruction/handoff.md) 为准；历史实现、源码导航与用户决策保留在 [2026-09-11 项目总览与交接快照](docs/project_status_2026-09-11.md)。

截至 2026-09-14，M3/M4 在声明的平台族内已有验收，受限 QEC 扩展已完成两个/四个 surface logical qubit 的 GHZ、重复稳定子读出及声明单事件恢复。四逻辑案例为 68 原子、1868 门与控制槽；这不是任意布局最优或全电路噪声容错证明。当前 checkpoint schema 为 **19**。后续 [性能优化](docs/compile_performance_analysis.md)、[架构演进](docs/architecture_evolution_plan.md) 与 [外部文献方案](docs/external_compiler_research.md) 均为待实施建议。

Git 仓库包含源码、测试、配置、文档和复现脚本；`artifacts/` 中的生成动画、运行记录与 checkpoint 不随 Git 提交。文档中历史产物链接和本机服务地址需要在相应环境重新生成或启动。

该快照之后新增 [M3-B 独立任务与操作 IR](docs/task_program.md)：零门运输、准备/效果/清理拆分及 schema 12 恢复。`python examples/run_task_program.py` 使用同一工作台输入生成独立任务回放；该入口保留串行；[M3-C–F](docs/milestone3.md) 另有持久编译与真实 1Q/运输并行，入口 `python examples/run_m3.py`。


从给定 PhysicalCircuit 生成可验证、可回放的原子操作调度。M0–M2 基准、M3 持久布局与操作并发、M4 策略比较均保留对应验收范围；详见 [M3](docs/milestone3.md)、[M4](docs/milestone4_complete.md)、[编译合同](instruction/compiler_contract.md) 与 [物理规则](instruction/physics.md)。旧示例只证明各自声明的能力，当前整体状态见 [handoff](instruction/handoff.md)。

新增可选择的 `row_column` AOD 后端：有序行列伸缩、同步三次轨迹、AOD–AOD 配对，详见 [后端规范](instruction/aod_backends.md)。`rigid` 基准仍保留。

```powershell
python examples/run_reconfigurable_aod.py --backend row_column
python examples/run_reconfigurable_aod.py --backend rigid
node tests/replay_row_column.cjs
```

报告入口：`artifacts/row_column/index.html`，对照后端为 `artifacts/rigid/index.html`。后端在执行前选择，回放的真实比例/关键帧选项只改变呈现时间。

依据已拆分的 [工程规范](instruction/README.md) 与 [M0–M6 路线](instruction/milestones.md) 构建。Python 3.11+，空间单位 μm，时间单位 μs。

新任务先读 [agent.md](agent.md) 和 [当前交接状态](instruction/handoff.md)，再按任务选读 [instruction 文档索引](instruction/README.md)。原 architecture 路径保留为导航，全文已归档。

```powershell
python -m pip install -e ".[test]"
python -m pytest --visual
```

统一人工验收入口：`artifacts/acceptance/index.html`。

- `python -m pytest`：运行机器断言，只生成 `machine-tests.json`，不为每个断言套用默认布局图。
- `python -m pytest --visual`：机器测试结束后，执行并渲染六组验收场景。
- `python examples/build_acceptance_report.py`：独立执行六组场景并生成报告。机器测试栏目会明确标为最近一次测试结果。
- `python examples/run_milestone0.py`：初始化、显示 ready gates、提交 WAIT，保存 checkpoint、trace 和 metrics，不另建一套图形报告。

六组场景与 pytest 共享 `testing/scenarios.py`，分别验证：

1. 63 个 trap 的稀疏/满占据，7.5 μm 网格、禁用 trap 和区域边界。
2. 全部原子的正反向 holder 映射、空位及 AOD 派生位置。
3. 16 门逻辑 DAG 的全部依赖边、每步 predecessor 计数和 ready frontier；只画初始及 8/12/16 个逻辑门完成后的关键帧。
4. 重复持有、缺失 holder、越界、禁用 trap、偏离网格的结构化错误。定位标记来自验证器输出，不手写冲突对象。
5. 保存运行中 checkpoint，恢复队列/RNG/trace 后继续执行，与不中断执行逐字节比较。
6. 外部派生 DAG/队列/trace 无法改变原状态，失败事件不部分提交。

另外的机器测试覆盖跨进程和不同 `PYTHONHASHSEED` 恢复、损坏快照、相同时间的新事件排队、报告失败状态及主题重绘。

## 状态与写入边界

`SimulationState` 的公开字段只读；Atom、DAG、队列、trace、world 和 placement 都是不可变值或只读映射。`transitioned()`、`push()`、`appended()` 返回新对象。只有 Executor 把通过验证的完整下一状态安装到当前 runtime；提交失败不消耗队列、不改变时间/版本/trace。

这是一项 Python API/架构约束，不是防恶意反射的安全沙箱；有意使用 `object.__setattr__` 仍可绕过 Python frozen 限制。

Placement 是 holder 真值，World 是几何真值。Atom 不保存独立位置或 home；occupancy 由 holder 映射推导（空 trap 可通过 `.get(trap_id)` 得到 None）。

原子与物理比特共用一个 `Q000、Q001…` 编号。`Atom.id` 同时用于布局、holder 和电路门参数；不再保存 `physical_qubit_id` 或 A→Q 映射。内部类名 `Atom` 仅描述运动与持有行为，门操作如 `CZ(Q000, Q001)` 直接引用对应原子。trap 和 gate 保留各自独立的编号。

## 配置、快照与恢复

`LayoutConfig` 统一创建网格、三区、隔离带和启用/禁用 trap，示例配置在 `configs/world/acceptance.json`。网格间距属于世界配置，主题不再决定物理网格。允许的 SLM 位置是世界范围内、位于允许区域的网格交点；隔离带只有参考线，不标为可配置 SLM 位置。

Checkpoint schema 19 使用统一 Q 编号，保存 circuit、逻辑运行状态、world、placement、队列、RNG、trace、metrics、硬件参数、物理计划、操作依赖与资源区间。QEC 模式还保存 Clifford 量子态及测量报告，真实投影与报告翻转在提交记录中区分。详见 [量子读出核心](docs/quantum_readout_core.md)。`RNG_DRAW` 是验证可复现性的基础事件，不代表物理噪声。

```python
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.simulation import Executor

restored = SimulationState.restore(saved_snapshot_json)
Executor(restored).run()
```

恢复检查字段、DAG 依赖计数、trace 版本及队列时序，并交叉核对物理 plan、cursor、预约、下一事件、时长、位置和门状态；不使用 pickle。不兼容的旧 checkpoint 须从原始输入重新编译，不能直接改写 schema 号；Raman 继续固定 1 μs。运行示例和验收命令可重新生成当前产物，不改写历史 trace 时长。

## 可视化

运行 `python examples/visualize_circuit.py --scenario three_gate` 打开 `artifacts/visualization/index.html`。运动播放已抽成可复用组件，程序通过 `VisualRecorder` 接入事件 observer，网页通过 `NeutralAtomViewer.mount()` 嵌入，详见 [接入文档](docs/visualization.md)。

时间统计包含装载、运输、回程、卸载、CZ 脉冲、空载、开关、空闲八类，有 Raman 时增加单比特类别；当前汇总按串行时间计算并拒绝重叠，原子累计时间单列。原子列表支持搜索/分页，详细操作按需展开。M1/M2 报告共用此组件，不再默认展示逐操作长图。

`VisualScene` 是只读绘图数据；PNG、SVG 和错误定位共享 renderer 与 `VisualTheme`。布局保持 x/y 等比例，原子编号与门作用比特可见。空闲靛蓝、移动橙色、gate/measure 运行中红色。

修改 `configs/visual/default.json` 后，可以仅根据已保存快照重新渲染报告，场景断言和模拟不重跑：

```powershell
python -m neutral_atom_env.testing.acceptance --rerender --theme configs/visual/default.json
```

报告每轮先失效旧 PASS，再写入当前结果。失败场景保留错误，不能被成功图片掩盖。旧产物目录不再作为验收入口，也不会自动重复生成。

## 实现范围

已实现初始化、不可变领域值、逻辑 DAG、holder 校验、稳定事件队列、原子式事件提交、结构化错误、checkpoint 恢复及观察型渲染。

MEASURE 的基本区域校验由 MeasurementDevice 执行；双比特门要求原子位于 entanglement 区。它们还不是完整物理设备模拟。逻辑 DAG 验收使用纯 reducer，不声称在 storage 执行了物理 CZ。

## Milestone 1：刚性 AOD 的连续移动

```powershell
python examples/run_single_gate.py
python -m pytest tests/test_milestone1.py
```

实现与验收计划见 `docs/milestone1.md`，报告入口为 `artifacts/milestone1/index.html`。
基准使用一个初始预置于 EZ 的静态伙伴 Q001，以及从 storage 搬运的 Q000。AOD 晶格间距保持 5 μm，Q000 连续移动到非 SLM 坐标 (3,-25)，与 SLM(5,-25) 上的 Q001 距离 2 μm。没有放大相互作用半径，也没有把两个同时装载的原子拉近。

已实现固定 footprint 的 capture closure（包括 incidental 原子）、解析整段 clearance 检查、全 EZ actual pair 枚举、显式 eager return 计划、load/offload 对齐与占据检查，以及经事件提交的资源预约/释放、DAG 状态和指标。每个 operation 的 start/complete 都记录在 trace。

基准预期：pulse 于 156.3 μs 完成，offload 后总周期 312.3 μs，AOD 路程 56 μm，load/offload 各 1 次。附带原子场景原子总路程从 56 增到 112 μm。

上述 M1 是恒速分段的受限运动学/几何基准；row_column 另有峰值运动学限制。当前 rigid 联合停车与 single_trap 已支持受限全 SZ 准备，M3-A 动态光阱规则已实现；通用持久起态待完成。陷阱深度、温度、原子损失和 RF 波形不在当前研究范围。
连续 eager 多 gate 已由 M2 支持；KEEP_LOADED 终态执行/恢复已有底座。动态 masks 和稳定 SLM 单比特串行执行已实现，单 trap KEEP 续接及 1Q/运输并行已实现，batch/RL 属于后续。真实量子态不纳入当前调度研究边界。


## Milestone 2：连续 eager 电路

`python examples/run_circuit.py` 生成 `artifacts/milestone2/index.html`。涵盖重复 pair、真实换伙伴、`CZ(a,b), CZ(a,c), CZ(b,d)`、独立门汇合，以及无法编译时的结构化诊断。初始布局公开限定：a/d 在 storage，b/c 已在 EZ；没有隐藏的伙伴预运输。

```python
from neutral_atom_env.simulation.milestone2_factory import make_circuit_state
from neutral_atom_env.simulation.scheduler import EagerScheduler

state = make_circuit_state('three_gate')
result = EagerScheduler(state).run()
assert result.status == 'completed'
print(state.metrics())
```

恢复后使用 `EagerScheduler(restored).run()` 继续整条电路。`Executor.run()` 只完成已经入队的计划。物理路径拒绝公开 `GATE_*` 注入；M0 逻辑演示专用 `LogicalTestExecutor`，不代表物理门执行。

三门独立预期：总 wall time 1112.9 μs，逻辑完成 888.9 μs，AOD/原子路程 256/216 μm。空载移动显式计时、只累加 AOD 路程。该节为受限 CZ 基准；当前参数化 U3/单比特别名另有 Raman 物理执行，CPHASE 仍不支持。完整契约及算式见 [M2 说明](docs/milestone2.md)。

`python -m pytest -q` 检查全部回归；重建 M1/M2 后运行 `node tests/replay_controls.cjs` 检查共享回放控制。


## 全 SZ 起步：rigid 联合运输与 EZ 交接

`python examples/run_rigid_parking.py` 读取 `configs/circuits/rigid_parking.json` 并生成 `artifacts/rigid-parking/index.html`。当前动态支撑规则下，默认四原子六 CZ 只完成前四门，对角门 G004/G005 因 `SHARED_AXIS_SUPPORT` 被拒绝，报告保留部分回放与诊断。受支持场景中，两个目标随完整捕获集合一起运到 EZ，一个转交 SLM，其他 AOD 原子局部靠近执行 CZ；恢复构型、重新接回后一起返回。rigid 间距始终不变。

部分交接是显式开启的理想硬件能力，holder 只在 Executor 完成事件时改变。可用 `--circuit` 传入 CZ PhysicalCircuit JSON，`--scenario pair --output artifacts/rigid-parking-pair` 查看最简单两原子流程。详见 [接口与物理契约](docs/rigid_pair_parking.md)。


## 输入电路的可替换编译管线

```powershell
python examples/compile_circuit.py --circuit configs/circuits/single_trap.json --platform configs/platforms/single_trap.json --placement configs/placements/eight_atoms.json --strategy single_trap
```

入口 `artifacts/single-trap/index.html`。只有一个活动 AOD trap：a 先放入 EZ SLM，b 随后到达执行 CZ，再逐颗返回 SZ。电路、平台、初始布局分别输入，编译策略可通过 `compiler=` 替换，物理 backend 与 observer 保持分离。当前支持 CZ、稳定 SLM 的 U3/单比特别名与有限路由候选，不保证任意门集/布局成功；M3 跨门动作仍未全部完成。见 [接口、输入和验收范围](docs/circuit_pipeline.md)。


M4 greedy 已接入线路工作台，默认示例可编辑并重新编译。候选成本、连续 Raman、统一终态与复现见 [M4 greedy](docs/milestone4_greedy.md)；本轮记录见 [交接日志](instruction/logs/2026-09-11-m4-greedy.md)。
