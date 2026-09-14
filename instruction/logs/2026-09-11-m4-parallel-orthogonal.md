# 2026-09-11 · 单比特并行与半格正交搜索修正

- 状态：COMPLETED（本轮修正，不代表 M4 全部完成）
- 用户纠正：不同 qubit 的单比特门允许直接并行；贪心运输限定横平竖直、2.5+5k μm 通道。
- 根因：旧共享 RAMAN_0、HANDOFF_GUARD 和单门填充循环将独立单比特门串行化，旧验收没有覆盖此要求。按用户确认修改平台资源模型，不把旧测试通过当模型正确。
- 范围：逐 qubit Raman 资源、实际并行调度/回放、稳定 SLM/同原子互斥保持；正交通道覆盖空载、载原子、CZ 接入及退出，全部保留物理扫掠校验。

## 完成内容

1. `motion/task_validation.py`、`motion/validation.py`、`hardware/raman.py`、`simulation/operation_program.py` / `physical_executor.py`：不同 qubit 使用各自的 `RAMAN:Qxxx` 及 atom/trap 资源。去掉跨 qubit 的全局 Raman 和交接互斥；交接中的目标本身仍不能 Raman。独立门允许不同种类和不同 U 参数，固定 1 μs。Raman busy time 统计区间并集，四门并行时为 1 μs，不累计成 4 μs。
2. `simulation/m4.py`：从 AOD 服务实际几何和资源轨迹推导每原子的连续可用窗口；按 DAG 前驱完成时间尽早加入独立 Raman，包括同一 qubit 的后续层。窗口可以跨不相关 AOD 操作边界；0.3 μs CZ 和独立 1 μs Raman 可以同时开始，不能因为基础服务短于 Raman 就漏掉并行。最终仍经 scheduled_program 全表独立审计与唯一 Executor 提交。
3. `motion/planners.py` 的 `OrthogonalHalfGridPlanner`、`motion/greedy.py`、`motion/single_trap.py`：贪心候选的每段只改变一个坐标，主通道为 x 或 y = 2.5+5k μm；端点附近以 ≤2.5 μm 的正交短段接入。空载暗阱也不能走旧对角捷径。候选按距离/段数确定性排序，逐段验证支撑、碰撞、边界和作用对。未降低安全阈值，仍计入所有空载/载原子路程、开关、交接及退出。
4. `visualization/recording.py`、`viewer.js`：记录每操作的 qubit_ids，按原子显示所有同时进行的 Raman 脉冲与门名，资源行拆为 Raman Q000 等。修复「查看门操作」落在同时完成事件边界而看不到脉冲的问题，改定位实际操作区间中点。实现中发现的 updatePanel 局部 effects 作用域错误已修复并经 Node/实际浏览器复验。
5. `workbench.js` / `.html`：新增「单比特并行验收 · 4 门 / 1 μs」预设，更新物理并行及路线说明。任意受支持线路编辑、随机、U3 参数、layout、实际重编译、失败弹窗/下载/恢复仍保留，最高 32×。
6. checkpoint 升为 **schema 14**，拒绝 1–13；共享资源及 busy time 语义变更使旧活动计划不能直接续跑。旧录制 HTML 仍可读，历史资源标签仅作兼容显示。已同步 agent、physics、motion、state、compiler、workbench、M4 规范与 handoff。

## 验证

| 命令或检查 | 本轮结果 | 证据 |
| --- | --- | --- |
| `python -m pytest -q --basetemp=artifacts/pytest-parallel-full` | **323 passed、1 warning、715.04 s** | `artifacts/m4-parallel-full-tests.log`；warning 是既有 dateutil 弃用提示 |
| `python -m pytest -q tests/test_parallel_orthogonal.py tests/test_m4.py tests/test_ez_switch.py tests/test_raman.py tests/test_task_ir.py` | 52 passed、159.32 s | `artifacts/m4-parallel-focused.log` |
| `python -m pytest -q tests/test_parallel_orthogonal.py` | 7 passed、25.83 s | `artifacts/m4-parallel-asap.log`；含短 CZ/1Q 同时开始、逐边界恢复和同 qubit 冲突拒绝 |
| `python examples/validate_parallel_orthogonal.py` | 六例符合预期，所有记录独立重放 verified | `artifacts/m4-parallel-matrix.log`、`artifacts/m4-parallel-orthogonal/acceptance.json` |
| `python examples/verify_m3.py <上述各案例目录>` 等价批量调用 | 最终六例 verified | `artifacts/m4-parallel-final-verification.log`；不调用 compiler；最终 HTML 由当前 viewer 重新生成后复验 |
| `node tests/m4_workbench_controls.cjs http://127.0.0.1:8767` | PASS | 实际 HTTP 编译、任意编辑/U3/layout、随机撤销、导入导出、预算失败弹窗/下载及恢复 |
| `node tests/m4_controls.cjs` | PASS | 混合线路中两门同时开始、同 qubit 后继顺序及逐 qubit 资源行 |
| `node tests/parallel_1q_controls.cjs artifacts/m4-parallel-orthogonal/four-1q/index.html` | PASS | pulse 按钮到 0.5 μs；四个原子、四个脉冲和门标签；资源并行；录制数据不变 |
| `node tests/playback_boundaries.cjs`，四例 index.html 参数 | PASS | four-1q、two-layers、mixed-row、user-current 的 1×/32× 完整播放与暂停续播 |
| 实际内置浏览器 | PASS | 四门真实编译 4/4、1 μs；0.5 μs 时四个脉冲；四条资源行均 0–1 μs；添加 Q000 下一列 H 后重新编译 5/5、2 μs；混合线路两种模式 32× 均到 969.9 μs 终态，截图已查看 |

