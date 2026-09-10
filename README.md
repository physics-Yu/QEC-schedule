# Neutral Atom Environment — Milestones 0–2

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

Checkpoint schema 8 使用统一 Q 编号，保存 circuit 顺序、逻辑运行状态、world、placement、事件序号与待执行队列、当前 RNG 状态、trace 和 metrics，并加入硬件参数、physical plan、operation 游标和 reservation。`RNG_DRAW` 是验证可复现性的基础事件，不代表物理噪声。

```python
from neutral_atom_env.simulation.state import SimulationState
from neutral_atom_env.simulation import Executor

restored = SimulationState.restore(saved_snapshot_json)
Executor(restored).run()
```

恢复检查字段、DAG 依赖计数、trace 版本及队列时序，并交叉核对物理 plan、cursor、预约、下一事件、时长、位置和门状态；不使用 pickle。旧 schema 1–7 不包含当前完整运行时数据，因此显式拒绝恢复。运行示例和验收命令可重新生成 schema 8 产物。

## 可视化

运行 `python examples/visualize_circuit.py --scenario three_gate` 打开 `artifacts/visualization/index.html`。运动播放已抽成可复用组件，程序通过 `VisualRecorder` 接入事件 observer，网页通过 `NeutralAtomViewer.mount()` 嵌入，详见 [接入文档](docs/visualization.md)。

时间统计固定七类，按设备累计；原子列表支持搜索/分页，详细操作按需展开。M1/M2 报告共用此组件，不再默认展示逐操作长图。

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

这是恒速分段的运动学/几何模型，未包含加速度、陷阱深度、温度、原子损失或 RF 波形。两个目标均从 storage 出发时，rigid 编译路径明确拒绝，分阶段放置伙伴尚未实现；不假装通过初始预置完成了这一过程。
连续 eager 多 gate 已由 M2 支持；KEEP、batch、真实量子态及 RL 留给后续里程碑。


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

三门独立预期：总 wall time 1112.9 μs，逻辑完成 888.9 μs，AOD/原子路程 256/216 μm。空载移动显式计时、只累加 AOD 路程。参数化门（含 CPHASE）返回 `UNSUPPORTED_GATE`。完整契约及算式见 [M2 说明](docs/milestone2.md)。

`python -m pytest -q` 检查全部回归；重建 M1/M2 后运行 `node tests/replay_controls.cjs` 检查共享回放控制。


## 全 SZ 起步：rigid 联合运输与 EZ 交接

`python examples/run_rigid_parking.py` 读取 `configs/circuits/rigid_parking.json` 并生成 `artifacts/rigid-parking/index.html` 完整六门动画。两个目标随完整捕获集合一起运到 EZ，一个转交 SLM，其他 AOD 原子局部靠近执行 CZ；恢复构型、重新接回后一起返回。rigid 间距始终不变。

部分交接是显式开启的理想硬件能力，holder 只在 Executor 完成事件时改变。可用 `--circuit` 传入 CZ PhysicalCircuit JSON，`--scenario pair --output artifacts/rigid-parking-pair` 查看最简单两原子流程。详见 [接口与物理契约](docs/rigid_pair_parking.md)。
