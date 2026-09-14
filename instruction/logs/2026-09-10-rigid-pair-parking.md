# 2026-09-10 · rigid 双原子运输与 EZ 临时交接

- 状态：COMPLETE（用户指定的 rigid 门内交接与 CZ 电路基线；非完整通用 M3）
- 用户授权：全部原子初始位于 SZ；rigid AOD 同运目标对，在 EZ 将一颗交给 SLM，剩余移动原子靠近执行 CZ，恢复构型、接回、同运返回；完整 PhysicalCircuit 到动画。暂不启用非 rigid 或通用 KEEP 策略。
- 范围：显式部分交接硬件能力、逐操作 bindings、执行/恢复硬逻辑、独立物理计划校验、有限电路编译与共用回放。
- 发现当前源码含另一路由任务的 HalfGridPlanner/独立 validate_plan/SLM clearance 与 schema 7；保留这些接口，不用旧 handoff 的 schema 6 假设覆盖源码。

## 实现

- `domain/operations.py`、`hardware/partial_transfer.py`、`hardware/rigid_aod.py`：显式理想能力开关、PARK/RECAPTURE、逐操作不可变 transfer_bindings；源 holder、目标空闲、静止/对齐、EZ trap 与几何硬校验。默认能力关闭，完整装卸的 capture closure 不变。
- `motion/rigid_parking_compiler.py`：联合捕获、实际空 EZ trap、停车、局部平移、CZ、恢复构型、接回、逆路线共同返回。复用可注入 planner，有限搜索不冒充完备。
- `motion/parking_validation.py`：独立重放真实计划，核对阶段、交接集合、时间、全捕获几何、资源及回归；移动豁免仅覆盖紧邻交接的真实绑定。
- `simulation/physical_executor.py`、`runtime_validation.py` 与 checkpoint codec：完成事件才提交 holder；恢复逐操作重建 placement，schema 8 拒绝旧版本。非法操作/快照不部分修改状态。
- `simulation/rigid_parking_factory.py`、`configs/circuits/rigid_parking.json`、`examples/run_rigid_parking.py`：真实 PhysicalCircuit 输入，经 DAG/scheduler 编译执行，记录完整四原子六 CZ 电路。失败页和 result 状态不会保留旧成功展示。
- 共享 `visualization/recording.py`、`summary.py`、`viewer.js`：选择性交接动画、静态 parked 原子、正确去程路径、七类统计与真实时序条。静态 renderer 调整近距离门原子标签，避免遮叠。
- 设计/使用/数值和范围见 [实现说明](../../docs/rigid_pair_parking.md)，同步 README 与相关 instruction。

## 本轮验证

| 命令 | 结果 |
| --- | --- |
| `python -m pytest -q` | 最新完整运行 171 passed, 1 warning，179.01 秒；warning 为既有 dateutil 弃用提示 |
| `python examples/run_rigid_parking.py` | 六 CZ completed，78 operations、168 commits，全部回归初始 placement/axes |
| `python examples/run_rigid_parking.py --scenario pair --output artifacts/rigid-parking-pair` | 单 CZ completed，13 operations、28 commits |
| `python examples/run_single_gate.py` / `python examples/run_circuit.py` | M1 五场景 / M2 五场景 PASS |
| `python examples/run_reconfigurable_aod.py --backend row_column` | 三场景 PASS |
| `python examples/run_motion_planner.py` | row_column 与 16 原子左右路线三场景 PASS |
| `python examples/visualize_circuit.py --scenario three_gate` | completed，81 compact frames |
| `node tests/parking_controls.cjs` | 单门实际数据：交接中/完成后 holder、静态 anchor、局部 CZ、恢复/接回；完整六门、rigid 轴与源数据不变 PASS |
| `node tests/replay_controls.cjs` / `replay_row_column.cjs` | 原有 rigid/row_column、多门、双时钟与回放控制 PASS |
| `node tests/viewer_component.cjs` | 512 原子合成渲染数据、双实例/清理与真实 row_column PASS；非物理规模测试或浏览器 FPS |
| `node tests/schedule_controls.cjs` / `motion_controls.cjs` | 时序位置/短脉冲/定位、计划路线/避让开关与不可变数据 PASS |

`tests/test_rigid_parking.py` 新增 23 个用例，覆盖独立预期、各事件边界恢复、六门换伙伴/汇合、非法 PARK/RECAPTURE、伪造阶段/时长/几何/资源、恢复篡改与无停车位诊断。完整测试包含这些用例，不将多轮数量累加。

单门独立预期：联合装载 100 μs；联合到达 180；停车完成 280；CZ 296–296.3；恢复构型 312.3；接回 412.3；回 SZ 492.3；最终卸载 592.3。AOD/atom 路程 96/176 μm。

六门：wall=3666.9370849898487 μs，逻辑完成=3352.6528137423866 μs，AOD/atom=632.5685424949238/2417.7056274847714 μm。每次捕获四颗，包括两颗附带原子；停住一颗后其余三颗共同移动。

静态检查 `artifacts/rigid-parking-pair/pulse.png`：Q000 在 EZ SLM，Q001 为 AOD 原子，距离 2 μm，标签上下错开放置；轴间距保持 10 μm。本轮未进行真实浏览器验收，前序本地 HTML 自动访问被 URL 安全策略限制，未绕过。Node 使用 DOM/Canvas doubles。

## 限制和下一步

选择性转移是独立于 rigid 的显式理想能力，尚未模拟 RF/光强/空 trap 光场或实验保真度。当前每门返回卸载，未实现通用 KEEP、非 CZ、多 AOD、任意初始布局和数百原子物理规模验证。编译候选有上限，失败不代表无解。

下一条可执行任务：为现有 rigid pipeline 加独立布局输入与多个合法 EZ 停靠位场景，在不改作用距离/安全间距的条件下增加编译覆盖，然后再讨论跨计划驻留策略。
