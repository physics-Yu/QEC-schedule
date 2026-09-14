# M4：贪心编译与线路工作台

> 本文保留 greedy 的迭代与历史成本。当前四策略、实际前瞻和 MOVE 子窗口以 [M4 完整策略合同](milestone4_complete.md) 为准；统一最新物理比较见 [验收](m4_acceptance.md)。

**单台 AOD 多 trap 试验**：现可选 1×2 / 1×4，按同排需求联合装卸及运输后再执行 CZ；见 [能力与限制](multi_trap.md)。本页默认单 trap 持久服务保持；新增阵列构造器没有宣称批量 CZ 或独立 cell 运动。

**当前门规则（2026-09-11 最新）**：仅 H/X/Y/Z/T/CZ 可执行；仅同类型门可并行，异类型门（含 CZ/1Q）不得重叠。内部 U 参数仅记录固定门效果。checkpoint schema 17，拒绝旧 1–16；旧输入不自动转换。详见 [门规范](gate_contract.md)。本页旧门集和任意类型并行描述以该规范为准。

状态：2026-09-11，greedy 已实现按需求选择 EZ 网格位置与失败弹窗，并修正独立单比特并行和半格正交运输。M4 整体仍有 critical-path、有限 lookahead 和更细决策边界待做。保持用户要求：初始条件 → 编辑线路 → 编译/验证 → Executor → VisualRecorder → 共用回放。

## 直接操作

运行 `python examples/circuit_workbench.py --port 8766`，打开 http://127.0.0.1:8766/ 。默认载入「贪心验收 · 连续 Raman / CZ 复用」，编译策略为 `greedy`。

先设置原子数、layout 和 seed，再点击/拖入门；CZ 在同一列点击两个原子，门集仅 H/X/Y/Z/T/CZ，可编辑列与操作数，无可编辑角度。点击「编译并生成动画」，或保留自动编译。随机载入、撤销/重做、JSON 导入导出、旧版本标记、取消和回放下载仍可用。策略可切回 M3 resident / returning / legacy；旧 JSON 缺少 compiler 时保留 legacy。

单比特操作固定 **1 μs**，最高播放倍率 **32×**；倍速不改物理时间。工作台限制 1–32 原子、64 门；90 秒编译超时是交互预算，不保证所有上限线路均能完成。

回放上方的「M4 贪心决策」显示每段开始时间、选中的门/静态伙伴/EZ 站点、实际服务时间、合法候选数和补充 Raman 区间。所有结果来自实际提交事件；不把列号解释为物理并行时间。

## 局部候选与选择

`motion/greedy.py` 的 `GreedyCompiler.alternatives(gate_id, state, site_limit=4)` 只读构造当前 READY 门的候选：

- CZ：两个操作数分别作为静态伙伴，枚举有限 EZ 站点；每站点比较左/右/上/下四侧，并复用合法当前姿态。占位迁移、卸下无关 loaded 原子、装载、暗阱重定位和最后 CZ 全部是显式操作并计费。
- Raman：稳定 SLM / 静止 AOD 均提供直接作用候选。<5 μm 先沿正交通道分离；备用 SLM 安置方案按实际运输与交接成本比较。
- 路线：对 OrthogonalHalfGridPlanner 的半格正交候选按 Manhattan 总路程排序，逐条经 backend 完整扫掠验证，采用第一条合法路线。只保证此候选族内选择，不声明连续空间最短路或全局可路由。

候选保存 gate/anchor/site、完整 CompiledPlan、预计结束 holders。排序键为 `(门完成时间, 装卸次数, AOD 路程, 稳定候选 ID)`；时间来自完整操作之和，包括 load/offload、开关、空载/载原子运动和 pulse。不是直线距离近就优先。

`simulation/m4.py::run_m4` 默认每次考虑最多 16 个 READY CZ，每方向首先精确验证 4 个 EZ 站点；若没有合法 CZ，考虑 READY Raman。预算截断和最终拒绝均记录；没有候选时返回 stalled，有限失败不等于物理无解。决策日志的 truncated 为未检查门及站点方向的条目总数，不是已验证失败候选数。默认最多 10000 次服务决策。

## 按需求分配 EZ（本轮新增）

