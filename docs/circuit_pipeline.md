# 可替换电路编译管线与单 trap 基线

> 范围更新：当前 schema 13；M3-A 动态光阱、交接支撑和活动空 AOD 扫掠已实现并重新运行标准十二 CZ 基线。参数化 U3/别名串行执行已实现，见 [工作台](circuit_workbench.md)；M3-B 独立串行任务已实现，见 [任务接口](task_program.md)；最小并行与单 trap 持久编译已实现，见 [M3](milestone3.md)。[M3-A API/证据](dynamic_traps.md)；[后续目标契约](../instruction/compiler_contract.md)。

输入电路、平台配置、初始原子布局，生成经过物理校验的时序计划、实际事件和共享动画。输入入口不包含固定门序列、原子数量或场景坐标。当前实现用户选择的单活动 AOD trap 串行 CZ 编译策略。

## 运行

```powershell
python examples/compile_circuit.py --circuit configs/circuits/single_trap.json --platform configs/platforms/single_trap.json --placement configs/placements/eight_atoms.json --strategy single_trap --output artifacts/single-trap
```

默认示例是八原子、十二个 CZ；覆盖独立门、换伙伴和依赖汇合。动画在 `artifacts/single-trap/index.html`，输入依赖、实际时序图、关键帧在 `report.html`。另保存原始输入、编译策略配置、plans、trace、metrics、初末 checkpoint、recording 与编译结果。失败会使旧成功入口失效；`result.json` 区分 completed、stalled、failed。

输入文件分别是：

- [电路](../configs/circuits/single_trap.json)：`{"gates":[{"id":"G000","gate_type":"CZ","qubit_ids":["Q000","Q001"]}]}`。依赖由同一物理比特上的输入门顺序推导。
- [平台](../configs/platforms/single_trap.json)：world bounds/zones/traps/grid、hardware 参数、AOD 初始 pose 和行列数量。距离单位 μm、时间单位 μs；当前恒速参数是未标定的运动学模型。
- [初始布局](../configs/placements/eight_atoms.json)：`{"Q000":"S000","Q001":"S001"}`，允许增加不参与电路的旁观原子。未知 Q、重复占用或非法 trap 在初始化时拒绝。

更换这些文件即可改变门序列、原子数、trap 名称、坐标、zone 和初始映射，不需要修改 factory。测试另外使用三原子、不同 Q/trap ID、平移后的坐标系与不同 EZ 站点，不只重复默认布局。

## 分层与插件契约

```text
PhysicalCircuit → DynamicGateDAG → READY frontier
                                      ↓
平台 + 初始布局 → 当前 SimulationState → 调度 policy
                                      ↓
                       GateCompiler.compile(intent, state)
                                      ↓
                           不可变 CompiledPlan
                                      ↓
                    独立程序校验 + hardware 约束
                                      ↓
                         Executor → 实际事件
                                      ↓
                    新 placement / DAG / metrics → observer
```

`GateCompiler` 是 [编译策略协议](../src/neutral_atom_strategies/planning/compilers.py)，物理 `hardware.backend` 是另一层。前者决定如何实现门，后者决定哪些运动/交接/作用合法。不能为了更换运输策略去修改 circuit 或 renderer。

```python
import json
from pathlib import Path
from neutral_atom_env.platform import Platform, load_circuit
from neutral_atom_app.pipeline import run_circuit
from neutral_atom_strategies.motion.single_trap import SingleTrapCompiler

circuit = load_circuit('configs/circuits/single_trap.json')
platform = Platform.load('configs/platforms/single_trap.json')
placement = json.loads(Path('configs/placements/eight_atoms.json').read_text())
result, state, recorder = run_circuit(
    circuit, platform, placement,
    compiler=SingleTrapCompiler(anchor_order='reverse'),
)
recorder.write('artifacts/custom-circuit/index.html')
```

外部实现只需提供 `compile(intent, state) -> CompiledPlan`，通过 `compiler=YourCompiler()` 注入，无需修改注册表。`make_compiler` 为 CLI 提供内置 `single_trap` 与 `legacy_eager` 名称；选择旧策略不会自动修改平台或隐式预放 EZ 伙伴，超出旧策略能力时返回诊断。

还可以传 `policy=...` 替换调度选择；其当前契约为 `compile_first(state) -> (plan_or_none, failures)`，它可以调用编译器比较可执行候选。`compiler` 与 `policy` 不同时传。当前 EagerBaseline 按稳定 READY 顺序选择首个可编译门，plan 整体串行预约；不是已实现时间窗口优化器或并行调度。

编译器只推演状态，失败不能修改实时 holder/DAG/trace。Executor 仍是唯一实时写入者。调度释放 successor 的依据是真实 pulse 完成，而不是编译成功。

## 单活动 trap 策略

硬件设置 `backend='rigid'`、`rows=columns=1`，`selective_transfer_enabled=False`。SZ 的 SLM trap 继续持有其他原子；“一个 trap”指一个活动 AOD trap，不是全平台仅有一个 SLM trap。没有在过程中改变 AOD 轴数量或使用非 rigid。

每个 `CZ(a,b)`：

1. 空 AOD 到 a 的 SZ 来源，LOAD(a)。
2. 将 a 搬到一个实际空 EZ SLM trap，OFFLOAD(a, EZ)。
3. 空 AOD 去接 b，LOAD(b)，将 b 搬到 a 旁边的作用位置。
4. a 静态、b 由 AOD 承载，校验全 EZ 作用对并执行 CZ。
5. b 返回本次 SZ 来源并卸载。
6. 空 AOD 返回 EZ，重新 LOAD(a)，将 a 搬回本次 SZ 来源并卸载。
7. 空 AOD 返回计划起点；调度器选择下一个 READY 门。

