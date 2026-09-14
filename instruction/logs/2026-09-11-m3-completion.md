# 2026-09-11 · M3-C–F 整体实现

- 状态：COMPLETED（声明 M3 范围实现、机器与离线控制验收完成；真实浏览器视觉复验受工具阻塞，单列未完成）
- 用户目标：一并实现 M3 剩余任务，不再按子阶段停下。
- 用户确认的返修点：M3 先完成正确、可运行、可验收的确定性基线；详细考虑 M4 时允许返修调度接口、策略分层、候选成本与复用决策，不以当前启发式作为永久架构或全局最优。
- 保留约定：真实物理 pipeline、单比特固定 1 μs、最高 32×、初始条件优先和随机载入；不放宽物理安全规则。

## 实现

| 工作包 | 源码与行为 |
| --- | --- |
| C | motion/persistent.py：PersistentTargetCompiler、ResidentCompiler、ReturningCompiler；真实 EZ/loaded/异位空 AOD 续接、KEEP、RETURN_ONLY、新站点卸载、临时空位置换和共同完整终态。motion/family.py 识别 10 μm SZ/分离 EZ/足够容量/半格走廊，构造归纳与限定起态见 docs/milestone3.md |
| D | domain 增加 gate_effects/task_phase、scheduled execution_mode、origin time/metrics 和 running/completed operations；motion/scheduled.py 组装操作时间表；simulation/operation_program.py 独立 audit、纯 transition、完整未来验证和恢复前缀重建，Executor 唯一提交；资源逐操作释放，完成优先同时间顺序 |
| E | simulation/m3.py 有限确定性决策，两个实质不同 compiler，同终态共享 validator/Executor/viewer；区分 candidate_rejections 与 stalled，决策预算和物理拒绝保留未完成 DAG/holders；examples/run_m3.py 输出完整输入/诊断/trace/checkpoint/选项/终态，非成功退出码 1 |
| F | recorder 记录全部在途操作，viewer 对并行片段使用共同时间映射，类别与 AOD/Raman/CZ 资源区间图、逐原子分页/搜索；examples/verify_m3.py 独立重放录下的 plans，不调用 compiler，检查覆盖/资源/装卸/终态与逐字节 checkpoint；实际 256 原子世界中的多伙伴混合电路 |

schema **13** 拒绝旧 1–12；旧回放保留历史物理时间。ProgramBuilder / TaskProgram 的 serial 兼容路径继续保留。工作台新草稿默认 resident；旧无 compiler 字段导入走 legacy，anchor_order 只用于 legacy。新默认示例在 CZ 后对 EZ 静态锚点施加 U3，可显示与伙伴归还重叠；不会重置已打开的用户草稿。

## 验收记录

| 命令 / 检查 | 本轮结果 |
| --- | --- |
| 原 Task IR + workbench 回归 | 26 passed，60.69 s |
| M3 第一次专项 | 26 passed / 1 failed；发现 loaded Raman 的资源推导抛 TypeError；改为明确稳定 SLM 资格拒绝，原子性负例覆盖 |
| M3 专项含全部边界恢复、续跑、并发损坏、同时间与 hashseed | 29 passed，176.96 s（与其他检查并行运行） |
| 第一次 `python -m pytest -q --tb=short` | 289 passed / 1 failed / 1 warning，894.92 s；旧 trace 未携带资源字段导致 summarize_trace 与 recorder 不一致 |
| 修复后 `python -m pytest tests/test_visualization.py tests/test_m3.py -q --tb=short` | 35 passed，186.28 s |
| 最终完整 `python -m pytest -q --tb=short` | **292 passed，1 warning，573.95 s** |
| `node tests/m3_controls.cjs` | PASS：实际 Raman/loaded MOVE 同时出现、脉冲后继续移动、共同时间映射、资源并集/资源图跳转、交接 holder 提交与双支撑、关空阱定位、256 分页搜索、数据不变 |
| `node tests/viewer_speeds.cjs artifacts/m3-resident/index.html` | PASS：0.25–32×，physical/keyframe 两模式、精确进度、终点停止、不改物理记录 |
| `node tests/task_controls.cjs` | PASS：既有零门运输/拆分效果/cleanup 类别兼容控制检查 |
| `node --check src/neutral_atom_env/visualization/workbench.js` | PASS |
| `examples/verify_m3.py` 对 resident / returning / scale-256 / budget-failure | PASS：共享校验器/Executor 无 compiler 重放，独立门覆盖/资源/装卸/终态；失败只确认实际已执行前缀 |
| 预算失败检查点续跑 | PASS：恢复后完整 snapshot 与不中断 resident 运行逐字节一致，8 门恰好一次 |
| HTTP / 8766 | PASS：resident 选择、真实 1 μs Raman 与运输重叠、初始条件优先、32× bundle。证据 artifacts/m3-http-smoke.json |
| 维护文档链接检查 | PASS：agent/README/instruction 根模块/docs 的本地链接无断链 |

