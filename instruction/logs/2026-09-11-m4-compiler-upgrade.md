# 2026-09-11 · M4 图最短路与编译性能升级

状态：COMPLETED（本轮图最短路与重复重演优化，不表示全部性能问题关闭）。接续 [f902 超时核查](2026-09-11-m4-timeout-f902.md)。用户要求研究明确的路径规划算法、升级过慢的贪心/前瞻编译；沿用已授权的研究、实现、验收三个子 agent。

## 定位与改动

- 原路线是有限 portal/折线模板，最多审核 64 条，不是图最短路。新增 `motion/astar.py`，固定 masks/holder/rigid footprint 的半格通道图 A*，Manhattan 启发，完整 backend 扫掠，显式短接入和装卸首尾停点。先求同图忽略碰撞的下界路线，审核通过即精确早停；否则搜索合法边。固定图长度最短，rigid 恒速下对应纯运输时间最短；不保证全电路最优。
- RouteRequest 增加兼容的可选 state/depart/approach/edge_validator；旧无状态调用保留旧模板。单/多 trap M4 使用 A*，row_column 明确拒绝。节点预算和图内无路有不同错误，完整 program 与 Executor 复验保持。
- 原输入 cProfile：32 前瞻分支、1628 Executor steps、3320 runtime 验证、111190 次 transition，运行态反复重演约占带 profile 耗时的 79%；候选生成约 11%。性能原始数据 `artifacts/m4-timeout-f902/profile-before.pstats`，不是无分析器的用户等待时间。
- `operation_program._expected_prefix` 只缓存独立重建的期望状态，每个完整 plan/物理环境保留最近一个前缀、总计 32 项；不缓存 live validation 的通过标记。每次仍核验完整 trace 顺序、计划起点、所有 runtime 字段/DAG/pending 后缀。修改 world/hardware/atoms/circuit/AOD容量或 spacing 更换缓存键；短前缀恢复从头重建。
- trace 的精确字符串解析使用 4096 项 LRU，缓存递归只读的值，篡改字符串必然重新解析。lookahead 对可信内部持久状态用 dataclasses.replace 创建独立顶层 runtime，外部 checkpoint restore 审计保持。

## 当前证据

- 首轮升级原输入完成：55.967 秒，12/12，3787.5 μs，与原模拟总成本相同；152 operations / 320 commits（保留交接接入停点，比旧版多段），10 LOAD/10 OFFLOAD。独立 `verify_m3.py artifacts/m4-timeout-f902/upgrade` verified。
- A*、M4、多 trap、正交并行专项：47 passed / 147.93 秒。新 A* 11 用例含双墙必须多拐弯、独立 Dijkstra oracle、活动空格点、附带原子、完整容量边界和明确搜索失败。
- 策略专项：20 passed / 15.02 秒。私有状态 fork 的 9 项隔离/restore 等价检查通过。
- 升级贪心对照：13.334秒，12/12，完整终态3884.5μs、156operations，独立 `verify_m3.py artifacts/m4-timeout-f902/upgrade-greedy` verified。前后输入SHA256一致，只有greedy/lookahead之间的compiler字段不同；摘要在 `upgrade-comparison.json`。这是本机单次耗时（同时有其他检查），不是性能SLA或统计基准。
- 前后cProfile摘要保留 `profile-summary.json`：transition 111190→16032；runtime验证3320→4276次，累计时间292.075→56.518秒。实际分段增多但重复重演减少；带profiler时间不能当作用户等待时间，也不能把交叠的累计函数耗时相加。
- 热缓存损坏/环境隔离/容量、分支隔离与restore等价联合 **28 passed /12.72秒**。包括改变holder/masks/pose/metrics/runtime/time/DAG/transfer/trace/pending，修改硬件与measured原子导致重验拒绝、较早前缀恢复和32项上限。
- 最终全量 `C:/python312/python.exe -m pytest -q`：**460 passed /1 dateutil弃用警告 /731.26秒**；完整输出 `artifacts/m4-timeout-f902/pytest-upgrade.log`。最终代码下执行，不借用旧417通过数。
- `node tests/viewer_speeds.cjs artifacts/m4-timeout-f902/upgrade/index.html`：0.25–32×两种时间映射通过。HTTP8768首页200、编辑模板存在。浏览器自动化入口 `cua.getState()` 因nodeRepl.fetch连接失败，故本轮不声称进行了真实鼠标/截图验收；已生成可复用HTML并请求Codex文件预览，工具返回queued。
- 新worker每次spawn加载当前代码，原8768草稿/服务未重启，编辑、随机、导入导出和编译接口保持。完整用户报告见 [编译器升级](../../docs/m4_compiler_upgrade.md)。本轮相关文档本地链接检查通过。

## 剩余边界与下一条任务

本轮已解决旧模板不能多次绕障、原f902超时和主要重复重演开销。A*保证的只是固定状态/masks/目标的有限rigid图最短运输；门次序、站点、开关和KEEP/RETURN仍有界启发式。旧20行物理矩阵未全量重新生成，不能继承其数值作为新路径证据；没有任意32原子/64门交互延迟或成功率保证。

升级后profile仍出现约128.6万次AOD配置构造，候选共同准备和归还成本重复，前瞻在f902只比贪心节省97μs模拟时间但多用约43秒主机时间。下一条可执行工作：对这些重复纯计算建立有界完整键复用的独立等价/失效测试，再评估按墙钟时间分配搜索预算；任何降级必须显式报告，不得静默变更策略或把预算耗尽当无解。不得越过用户当前M4优先级直接进入M5。

研究来源/边界：[调研](../../docs/m4_pathfinding_research.md)、[已实现 A* 合同](../../docs/astar_routes.md)。未变更硬件参数、线路、策略搜索预算或 HTTP 90 秒超时；没有提交或发布。
