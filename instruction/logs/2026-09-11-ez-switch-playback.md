# EZ 开关候选与关键帧卡住排查

状态：实现、专项和完整回归完成；真实浏览器复验受连接限制。用户要求 compiler 将 EZ SLM 自由开关纳入估计，同时报告当前工作台关键帧在部分节点停住。

先读取最近服务器保存的真实 recording 复现播放；不刷新用户草稿。EZ 开关只允许空闲 SLM，支撑、开关成本、完整路径与终态继续由原 backend/validator/Executor 验证。

## 卡住根因

CUA getState 返回 nodeRepl.fetch request failed，未能读取当前浏览器内存。最近保存的 bea1faa3d00c406fbda9f0cfb0aba541（4 原子 10 门、99 ops）及 16177b8d005546f2b25dd768d094e5b4（65 ops）均逐帧复现卡在 1059.3106781186546 μs，playing=true。

相邻边界 1059.3106781186546 / 1059.3106781186548 μs 相差 2.2737367544323206e-13。timeSlices 却为这个舍入间隙分配了 800 ms；每帧显示→仿真→显示的换算丢掉增量，播放永久停在片段起点。较长记录在 1934.621356 μs 还有同类间隙。

viewer.js 仅在显示层以 16 × Number.EPSILON × 时间量级归并邻近边界，去掉数值误差制造的 idle；独立 displayTime 累计进度，seek/模式切换/重新播放重设映射；串行极小空隙不会映射回 0。原 recording、事件、轨迹与物理 metrics 不变。服务按请求读取当前 bundle，避免保留启动时的旧版本。

examples/debug_workbench_playback.py 重新输出六份原记录的当前 viewer 和来源 SHA256 manifest，不重新编译、不改原保存文件。修复回放在 artifacts/m4-debug-current/{job}.html。

## EZ 编译与安全

PersistentTargetCompiler 增加可覆盖 route hook，默认 Persistent/Resident/Returning 路径保持。GreedyCompiler 在纯 trial builder 中比较保留 supports、关闭直线路径上的空 EZ、关闭所有已开启空 EZ 三种有限集合（去重），每组尝试直达和十条有限走廊。实际开关+运输时间最短者胜，同价优先少关灯；不是所有 masks 的全局搜索。

只关闭空闲 EZ SLM，不能撤掉驻留原子的支撑。显式 TRAP_SWITCH 按 hardware.switch_duration_us 计时；bound OFFLOAD 内重新建立 SLM 支撑已包含在 transfer 时长，不重复计费。安全静止位置可显式重新开启，完整 terminal 恢复初始 masks。整段碰撞、SLM 排斥和 holder 支撑仍用原 backend/validator/Executor。

候选和 decision_log 新增 switch_operations / ez_switch_operations；工作台显示空 EZ 关灯次数。examples/run_ez_switch.py 生成实际零门任务演示：准备 → 关闭空 EZ0 → 从 (0,-35) 到 (10,-35) → 重新开启 → 完整归还。关灯 1 μs + 直行 20 μs = 21 μs；保留 SLM 绕行 40 μs。高开关成本 100 μs 时选择绕行。

## 验收证据

- `python -m pytest tests/test_ez_switch.py tests/test_m4.py -q`：16 passed，31.40 s。新测成本选择、每个事件边界恢复、重新开启、占用支撑禁止；原 M4 13 项通过。
- `tests/playback_boundaries.cjs`：最近六份保存记录全部在 1×/32× 完整结束，含两个原卡住实例；暂停续播正常，原物理 JSON 不变。
- 最近 10 门输入重新编译到 artifacts/ez-switch-current：56 operations、126 commits、3565.343209 μs、10 LOAD/10 OFFLOAD、Raman 重叠 4 μs。独立 verifier 重放完整 checkpoint、门覆盖、资源和终态通过。本实例未选额外 EZ 关闭，收益主要来自合法直达候选，不归因于关灯。
- artifacts/ez-switch-demo：9 operations、4 任务、0 门、374.801099 μs，独立 verifier 通过。viewer 检查 MOVE 穿过时 EZ0 disabled、终态 enabled，与真实记录一致。
- 当前 viewer 在 EZ 串行演示、M3 resident 并发和 256 原子 /2 记录中，两种模式都完整结束且数据不变。旧 M1 /1 输入被版本检查拒绝，未篡改历史格式。
- `viewer_speeds.cjs`：新实例 0.25–32×、两种映射和端点通过。两个 JS 文件语法检查通过；HTTP GET 验证 8766 提供新 displayTime/timeTolerance bundle。
- 额外启动 8767 隔离 HTTP 测试服务被自动审批拒绝，仅返回 blocked by policy；未绕过、未声称该额外编辑器检查通过。最终日志的 shell 写入也被拒绝，改用限定文档的文件补丁。

最终 `python -m pytest -q`：**308 passed、1 warning、613.38 s**，警告为既有 dateutil utcfromtimestamp 弃用提示。包括原 305 项及新增 3 项 EZ 开关检查；常规 HTTP 工作台测试在全套回归内通过，额外隔离服务的检查仍按上述未完成记录。

## 交接

当前 http://127.0.0.1:8766/，PID 12336（再次操作前核验）。旧 PID 12348 在核实命令行为本项目服务后更新。没有控制或刷新用户现有页面；旧页持有旧 JS，刷新前先导出草稿。最近原输入仍在 artifacts/workbench/bea1faa3d00c406fbda9f0cfb0aba541/input.json，可直接打开修复后的原记录回放。

真实浏览器视觉复验未完成（CUA 连接错误）；离线 DOM/Canvas 完整播放不冒充截图或 FPS。schema 13 / viewer /2 保持。M4 首版数值保留为历史，新直达/开关候选成本应重新编译比较。

已同步 handoff、motion_planning、visualization、milestone4_greedy。后续继续 M4 critical-path/lookahead；更多 masks、并发开关须另设预算和时空验证。本轮未 Git 提交、未发布、未改全局 memory。
