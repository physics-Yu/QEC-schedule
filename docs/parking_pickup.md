# Parking 拾取模块与可编辑演示

**当前v2已替代下方初版流程：** 朴素版保留已匹配轴，仅停车本批新行/列；`pattern_optimal`现已实现最少兼容批次与行列方向比较，不再是预留。空位不限、无目标行列跳过。实现/接口结果与本轮证据见 [v2合同](parking_compatibility.md)。下文原始双轴逐组parking及旧验证数字仅用于追溯初版。

2026-09-17。实现用户提供的 `parking_movement_baseline_and_pattern_optimization.md` 中的朴素构造，并增加对称的逐列版本。它是固定目标集合的运输子程序，不选择量子门，不重写电路，也没有实现 Pattern 优化或论文复现。

## 使用

完整环境工作台：在仓库根目录运行 `python examples/parking_workbench.py --port 0`，打开输出的网址。独立入口无需 SMT。

无需安装的分享版：直接打开 `demo/parking/index.html`，或从 Demo 首页选择 **Parking Lab**。分享版使用浏览器内构造式模板，编辑器与方法讲解可随当前配置一起导出；范围区别见 [离线说明](parking_portable.md)。

1. 设置 SLM 行列、间距、AOD 行列容量、正方向 parking 偏移和集体位移。
2. 用画笔点击或拖动画格子：空 SLM、保护原子、待移动原子；可切换已有原子的目标状态。
3. 选择逐行或逐列，手动点击“编译并执行演示”。修改草稿不会自动编译。
4. 回放支持暂停、拖动、最高 32×；可直接跳到拾取终态、集体运输起点、每组结束时刻，下载完整离线动画和输入 JSON。

失败会显示带阶段和错误码的报告，保留输入与上次动画。报告表示指定固定构造失败，不是所有路线都不可行的证明。Pattern 优化选项置灰；API 请求 `pattern_optimal` 返回 `STRATEGY_NOT_IMPLEMENTED`，没有隐藏回退。

## 可调用接口

```python
from neutral_atom_env import NeutralAtomEnv
from neutral_atom_strategies.motion.parking import (
    ParkingConfig, PlanningFailure, plan_pickup, plan_collective_transport,
)

result = plan_pickup(
    env.snapshot(),                       # 或 SimulationState
    target_ids={"Q000", "Q001"},
    config=ParkingConfig(rows=2, columns=3),
    strategy="naive_rowwise",             # 或 naive_columnwise
)
if isinstance(result, PlanningFailure):
    print(result.code, result.phase, result.message)
else:
    if result.plan:
        env.submit(result.plan)
        env.run()
    onward = plan_collective_transport(env.state, 60, 30)
    if onward:
        env.submit(onward)
        env.run()
```

模块只构造计划，不改变传入状态。成功结果包含真实 `plan.operations`、预测 `final_aod_state`、原子到行列槽映射、拾取耗时、转移批次数、parking 段数、拾取期间所有已载原子的累计路程、每组时刻。预测状态不可代替执行后的版本化环境；续接必须使用 `env.state`。空目标返回零操作。

模块要求：`row_column_orthogonal` 后端；入口 AOD 空载、所有行列关闭；目标位于声明的规则源网格；容量覆盖目标的不同源行数和列数。几何、障碍、计时来自快照，不能只提供目标位置而丢掉其他占据 SLM。

独立场景工厂是 `neutral_atom_experiments.parking_demo.make_state(spec)`；`run(spec)` 验证完整拾取和集体运输，再从原始检查点独立重放。用户应用应分别处理输入错误和结构化规划失败；HTTP 工作台会将二者均记录为失败任务。

## 物理语义与流程

每条活动行和活动列的所有交点都存在，包括空阱。逐行流程先把列轴停到 `source_x + epsilon_x`；仅打开列轴时没有二维交点。随后每行：

1. 仅将本行需要的列对齐到源 x；已载原子随共享列一起移动。
2. 激活本行并建立交接支撑，按**全部活动交点的真实捕获闭包**装载。
3. X parking，再 Y parking；到拐角停止后进行下一段。
4. 核验累计承载集合、未处理和保护原子的 holder、活动行列全部处于停车位置。

逐列版本先打开停车行；每列先对齐所需行的 y，再增量装载新列，同样 X 后 Y parking。两者映射均按目标源坐标递增排列，最终每个目标在 `(source_x+epsilon_x, source_y+epsilon_y)`。不卸载、不归还，保留 AOD 承载。

集体运输是独立计划，从实际停车终态整体 X 平移后 Y 平移。演示要求 X 位移至少等于源 patch 宽度 +10 μm，以确实远离源 patch；这属于演示目标，不是环境硬件限制。固定路径受阻就报告失败，本轮没有搜索绕行。

### 增量装载接口补齐

