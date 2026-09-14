# 可替换的路径规划与物理验证

**当前门规则（2026-09-11 最新）**：仅 H/X/Y/Z/T/CZ 可执行；仅同类型门可并行，异类型门（含 CZ/1Q）不得重叠。内部 U 参数仅记录固定门效果。checkpoint schema 15，拒绝旧 1–14；旧输入不自动转换。详见 [门规范](../docs/gate_contract.md)。本页旧门集和任意类型并行描述以该规范为准。

用途：修改路线、接入调度策略或后续 RL 时先读本文件；后端方程见 [aod_backends](aod_backends.md)，事件与指标见 [motion_execution](motion_execution.md)。保持 M0→M6 顺序。本文主体描述已有有限路线接口；KEEP 终态已有执行底座，通用目标任务设计见 [compiler_contract](compiler_contract.md)。

## 复杂性与本轮范围

row_column 不是单个点的二维寻路：配置包含 C 条列坐标与 R 条行坐标，一个选择会同时改变多个交点。固定 footprint 的 rigid 则可将整个阵列的平移用二维原点图表达，但边必须检查全部活动空阱和携带原子。两类后端仍须满足轴顺序、间距、边界、原子间距、SLM 避让和最终门作用对约束。完整路线还必须具有合法装卸与资源语义。

对 K 段、M 个携带原子、S 个静态原子和 T 个开启 trap，几何检查约为 `O(K*(M²+M*S+M*T))`；再加轴检查、状态构造和序列化成本。完整路线搜索的困难取决于配置空间和障碍，不能把单段检查成本当成通用搜索成本。本轮默认最多 6 条候选，编译器对自定义候选最多消费 64 条；失败只表示候选耗尽。

## 四层边界

| 层 | 当前入口与职责 |
| --- | --- |
| policy / scheduler | 选择 READY 门、目标配置、结束策略；`EagerBaseline(compiler=...)` 可注入编译器，`EagerScheduler(state, policy=...)` 可替换策略 |
| motion planner | `MotionPlanner.candidates(RouteRequest)` 返回包含起点和终点的完整 AODConfiguration 序列；只提出几何路线，不改实时状态 |
| backend + validator | backend 校验每段物理约束并计算时长；`validation.validate_plan` 审核完整计划的装卸、门、资源、指标和最终状态 |
| Executor | 提交并执行实际 plan，执行及恢复时复核约束，不调用 planner 重新选择路线 |

`MotionCompiler(planner=...)` 默认使用 `HalfGridPlanner`。`compile(intent,state,target_configuration=...)` 允许上层替换作用位置与轴配置；仍受支持的捕获/目标族以及实际 CZ 几何约束限制。该 legacy 路线编译路径使用 RETURN_AND_OFFLOAD：完整回源并恢复起始配置。另有 single_trap/program 的逐次装卸与 KEEP 终态底座，不能用此处 legacy 限制代表全部程序接口；非 gate 任务和单 trap 持久起态已实现；任意布局完备路由仍不承诺，见 [M3 平台族](../docs/milestone3.md)。

```python
from neutral_atom_env.motion.compiler import MotionCompiler
from neutral_atom_env.motion.planners import HalfGridPlanner
from neutral_atom_env.planning.eager_baseline import EagerBaseline
from neutral_atom_env.simulation.scheduler import EagerScheduler

compiler = MotionCompiler(HalfGridPlanner(sides=(-1,), id='left-first'))
result = EagerScheduler(state, policy=EagerBaseline(compiler=compiler)).run()
```

自定义 planner 只需 `id` 和 `candidates(request)`。request 含 start/target、grid、绑定集、只读 world/hardware；M4 另传可选只读 state、depart/approach，独立图测试可传 edge_validator；无需引用 Executor。不同合法 planner 可提交不同 operations：`exact_validate` 保留兼容名字，其实现不再重编译或比较默认模板。

## 默认候选与停点

**M4 当前路线（2026-09-11 算法升级）**：单/多 trap rigid 使用 `AStarHalfGridPlanner`。仅水平/垂直线段，长段位于 x 或 y = `2.5+5k μm`；首末正交接入≤2.5 μm。完整容量决定边界，实际活动空/载阱共同参与 backend 扫掠。固定 holder/masks/目标下，A* 给出有限通道图内最短距离；rigid 恒速下等价于纯运输时间最短，不是整线路最优。先求同图几何下界路线，物理复验通过即精确早停；否则搜索合法图，总展开预算20000。预算耗尽与图内无路分开报告。空载、载原子和归还均使用同接口，显式保留交接边界和完整 program 审计，不缩小 clearance。旧 OrthogonalHalfGridPlanner/64条枚举仅保留为兼容和对照，不再是 M4 默认；详见 [A*合同](../docs/astar_routes.md) 与 [升级日志](logs/2026-09-11-m4-compiler-upgrade.md)。

首先尝试右移半个 world 网格间距，然后连续沿纵向通道运输，最后对齐作用配置；再尝试左侧。必要时先进入半行间隙、横向连通至目标附近的半列通道，再纵向运输。右侧出界、携带原子或开启 trap 阻挡等均可能触发备选路线。

`simplify_route` 在完整行列坐标空间中合并同向共线段，不仅比较阵列原点。转弯、反向运动、不同伸缩比例必须保留；不会跨越 LOAD/PULSE/OFFLOAD 合并。row_column 每个保留段仍采用零端点速度的三次轨迹，尚未做跨转弯平滑或速度前瞻。

