# 可选择的 AOD 运动后端

2026-09-16 工作台目录收敛：当前平台固定展示正交有序行列，初始偏移移入高级设置；旧后端通过历史输入读取，不在常用菜单推荐。物理实现未删改。[能力和配置说明](../docs/workstation_compilers.md)。

2026-09-15最新：新增 `row_column_orthogonal`（`configs/hardware/row_column_orthogonal.json`），继承有序行列完整物理校验，单MOVE只改x或y；未变轴全程保持。`row_column`原本就支持独立轴保持，截图绕路来自策略候选缺失。共享 `motion_router=axis_hold` 与backend分别选择，两种行列后端均验收；正交约束在env，直接/分轴保持候选在strategies。Q000原8门反事实与完整QEC结果见[修复报告](../docs/axis_hold_strategy_fix.md)。schema19结构不变；切后端须重新编译，旧检查点不自动改变后端。

2026-09-15扩展：新的`SMTOrderedAxisPlanner`和贪心已在同一34原子完整QEC GHZ上比较有序行列配置，包含真实MZ读出/恢复。二者同17CZ批次、最大9对并行，完整物理/量子/重放通过；新SMT并未更快。旧`smt_batch.py`仍为rigid受限实验；本次不将其冒称已升级或全局SMT。[报告](../docs/qec_ordered_smt_comparison.md)。

2026-09-15：策略包新增 `scheduling/ordered_greedy.py`，已在固定EZ/每批归还的小规模编辑实验中搜索独立有序行列目标，包含先提取、非均匀变距、真实合批和全部扫掠校验。环境后端未改。不能再把“所有策略只支持固定axes平移”当作当前结论；原patch/SMT实验仍是该限制。[范围与对照](../docs/ordered_axis_greedy.md)。

2026-09-12当前：工作台支持rows×columns总容量≤128和两组非均匀offset，rigid只保持这些相对坐标而不要求等间距。二维6×6/36数据原子联合装卸与9/18CZ并行已有执行证据。捕获基于真实活动交点而非外接矩形内全吸取。动态变距backend仍存在，但新patch策略只搜索固定axes平移。schema18；[批量CZ](../docs/batch_cz_contract.md)、[二维研究](../docs/surface_2d_research.md)。下方uniform/single-pulse限制是历史实现范围。

**当前工作台更新（2026-09-11）**：单台 rigid AOD 可选 1×1 / 1×2 / 1×4，后两者固定 10 μm 列间距；M4 联合准备/运输已接入可编辑线路，具体范围见 [多 trap 试验](../docs/multi_trap.md)。不是多个 AOD，也不是任意多 cell 持久服务或 batch CZ。当前 schema 17；下文早期 schema 和 planner 能力说明保留历史范围。

用途：修改阵列形状、运动计时、路径验证、捕获或 backend 选择时读取。依赖 [physics](physics.md)、[motion_execution](motion_execution.md)；不改变 M0→M6 顺序。

## 1. 文献依据与实现范围