警告仅为既有 dateutil 使用 datetime.utcnow 的弃用提示。全量复验期间没有修改物理参数；旧 rigid-parking 对角非法例仍拒绝。兼容汇总修复从 trace 的原始 plan/OperationInterval 补读资源；没有修改旧 trace。另修正非零绝对时间下 cycle_makespan 的验证算术，使用与 reducer 相同的 end − start，未放宽公差。恢复支持完整 program 后的 WAIT/RNG 兼容事件，并拒绝在途插入。

## 可重现的物理结果

输入 `configs/workbench/m3_mixed.json`：6 原子、4 CZ + H/U3/X/U3，其中不同伙伴包含 CZ(a,b)、CZ(a,c)、CZ(b,d)。两种策略同初态、同全体 holders/axes/masks 归还目标。

| 指标 | resident | returning |
| --- | ---: | ---: |
| 完成门 / operations / commits | 8 / 106 / 230 | 8 / 110 / 228 |
| plans | 9 | 4 |
| 全程序 wall / μs | 4577.884560239698 | 4902.918265717286 |
| 逻辑完成 / μs | 3258.3055523159915 | 4292.760534658647 |
| LOAD / OFFLOAD | 11 / 11 | 12 / 12 |
| AOD 距离 / μm | 1187.8422801198487 | 1248.8591328586433 |
| 原子距离 / μm | 836 | 840 |
| Raman / 重叠 / μs | 4 / 4 | 4 / 4 |

256 原子运行：4 CZ + 4 U3、8 effects、97 operations、9 plans、212 commits；wall 11981.276813985776 μs，逻辑完成 8758.725737146313 μs，AOD 距离 4989.538406992889 μm，原子距离 3121 μm，10 LOAD / 10 OFFLOAD，Raman 与运输重叠 4 μs。真实世界包含全部 256 原子及旁观原子安全检查，不表示全部原子都被运输；不是稠密线路或浏览器 FPS 性能证明。

## 宿主开销与产物

下列为本机本次运行的编译+Executor+recording 墙钟，不含 HTML/JSON 写入；曾与 pytest 并行，不能视为独占机器性能基准，也不计入模拟 μs。

| 目录 | 运行墙钟 / s | recording.json / bytes | index.html / bytes |
| --- | ---: | ---: | ---: |
| m3-resident | 26.904 | 316094 | 366617 |
| m3-returning | 16.982 | 317408 | 367931 |
| m3-scale-256 | 125.878 | 640663 | 691186 |
| m3-budget-failure | 2.773 | 43756 | 94279 |

每个目录均保存 input/family/run_options/terminal/result/candidate_rejections/diagnostics/recording/trace.jsonl/checkpoint/index.html。verify 另输出 verification.json；失败目录有 resume_verified.json。viewer 按维护源重新生成，没有手改 artifacts HTML。

```powershell
python examples/run_m3.py --output artifacts/m3-resident
python examples/run_m3.py --compiler returning --output artifacts/m3-returning
python examples/run_m3.py --atoms 256 --output artifacts/m3-scale-256
python examples/run_m3.py --max-decisions 1 --output artifacts/m3-budget-failure
python examples/verify_m3.py artifacts/m3-scale-256
python -m pytest -q --tb=short
node tests/m3_controls.cjs
```

## 浏览器与交付限制

CUA `getState` 本轮再次报 `nodeRepl.fetch request failed`。按 computer-use 技能尝试备用 Windows 浏览器路径：初始化与列出应用成功；请求 Edge 新标签页时工具因无法可靠判定当前 URL 而自动中止，之后未继续浏览器操作。没有浏览器视觉 PASS，也没有刷新已有用户草稿。离线 DOM/Canvas 与 HTTP 是独立验收类型，不能替代真实窗口交互；工具恢复后补验实际播放/资源图/32×/规模视图。

8766 工作台已更新，最终默认三门示例 HTTP 编译完成并验证 1 μs 重叠，最后 PID 见 handoff（会话状态，重启后需复查）。仍仅监听 loopback，90 s 编译预算、32 原子交互上限保持；256 原子走 CLI。正常预算/验证失败保存可恢复当前状态；杀进程、取消或超时不保证最终 checkpoint。草稿未自动持久化，刷新前导出。

## 交接与下一步

同步 agent、README、milestones、compiler_contract、architecture、motion_planning/execution、state_circuit、visualization、validation、model_audit、circuit_pipeline/workbench、task_program、dynamic_traps 与日志索引。新增 docs/milestone3.md；旧完成日志和日期快照保留原状。GAP-003、005–009 只在声明 M3 范围关闭；浏览器复验单列未完成。

下一条任务是详细设计 M4，先处理用户保留的返修点：目标/候选/成本接口、驻留/退出决策、program 内时间窗口和失效边界，再比较 basic/greedy/critical-path/有限 lookahead。不得改 clearance 或用不同终态取得虚假收益。M3 不实现多 AOD、批量 CZ、RL 或量子振幅/测量反馈。

本轮无 Git 提交、发布或对外消息；当前源码未本地提交，历史 GitHub 同步不代表包含本轮变更。