默认以 world 的候选网格间距生成半格，不意味着任何密网格都能容纳设备。半格小于安全间距时候选可能全部失败；不缩小 clearance 强行通过。M1 `blocked` 工厂的 1 μm 密网格，首段 0.5 μm 小于 1 μm 避让半径，当前先报 `INVALID_TRANSFER_PATH`；另有专门整段障碍测试覆盖 `PATH_BLOCKED` 和 `SLM_PATH_BLOCKED`。

## SLM 避让是明确的项目简化

新增 `HardwareConfig.slm_clearance_um=1` μm，为未标定的保守几何排斥半径，独立于原子间距与门作用半径。开启的实际 SLM trap 即使没有原子也参与检查；网格候选点和关闭的 trap 不参与这一项检查。此模型不是光腰、势阱深度、加热或损失计算。活动空 AOD 对静态原子的完整扫掠已按 M3-A 校验；精细光场仍不模拟。

每颗携带原子的全线段都检查，包含附带原子。只有 LOAD 后首个 MOVE 标为 `depart`、OFFLOAD 前最后一个 MOVE 标为 `approach`，才允许接近自身绑定的 trap：对应端点必须对齐，另一端必须退出避让区，距离沿线段单调变化；其他 trap 无豁免。bindings 必须等于实际捕获闭包，不能伪造标签或替换绑定绕过验证。

## 计划与恢复

计划新增 `planner_id`（说明来源，不提供授权）；MOVE 新增 `transfer_phase`。当时 checkpoint 升为 schema 7；当前已为 schema 15，明确拒绝 1–14，旧产物必须重建。独立验证检查状态指纹、operation 身份/顺序、准确时长、完整资源、requested/incidental、真实 pair、路程和回归 placement/axes。活动 checkpoint 还会从 eager 起始几何推演整个计划；不只信任 trace 与 cursor 的互相一致。

M4 已通过上述接口接入 rigid 障碍图搜索；如果要增加曲线、异步轴进度、并发 MOVE 或更丰富结束策略，必须同步扩展 backend、全路径验证、checkpoint 与 observer，不能仅让画面看起来合理。

## 验收与可视化

`tests/test_motion_planner.py` 覆盖独立 planner 提交/恢复、空开启/关闭 trap、附带原子、豁免滥用、元数据篡改、全配置共线合并、上层目标与策略注入。`examples/run_motion_planner.py` 生成三类实际执行证据：行列伸缩、16 原子右侧通道、16 原子左侧起步及必要连接通道。

共享 viewer 加入计划去程、途经点编号和 SLM 避让区开关；所选原子无运输路线时不会冒用其他原子的轨迹。未选中时显示本计划首个被搬运的门操作数。两种时间模式、SLM/AOD 等尺寸圆环和颜色约定保持不变。返回仍沿验证的逆路线；虚线不是额外物理位移。

集成说明：路线契约最初升级到 schema 7；rigid 部分交接随后新增 transfer_bindings 等字段并升级 schema 8。两项工作已完成集成与完整回归，证据见 [交接日志](logs/2026-09-10-rigid-pair-parking.md)。legacy 保留 RETURN_AND_OFFLOAD，通用 Program 已支持 KEEP_LOADED 终态验证；单 trap 跨计划 KEEP 已由 PersistentTargetCompiler/ResidentCompiler 实现，族外状态仍逐候选验证。


部分交接集成现状：rigid parking 已完成，见 [接口](../docs/rigid_pair_parking.md)。它复用同一 MotionPlanner 候选入口，并在装卸边界保留必要停点；PARK 前 approach 和 RECAPTURE 后 depart 的豁免只覆盖显式 EZ 绑定集，其余移动原子照常检查。默认有限候选和独立验证继续生效。

AOD trap 的间距另有不可放松的严格 >1.01 μm 下限，与本文件的 SLM 中心排斥半径不是同一参数。空 AOD trap 也检查；两外列之间有中间列时，不允许为了达到 2 μm 门距离而把相邻间距压至 1 μm。默认合法 row_column 演示改为相邻列，旧外列例明确拒绝，详见 [aod_backends](aod_backends.md)。

## M3 路线接口的扩展要求（待实现）

上层给目标状态或允许域与资源/时间约束，局部 compiler 负责交接、开关及路线组合，MotionPlanner 只处理给定运动段的可行轨迹。合法 loaded/EZ 起态不应强制重新初始化；路线终点不必等于来源，依任务终态验证。

启用/关闭是离散操作，不是几何 planner 可偷偷添加的豁免。对 K 段、A 个活动 AOD trap、S 个静态原子，活动阱对静态原子的扫掠至少增加 O(K*A*S) 的直接检查；稀疏启用可少于容量，但必须包含活动空交点。其他原子对/SLM/轴约束仍保留；该估算是单候选验证成本，不是路由搜索复杂度保证。

关闭状态定位也要时间与控制轨迹，重新开启前校验所有交点。轴 ID/间距/顺序约束不因关灯而隐式解除。并发路径须在共同时钟区间对其他活动轨迹和固定原子检查；当前串行几何请求不能直接证明该安全性。

候选拒绝后可继续有限搜索；耗尽后给出预算、目标域和失败原因，最终运行终止。局部最短路不一定令 circuit 最快；返回少量成本/终态不同的合法候选交 scheduler 选择，不能宣称有限 HalfGridPlanner 对任意布局完备。


M4 greedy 的 route 比较直达/有限走廊与空 EZ SLM 开关策略，按真实开关加运输时长选择。占用 SLM 不可关闭，bound handoff 或安全显式开关恢复支撑；见 [EZ 开关与回放修复](logs/2026-09-11-ez-switch-playback.md)。
