# 2026-09-15 非 RL 发布快照

**2026-09-16 后续更新**：[原通用工作台现已接入新版策略](ordered_workbench.md)，保留自定义原子数/布局/AOD；下文保存上一轮 QEC 实验及发布结果，不代表新版控制器已自动重编的结果。

本次 GitHub main 整理版对应测量落点策略工作台（开发机原入口 8798），在已有环境/策略分离的基础上，收录有序行列贪心、独立 SMT 批次选择、离散正交路线、分轴到位、QEC 物理线路编辑器和测量支撑/落点策略。新增 RL 算法及训练工作不属于本次交付。

## 入口和复现

在完整仓库根目录执行，Python 3.11+；本轮验证使用 Windows / Python 3.12。完整依赖安装：

```sh
python -m pip install -e ".[smt,test]"
python demo/launch.py
```

首页新增“有序 AOD · QEC 编译”。三个编译服务和首页均使用本机回环地址，编译服务自动选择端口；首页冲突时加 `--port 0`。电路默认载入后不编译，点击电路区按钮才执行。最新 [两策略已编译动画](../demo/qec/replays.html) 可直接离线打开，不依赖原电脑的 artifacts 或运行中的服务。

完整重编译、独立物理重放和审计：

```sh
python examples/run_qec_ordered_experiment.py --input demo/qec/reference/input.json --output artifacts/qec-reproduce
python examples/analyze_qec_ordered_experiment.py artifacts/qec-reproduce/qec_ghz2
python examples/run_qec_ordered_experiment.py --serve --port 8798 --output artifacts/qec-reproduce
```

快速回归与入口检查（HTTP 检查会自行启动、关闭独立服务，不影响现有工作台）：

```sh
python tools/check_architecture.py
python tools/check_demo_bundle.py
python tools/check_demo_http.py
python -m pytest tests/test_readout_placement_policy.py tests/test_qec_ordered_comparison.py tests/test_environment_boundary.py tests/test_axis_hold_routes.py tests/test_ordered_routes.py tests/test_ordered_axis_greedy.py -q
node tests/qec_editor.cjs demo/qec/reference/input.json
node tests/qec_axis_hold_replay.cjs demo/qec/reference
```

末两项需要 Node.js，使用离线 DOM/Canvas 替身，不是真实浏览器。完整案例可能需要数分钟。每个策略是独立工作进程，执行后再独立重放；物理时间（μs）与编译/验证墙钟时间（s）分开统计。编辑电路失败会留下执行前缀和原因；预算耗尽、SMT UNKNOWN 或有限路线失败不能解释为物理无解。

`examples/run_ordered_axis_experiment.py` 是较小的有序轴对照入口。`examples/check_q000_axis_hold.py` 和 `examples/audit_readout_policy.py` 是历史问题定位脚本，默认需要未纳入 Git 的原始 checkpoint，不能当新克隆的快速开始；对应结论、快照路径和参数见各专题报告。完整新案例可由上方命令重建，不依赖这些历史取证脚本。

## 分层与所有权

| 层 | 入口 | 职责 |
| --- | --- | --- |
| 环境 | `neutral_atom_env` | 实际支撑、全部活动行列交点、序关系、连续路径校验、操作事件、量子测量和恢复；唯一状态提交者 |
| CZ 策略 | `scheduling/ordered_greedy.py`、`smt_ordered.py` | 从当前就绪门构造有序轴批次；贪心保留基线候选，SMT 独立构造约束 |
| 测量策略 | `scheduling/readout_placement.py` | 选择 AOD/SLM 支撑与目标，低成本排序；少量完整路线实现后按实际成本反馈选择 |
| movement | `motion/ordered_routes.py`、`axis_hold_routes.py`、`ordered_transfer.py` | 达到上层指定目标；占据格预筛选、轴保持路线、物理验证；不自行决定测量地点 |
| 实验协议 | `neutral_atom_experiments/qec_ordered_comparison.py` | 两块 surface-code GHZ 电路、布局、噪声声明、协议和终态验收 |
| 控制与界面 | `neutral_atom_app/smt_experiment.py`、`visualization/qec_*` | 组装策略、手动编译、作业隔离、失败反馈、编辑/结果展示 |

所有策略路径相对于 `src/neutral_atom_strategies/`。完整依赖合同见 [环境/策略边界](environment_strategy_boundary.md)；后端限制不是策略搜索能力的证明。

## 哪些固定，哪些可配置，哪些由编译计算

