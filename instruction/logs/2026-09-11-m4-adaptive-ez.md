# 2026-09-11 · M4 按需求分配 EZ 与失败验收

- 状态：COMPLETED（本轮需求完成，M4 整体仍待进一步优化）
- 用户目标：从固定少量 EZ 站点升级为按线路需求开关 trap、选择驻留伙伴及换原子；失败弹窗汇总；保留任意受支持线路编辑与真实重编译。
- 基线：M4 greedy、schema 13、固定 Raman 1 μs、最高 32×；此前连接恢复已完成。
- 本轮边界：单 rigid AOD、CZ + U3/别名，有限候选搜索；不改变物理间距和 Executor 唯一提交规则。

## 设计

新增显式 adaptive EZ 平台选项，声明完整候选格点且初始关闭，编译器按当前操作数和占位选择。旧输入缺少选项仍复现原双站点平台。候选格点是静态 world，开关才决定实际光阱；不在执行时添加几何。

失败保留输入、实际记录、预算和拒绝原因；有限搜索失败不等于物理不可实现。计划验证成功、失败与编辑后恢复，随后完成浏览器验收和回归。

## 实现

- `visualization/workbench.py`：显式 ez_policy 与 max_decisions 输入验证、全 EZ 候选网格初始关闭（4 原子 row 为 36 点）、失败汇总。旧缺字段输入不改变平台。
- `motion/greedy.py`：从全网格按操作数当前位置、resident、loaded、驱逐和交接估价排序，再精确比较合法计划；保持真实路线/开关成本。`simulation/m4.py` 新增 adaptive_sites 参数、失败阶段与搜索范围，首轮该门两个方向都失败时扩大到下一组候选；每段记录实际 EZ mask 变化。
- `workbench.html/js`：初始条件中的 EZ 选择与预算、保留全部编辑/随机/撤销/导入导出，决策表列出具体 EZ 开/关；失败遮罩和下载记录，返回编辑可再次编译。
- `workbench_server.py`：编译前保存输入，正常结果另存 failure_report 和离线 index.html；进程异常/超时由父进程保存输入、最后进度和原因。
- `examples/run_m4.py` 识别 adaptive 输入，不错误宣称属于旧 M3 平台族；新增 `examples/validate_adaptive_ez.py` 复现电路矩阵并逐项调用独立 verifier。
- 同步 `docs/milestone4_greedy.md`、`docs/circuit_workbench.md`、`instruction/compiler_contract.md` 和 handoff。

## 本轮验证

| 检查 | 结果与证据 |
| --- | --- |
| `python -m pytest tests/test_m4.py tests/test_ez_switch.py tests/test_workbench.py -q --basetemp=artifacts/pytest-adaptive-base` | 32 passed，42.22 s |
| `python -m pytest tests/test_adaptive_ez.py -q --basetemp=artifacts/pytest-adaptive-fallback` | 8 passed，22.29 s；真实几何拒绝和扩大搜索随后简化为固定预算，最终 `-k geometry --basetemp=artifacts/pytest-adaptive-geometry-final` 为 3 passed、5 deselected、1.29 s |
| `python -m pytest -q --basetemp=artifacts/pytest-adaptive-full` | 314 passed、1 warning、646.31 s；日志 artifacts/m4-adaptive-full-tests.log。收集时包含首批 6 项 adaptive 测试，后两项几何测试见上行专项，不将 314 写成 316 项全量回归 |
| `python examples/validate_adaptive_ez.py` | 8 条完成、1 条预期预算停滞；9 份全部独立重放 verified。artifacts/m4-adaptive-ez/acceptance.json 含 source SHA256 |
| `node tests/m4_workbench_controls.cjs http://127.0.0.1:8767` | 遮罩修复前后均检查，最终 PASS；真实 HTTP + DOM doubles，含编辑 U3/初态、随机/撤销、导入导出、预算失败、弹窗、下载、恢复。artifacts/m4-editor-http.json |
| `node tests/playback_boundaries.cjs` 加 partners-row/random-16-44/user-current/budget-failure 的 index.html | 四份完整关键帧 1×/32× 和暂停后恢复 PASS |
| 内置浏览器真实交互 | U3 θ=.123、添加 Q000/Q003 CZ 后 9/9 完成、1595.629 μs；真实预算失败；可见遮罩截图；关闭后提高预算/随机载入并编译成功；关键帧和真实时间两模式 32× 到终态 |
| 8766 更新 API | preview 保留 adaptive/max_decisions，36 个初始关闭 EZ 点；未刷新用户原草稿 |

