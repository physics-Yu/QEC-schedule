# 步骤 7–12 验收

本文件保留步骤 7–12 的历史验收背景；当前公共路径已经按 R7–R12
迁移为 `PhysicalCircuit -> SemanticRequestPlan -> RuntimeScheduler -> epoch trace`。
默认仍为 d=3 rotated surface code；`run_cycle(config, code=...)` 接受任意满足公共接口的
QECCode。Memory、Entanglement、Measurement 自上向下对齐，Reservoir 位于 Memory 右侧。

## 7：任务池与资源锁

`scheduler/model.py` 提供 Task、TaskState、Pool、Priority、ResourceLock。
状态包括 WAITING、READY、RUNNING、DONE、BLOCKED。
任务池包含 P_MOVE、P_1Q、P_ENTANGLE、P_MEASURE、P_REFILL；最后一项为后续 refill 保留，当前不生成 refill 操作。
PREPARE/RESET 与单原子控制进入 P_1Q，但使用独立 state_preparation 设备资源。
资源锁按 owner 原子性申请全部资源，容量不足时不保留部分锁；未知资源不会被默认为可用。

## 8：事件驱动调度

`Scheduler(config).run(plan, initial_state)` 消费硬件 lowering 结果，不依赖 surface-code 私有结构。
按剩余关键路径优先，其次按进入 ready 的时间和稳定 ID 排序；并非全局最优求解器。
完成事件推进时钟，不使用固定时间步调度。依赖完成后任务才进入 ready；容量不足时标记 BLOCKED，下一完成事件后重试。
没有可执行任务且没有未来事件时报告 deadlock 和相关任务 ID。

运输任务连续包含 PICKUP、MOVE、DROPOFF，trace 保留三段各自的精确时间。
AOD custody 从 pickup 开始持续到 dropoff 完成；阶段之间不另行调度。
兼容且各阶段时长一致的运输可共用一个 AOD 控制器，原子锁仍逐个持有。
其他纠缠 pair/site/zone 与测量 site/zone 的 reservation 从入口动作前持有至全部出口动作完成。
测量后暂留的 ancilla 占位持续到 RESET 后运走；无出口的 reservation 持有至整个运行结束。
相同区域、相同时长、原子不相交的 ENTANGLE 或 MEASURE 可以共享一批激光操作。
若候选批次受区域或 site 资源限制，调度器只接纳可以原子性获得资源的子集。

资源含 AOD、local_1q、rydberg、imaging、state_preparation、atom_lock、pair、site、zone。
zone 容量单位是**原子数**，纠缠 pair 需 2 个单位。几何 site/pair 数仍构成额外上限。
多个 AOD 控制器视为彼此独立、参数相同的设备，不模拟其光路互扰。

## 9：完整运行与指标

```powershell
.\.venv\Scripts\python.exe examples/demo_surface_code_cycle.py
.\.venv\Scripts\python.exe examples/demo_surface_code_cycle.py --rounds 3 --primitive CNOT --no-plot --output-dir results/three_rounds
```

`trace.json` 含初末 HardwareState、逐 epoch 起止时间/端点/依赖/原子、request/epoch ID、
资源持有区间及容量、调度决策、AOD 参数、运行配置和 state snapshots。
默认单轮最后 RESET 并返回 Memory，所以动画中 measurement 发生在返程前。
输入 HardwareState 不被修改。

`validate_trace` 独立检查 epoch 持续时间、依赖、原子 epoch 不重叠、位置连续、
设备容量、资源覆盖、AOD tone 兼容性、Rydberg pair 几何、measurement keys、
最终位置和 trace duration。
此检查不是连续轨迹碰撞检查；直线运输可能经过其他原子/障碍物，尚未加入避碰规划。

`metrics.json` 输出：

- 总时长、epoch/physical gate 数；运输、1Q、纠缠、测量的设备占用时间。
- AOD epoch 数、平均/最大原子数、总运输距离。
- Rydberg epoch 数、平均/最大 pair 数；imaging epoch 数和平均/最大原子数。
- 设备利用率、X/Y tone 利用率、entanglement/measurement occupancy。
- 每次调度的 ready/selected/successful-batch/batch-size/rejection diagnostics。

