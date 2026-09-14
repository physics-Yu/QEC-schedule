# M4 同平台策略验收

本页对应 `examples/validate_m4_complete.py`，用于比较 basic、greedy、critical_path、有限 lookahead。验收范围是单台、单 trap、adaptive EZ 的有限线路族；不要求全局最优，也不将批量 CZ、多 AOD 或 RL 计入 M4。

## 可复现入口

```powershell
python examples/validate_m4_complete.py --output artifacts/m4-complete-final
python -m pytest tests/test_m4_acceptance.py -q
python examples/verify_m3.py artifacts/m4-complete-final/reuse/lookahead
```

默认比较 `parallel`、`reuse`、`critical_branch`、`critical_priority`、`occupancy` 五种输入，每种执行四个策略。可用 `--cases`、`--strategies` 选择子集，`--site-limit`、`--beam-width`、`--rollout-budget` 改变明确的搜索预算。子集结果不等于完整矩阵。

每个策略从同一输入构造初态，比较初始完整 snapshot SHA256 与 terminal SHA256。硬件、SLM 候选网格、碰撞条件、5 μm Raman 邻距、门集和终态完全相同；basic 也使用当前 GreedyCompiler 的局部物理候选，在每次门服务后显式归还。这里不是拿旧 M3 路线与新 M4 路线混合比较。

主指标为包含完整原始 holders、AOD axes 与 masks 恢复的总完成时间；另报逻辑完成时间、LOAD/OFFLOAD、AOD 与原子路程、按资源占用区间计算的利用率、候选数、遗漏数量、实际搜索节点、预算触顶和编译墙钟时间。Raman 各目标资源分列，多个资源利用率不相加冒充总利用率。

## 独立核验

每行保存 input、terminal、run_options、checkpoint、trace、recording、decisions、diagnostics、candidate_rejections、failure_report、comparison 和共用 viewer HTML。`verify_m3.py` 不调用策略或 compiler，重放实际保存的 plans，检查 checkpoint 一致、门恰好一次、物理验证、时长、资源冲突、装卸数量及终态。

- `parallel`：四个独立 H 必须在同一个 1 μs 完成，不需运输。
- `reuse`：同一 pair 三次 CZ，展示保留原子相对每门归还的实际收益。
- `critical_branch`：独立分支与后续混合门链竞争，记录不同选择的收益或代价。
- `critical_priority`：较便宜的独立 CZ 与较贵的长依赖链竞争，核对 greedy 与 critical_path 的首选门确实不同，不以策略名称不同冒充行为不同。
- `occupancy`：六原子换伙伴和独立 pair，保留贪心或前瞻变慢的反例，不能只发布赢的线路。
- `budget_failure`：lookahead 的 max_decisions=1，必须真实停滞并保留已经执行的门和诊断，仍通过已提交计划的独立重放。
- `terminal_witness`：同一 CZ 的两候选均移动 98 μm、耗时 496.3 μs，分别把 Q000 留在 EZ_0_25 / EZ_15_25；下一 CZ 服务相差 10 μs。两条路径都执行完整线路和相同终态，并单独重放。这说明仅比较当前路程不足以判断后续成本。

## 当前轮结果

本轮 `python -m pytest tests/test_m4_acceptance.py -q`：**4 passed，58.87 s**，包括四策略实际 1 μs 并行、拒绝不同初态/终态的比较、两条等距候选完整执行和独立重放。机器验收和真实浏览器验收分别记录，本页不冒充浏览器验收。

**20 行全部完成线路和统一终态，并独立 replay verified。** 下表为包含完整退出的总时长，单位 μs：

| 输入 | basic | greedy | critical_path | lookahead |
| --- | ---: | ---: | ---: | ---: |
| parallel，4 H | 1.0 | 1.0 | 1.0 | 1.0 |
| reuse，重复 pair | 2856.9 | 952.9 | 953.9 | 952.9 |
| critical_branch | 2956.9 | 3023.9 | 2398.9 | 2078.9 |
| critical_priority | 3056.9 | 2383.9 | 2335.9 | 2035.9 |
| occupancy，6 原子 | 4229.2 | 4158.2 | 3869.2 | 3578.2 |

