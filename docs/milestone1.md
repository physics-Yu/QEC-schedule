# Milestone 1：单 CZ / rigid AOD / eager return

本文件保留 M1 的具体实例与指标。整体路线见 [milestones](../instruction/milestones.md)，编译/事件细节见 [motion_execution](../instruction/motion_execution.md)，当前未修正问题见 [model_audit](../instruction/model_audit.md)。

## 范围和实现边界

一个 `ExecuteGateBatchIntent` 只含一个 READY CZ，单个刚性矩形 AOD，单个 interaction slot，结束方式只允许 RETURN_AND_OFFLOAD。
Policy 决定 eager return；compiler 编译；hardware 验证；Executor 通过事件提交 holder、pose、DAG、reservation 和指标。
不实现 batch、KEEP、多 AOD、复杂路径搜索、真实量子态或实验噪声。

## 演示参数（非实验标定）

| 参数 | 值 |
|---|---|
| AOD | 2 rows × 3 columns，spacing 5 μm |
| LOAD / OFFLOAD | 各 100 μs |
| 速度 | 0.5 μm/μs，分段直线、无加减速模型 |
| CZ pulse | 0.3 μs |
| 相互作用半径 | 2 μm，zone 内全局枚举距离不超过半径的所有 pair |
| 原子最小间距 | 1 μm；移动段用解析最近距离检查 |
| Escape | 优先右移 2.5 μm，再沿格间通道运输；可替换 planner |
| Interaction AOD pose | (3, -25) μm，允许不对齐 SLM 网格 |

保持原定 2 μm 距离，不通过放大作用距离来迁就规划器。
刚性平移只保持同一 AOD 上的相对距离，不限制 AOD 相对于 SLM 的连续位置。
基准使用 mobile–static 配对：Q001 预置在 entanglement 区的 SLM(5,-25)，Q000 由 AOD 移到非 SLM 位置 (3,-25)，两者距离为 2 μm。
SLM 对齐是 load/offload 的必要条件，不是 pulse 的条件。Q001 的预置属于初始布局，本里程碑不假装已经实现将两个 storage 原子分阶段运入 EZ。
如果两个目标都在同一 5 μm 刚性 AOD 上，二者距离不会因平移缩短；当前 compiler 必须报告缺少静态伙伴，不能改变作用半径或静默移动伙伴。
Zone 保持从上到下 storage / entanglement / measurement。

## 验收场景与独立预期

1. Baseline：Q000=(0,0)、Q001=(5,-25)，其余原子在 footprint 外。
   LOAD → depart (2.5,0) → corridor (2.5,-25) → align (3,-25) → CZ → reverse route → OFFLOAD。
   必须得到：1 个完成门、AOD 路程 56 μm、原子总路程 56 μm、总周期 312.3 μs、pulse 完成于 156.3 μs、load/offload 各 1 次。
2. Incidental：额外抓取 Q002=(10,5)，目标 pulse 仍只有 Q000/Q001；其余指标不变，原子总路程 112 μm。
3. Unintended pair：Q002=(5,0) 随 AOD 移动，Q003 静态位于 (10,-25)，pulse 会多出 Q002/Q003；必须在执行前拒绝，状态与 trace 不变。
4. Path blocked：负例使用 1 μm 静态网格、扩大 storage 到 y=-12，预置 Q003=(3,-10)，该密网格的半格仅 0.5 μm，当前默认 planner 首先因未退出 1 μm SLM 避让区而拒绝。整段穿过静态原子和空 SLM 的独立负例见 test_motion_planner.py / test_row_column_aod.py。
5. Offload conflict / alignment / disabled site：返回目标非法必须拒绝。
6. 过期或被修改的计划、资源忙、错误结束策略：拒绝；失败事件不得部分提交。
7. 每个事件保存/恢复后继续执行，与不中断执行的 final snapshot / trace / metrics 完全相同。

## 指标与报告

报告展示配置、机器断言、LOAD/MOVE/PULSE/OFFLOAD 时间线、少量关键帧和可播放轨迹。
输出 plan.json、initial/final checkpoint、trace.jsonl、metrics.json、timeline.png、animation.html。
移动中的位置由事件端点按时间插值，仅作 observer；真实 pose 只在移动完成事件提交。
必须区分 circuit_makespan_us（pulse 完成）与 cycle_makespan_us（offload 完成）；AOD busy 包括被该周期占用的 pulse 时间，laser busy 只计 pulse。

## 当前实现与运行

`python examples/run_single_gate.py` 生成 `artifacts/milestone1/index.html`；基准和 incidental 场景各输出真实事件快照、动画、时间线、编译计划和指标。
`python -m pytest tests/test_milestone1.py` 验证物理几何与事件提交。完整回归使用 `python -m pytest --visual`。
快照 schema 8 保存硬件参数、当前 physical plan、operation 游标、reservation 和累计指标，支持在每个事件边界恢复；不自动转换旧 schema。
运动学采用恒速线段，无加速度/jerk/温度模型；真实 trap loss、RF 波形与量子态不在本里程碑范围内。

## 回放显示与交互

AOD 的每个 trap（含空 trap）以橙色圆环表示，SLM trap 以等尺寸灰蓝圆环表示，两者均有图例，不再画阵列外接框。SLM 原子使用圆点，AOD 原子使用菱形；原子填充色独立表达空闲、移动、门或测量状态。圆环尺寸是显示符号，不表示实际光腰或作用半径。静态关键帧采用同样的符号规则。完整约定维护于 [可视化生成规范](../instruction/visualization.md)。

编号可切换全部显示、悬停/选中、全部隐藏，默认悬停/选中。画布右上方的 SLM traps 和 AOD traps 可独立选择，网格和已走轨迹也可独立开关；支持滚轮缩放、拖动、适配视图。点击原子或侧栏列表查看连续坐标、承载 trap、当前操作与目标伙伴。播放支持调速、时间拖动、事件跳转和九段操作跳转，短 CZ 脉冲可单独定位。

同一页面可选“真实时间比例”（1× = 25 μs 仿真 / s 屏幕）和默认“关键帧演示”。关键帧模式在 1× 下将装载展示 1.8 s、卸载 1.6 s、CZ 展示 1.8 s，移动段分别分配 0.8–2.2 s；整个基准演示 12 s。真实仿真周期仍为 312.3 μs。抓取/释放显示原位收拢/散开弧线及圆点/菱形过渡，包含附带捕获原子；门显示真实 pair 连线及进度强调。操作动效可关闭，侧栏承载状态在真实操作结束时才改变。切换模式保留仿真时刻并暂停，演示时间不写入指标。重建后运行 `node tests/replay_controls.cjs` 检查控制逻辑；该检查不代替真实浏览器视觉验收。