首次旧契约专项出现 5 failed / 48 passed：旧测试错误地要求独立 Raman 互斥、全局 RAMAN_0、所有交接阻塞 Raman，以及旧路径的 21 μs 捷径。已按本轮明确模型修改预期，并保留同原子交接/门冲突的负例。不是删掉物理校验来使测试通过。完整回归之后仅补充了文档/模块说明；最终 viewer 的作用域与 pulse 定位修复另经 Node、六例独立重放和真实浏览器确认。

## 物理验收矩阵

所有总时间均包含声明终态；预算失败是实际未完成片段，不当作成功。

| 案例 | 完成门数 | 总时间 μs | 峰值同时 1Q | 检查的正交 MOVE 数 | 状态 |
| --- | ---: | ---: | ---: | ---: | --- |
| four-1q | 4 | 1 | 4 | 0 | completed |
| two-layers | 8 | 2 | 4 | 0 | completed |
| mixed-row | 8 | 969.9 | 2 | 20 | completed |
| mixed-shuffled，seed 23 | 8 | 1303.9 | 2 | 29 | completed |
| budget-failure，max_decisions 1 | 5 | 484.3 | 2 | 10 | stalled |
| user-current，保存的 bea1faa3… 输入 | 10 | 3430.5 | 1 | 86 | completed |

mixed-row 的 G001/G004 均为 0–1 μs，G002 为 1–2、G003 为 2–3；与不相关原子的交接/运输重叠。原 10 门输入存在逻辑依赖，不能为了显示并行强行同时执行。当前路线/EZ 平台约束不同于历史实例，不能直接用历史总时间声称策略加速。

## 决策与边界

- 不同 qubit 的 1 μs 旋转可直接并行是用户明确指定的当前研究模型，不作为实验硬件普遍事实。目标必须处于稳定 SLM；移动中的原子 Raman 尚不支持。
- 半格通道适用于当前对齐的 5 μm 候选网格；端点接入与 CZ 偏移仍依赖完整校验，不把通道间距当作所有任意几何必然安全的证明。
- 保留单 AOD、非抢占服务和有限路线/EZ 候选（站点首轮 4、扩大至 12；路径预算 64）。没有全局最优、任意障碍完备性、所有 32 原子/64 门在 90 秒内成功的保证；失败仍展示真实诊断。
- M3/legacy 基线策略保持原服务选择方式；共享物理验证能力已更新，但不承诺其采用 M4 的全部 ASAP 填充。
- `summary.overlap_time_us` 沿用「各操作时长之和减区间并集」的累计额外并行工作量；它不是“至少两个操作同时执行的墙钟区间长度”。四个 1 μs 门的该值为 3 μs，Raman busy union 与 wall time 均为 1 μs。后续若修改名称/口径需独立处理兼容性。
- 没有验收长时间 FPS、外部浏览器或全门集稠密极限性能；不将 323 个回归用例解释为贪心全局完备。

## 可复现与服务

Windows / Python 3.12，workspace `C:\Users\86136\Documents\ChatGPT\QEC-scheduler`。`examples/validate_parallel_orthogonal.py` 保存输入、trace、schema 14 checkpoint、recording、失败/决策报告、HTML 与独立 verification；acceptance.json 保存物理编译时的源文件指纹。其后用当前生成器刷新 HTML，最终 viewer 指纹另外记录在 `final-source-sha256.json`，不覆盖原编译来源。

当前 8767 PID **24700**：`python examples/circuit_workbench.py --port 8767 --output artifacts/workbench-parallel-orthogonal`。8766 主服务核实命令后重启为 PID **19784**：`python examples/circuit_workbench.py --port 8766`。下次复用前须重新核实 PID。原用户页未刷新，新增验收 tab 12 已保留并停在四门并行示例，用户可直接编辑再编译。

未创建 Git 提交或发布；源码仍未形成本地提交。没有修改 memory。

## 下一步

在固定本轮模型与路线空间的前提下，继续 M4 的 next-use / critical-path / 有限 lookahead。入口 `simulation/m4.py` 和 `motion/greedy.py`，用同一输入、初态、EZ 平台及完整终态比较换伙伴/驻留代价；继续把不同可编辑线路的成功与失败都作为验收输入。不得重新加入跨 qubit Raman 互斥。
