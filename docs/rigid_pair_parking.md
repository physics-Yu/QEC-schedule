# 全 SZ 起步的 rigid 联合运输与 EZ 临时交接

本轮实现用户明确选择的流程：两个目标随同一个 rigid AOD 一起运到 EZ，将一个目标转交给预配置的空 SLM trap，剩余 AOD 原子局部平移，执行 CZ；随后恢复进 EZ 时的构型、重新接回目标，一起返回 SZ 并卸载。所有运输、交接和门操作都由实际事件提交。

这是一个完整 CZ 电路的可执行运输基线，涉及门内动态 holder；原路线中跨计划 KEEP、RETURN_ONLY、REPOSITION_AND_KEEP 的通用 M3 动作空间仍未全部实现。

## 运行与输入

```powershell
python examples/run_rigid_parking.py
python examples/run_rigid_parking.py --scenario pair --output artifacts/rigid-parking-pair
python examples/run_rigid_parking.py --circuit configs/circuits/rigid_parking.json
```

默认读取 [六门电路 JSON](../configs/circuits/rigid_parking.json)，构造真正的 `PhysicalCircuit`，然后由 `DynamicGateDAG → EagerScheduler → MotionCompiler → Executor → VisualRecorder` 执行并生成完整动画。可以传入相同 JSON 结构的 CZ 电路；当前示例布局提供 Q000–Q003，未知 Q 会明确拒绝，非 CZ 门会返回不支持的诊断。

```python
from neutral_atom_env.circuit import PhysicalCircuit
from neutral_atom_env.domain.models import PhysicalGate
from neutral_atom_env.simulation.rigid_parking_factory import make_rigid_parking_state
from neutral_atom_env.simulation.scheduler import EagerScheduler
from neutral_atom_env.visualization import VisualRecorder

circuit = PhysicalCircuit((PhysicalGate('G000', 'CZ', ('Q000', 'Q003')),))
state = make_rigid_parking_state(circuit=circuit)
recorder = VisualRecorder(state)
result = EagerScheduler(state).run(on_event=recorder.observe)
recorder.write('artifacts/custom-parking/index.html')
```

默认产物目录 `artifacts/rigid-parking/`：`index.html` 为运动播放器，`report.html` 为输入 DAG、时序表与第一门关键帧，另有 `circuit.json`、`plans.json`、`trace.jsonl`、`initial.json`、`final.json`、`metrics.json`、`result.json`、`recording.json`。开始时失效旧成功页，执行失败写 failed/stalled 证据。产物由源码生成，不手工编辑。

## 显式硬件规则

`HardwareConfig.selective_transfer_enabled` 默认 False。新演示以 `backend='rigid'`、该能力 True 初始化；其他既有基准不自动获得部分交接能力。

rigid 只约束所有 AOD trap 的相对坐标不变；选择性 AOD↔SLM 交接是另外一项明确的理想硬件能力。该开关表达可控制目标站点的转移，不表示已模拟光强、RF 波形、温度、势阱竞争或实验保真度。空 AOD trap 光场对被 SLM 保留原子的扰动仍未模拟。

新增操作 `AOD_PARK` 和 `AOD_RECAPTURE` 各携带不可变 `Operation.transfer_bindings`，明确 atom ID、mobile cell 和 SLM trap ID。backend 强制验证：能力开启、阵列静止、binding 集非空且无重复、实际源 holder 正确、目标空闲、SLM trap 启用且在 EZ、cell 与 trap 对齐、原子几何合法。未列入交接集的 holder 保持不变。

交接开始只验证并安排完成事件；完成时 Executor 才提交 holder。非法事件不消耗队列或改写 trace/state。PARK 不改变 CZ 的逻辑状态，CZ 只有真实 PULSE 完成才释放依赖。

完整 LOAD 仍按实际 capture closure 捕获，完整 OFFLOAD 仍必须处理全部已装载原子。原始 `plan.bindings` 保留 SZ 来源；局部交接 bindings 使用 EZ 目的地，二者不能混用。

## 编译和独立审核

当硬件为 rigid、选择性交接开启、两个目标都在 SZ 时，`MotionCompiler` 转入 `rigid_parking_compiler.py`。它枚举可同次捕获两目标的 footprint、两个目标的 anchor 选择、实际空 EZ trap，并复用可替换 `MotionPlanner.candidates()`。