- **Bluvstein et al., Nature 604, 451–456 (2022)**，[Optical tweezer generation](https://www.nature.com/articles/s41586-022-04592-6)：交叉 AOD 的两个控制方向分别设置行列位置；通过伸缩和平移重构，行列不交叉；运输使用三次插值。
- **Bluvstein et al., Nature 626, 58–65 (2024)**，[Shuttling and transfers](https://www.nature.com/articles/s41586-023-06927-3)：矩形行列阵列允许空位；移动保持行列顺序；支持 AOD–AOD 与 AOD–SLM 配对；SLM/AOD 转移涉及光强斜坡与分离动作。

以上是公开方法约束，不是实验室控制源码。新 `row_column` 后端是依这些约束构建的确定性运动学实现，不复现 RF 波形、光功率标定、量子态、echo、损失或论文保真度。

下表是几何 backend 能力；动态 masks 已在 M3-A 实现，见第 8 节。

| 能力 | rigid | row_column |
| --- | --- | --- |
| 阵列 | 固定行列数、统一固定间距 | 固定行列数，独立可变的有序 x 列坐标与 y 行坐标 |
| trap 坐标 | pose + (column × spacing, row × spacing) | (x[column], y[row])，所有交点均存在，允许空 trap |
| 运动 | 仅整体平移，恒速 | 行列伸缩与平移，共用三次进度函数 |
| 交叉 / 合并行列 | 无这种能力 | 拒绝；还检查最小行列间距，包含空行列 |
| 2Q 编译 | mobile–static | mobile–static；另支持同次捕获、同一行或列的 mobile–mobile pair |
| 捕获 | 保守 footprint 内未对齐原子拒绝 | 只转移与实际 trap 对齐的静态原子，完整纳入附带捕获 |

两个后端都允许连续非 SLM 坐标；load/offload 才要求与静态 trap 对齐。不能把 SLM 候选网格当作移动轨迹离散化。zone 保留用户确认的三区和隔离带，backend 不重新定义 lattice/zone。

## 2. 状态与配置

- `domain/aod.py::AODConfiguration(x_um, y_um)`：绝对物理坐标、有序不可变 tuple。二维交点的行列编号不随位置改变；构造时拒绝空轴、非有限数、重复/逆序轴。
- `world/world.py::AODRuntimeState`：保留 pose/rows/columns/spacing，增加可选 `column_offsets_um`、`row_offsets_um`，都以第零行列为原点且首项为零。它们替代对应方向的统一间距推导；不是给原子另存 position。
- `configuration()` 导出完整轴坐标；`configured(config)` 返回新 AOD 状态；等距轴规范化为 None，往返可精确恢复原状态。`spacing_um` 在非均匀轴存在时只保留默认几何参考，不可继续用于直接绘图。
- `HardwareConfig.backend` 选 `rigid`（默认）或 `row_column`。`hardware.get_backend(config)` 是 compiler、Executor 和恢复验证共享的选择入口。
- `Operation.target_configuration` 保存变形终点；既有平移仍可用 `target_pose`，同一 operation 不能混用。`CompiledPlan.initial_aod_configuration` 保存初始轴，恢复时不再从 uniform spacing 反推。
- 行列后端最初在 schema **6** 保存上述字段、选择器及参数；当前 schema **10** 还保存路线、交接字段、计划初始 placement 和动态 masks/交接支撑。旧 schema 1–9 明确拒绝，不在恢复时猜测默认后端或补造计划。重新运行生成命令更新报告；历史日志仍保留原 schema 的记载。

后端在 episode 初始化前选择；回放模式只改变观察时钟，不能在播放过程中切换物理模型并继续沿用旧 trace。

## 3. 三次轨迹与计时

一个 MOVE 内所有行列共享 `s=(t-t0)/T` 与 `u(s)=3s²−2s³`：

```text
x_i(t) = x_i(0) + u(s) * (x_i(1)-x_i(0))
y_j(t) = y_j(0) + u(s) * (y_j(1)-y_j(0))
```

这是本项目选择的具体三次形式，端点速度为零，段内 jerk 恒定。它不是全局 C2/C3 轨迹：段边界加速度可跳变，不能声称边界冲击也受有限 jerk 限制。需要连续加速度/实验控制时再扩展 profile，不自行改变现有公式而忘记更新恢复与回放。

令 `D=hypot(max_i |Δx_i|, max_j |Δy_j|)`，即整个 Cartesian 阵列中最长 trap 路程（包括空 trap）：

```text
T = max(1.5 D/v_max, sqrt(6D/a_max), cbrt(12D/j_max))
```

保证所有 trap 的峰值速度、峰值加速度和段内 jerk 不超配置上限。`speed_um_per_us` 对 rigid 是恒速，对 row_column 是峰值速度上限。演示 profile 的 0.5 μm/μs、0.01 μm/μs²、0.001 μm/μs³、严格 >1.01 μm 的 AOD trap 中心距来自用户指定的模型约束；这些数值不是论文设备标定。配置在 [row_column.json](../configs/hardware/row_column.json)。

路线接口与复杂性见 [motion_planning](motion_planning.md)。

## 4. 整段几何检查

1. 起终点轴长度固定、有序，所有 AOD trap 的中心距必须严格大于 `max(1.01, minimum_axis_spacing_um)` μm（包含空 trap），所有 trap 在 world bounds 内。等于边界也拒绝；浮点近似相等采用保守拒绝。初始状态、恢复、rigid 与 row_column 都调用共享 `hardware/trap_spacing.py`。因为共用单调 u，行列间距是两个端点间距的凸组合，因此全段不交叉，矩形范围内的端点也保证段内不越界。
2. 每颗移动原子的轨迹几何是直线段；逐一检查与静态存活原子的整段最近距离。
3. 对每对移动原子，检查相对向量从 `r_a(0)-r_b(0)` 到 `r_a(1)-r_b(1)` 的线段距原点的最小值；不能复用刚性后端“初始相对距离固定”的假设。测试含两端安全但段内过近的反例。
4. 执行门时阵列停止，沿用全 entanglement 区真实 pair 枚举，附带原子也参与。门判据仍是项目既有 2 μm 硬阈值，不能通过伸缩之外的参数修改让 gate 通过。
5. 对每颗携带原子检查开启 SLM trap 的整段排斥区（包含空 trap）；只有受限装卸首末段可接近自身绑定 trap。
6. 装卸完成才提交 holder；活动空 AOD 对静态原子的整段扫掠和启用检查已完成 M3-A（GAP-002）。RF/精细光场仍在范围外。动态关闭还检查共享行列上的全部剩余载荷。

## 5. 编译与执行边界

`motion/row_column_compiler.py` 当前为有限 eager planner：两个目标必须在初始实际捕获集中，并共用一行或一列；选择配置的 `mobile_pair_center`，由可替换 planner 先横移半格离开 SLM、沿通道运输，再调整到目标配置与门间距，执行 CZ 后沿原路展开、归还、卸载。包含所有附带原子；每段都交给 backend 校验。

backend 本身允许非均匀独立轴变化；planner 没有实现任意排列、交叉行列、对角 pair 自动路由、选择性屏蔽单交点、KEEP 或任意绕障。`PAIR_ROUTE_UNSUPPORTED` / `PAIR_CAPTURE_REQUIRED` 表示有限规划能力，不证明物理无解。对单静态 EZ 伙伴继续复用现有 compiler，但计时取所选 backend。

只有 Executor 安装下一状态；backend 的 load/move/offload 是只读推演。计划 start/complete、资源预约、逻辑依赖、恢复校验继续走同一物理事件状态机。

## 6. 指标与观察

- `total_aod_distance_um`：每段最长 trap 路程 D 的累加，表示阵列运动代价；伸缩时不能叫质心位移或所有 trap 路程之和。rigid 下与原指标一致。
- `total_atom_distance_um`：每颗实际移动原子的几何路程逐段求和；空 trap 不计，中列原子在对称压缩中不动便不计。不能以 `D × captured_count` 代替。
- MOVE 完成计入完整段；未完成段的部分统计仍不计。其余 wall/laser/cycle 指标沿用 M2 定义。
- Python `replay/trajectory.py`、HTML 与 PNG 使用完整轴坐标；HTML/Python 采用相同三次 u。运动段内保持原位的交点原子显示 idle，而不是仅因 AOD 全局 busy 显示 moving。
- 仿真时钟与显示时间映射、等尺寸 trap、交接动效等仍按 [visualization](visualization.md)；伸缩不能伪装成动画专用位置调整。

## 7. 重建与独立预期

```powershell
python examples/run_reconfigurable_aod.py --backend row_column
python examples/run_reconfigurable_aod.py --backend rigid
python -m pytest tests/test_row_column_aod.py -q
node tests/replay_row_column.cjs
```

两份报告分别写入 `artifacts/row_column/` 与 `artifacts/rigid/`。API 初始化：`make_row_column_state('pair_compression', backend='row_column')`；其余编译/Executor 接口不变。

| 场景 | 独立预期 |
| --- | --- |
| pair_compression | Q000=(0,0)、Q001=(5,0)，pulse 时为 (4,-25)/(6,-25)，轴 x=(4,6,8)、y=(-25,-20)；往返 AOD 64 μm、原子 116 μm |
| incidental | Q002=(5,5) 也被装载，pulse 位于 (6,-20)；末段从 x=7.5 调到 x=6，增加往返 58 μm，原子总路程 174 μm |
| mobile_static | 保留原非 SLM 配对几何，AOD/原子路程仍各 56 μm；计时改由三次峰值约束计算 |
| rigid 对照 | 前两例拒绝 STATIC_PARTNER_REQUIRED；mobile_static 保持 312.3 μs |

压缩基准 LOAD/OFFLOAD 各 100 μs，pulse 0.3 μs；各方向单程 MOVE 的最长位移依次 2.5、25、4.5 μm，本 profile 都由加速度下限主导。总时间 `200.3 + 2*(sqrt(1500)+sqrt(15000)+sqrt(2700)) = 626.6316896565988 μs`，门完成 313.4658448282994 μs。

测试还覆盖轴交叉/合并/计数/间距/越界、两类整段碰撞、额外 pair、每个事件边界恢复、轴/计划篡改、三次速度限制、四分之一时间的非线性采样。Node 检查控制与 Canvas 调用，不作为真实浏览器观感验收。

旧版外侧目标 x=(4,5,6) 的三列压缩是硬约束漏洞，现以 `outer_pair_blocked` 拒绝测试保留。两个间隙各 >1.01 μm，目标距离必然 >2.02 μm，不能满足 2 μm 门半径；空 trap 不能忽略或暗中关闭。合法演示显式更改初始目标为相邻列，不代表旧布局可执行。修复证据见 [日志](logs/2026-09-10-trap-spacing-display.md)。

## 8. 动态活动集合与 rigid 的关系（M3-A 已实现）

严格按 [physics](physics.md) 分离 AOD 容量、轴位置、enabled rows/columns 和 occupancy。SLM 逐点可开关，AOD 只按行列控制，活动交点是 Cartesian 积。rigid 下也可改变启用集合，但保留固定几何/轴身份；与 row_column 的变距能力独立。当前 AODConfiguration 拒绝空坐标 tuple 不妨碍当前“容量轴存在、活动 masks 全关”，不要以删除轴实现零活动阱。

已实现能力和操作校验（见 [动态光阱](../docs/dynamic_traps.md)）：开轴时审核所有新交点及受影响原子；关轴时确认所有承载原子均已安全交接；整段检查活动空阱对静态原子；计时的关灯定位；交接完成才提交 holder。不能由 selective_transfer_enabled 推导任意单 cell 可控，也不能在图上隐藏空交点后绕过物理验证。

现有所有建模 trap 严格 >max(1.01, minimum_axis_spacing_um) μm 的间距与轴不交叉约束继续保留。关闭不自动授权轴重排/越过/取消间距；若以后需要改变关闭轴的控制限制，须另立 backend 能力、验证和恢复契约。第 7 节外列压缩反例仍拒绝，不能靠未经实现的关中列想象使旧计划合法。

转移 ramp/稳定时间包含在预设交接成本内，独立切换和关闭定位也须声明计时；参数未经设备标定，不作为真实实验波形。动态 masks/交接、参数化串行 Raman 与独立任务已进入当前 schema 12；操作级并发仍未实现。旧 checkpoint 1–11 不能默认补值后复用。