新工作台草稿默认 `ez_policy: "adaptive"`：SZ 保持 10 μm 格点，EZ 在 x=0..width−5、y=−40/−35/−30/−25 的 5 μm 候选网格上**初始全部关灯**。world 中记录可用位置；SLM mask 决定当前实际开启的光阱。不是预先点亮这些候选，也不在执行时凭空添加 trap。旧 JSON 缺少 ez_policy 或显式 `pair` 时仍采用原两个开启的 EZ 站点。

`GreedyCompiler(adaptive_sites=True)` 针对两个 anchor 方向分别给全网格排序，考虑操作数当前位置、已有 resident、loaded 伙伴、占位驱逐及装卸代价。初筛只是启发式估计；入围后比较完整、经过验证的实际计划成本。该门首轮两个方向的候选全部失败时，每方向再尝试下一组 12 个；每轮 search 记录尝试数和遗漏数，不能称为穷尽搜索。重复门可以保留同一对；新伙伴经显式停车/装载加入，必要时换驻留点或驱逐占位原子。

装卸协议建立目标支撑并撤去源支撑，载入后空出的 EZ 因而关闭；单独关闭挡路的空 EZ 仍比较真实 TRAP_SWITCH 成本与绕行成本。占用支撑不得任意关闭。`decision_log[].ez_changes` 同时记录交接内的 mask 变化和独立开关，页面显示具体站点及开/关，不只统计独立开关数量。最终终态恢复全部初始 holder、AOD 与 masks。

adaptive 是新的候选几何选项，不套用旧 `m3-grid-10um-v1` 构造证明；所有候选、时序与执行边界仍由共享 validator/Executor 校验。不同策略对照必须使用相同 ez_policy，不能把平台变化造成的收益都归因于策略。

## 失败与复测

`max_decisions` 是 1–10000 的整数，包含最终归还；输入/导出均保留，legacy 不使用这个服务决策预算。工作台的搜索预算区可用小预算复现真实停滞。`failure_report` 汇总阶段、终止码、已完成/未完成门、预算、尝试/遗漏范围以及候选拒绝原因分组。页面弹出遮罩，允许下载输入、诊断、决策与实际 recording，然后返回编辑再编译。

HTTP worker 保存 input、checkpoint、trace、recording、index.html、decisions、failure_report 等。异常/超时由父进程保存输入、最后进度与失败原因；不伪造缺失的最终 checkpoint。取消不作为物理编译失败。固定 1 μs、最高 32×、随机载入/撤销/导入导出保持。

本轮复现：`python examples/validate_adaptive_ez.py`，产物 `artifacts/m4-adaptive-ez`。三种布局的换伙伴线路、4/6/8/16 原子的四条固定 seed 随机混合线路，以及用户原 10 门实例均完成；另有一次真实预算失败。九份计划全部通过不调用 compiler 的独立重放。详情见 [本轮日志](../instruction/logs/2026-09-11-m4-adaptive-ez.md)。下方旧指标属于首版历史，不能当作本轮同平台比较。

## 并发与边界

2026-09-11 最新用户规范：不同 qubit 上同类型单比特门允许并行，异类型门作用区间互斥。`fill_raman` 在只读预测中建立每个原子的稳定可用窗口，结合 DAG 前驱完成时间尽早安排每个 1 μs 脉冲。无关原子的 MOVE/交接不切断窗口，因此多个 Raman 可以同刻开始，也可以跨过 AOD 操作边界。搜索时排除与已安排异类型门脉冲相交的完整 1 μs 区间；若基础服务只有 0.3 μs CZ，独立 Raman 必须等 CZ 结束后安排。纯 Raman 按各 qubit 的依赖形成并行层，在 CZ READY 时重选服务。

之后 `scheduled_program` 重放整个时间表，独立检查依赖、实际 holders、完整轨迹、资源、效果覆盖和终态；Executor 唯一提交。一个 AOD 保持；Raman 改为逐 qubit 寻址资源 `RAMAN:Qxxx`，同时锁目标 atom/trap。取消旧全局 RAMAN_0 / HANDOFF_GUARD，同原子资源冲突与不同门类型的脉冲重叠均被独立验证器拒绝。稳定 SLM / 静止 AOD 及 ≥5 μm 邻距前提、固定 1 μs 和同 qubit 顺序不变。当前门集合与类型并行语义升级到 schema 17，旧 checkpoint 从输入重编译。