搜索上限为 64 个 source pose、每个 anchor 最多 16 个 EZ trap、每组最多 16 个 route、总共最多 256 个 route 尝试。当前上限为源码常量；有限搜索失败返回 `PAIR_PARKING_ROUTE_UNSUPPORTED`，不是物理无解证明。不能同次捕获的 pair、无法安全局部靠近的布局，不隐式单独搬运或修改初始状态。

局部靠近沿进 EZ 时两目标的相对方向缩短到 `norm(hardware.interaction_offset)`，默认 2 μm；这是规划目标距离，独立于 `interaction_distance_um`。缩小门半径会导致拒绝，不随之放宽判据。没有使用非 rigid 伸缩。

```text
空载定位（若需要）
→ SZ 联合 LOAD
→ 共同运输：源 trap 脱离 / 通道 / EZ trap 对齐
→ PARK 一个目标
→ 剩余 AOD 原子局部平移
→ CZ PULSE
→ 恢复进 EZ 时的 AOD pose
→ RECAPTURE 同一原子、同一 cell
→ 全捕获集合沿逆路线共同返回
→ SZ 联合 OFFLOAD
→ 空载归还原 pose（若需要）
```

`parking_validation.py` 独立重放所提交的 operations，不信任 planner 标签。它检查完整阶段顺序、每次交接集、精确时长、整段路径、全 EZ 作用对、recapture 前原构型恢复、全捕获集合回归，以及包含 EZ trap 的资源预约。

SLM 避让的局部豁免只能在紧邻交接的 approach/depart 段使用，只作用于显式绑定的 atom/trap。未绑定的其他 AOD 原子照常检查所有开启 SLM trap，不因其中一颗需要交接而获得通用豁免。

计划结束仍返回卸载，因此可以复用现有连续 scheduler。不同门按真实 DAG 状态选择；不能用可视化预设时间直接释放 successor。`target_configuration` 的任意上层覆盖在停车流程中明确拒绝，停车目标应来自真实空 EZ trap。

## 可复现数字

单门：Q000=(0,0)、Q001=(10,0) 均在 SZ；EZ_PARK=(5,-35) 初始为空；AOD 2×2，rigid spacing=10 μm。

| 时刻 μs | 已提交状态 |
| ---: | --- |
| 0 | 全部原子由 SZ 的 SLM 承载 |
| 100 | 两原子完成联合装载 |
| 180 | 两原子到达 (5,-35)、(15,-35) |
| 280 | Q000 转交 EZ_PARK，Q001 仍由 AOD 承载 |
| 296 | Q001 到 (7,-35)，与静态 Q000 距离 2 μm，开始 CZ |
| 296.3 | CZ 完成 |
| 312.3 | Q001 回到 (15,-35)，AOD 恢复进 EZ 构型 |
| 412.3 | Q000 重新由原 AOD cell 承载 |
| 492.3 | 两原子回到 SZ 来源位置 |
| 592.3 | 联合卸载完成 |

共同运输每程 40 μm，局部靠近/恢复各 8 μm：AOD 总路程 96 μm；原子总路程 `2×80+16=176 μm`；总周期 `4×100+96/0.5+0.3=592.3 μs`。装载/卸载各计 2 次，包含重新接回/临时停车；捕获数量累计为 3，表示装载事件数量之和，不是唯一原子数。

默认六门演示的四颗原子构成 SZ 的 10 μm 方形，因此每次完整捕获四颗，含两个附带原子。临时停住目标后，其余三颗随 rigid AOD 运动；额外作用对仍严格拒绝。六门总周期 **3666.9370849898487 μs**，逻辑完成 **3352.6528137423866 μs**，AOD/原子路程 **632.5685424949238 / 2417.7056274847714 μm**，168 个提交事件。参数未标定。

## 恢复、动画与边界

checkpoint 升级为 **schema 8**，保存逐操作交接集和显式能力，拒绝 schema 1–7；旧产物需重建。runtime 校验从初始 placement 逐操作推导 holder，不能再用一个全局 loaded 布尔值代表所有原子。

播放器只对本次 PARK/RECAPTURE 集合做交接形变；其他原子不切换 marker。停在 SLM 的原子在移动段保持真实静态坐标，计划路径叠加也在停车处停止该原子的去程。时序表将 PARK 归入卸载、RECAPTURE 归入装载，按真实操作区间定位。图中的圆环大小不代表物理距离。

当前未实现通用跨门 KEEP、任意初始布局路由、多 AOD、batch pulse、非 CZ 物理执行或 QEC 状态。此页面是实际轨迹的离线回放，非实时浏览器推送。单门与四原子完整电路是不同层次的验收，不能称作数百原子物理规模测试。