重复 pair 的 LOAD/OFFLOAD 从 basic 的 9/9 降到 greedy/lookahead 的 3/3。critical_branch 保留了明确反例：greedy 比 basic 慢 67 μs；CP 和 lookahead 分别比 greedy 少 625 / 945 μs，对应 LOAD 9 → 7 / 6。critical_priority 的 greedy 首选 G000，CP 首选更长依赖链的 G001，已独立断言实际决策不同。CP 在 reuse 上比 greedy 多 1 μs，原因是先处理独立 H，失去了与运输重叠的机会；不能把关键路径视为必胜策略。本矩阵没有出现 lookahead 比其余策略更慢的案例，也没有据此宣称其普遍占优。

lookahead 五个案例实际编译墙钟为 **0.84 / 33.50 / 167.81 / 87.37 / 151.20 s**，搜索节点累计为 **2 / 18 / 34 / 26 / 39**，每次决策预算仍为 8。部分 CLI 成功案例超过工作台 90 s 交互预算；这是公开的性能限制，不能把离线成功描述成同预算 HTTP 成功。全部策略的逐行编译时间、候选/遗漏计数、距离和资源利用率保留在各 `comparison.json` 与总 `acceptance.json`。

预算失败保留 **2/4 门、476.3 μs、14 operations、2 LOAD / 1 OFFLOAD**，独立重放通过；没有把逻辑部分完成当作终态完成。两条等距终态见证的完整总时长分别 **1684.6 / 1654.6 μs**。矩阵 20 条、主预算失败 1 条、终态见证 2 条、最终诊断见证 2 条，共 **25 份实际执行记录**分别独立核验。

`artifacts/m4-complete-final/acceptance.json` 保存 Python **3.12.1**、实际参数与编译进程开始时源码指纹 `e8b7fa24d7d8bba531329a53b530e4dbbea75947d82b077e19cc9fc58f160c44`。编译时间是当前主机实际墙钟记录，运行期间存在其他开发验证进程，不能把它当作隔离硬件的性能测量；物理 makespan 来自实际执行时间表，不受主机竞争影响。

矩阵运行期间发现并修正了两类诊断问题：达到节点上限不一定真的遗漏分支；所有根候选失败时要保留完整搜索报告。该补丁只改变报告与异常携带，不改变候选、评分、排序、配额或执行计划。物理矩阵保留其编译版本，manifest 的 `source_changed_during_run` 如实为 true；不将它描述成全部由最终诊断版本重新编译。最终代码已对 `critical_branch/lookahead` 独立重放，5 门 / 65 operations / 2078.9 μs 一致。最终预算诊断另外保存在 `diagnostics-final/acceptance.json`，带自己的源码指纹：单 H 搜索恰好 1 节点完成，`limit_reached=true` 而 `budget_exhausted=false`；另一真实 1 节点截断搜索遗漏 2 个根，`budget_exhausted=true`，保留 1 个已执行门，二者都通过独立重放。全部根失败由策略专项回归核验，详见本轮交接日志。

早期 generator 导出的 input 漏写 `ready_limit/site_limit`，现已修正生成器，并按保存的 run_options 同步既有 input 元数据，记录在 `export_metadata_correction.json`。最终逐一检查 **23 份策略输入**（20 行矩阵、主预算失败和 2 条最终诊断），包括最后生成的 budget_failure，预算均与 run_options 一致。该同步不改 checkpoint、trace、recording、物理时钟或执行结果；用于保证下载输入后在编辑器里使用实际的搜索预算。

## 有限搜索边界

默认 max_decisions=100、site_limit=1、ready_limit=8、lookahead_depth=2、beam_width=2、每次决策 rollout_budget=8。前瞻只对有限分支执行真实推演，使用实际已搜索时长、实际终态清理和未搜后续门的 pulse critical-path 下界评分；未搜索运输成本没有被假装为精确预测。深度、候选遗漏及 horizon_complete 都在 decisions 中公开。更大搜索预算不保证单调改善所有线路；需要重新比较执行成本和编译耗时。

任何“完成”仅指声明的 M4 策略和验收范围，并不意味着任意 32 原子/64 门都可在交互预算内编译，也不意味着已找到最大并行集或全局最短调度。