共用 viewer 逐 qubit 展示资源行和每个同时执行的脉冲环、门 ID/操作数；“查看门操作”定位真实区间中点，避免落入同时间的中间完成事件。新增工作台预设“同类型并行验收 · 4 H / 1 μs”。仍可任意编辑/随机载入/导入支持的 H/X/Y/Z/T/CZ 线路后实际重编译。

移动搜索改用 `OrthogonalHalfGridPlanner`：横平竖直，主通道坐标为 2.5+5k μm，首末接入段不超过 2.5 μm。空载同样受限；不再尝试斜线直达候选。路径仍逐段通过完整安全校验。本轮证据在 `artifacts/m4-parallel-orthogonal`：4 门 1 μs、两层 8 门 2 μs、两种 layout 的混合线路、真实预算失败及用户原 10 门实例，均独立重放通过；详见 [纠正日志](../instruction/logs/2026-09-11-m4-parallel-orthogonal.md)。

本版采用**滚动的非抢占 AOD 服务段**：运输准备到当前选中门的 effect 为一个承诺段，脉冲后不自动往返。Raman 在段内按完成事件补充；若中途释放了更好的 CZ，不撤销已承诺的 AOD 段。这是当前明确的贪心边界，不是每个物理事件重新做全局搜索，也不承诺最大基数并行集。后续可返修 prepare/effect 提交边界和 live candidate admission，不能修改正在执行的轨迹来抢占。

没有 M3 的「见 READY Raman 就归还 loaded 原子」规则。程序结束时用显式统一 terminal 完成清理；跨 checkpoint 续跑必须传原 terminal，不能把恢复点当成新的初始归还目标。

## M4 触发的 M3 修正

32 原子运行发现：两个 EZ 均驻留，原 SZ 出现置换时，旧 `PersistentTargetCompiler.target` 排除所有最终目标点，导致尚空闲的 SZ 也不能临时停车，退出误报 NO_TERMINAL_CAPACITY。

现在允许空闲的后续目标点作为显式临时停车点。此前已经归位的站点必然被占用，spare 不会选择它；后续目标在遍历时继续修复。装卸和运输都经原 backend/Executor；没有隐藏重排、增加容量或放宽距离。四原子最小反例和原置换测试通过；原始 32 原子失败产物保留，修复后的运行和独立重放通过。

## 验收与复现

本轮最终完整回归 **305 passed、1 warning、514.07 s**（含 13 项新增 M4 检查）；命令和具体证据见 [本轮日志](../instruction/logs/2026-09-11-m4-greedy.md)。

```powershell
python examples/run_m4.py --input configs/workbench/m4_parallel.json --output artifacts/m4-parallel
python examples/run_m4.py --compiler resident --input configs/workbench/m4_parallel.json --output artifacts/m4-parallel-resident
python examples/run_m4.py --compiler returning --input configs/workbench/m4_parallel.json --output artifacts/m4-parallel-returning
python examples/verify_m3.py artifacts/m4-parallel
python examples/run_m4.py --atoms 32 --output artifacts/m4-scale-32-fixed
python -m pytest tests/test_m4.py -q
node tests/m4_workbench_controls.cjs
node tests/m4_controls.cjs
node tests/viewer_speeds.cjs artifacts/m4-parallel/index.html
python examples/render_m4_acceptance.py
```

`verify_m3.py` 名称保留，但 verifier 不调用任何 compiler：直接重放保存的 plans，比较整个 checkpoint，再检查门恰好一次、固定时长、每资源无冲突、装卸与声明终态。CLI 保存 input/family/terminal/run_options/result/decisions/diagnostics/candidate_rejections/recording/checkpoint/trace/index.html；重跑前撤销旧 verification。HTTP worker 另外保存 decisions.json。

同一 4 原子 8 门输入和完整归还：

| 策略 | 总耗时 μs | 逻辑完成 μs | LOAD / OFFLOAD | Raman 重叠 μs |
| --- | ---: | ---: | ---: | ---: |
| M4 greedy | 1084.321356 | 538.610678 | 3 / 3 | 4 |
| M3 resident | 1495.321356 | 940.610678 | 4 / 4 | 3 |
| M3 returning | 3311.164069 | 2756.453391 | 9 / 9 | 2 |

