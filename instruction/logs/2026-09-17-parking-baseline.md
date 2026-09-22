# 2026-09-17 · Parking 基线模块与可编辑演示

## 范围与实现

按用户给定工程文档实现固定目标 pickup，支持 `naive_rowwise` 与对称 `naive_columnwise`。完整说明见 [合同](../../docs/parking_pickup.md)。`pattern_optimal` 为明确未实现的选项，未接入 RL，也不选择量子门。

- `strategies/motion/parking.py`：只读规划，捕获闭包、共享轴联动、X 后 Y parking、规范终态、分阶段计时与全载荷路程。
- `experiments/parking_demo.py`：可编辑三态网格工厂、全部保护原子、分离的集体运输、完整预验证与独立重放。
- `app/visualization/parking*`：手动编译、涂画目标/占据、逐行/列、跳转、输入和动画导出、结构化失败。所有回放复用共用 viewer。
- `examples/parking_workbench.py` 与 Demo 首页/启动器：独立可调用和可发现入口。

## 失败与修复记录

1. 初次完整任务在第二次装载失败 `AOD_BUSY`。根因是后端 LOAD 只支持空载。保持该限制，扩展显式、有能力开关的有序 RECAPTURE；强制新增 bindings 等于全部活动交点新增捕获闭包。默认能力关闭，独立场景显式开启。没有逐原子寻址，没有放松几何/扫掠/支撑条件。
2. 中段碰撞测试最初用非 5 μm 网格点，环境正确先拒绝非法 SLM。改为合法 `(5,0)` 保护点和 7.5 μm X parking，检查路径中段碰撞；未改物理网格规则。
3. 世界边界测试最初遗漏同步 zone 边界，随后断言错误码名称不匹配；修正测试夹具和使用实际 `AOD_OUTSIDE_WORLD`，仍要求越界规划失败、快照不变。
4. viewer 测试最初试图调用不存在的 speed onchange；实际播放器每帧读取 select 值。按真实控件行为设置值后，32×到终点通过。
5. 浏览器连接 `nodeRepl.fetch request failed`。没有真实 GUI 通过证据；下方仅 HTTP、实际 JS 和 DOM/Canvas 替身验证。服务重启命令被自动执行策略拒绝后，保留已有服务，改用新空闲端口加载最终代码。

## 验证

- `python -m pytest tests/test_parking.py tests/test_dynamic_traps.py tests/test_row_column_aod.py tests/test_environment_boundary.py -q`：初批50通过。
- `python -m pytest tests/test_rigid_parking.py tests/test_single_trap_pipeline.py -q`：40通过。
- 增补三组棋盘格/世界边界、整理模块输入后，`python -m pytest tests/test_parking.py -q`：最终11通过。合计91个不同用例；其中占据穷举在两个测试内各覆盖81个三态 mask。
- `node tests/parking_pickup_controls.cjs URL`：实际页面 JS + HTTP（DOM/viewer 替身）通过；编辑、手动编译、两策略、能力不足失败、空目标、动画导出。
- `node tests/parking_viewer.cjs JOB_DIR...`：两个实际动画的保护原子坐标、停车/集体运输、三次插值中点、32×到终点、记录只读通过。
- `python tools/check_architecture.py`：164模块，无越层依赖；Python/JS语法检查通过。
- Demo 启动器：首页＋四个编译服务均 HTTP 200；Parking 动态入口存在。最终独立服务能读取旧已验证任务；非法 preview 返回400。
- `tools/build_demo_bundle.py` / `tools/check_demo_bundle.py`：134文件，哈希、大小、相对链接和历史动画校验通过。

默认6原子（4目标、2保护）：逐行472.108834 μs，逐列688.298335 μs，集体运输均323.900738 μs。两个方案停车与最终坐标一致。逐行累计载荷拾取路程25 μm，包含此前载入原子后续联动。

交付服务：`http://127.0.0.1:58596/`，PID44768；最终代码，记录目录 `artifacts/parking-delivery/jobs`。逐行任务 `374a2027813d4fa0861d9b651759737a`，逐列任务 `c2b3b18ba27f44b0be0ccfb103ce3c02`。57990为本轮早期服务，历史工作台未停止。所有地址/PID仅本机当前会话有效。

## 未完成与下一步

真实 GUI 排版/拖画待人工验收；Pattern 优化未实现。仅固定正向 parking、正交固定集体运输，不证明无解或最优，不模拟光功率与保真度。后续优化须在相同目标集合、全部障碍、硬件快照和规范拾取终态下比较。外部障碍通过 JSON 编辑，源 patch 支持画笔。

本轮未要求发布，未创建 Git 提交或推送；已有 RL 工作保留。模块、入口、说明及验收记录均在本地。
