# M3-A：动态光阱与交接

2026-09-10 实现时使用 checkpoint schema **10**；当前 schema **13**，viewer 格式 **neutral-atom-view/2**。本页描述动态支撑的串行操作实现；U3 与 M3-B 任务拆分随后已实现，见 [任务 API](task_program.md)，M3 最小操作级并行随后已实现，见 [M3](milestone3.md)。

## 状态与时间

- `WorldState.traps` 保存固定候选几何。`StaticTrap.enabled` 只提供初始化默认值；实时开关真值是 `SimulationState.slm_enabled`，不能通过改 world 配置开关现有原子。
- `AODRuntimeState.rows/columns` 为容量，`configuration()` 为完整轴几何，`enabled_rows/columns` 为布尔 masks。默认全关，活动 cell 为启用行列的 Cartesian 积。cell ID 不因开关改变；关闭轴仍遵守 backend 的顺序、间距、边界和运动计时。
- `TrapState(rows, columns, slm)` 是不可变、规范排序的支撑快照；plan 保存 `initial_traps` 与 `predicted_traps`。恢复从起态重放真实操作，核对每个运行边界的 masks 和交接阶段，不从当前 masks 猜起态。
- `OperationType.TRAP_SWITCH` 的 `switch_state` 声明目标开关状态；`ProgramBuilder.add(..., switch_state=...)` 构建。开始验证，完成提交；时长来自 `HardwareConfig.switch_duration_us`。默认 **1 μs** 是项目可配置成本，未经设备标定。
- LOAD/RECAPTURE、OFFLOAD/PARK 的开启目标及撤去源光阱包含在现有 load/offload 时长内（默认各 100 μs，含 ramp/稳定余量），不另收一次独立开关成本。trace 保存 `switch_timing=included_in_transfer_duration`。

## 可恢复的交接边界

1. 开始前：对齐合法 SLM 格点，静止、源 holder、目标占位及完整受影响集合合法。
2. `OPERATION_STARTED`：建立目标支撑，保存 `TransferRuntime(kind, bindings, source_traps, target_traps, stage='target_supported')`；源支撑保持，holder 仍归源。此时禁止运动、其他开关或新交接。
3. `OPERATION_COMPLETED`：再次验证；同一完整下一状态内提交新 holder、撤去源支撑、清除 transfer。没有无支撑窗口、双 holder 或坐标变化。

这是包含稳定余量的粗粒度交接协议；没有另设光强、ramp 百分比或波包阶段。时间区间取活动 operation 的 start/duration。backend 的 `load/offload/park/recapture` 是只读完整推演，Executor 使用 begin/finish 两个边界提交。

SLM→AOD 开启绑定 cell 所需行列，检查全部活动交点；完整 LOAD 的实际捕获集合必须等于 bindings，包括附带原子。部分 RECAPTURE 不会暗中抓取其他原子，新增交点靠近未绑定静态原子即拒绝。rigid footprint 内未对齐的原有保守检查仍保留。

AOD→SLM 先开启目的 SLM。关闭目标 cell 时优先选择没有剩余载荷的整行，否则选择没有剩余载荷的整列；两者都携带其他原子则返回 `SHARED_AXIS_SUPPORT`。全部卸载后两个 masks 全关。因此单 cell 独立控制没有被偷偷引入。

## 安全边界与旧案例变化

活动 AOD 的所有交点（包括空阱）到全部静态原子的线段最短距离必须不小于 `minimum_clearance_um`。rigid 直线与 row_column 同步单调三次轨迹均覆盖整段。新开启操作也检查全部交点；对齐例外只用于 begin-transfer 的零长度、明确绑定对象，MOVE 的 depart/approach 标记不能免除活动空阱扫掠。

关闭后的空 AOD 可以重定位，仍受 backend 几何限制且累计真实时间/AOD 路程。开启空 SLM 不能绕过绑定交接在 mobile 原子下方建立支撑。带载行列或已占据 SLM 不能直接关闭。loaded 原子的相互碰撞、活动 SLM 路径避让和严格完整轴间距仍校验。

已声明 depart/approach 段的对齐、单调离开和清出端点契约继续保守保留，即使 LOAD 已关闭源 SLM；普通 backend 对已关闭源的运动无需该 SLM 例外。计划中伪造或遗漏边界标记仍由独立 validator 拒绝。

旧 rigid-parking 四原子 2×2 六门案例现在只完成前四个有替代捕获 footprint 的同行/同列门；两条对角 pair 需要全捕获，随后只 PARK 一颗会切断其他支撑，最终明确 `stalled`。未移动初始原子、放宽距离或隐式搬动伙伴来保留旧六门成功结论。双原子停车仍通过；完整四阱的整行交接也有正例。

## 证据入口

```powershell
python -m pytest -q tests/test_dynamic_traps.py
python examples/run_dynamic_traps.py
python examples/compile_circuit.py --circuit configs/circuits/single_trap.json --platform configs/platforms/single_trap.json --placement configs/placements/eight_atoms.json --strategy single_trap --output artifacts/m3-single-trap
node tests/single_trap_controls.cjs artifacts/m3-single-trap/index.html
```

`artifacts/m3-dynamic-traps`：独立明确起态的空阱开/关 + 一门程序，29 operations，1125.721356 μs，其中独立开关 2 μs；输出交接/开关 checkpoint、trace、图像和回放。它将空 AOD 起点声明为 (-5,0)，用于展示安全位置开启，不替换标准基线输入。

`artifacts/m3-single-trap`：原输入八原子十二 CZ，336 operations、696 commits、18026.915473838395 μs；36 LOAD、36 OFFLOAD，全部从真实支撑阶段执行。时间不变是因为开关包含在装卸时间内，空载路线已经关灯。

viewer 从 Executor 帧读取 masks/transfer，关闭的 AOD 不绘制活动圆环，关闭 SLM 有独立禁用标记；交接显示目标支撑已建立、已提交 holder。SLM mask 首帧完整保存、变化时再保存，null 沿用前帧。八类 schedule 新增独立光阱开关；仍只支持串行区间，未把并行统计冒充完成。

最终验证及明确未验证项见 [本轮日志](../instruction/logs/2026-09-10-m3-dynamic-traps.md)。旧 checkpoint 1–9 和 viewer /1 不自动补造光阱历史，需重新生成。