32 原子实际世界、8 门、112 operations、236 commits：全部门和统一终态完成，wall 6099.576826 μs，12 LOAD / 12 OFFLOAD，Raman 重叠 3 μs。不是所有 32 原子都参与运输，也不是密集 64 门性能证明。

保留另一条 6 原子混合线路的贪心反例：greedy 先选局部较快的独立 CZ，占用 EZ 后使后续线路需要更多迁移。同输入及终态：greedy **5699.906975 μs、16 次装卸**；resident **4577.884560 μs、11 次**；returning **4902.918266 μs、12 次**。结果分别在 `artifacts/m4-greedy-fixed`、`m4-mixed-resident`、`m4-mixed-returning`。不能从上述收益样例推广「贪心总比 resident 快」。critical-path/next-use/lookahead 将针对这种承诺和占位代价改进。

静态验收图由真实 input/recording/metrics 生成；离线 viewer 检查连续 Raman、运输重叠、资源跳转和 0.25–32×。编辑器控件替身执行真实前端处理器，通过实际 HTTP 测试放门、编辑 U3、改变原子/layout、编译、随机/撤销/重做、导入导出与决策表。

**真实浏览器视觉验收未通过工具条件**：CUA `nodeRepl.fetch request failed`；Windows 工具读取 Edge 状态时因不能可靠确认 URL 被自动审批中止，之后没有继续浏览器操作。上述机器/静态检查不能替代浏览器截图或 FPS。

本节是首版历史验收；当前 checkpoint 为 schema 17、viewer /2。最新单比特并行模型和真实浏览器验收见下文及 [修正日志](../instruction/logs/2026-09-11-m4-parallel-orthogonal.md)。批量 CZ、多 AOD、测量反馈、保真度模型或 RL 尚未实现。


## EZ 空 SLM 开关与关键帧修正（2026-09-11 后续）

前述表格为 M4 首版验收快照；新增合法直达和开关候选后，应重新编译比较，不把历史成本当作当前算法的固定预期。

GreedyCompiler 的局部 route 现在比较保留当前 supports、关闭直线路径上的空 EZ SLM、关闭所有已开启空 EZ SLM 三种有限策略（重复集合合并），每种尝试直达和有限走廊。空 EZ 关闭为真实 TRAP_SWITCH，成本采用 hardware.switch_duration_us；相同成本优先少关灯。已占用 SLM 不可关闭；卸载时经原 bound handoff 建立目标 SLM 支撑，或在安全静止位置用显式 switch 重开，完整 terminal 继续恢复初始 masks。不是任意子集全局搜索。

候选和 decision_log 增加 switch_operations / ez_switch_operations，工作台显示「空 EZ 关灯次数」。这里统计显式关闭操作；装卸内建立/撤去支撑已包含 transfer 时长，不重复计费。SLM 持有的驻留原子不能通过关灯解除占位。

当时的演示 `python examples/run_ez_switch.py` 生成 artifacts/ez-switch-demo：跨越空 EZ0 时，关灯 1 μs + 直行 20 μs = 21 μs，保留光阱绕行 40 μs；演示显式重新开灯并完整退出，独立 verifier 通过。该成本是旧路径策略的历史结果；当前正交通道约束下，这个几何使用 30 μs 半格路线，开关成本 1/100 μs 均保留已开启 EZ，见 `tests/test_ez_switch.py`。不得继续将旧 21 μs 作为当前预期。

关键帧停住已从最近真实 workbench 记录复现：1059.3106781186546 与 1059.3106781186548 μs 的相邻边界被拉伸成 800 ms，逐帧显示→仿真→显示舍入丢失进度。viewer 在显示层按相对机器精度合并边界，独立累计演示时间；记录、轨迹、物理时长不变。六份保存记录、新编译实例、1×/32×全程与暂停续播检查通过。`examples/debug_workbench_playback.py` 可用当前 viewer 重绘原保存实例，写出来源 SHA256；不会重新编译或改原 recording。服务器每次请求读取当前 viewer bundle，新版本仍需页面重新加载才能应用。

本次最终完整回归 **308 passed、1 warning、613.38 s**。细节见 [后续日志](../instruction/logs/2026-09-11-ez-switch-playback.md)。