每门包括三次真实 LOAD、三次 OFFLOAD、一次 pulse；没有伪造 PARK 事件，也不需要选择性部分交接能力。来源取自当前 placement，并非 atom 永久 home 属性。当前返回目标是本计划开始时的来源位置，完整电路结束后全部回到输入布局。

策略尝试两个 anchor 顺序，每个最多 32 个空 EZ trap；每次 loaded 路由最多 64 个 HalfGridPlanner 候选。距离目标取 `hardware.interaction_offset`，不能改变 gate 半径或 clearance 让规划通过。无路返回有限候选耗尽，不能视为物理无解证明。当前空载先关 AOD 再直线定位，路径计时；LOAD/OFFLOAD 显式记录交接内启用/撤去支撑，活动空阱也检查完整扫掠。

## 通用程序校验

[ProgramBuilder 与 replay_program](../src/neutral_atom_env/program/builder.py) 建立独立于运输模板的执行契约：

- 每个 LOAD/OFFLOAD 明确声明 `Operation.transfer_bindings`，包括实际 atom、cell、源或目的 SLM trap。`plan.bindings` 只汇总各原子的首次装载，不能当作每次装卸的共同目标。
- `initial_placement` 与 `predicted_placement` 分开，恢复不再假设终点等于起点。另保存 initial_traps/predicted_traps，checkpoint 为 **schema 13**，旧 1–12 拒绝恢复，需重新生成。
- 校验实际操作序列、装卸集合、holder/占用/对齐、整段避让、精确时长、真实作用对、总距离、资源及最终预测状态。当前程序对应一个 READY CZ，必须恰好一个实际 pulse。
- 装卸次数、先搬哪颗、运输路线、EZ 停留时长不是固定的物理模板。`RETURN_AND_OFFLOAD` 的回归要求来自显式 intent；程序也能表达 `KEEP_LOADED` 终态，并已验证其执行与保存恢复。
- approach/depart 豁免必须紧邻真正的装卸操作，且绑定完全一致；无关 trap 与其他原子不获得豁免。offload 在移动中拒绝，必须声明实际承载 cell。
- 新程序接口保留旧 M1/M2/联合停车计划的独立兼容审计，未删除其历史策略契约。策略名仅为来源说明，不授予物理豁免。

M3 的 PersistentTargetCompiler/ResidentCompiler 已支持声明单 trap 平台族的 loaded 起点、无门清理、驻留与新站点卸载；族外不保证任意 KEEP 状态都有有限可行路由，见 [M3](milestone3.md)。

## 结果与验收口径

第一门：a 初始 (0,0)，b 初始 (10,0)，a 停靠 EZ0=(5,-35)，b 在 (3,-35) 做 CZ。装载运输长度为 a 去/回 40/45 μm、b 去/回各 48 μm；空载两程各 `sqrt(5²+35²)` μm。原子总路程 **181 μm**，AOD 路程 **251.71067811865476 μm**，总周期 **1103.7213562373095 μs**。回程不要求机械地复用同一条路线。

默认十二门：696 个提交事件、336 个 operations，wall **18026.915473838395 μs**，逻辑完成 **17163.26724323606 μs**，AOD/atom 路程 **5411.657736919199 / 3502 μm**，装载/卸载各 36 次，附带运输原子为 0。

动画从实际提交记录产生，所有交接只有当前一个原子变化；停在 EZ 的 anchor 在 b 运输时保持静止。八类 schedule 仍显示实际时序，不只汇总总量。查看新入口，旧 rigid-parking 页面仍是旧联合运输策略。

物理测试覆盖逐事件边界恢复、来源与目标不同的交接、非回归终态、外部布局/电路/编译选项变化、非法程序与明确诊断。Node 控制检查使用 DOM/Canvas doubles；M3-A 本轮另已查看静态支撑图并用真实浏览器检查动态开关、交接和 holder 提交，未做完整 FPS/全尺寸验收。

## 与 M3 的关系

原 M3 的目标是动态 placement 与 KEEP、RETURN_ONLY、REPOSITION_AND_KEEP、新站点卸载等跨计划动作。当前完成其所需的程序/状态抽象，以及用户指定的单 trap 返回基线；不能把整张 M3 动作表标为完成。

当前能接受外部定义、规模不写死的 **CZ + U3/别名混合电路**，前提是物理比特在输入布局中、平台满足策略要求、有限路由搜索能找到合法路线。单比特当前仅支持稳定 SLM 的串行执行；测量、CPHASE、多 AOD 和任意障碍布局的完备路由未实现，因此不承诺任意门集/任意布局总能成功。

## 下一步接口迁移

M3-A 动态光阱和交接/扫掠硬规则已完成；M3-B 目标状态任务已接到局部 compiler 和独立 validator；M3-C 单 trap 持久编译与 M3-D 操作级调度也已实现。保留现有 Python 注入方式作为兼容基线，新的目标/约束与有限候选 API 见 [M3](milestone3.md)，M4 仍需返修全局策略接口。U3/别名、gateless 任务、loaded 起点、显式终态和 1Q/运输重叠按 [M3 工作包](../instruction/milestones.md) 验收；不把一门一个完整往返固化为通用接口。
