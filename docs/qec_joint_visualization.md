# 联合策略的记录与界面

2026-09-12，步骤3 attempt1。主任务统一首次74项检查通过（8.94s，包含本页批次记录与 Node 测试）；随后完整481槽物理编译与120计划独立重放通过。本页面的正式浏览器子验收一次通过，阶段状态由主任务账本维护。

工作台新增 `compiler=qec_joint`，继续使用 `qec_enabled=true` 和 `layout=surface_qec_ghz2`。编辑器保留实际 gates、condition、depends_on，编译分派至 `simulation.qec_joint.run_qec_joint`。切换三个 QEC 策略时保留当前草稿。保存结果恢复接口接受 qec_joint，仍展示实际结果来源，不重新编译或改写源产物。

原生 Raman 批次的 recorder 保存有序 `gate_ids`、`applied_by_gate`、`applied_gate_ids`、`gate_qubits`、每门 U 参数和所有目标 holder。整体 `applied` 表示至少一个目标实际打光。每个原子的活动来自其自身已提交 DAG 与条件：真为 gating，假为 controlling。全假批次归 control，混合批次归 Raman；设备忙时不按目标数量累加。

viewer 根据 `applied_gate_ids` 和 `gate_qubits` 只绘制真实目标进度弧，假条件目标保持闲置色，混合批次字幕分别列出打光原子和不打光原子。没有新增元数据的旧单门记录继续使用原 applied/qubit_ids 字段，已有离线产物不改写。

决策表显示实际原生批大小、两种读出服务的合法成本或拒绝码、选定服务与节省时间；完整候选报告仍保留在原始决策 JSON。候选拒绝不是正式阶段失败，界面不将拒绝候选伪装为已执行操作。

新增 `tests/test_raman_batch_visualization.py` 包含实际 Executor 全真/混合/全假三种批次，调用 Node DOM/Canvas 检查真实目标弧线位置与数量、无假光、旧字段兼容和数据不变；它不代替真实浏览器验收。

正式浏览器命令：`python examples/accept_joint_qec_ui.py --saved-job 03a43acfc3a55199bc9ce6d971d37a92`。新服务8784，PID28316，保存结果链接 `http://127.0.0.1:8784/?job=03a43acfc3a55199bc9ce6d971d37a92`，不重编完整481槽。正式输入、开始时间和预期标准先写 `artifacts/qec-roadmap/step3-attempt1/ui-subcheck/attempt.json`，结果在同目录 `browser-acceptance.json`。

- 实际 Q000/Q006/Q009/Q015 同批 H、mobile holder、静止及至少5μm邻距通过。
- 实际 Q018/Q021/Q026/Q029 在 MZ 静止 AOD 上测量与复位，测量中点尚无该次读出，活动与holder一致。
- 三个混合条件批次各14门，实际仅一个目标打光；真实 Canvas 的弧线数量和位置逐目标核对，假目标无光，截图保留。
- 同一19255.9μs记录的32× physical和keyframe全程分别24.625s和23.578s，到原34个SLM终态，无page error。上述时间是本机浏览器单次观测。
- 唯一新编译来自真实编辑的 H0/H9/CZ(0,9)/H9/CZ(0,9)/X1 六门，job `7d842abca67e4b79bcaf65919377bc69`，实际 qec_joint、1247.6μs、六效果各一次、原holder终态。它预先声明为非GHZ协议，量子GHZ和协议完整性false符合预期，未伪报QEC正确。
- `source-stability.json` 的 `changed_during_run=false`；保存来源、短输入、trace、checkpoint、截图都保留在子验收目录，未覆盖步骤2证据。