利用率为“占用容量×时长 / 可用容量×总时长”，AOD 包含 pickup/dropoff。
分类设备时间可能并行，不能相加解释为总墙钟时长。
`N_ready` 是前驱已完成且尚未开始的物理门；`N_executed` 是该时刻刚开始的物理门。
没有 ready 门时 P 为 null。另记录 resource-blocked ready **任务**随时间的积分，
不把运输阶段数量当作物理门的理论并行度。

默认 CZ 单轮参考结果（估计参数，不是实验测量值）：

| 指标 | 结果 |
|---|---:|
| physical gates / semantic requests | 104 / 104 |
| physical epochs | 46 |
| 总时长 | 1310.000 μs |
| AOD epochs | 30 |
| Rydberg epochs / max pairs | 4 / 6 |
| imaging epochs / max atoms | 1 / 8 |
| 最大 AOD batch | 7 atoms |

## 10：原子动画

默认 `results/demo_animation.html` 自包含且可离线打开，无外部服务或 CDN。
只读 epoch trace，通过 AOD epoch 起止位置进行插值；无重新调度。
区分 data 圆点、X ancilla 三角、Z ancilla 方块、reservoir 菱形。
Rydberg epoch 显示同一批全部红色 pair 连线，imaging epoch 显示批量高亮。
支持播放/暂停、重启、×1/×5/×20、拖动时间和 Next epoch。
×1 明确定义为每秒播放 100 μs 模拟时间；短至 1 μs 的 gate 可用逐事件功能检查。

同时提供 `create_matplotlib_animation(trace)`，返回 Matplotlib FuncAnimation；
示例加 `--gif` 输出 `demo_animation.gif`。GIF 使用均匀采样，极短脉冲可能落在帧间；
精确事件验收以交互 HTML 和 trace 为准。

浏览器验收已确认布局、逐 epoch 推进、×20 播放到结束、时间拖动与六 pair 高亮。

## 11：时间线

`results/demo_timeline.png` 为 Matplotlib 导出的 epoch-oriented 设备 custody 与逐原子参与 Gantt 图。
颜色按 epoch 类型区分；横轴统一为 μs。数据全部来自同一份 trace epochs。
默认 1 μs 激光操作在整轮尺度很窄，这是实际配置下的时间比例。
设备行表示占用区间；多设备容量的精确占用量以 resource_spans/metrics 为准。

## 12：硬件参数与扫描

硬件 YAML 的 `timing` 配置时长与移动速度；`aod` 配置 X/Y tone、速度和轴执行模式；
`entanglement`/`measurement` 配置动态工作区能力；`devices` 和 `zones` 配置资源容量。
`configs/sweep_default.yaml` 提供明确命名的资源 overrides，每组只相对于基准配置修改。

```powershell
.\.venv\Scripts\python.exe examples/demo_parameter_sweep.py
```

输出 `results/sweep/sweep.csv`、`sweep.json`、`sweep.png`，以及每组独立目录中的 trace/metrics。
case ID 限制为安全目录名；未知参数、非法容量、非法 timing 或不合法几何会被拒绝。
修改后的完整几何、timing、AOD 和实际资源容量保存在各组 trace 中，可复现。

| 配置 | 总时长 μs |
|---|---:|
| baseline | 1310.000 |
| move_speed_half | 2587.000 |
| move_speed_double | 671.500 |
| one_tone_per_axis | 2648.000 |
| entanglement_three_pairs | 2611.000 |
| measurement_four_atoms | 1528.000 |
| rydberg_three_pairs | 2611.000 |

这组参数下运输是主要限制，减少 AOD tone、Rydberg pair 或 measurement capacity
都会产生可见的 epoch 分裂和周期变长。这是当前布局、确定性放置和贪心调度器的结果，
不保证任意扫描全局最优或严格单调。

## 回归与范围

运行 `python -m unittest discover -s tests -v`。
覆盖默认完整运行、CZ/CNOT 三轮、另一种 QEC code、锁原子性、依赖/原子独占、
错误 trace 拒绝、轨迹插值、容量限制、deadlock、epoch 可视化、指标和资源扫描。
10 个同位移原子的实际执行为 1 epoch / 12 μs / 一份 AOD custody；
改成 1 个 x tone 后为 10 epochs / 120 μs。
GitHub Actions 在 Python 3.10 和 3.12 上运行测试和 demo，并上传输出。

LogicalIR 仍是表达/校验接口，任意逻辑门的容错编译不属于本次 Task 7–12。
当前完整链路从 QEC syndrome circuit 开始，不模拟量子态、噪声、loss、decoder 或脉冲。