| 项目 | 当前处理 |
| --- | --- |
| QEC demo 线路/布局 | 协议生成器提供 34 原子、483 槽模板；当前平台固定，编辑线路仍可用相同平台编译。不是任意原子数/布局的通用 QEC 编译器 |
| 物理 gate | QEC 为 Clifford H/X/Y/Z/CZ + MEASURE/RESET/条件槽；普通工作台另支持 T；修改为其他电路后，不能用 GHZ 协议断言冒充通用正确性 |
| 硬件 AOD | 行数×列数派生容量；坐标 offsets 是相对首轴的偏移。QEC 平台 7×14，序关系和活动交点由环境检查 |
| 后端和路由 | 后端 `row_column` / `row_column_orthogonal` 与策略路由 `axis_hold` / `legacy_corridor` 独立配置；正交后端只规定单原语改变一组轴 |
| 测量候选 | 用户选 adaptive / aod_only / slm_only，预算默认 16 个目标、3 个合法计划；默认值读取 [配置](../configs/strategies/readout_placement.json) |
| 测量落点与路线 | 编译生成有序目标候选，先估价，再计算有限路线并比较实际完整服务时间；不固定“首个合法者胜出” |
| CZ 门批次、配对方向、轴间距 | 策略根据当前门前沿和有序轴约束构造；CZ 实际作用对由环境复核 |
| CZ 服务组织 | 当前仍每批归还源 SLM、完整服务串行；测量服务也返回源位。这些是现行控制策略限制，不是硬件要求 |
| 运动与打光 | 当前 2.5 μm 离散路线族；同向直行合并，转弯或反向保持停点。单比特 1 μs 为固定项目参数，不提供 UI 可选项 |
| 回放与统计 | 从真实执行记录派生；速度上限 32× 仅改变显示；逐原子累计距离、装卸、门、等待由独立统计模块汇总 |

各实验支持的算法范围不同，旧工作台不会因研究策略新增而自动获得任意二维能力。研究用策略不混入通用菜单。测量策略通过 `readout_service(..., placement_policy=...)` 注入，未注入的历史调用仍走旧 SLM 流程。

## 保存的完整对比结果

这是前一轮完整物理编译的证据，本次只整理/导出，没有重新编译这条 483 槽电路。仓库提供 [原始对比](../demo/qec/reference/comparison.json)、[分析](../demo/qec/reference/analysis.json) 及两份动画/CSV，文件哈希由 [demo manifest](../demo/manifest.json) 管理。

| 指标 | 有序贪心 | SMT 当前最大批次 |
| --- | ---: | ---: |
| 总物理时间 / μs | 24337.380746 | 24975.219036 |
| CZ 批数 / 最大并行对数 | 17 / 9 | 17 / 9 |
| LOAD / OFFLOAD 操作次数 | 27 / 27 | 27 / 27 |
| 所有原子累计路程 / μm | 13252 | 13270 |
| 编译墙钟 / s | 238.184 | 179.990 |
| 独立重放墙钟 / s | 108.228 | 113.484 |

两个结果均 8 次测量服务选择 AOD；相对旧测量策略各减少 3653.086159 μs。66 计划独立重放、checkpoint 逐字一致、483 效果各一次和终态验证通过，逻辑 XX/ZZ、16 个码稳定子和完整测量协议通过。9 对 transversal CNOT 对应的 CZ 在同一批；不是把显示相邻的条件 X/Z 槽都当实际打光。

开发机当时还有其他验证负载，墙钟不是隔离性能基准。SMT 在本例并未减少 CZ 批数，完整物理时间更长；不能宣称 SMT 普遍优于贪心。

## 已知边界与后续工作

- 路线、目标、beam 和 SMT 模型搜索均有预算；不是完备的高维最短路或全电路最优搜索。
- 整体进 EZ、串行完整服务、每批归还和测量后归还仍是预设组织规则；跨批驻留和全局并发待进一步策略化。
- 稳定 AOD 测量复用当前理想非破坏测量模型；未验证真实设备光学串扰、加热、损失和全电路噪声容错。
- 最新编辑器及动画完成 HTTP 和离线 DOM/Canvas 检查；浏览器连接故障使真实 GUI 验收仍待补齐。上一版真实浏览器成绩不能替代这一项。
- 本轮回归、打包和新克隆检查见 [发布日志](../instruction/logs/2026-09-15-stable-release.md)。环境边界和物理约束不因发布而放宽。

专题报告：[有序贪心](ordered_axis_greedy.md)、[离散路线](ordered_routes_v2.md)、[QEC/SMT](qec_ordered_smt_comparison.md)、[分轴到位修复](axis_hold_strategy_fix.md)、[测量落点策略](readout_placement_policy.md)。