原后端的 `AOD_LOAD` 只接受空 AOD，因此第二组拾取最初报 `AOD_BUSY`。本轮保持该语义，并扩展显式 `AOD_RECAPTURE`：开启已有 `selective_transfer_enabled` 能力时，有序行列后端可以在保留载荷的同时增加拾取。参数名称是历史命名，**本实现不提供逐原子寻址**：新增 bindings 必须与全部活动交点计算出的新增 SLM 捕获集合完全一致。

能力默认仍为关闭；独立 Parking 场景显式开启。已有 rigid 部分转移行为不变，有序后端的部分卸载仍未启用。交接计时、全交点扫掠、碰撞、行列顺序、边界和承载轴不得关闭的检查全部保留。不是通过扩大作用距离或关闭碰撞校验实现增量抓取。

`epsilon` 是物理位移，非数值容差。保守预检要求 `epsilon > b` 且 `spacing-epsilon > max(b, axis_spacing_floor)`，随后仍执行完整路径验证；`b` 取环境相关净距/对齐参数的最大值。默认 10 μm 源间距、2.5 μm parking 是本项目示例参数，非普适设备标定。这里只模拟运动学、支撑与离散事件，不模拟 RF 功率、光场、波包或实验保真度。

## 10×10 格点编辑器（2026-09-17 更新）

默认演示为10×10、100个SLM格点，含43个待移动原子、42个固定原子、15个空位；目标分布跨全部10行和10列。AOD初始10×10，源间距10 μm，parking偏移各2.5 μm，最终整体 +X 140 μm、+Y 40 μm。`large_input()`提供这个可复现输入；`default_input()`保留原2×3入门样例，页面默认接口改为大例。

编辑区使用SVG格点：红实心圆是待移动原子，蓝实心圆是固定原子，灰色虚线圈是空SLM。编号默认隐藏，可开启；悬停查看坐标和编号，支持键盘Enter/空格、点击和拖动画笔、150%/200%缩放。Parking与最终位移折叠，显示源宽度及最小搬远距离，可一键按目标匹配AOD行列、自动设置搬远距离；两个按钮只修改草稿，仍需手动编译。回放保留共用viewer的活动/支撑配色，与编辑器的目标集合配色含义不同。

大例暴露出原串行执行器每事件核验整个长计划的重复成本。演示控制程序现在在每组完成parking的静止边界分段提交，保持原完整规划的操作顺序、参数和物理时间。原计划仍先完整审计，每个分段仍经 `finish → submit → Executor` 及运行时检查，完整任务仍从初始检查点独立重放；没有关闭任何物理校验。可调用 `plan_pickup()` 仍返回完整计划。分段只改变计划ID和管理事件数，原子轨迹及装载/运动操作不变。

## 输入与界限

可编辑演示支持 SLM/AOD 各维 1–16，AOD 总交点不超过128；SLM 间距为 5/10/15/20 μm，与当前环境 5 μm 静态候选网格一致。核心模块没有16行列的UI限制，仍受传入硬件与几何约束。

`cells[r][c]`：0 空、1 保护、2 目标；行索引向 +Y，列索引向 +X。原子 ID 为 `Q{r*columns+c:03d}`。改变列数会重新编号草稿，不能跨草稿依赖旧 ID。

JSON 可额外提供 `obstacles: [[x,y], ...]`（最多16个），作为网格外保护原子；必须属于环境允许的静态网格与边界，不能和源 SLM 重复。它们同样参与全程校验，不能被当作可忽略背景。当前画笔编辑源 patch，外部障碍通过 JSON 设置。

入门示例有6个原子，其中4个目标、2个保护原子；目标 mask 为 110/011（按源行索引从0向上）。逐行拾取 472.108834 μs、逐列 688.298335 μs；相同集体运输 323.900738 μs。逐行拾取期间总载荷路程 25 μm，包含已载原子在后续对齐中的联动。它们只是本示例的真实仿真计时，不证明某策略普遍更优。

## 验证与未来接口

`tests/test_parking.py` 覆盖两个策略全部 2×2 三态占据组合（每策略81个），默认完整任务、三组棋盘格、容量/间隙/边界失败、连续路径中段障碍、漏报捕获集合、能力关闭、载荷支撑和快照不变。相关环境/旧转移回归另行执行。

`tests/parking_pickup_controls.cjs URL` 使用实际页面 JS 和 HTTP 编译器核验编辑、手动编译、两种策略、跳转、导出、容量失败与空目标；`tests/parking_viewer.cjs JOB_DIR...` 使用实际导出渲染器检查保护原子、停车/运输坐标、插值、32×到终点和数据只读。两者 DOM/Canvas 为替身，**不是实际浏览器 GUI 验收**；本轮浏览器连接失败，仍需人工查看页面排版与真实拖拽。

后续优化版本应复用同一目标集合、全部障碍与硬件快照，并返回相同规范停车终态；比较总时间、转移批次、parking 段数及全部载荷路程。策略可替换；环境校验和执行器不能因优化而绕过。