dateutil 的 datetime 弃用警告为既有 warning。Python 完整回归收集后补充测试与前端显示/遮罩修复，前端另经实际 HTTP 及浏览器验证；未重复整套长回归。

## 电路尝试

| 输入 | 状态 | 完整终态耗时 μs |
| --- | --- | ---: |
| 5 CZ 换伙伴，row | completed | 2701.489 |
| 同逻辑线路，grid | completed | 2674.259 |
| 同逻辑线路，shuffled/seed19 | completed | 2349.488 |
| 4 原子混合随机，seed41 | completed | 3279.379 |
| 6 原子混合随机，seed42 | completed | 3947.020 |
| 8 原子混合随机，seed43 | completed | 5611.653 |
| 16 原子混合随机，seed44 | completed | 6509.256 |
| 原保存 bea1faa3… 10 门线路 | completed | 3065.526 |
| 5 CZ，max_decisions=1 | stalled，1/5 完成 | 已执行 454.203 |

预算失败码 DECISION_BUDGET_EXHAUSTED，首轮实际尝试 8 个候选，遗漏 64 个方向/位置条目，剩余 g1–g4；保存真实 7 操作和 checkpoint。它不是路由不可行结论。边界几何专项另验证 CANDIDATES_EXHAUSTED 与具体拒绝分组，以及扩大搜索找到合法站点；不模拟失败来替代物理检查。

## 浏览器发现与修正

原生 `<dialog>.showModal()` 在此次内置浏览器没有实际出现，尽管摘要 DOM 已写入；未据 DOM double PASS 误称视觉通过。改为明确 fixed 遮罩、role=dialog、关闭/下载/键盘操作后，实际截图出现居中弹窗及背景遮罩。随机线路 8/8、43 操作、2366.120584 μs；其 EZ_25_25、EZ_5_25 按需开启，loaded Raman 在 EZ_0_25 卸载开启、随后载入关闭，最后退出恢复全部 masks。浏览器产物目录 `artifacts/workbench-adaptive-ez/a5c6f688c45149858d7ad92c09b54eaf`，验收摘要 `artifacts/m4-adaptive-ez/browser-acceptance.json`。

## 限制与下一步

没有全局最优或连续任意坐标搜索保证。候选网格是明确平台简化，初筛估计只决定有限搜索次序；排序后仍以完整验证计划计费。当前最多 16 READY、每方向首轮 4、失败扩展 12，未搜索部分明确记录。占位驱逐与换伙伴沿用真实装卸；单 AOD 服务仍非抢占，Raman 只填合法 MOVE 窗口。新平台与旧双点的耗时不可直接当同平台策略收益。

下一项：在相同 adaptive 平台、输入与终态下比较 next-use/有限 lookahead，改善长期驻留与退出代价；继续通过任意编辑线路复测。M5 多 AOD/批量 CZ 与 M6 RL 未启动。

服务：8766 PID 18536；8767 PID 22728，重用前核实。没有 Git 提交/发布，没有改动安全策略，没有更新记忆文件。

CLI 最终补充检查：run_m4 从输入继承 max_decisions；显式参数优先且写回导出输入。保存的 budget-failure 输入不加 CLI 预算参数仍按 1 次决策失败，避免导入/命令行预算不一致。
