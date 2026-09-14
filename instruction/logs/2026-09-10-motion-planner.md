# 可替换 planner 与 SLM 避让

状态：COMPLETE（本任务声明的路线接口、SLM 避让、默认路线与可视化范围）。

## 复杂性与范围

行列配置空间维数为 columns+rows，路线同时受行列顺序、所有携带原子、实际开启 trap、门区域和资源约束。对 K 段、M 个携带原子、S 个静态原子、T 个开启 trap 的计划，解析几何检查约 O(K*(M²+M*S+M*T))。完整路径搜索另随候选数量增长，当前不承诺全局最优或完备。

本轮分四层：policy/intent 选门和目标；可替换 RoutePlanner 给出轴途经点；backend 验证并计时；Executor 执行已验证计划。独立 validator 推演提交方案，不重新运行默认 planner 比较模板。

安全边界：新增针对实际开启 SLM trap 的保守 clearance；候选网格点不是障碍。只有 LOAD 后首段离开和 OFFLOAD 前末段接近能豁免各自绑定 trap，仍须对齐、向外/向内单调且在另一端离开避让区；不允许用任意标签绕过其他 trap。

默认方案优先右侧半格通道，必要时枚举左侧和水平连接通道；合并完整配置空间中同向共线的途经点。保留 eager 返回/卸载，M3 KEEP、任意重排、连续曲线与全局搜索不在本轮实现。

验收：不同 planner 方案均可执行；同坐标附近空 SLM trap 负例；豁免滥用、资源/时间/承载/最终状态篡改拒绝；每边界恢复；原子真实轨迹和两种视觉时间模式；重建当前 visualization 共用组件，不修改历史 testing/replay.html。

## 实现与证据

- `motion/planners.py` 定义 RouteRequest / MotionPlanner 和半格通道候选；`routing.py` 将候选交给 backend 校验/计时；compiler 可接收 planner 与 target_configuration。默认最多 6 条候选，自定义候选消费上限 64。
- `motion/validation.py` 对实际 operations 做完整推演，取代重新生成默认计划后比较；Executor 和 runtime restore 调用独立验证。不同合法左侧路线可以提交和恢复，测试中禁止再次调用 compile 仍能完成。
- `hardware/slm_clearance.py` 对开启 trap（含空 trap）检查解析线段 clearance；只在正确装卸首末段允许自身对应 trap 的单调对齐路径。附带原子同样检查。
- `EagerBaseline(compiler=...)` / `EagerScheduler(policy=...)` 使后续层级可替换实现，无需改 Executor。KEEP 等结束策略未在本任务提前实现。
- 共享 recorder 保存 plan 的逐原子去程、planner 来源和装卸阶段；viewer 增加计划路线、编号途经点、SLM 避让区开关。去程与返回、关键帧/真实比例均基于实际操作，参数不因显示变化。
- 新增 `testing/motion_report.py` / `examples/run_motion_planner.py`：行列伸缩、16 原子右侧路线、16 原子左侧起步及必要连接通道，均实际执行，图中同时保留开启的空 SLM trap。

| 本轮命令/检查 | 结果 |
| --- | --- |
| `python -m pytest -q --disable-warnings` | 146 passed, 1 warning；输出 artifacts/motion-pytest.txt；这是后续并行 schema 8 变动前的完整基线 |
| `python -m pytest tests/test_motion_planner.py tests/test_row_column_aod.py -q --disable-warnings` | 后补两项恢复/旧版本测试及 schema 8 集成后，31 passed |
| `python examples/run_motion_planner.py` | 3 场景通过；AOD/atom=68/186、56/896、66/1056 μm |
| `python examples/run_reconfigurable_aod.py --backend row_column` | 3 场景通过；当前用户原 URL 已重建 |
| `python examples/run_single_gate.py` / `run_circuit.py` | M1/M2 各 5 场景通过，重建原报告与动画 |
| `python examples/visualize_circuit.py --scenario three_gate` | 新三门 81 帧（含初始帧），37 operations，75595 bytes 的当次 recording |
| Node `motion_controls.cjs` | 三场景路线/避让开关、按原子切换、双时钟、输入不变性通过 |
| Node `replay_controls.cjs` / `replay_row_column.cjs` | 四个既有 M1/M2 回放、三个 row_column 回放通过 |
| Node `viewer_component.cjs` / `schedule_controls.cjs` | 分页/组件隔离/清理、真实时序/短门/跳转/同步游标通过 |
| 静态图 | 查看 routes.png，调整紧邻途经点的编号上下交错，避免重叠 |
| 真实浏览器 | 本地 HTML 自动浏览受 URL 安全策略阻止；没有新增浏览器视觉验收，Node doubles 不替代该证据 |

## 独立数字的变化

M1：(0,0)→(2.5,0)→(2.5,-25)→(3,-25)，单程仍 28 μm，完整周期仍 312.3 μs。

row_column 去程最大 trap 位移为 2.5、25、6.5 μm；AOD 往返 68 μm，时间 `200.3+2*(sqrt(1500)+sqrt(15000)+sqrt(3900))=647.608601170434 μs`。Q000 路程 58，Q001 路程 68，Q002 路程 60（若附带），共 126 或 186 μm。Q002 最后从 x=7.5 调到 5，不能沿用旧路线“不动”的断言；独立自定义路线测试仍覆盖真正静止的交点。

M2 three_gate 总 1116.9 μs、逻辑完成 890.9 μs、AOD/atom=258/218 μm；join 为 1076.9/900.9 μs、238/198 μm。第三源靠近边界，需要左侧起步和连接通道。这些增加来自可验证路线，不通过修改作用半径抵消。

## 并行变动与交接

本任务最初引入 schema 7。开发期间发现同目录 [rigid pair parking 任务](2026-09-10-rigid-pair-parking.md) 已增加部分交接字段和 schema 8；保留其实现，并进行上述 31 项兼容复核与 fresh-process 报告重建。另一任务的部分卸载/重新抓取仍由其独立日志验收，本任务不替它声明完成。未来它继续修改共享代码时，以其后续验证与当前源码为准。

下一步：后续 policy/planner 可以选更复杂目标和路径；完整搜索、跨段平滑、并发、不同站点卸载与 KEEP 需扩展对应契约。目前错误诊断给出有限候选首个失败原因，不等于全局无解。详见 [motion_planning](../motion_planning.md) 与 [handoff](../handoff.md)。
