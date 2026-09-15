# ROUTES V2：连续直行与占据格避障

2026-09-15。用户明确：“关掉格点”指**路径搜索将仍在 SLM 上的原子占据格标为障碍**，不是关闭物理 trap。该澄清替代此前可能的硬件开关解释。本轮未新增物理 SLM 关灯动作。

当前可编辑入口 <http://127.0.0.1:8794/>，页面标注 ROUTES V2；服务 PID21508，数据 `artifacts/ordered-axis/attempt4-discrete-grid`。原 attempt3 保留，不用新数据覆盖历史成绩。

## 改动

- 新增 `motion/ordered_routes.py`，将有序行列策略的路径模块独立出来。
- 路径坐标从 `2.5+5k` 扩展为 `2.5+2.5k μm`（k 为整数，即 2.5 μm 间隔）；仍采用正交路线，作用位置保留短接入段。
- `merge_straight_runs` 合并连续、同轴且各轴均不反向的运动段。每个 trap 继续沿自身直线移动，取消中间 waypoint 的零速停顿。水平/竖直切换以及任何轴反向时保留停止点；不跨 LOAD、pulse、switch、OFFLOAD 合并。合并后重新计算实际三次轨迹时长并重新校验整段，不能只改动画。
- `OccupiedSLMGrid` 从 LOAD 后预测状态中的静态 holder 生成障碍节点，并按既有安全距离标记附近网格节点。被抓走的源原子已转为 AOD holder，其源格不再被原子占据；其他 SLM 原子仍是障碍。没有修改实时 placement。
- 预筛选检查全部活动 AOD 行×列交点，包括空 trap；检查线段经过的中间网格节点，而不是只检查两端。跨障碍的路线不进入完整物理程序构造额度。相同地图随当前候选载荷/状态重建，没有跨状态复用过期障碍。
- 保留完整连续扫掠和物理校验：格点预筛选只是必要条件，不能证明安全；非格点接入、空开启 SLM、AOD 内部碰撞、实际作用对仍由 backend 审核。
- 路线去重/合并后按真实三次运动学时长排序，而不只按几何长度；候选共用已校验的只读空载定位/LOAD 准备，减少重复计算。

仍是有限 portal/corner 候选搜索，不是整个 C+R 维离散网格的完备 A*。本轮没有把原 rigid A* 改为高维 A*，也没有新增辅助腾挪或跨批驻留。

## 修复的事件时间错误

新直行方案暴露 `ProgramBuilder.finish` 中两种求和的 ULP 差异：某计划原累计时长为 `614.448961784611`，最后 interval 终点为 `614.4489617846111`。PLAN_COMPLETED 因而可能在最终 OPERATION_COMPLETED 前入队，严格运行时报告 `PLAN_TAMPERED: Program pending timeline mismatch`。

修复：scheduled program 的 `estimated_duration_us` 精确取 `max(interval.end_us)`，与实际调度区间共用同一终点。未降低校验精度、添加容差或改变硬件时间公式。环境只改这一通用构造器时间一致性问题，寻路算法仍全部在外部策略包。

## 实际结果

同一输入和终态，新版五例 × 双策略共十次执行全部成功，门恰好一次、终态恢复、独立无编译器重放 checkpoint 逐字一致。以下比较**同一个有序贪心的旧版与新版**，单位 μs；它同时包含网格、直行合并与路线排序变化，不能将收益单独归因于占据格。

| 案例 | 旧版 attempt3 | 新版 | 新版 CZ 批次 |
| --- | ---: | ---: | --- |
| 三列变距 | 1213.55 | 1019.75 | 3 |
| 二维变距 | 1470.81 | 1263.59 | 4 |
| 原本可并行 | 889.40 | 649.70 | 4 |
| 矩形闭包 | 2160.03 | 1890.22 | 5+1 |
| 交叉依赖 | 3054.82 | 2250.64 | 3+2+1+2 |

占据格预筛选分别拒绝4092/3752/3484/1920/8232条跨障碍路线提案。这是跨候选/后备搜索累计次数，不是互不重复的路径数量，也不能当作编译加速倍数。编译时间仍受候选组合、完整校验和并发本机负载影响，未做稳定性能基准。

## 验收

- 71 个不同测试通过：主批次首次70通过、1个新测试错误地从执行后状态重放，修正为保存初始checkpoint后，4个路线专项全部通过（其中3项与主批次重叠）。未修改严格重放断言。此前8个有序策略测试在真正时间终点修复后已全部通过。
- 覆盖：直行取消中间停点、转弯与反向保留停点、新格点直通、静态占据格、抓取后源格释放、线段中间障碍、共轴/序关系/闭包、时间终点精确一致和实际重放、动态支撑、行列后端及环境边界。
- `route_audit.json` 对十份最终 plans 的所有连续 MOVE 区间检查：全为正交段，已无可以进一步合并的同向直行停点，LOAD/pulse 等边界不跨越。
- `tools/check_architecture.py`：134模块、零违规。非全仓测试。
- 真实内置浏览器：现有8794刷新为 ROUTES V2；在三CZ后加H，双策略实际编译成功（job `eb046141b57c440c905215acfca58e2a`），有序策略1020.75μs、三CZ合批，逐字重放；真实时间比例和关键帧模式均以32×自然播放到终点。
- 本轮没有Git提交/推送。

## 复现

```powershell
C:/python312/python.exe examples/run_ordered_axis_experiment.py --output artifacts/ordered-axis/routes-v2-reproduce
C:/python312/python.exe examples/run_ordered_axis_experiment.py --serve --port 8794 --output artifacts/ordered-axis/attempt4-discrete-grid
C:/python312/python.exe -m pytest -q tests/test_ordered_routes.py tests/test_ordered_axis_greedy.py tests/test_runtime_prefix_cache.py tests/test_row_column_aod.py tests/test_environment_boundary.py tests/test_dynamic_traps.py
C:/python312/python.exe tools/check_architecture.py
```
