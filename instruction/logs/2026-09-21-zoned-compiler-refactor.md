# 2026-09-21 · QMAP 架构适配与编译器分层重构

- 状态：COMPLETED（架构重构、接入与正确性验收）；QEC 性能优化 OPEN，未达到替换原协议默认策略的标准。
- 用户目标：依据 Search Smarter, Not Harder / QMAP 架构重构整个算法逻辑，保留本地环境及原可编辑工作台。
- 基线：旧 ordered controller 无条件 stage 整片；每批 CZ 归还。工作区有多项既有未提交变更，未回退、未推送。
- 规范：[编译合同](../compiler_contract.md)、[物理/策略边界](../../docs/environment_strategy_boundary.md)、[当前实现](../../docs/zoned_compiler.md)。

## 已实施

- 新 `strategies/zoned` 的 schedule / reuse / placement / routing / landing / codegen / controller；共用动作工具抽到 motion。
- 原 Studio 新默认 `zoned_ids`，保留旧贪心、SMT 和锁定协议；算法独立于示例。
- 并行初态优化 worker 接入新策略，终态合同由外层统一控制。
- 路径生成前检查落点保护与容量；直达构造优先，有限通道后备；实际动作仍由原环境校验。
- 减少无关搬运、加入 EZ 驻留和 terminal 循环换位临时落点。

## 开发中发现并修复

- 首次不可达预测落点忘记声明假设 SLM 支撑开启，修复私有假设，不触碰实时状态。
- 部分矩形的闭包被过早当作完整批次约束，16 原子拆成 2/4 对；改为部分组合允许补全、最终捕获严格校验，新增四轮八对 CZ 回归。
- 逐次最近落点打散原始 QEC 几何，第一次完整协议在 187.93 s 停止、剩余 124 门；失败留在 `artifacts/zoned-compiler/qec-ghz2`。改为下一伙伴变化时优先保留 EZ 工作支撑，开发中间版在 `qec-ghz2-preserve` 完成，但不当作最终版本成绩。
- 新配置默认终态与 placement worker 参数重复，明确由外层拥有终态；stable/fixed 并行 worker 均通过。
- 最终组合搜索版在 `final/qec-ghz2` 的第 81 个完成门后出现 `READOUT_TARGETS_EXHAUSTED`：128 个读出构造均因单侧补齐闲置轴越界而失败。为新控制器读出启用 bounded_spares，最终 `final/qec-ghz2-bounded-readout` 完整通过。失败产物均保留；没有改物理边界或修改门集让案例通过。

## 最终验证

- 109 项相关 Python 回归通过（115.91 s），命令如下。覆盖新控制器、旧路线/策略、配置、并行初态优化两种终态、读出、环境边界。不是全部仓库测试。
- 新编译器测试包括四轮八对真实 CZ、循环换位、测量/复位/条件门、非均匀与不同 layout、失败候选私有隔离、独立重放和 EZ 边缘读出。
- `node tests/ordered_workbench_controls.cjs http://127.0.0.1:58133` PASS：实际 JS handler + HTTP，覆盖手动编译、非均匀轴、切换 SMT、旧配置升级、QEC 锁定与草稿恢复。该项使用 DOM/viewer 替身，另有真实 GUI 验收。
- 真实 Codex 浏览器：鼠标编辑 4 原子 H×4 + CZ×2，6/6 完成、735.382 μs；关键帧与真实时间模式均以 32× 到终点。16 原子新版 32/32 门完成；观察八对红色 CZ 连线、AOD 承载 8 原子，关键帧 32× 到终点。最后停在可编辑原线路及第一批八对 CZ 帧。
- `python tools/check_architecture.py`：198 模块无反向依赖。`git diff --check` 无空白错误（有既存 LF/CRLF 提示）。Demo bundle 再生成 134 文件。
- 证据目录 `artifacts/zoned-compiler/final/`：`summary.json`、`validation.json`、`workbench-controls.log`、`delivery-source.json`。后者记录交付工作区 257 个文件哈希，不冒充已提交 Git 版本，也不追溯冒充开发中旧尝试的源码指纹。

```powershell
python -m pytest tests/test_zoned_compiler.py tests/test_readout_placement_policy.py tests/test_ordered_workbench.py tests/test_studio_config.py tests/test_studio_config_files.py tests/test_studio_placement.py tests/test_environment_boundary.py tests/test_ordered_axis_greedy.py tests/test_axis_hold_routes.py tests/test_ordered_routes.py -q
```

## 同条件比较与负结果

全部以相同输入、平台和 stable 终态比较；两方均完成所有门槽、物理校验、终态校验及各自独立重放。墙钟为单次开发机观测，包含执行器，独立重放另计。

| 案例 | 旧 / 新编译 s | 旧 / 新物理 μs | 判定 |
|---|---:|---:|---|
| sparse20：20 原子 12 门 | 11.41 / 3.85 | 3813.50 / 5131.70 | 只抓必要 8 原子（旧 20）；编译快 66.2%，物理慢 34.6% |
| random20：20 原子 60 门深度 4 | 41.54 / 18.43 | 11255.34 / 12095.96 | 编译快 55.6%，物理慢 7.5% |
| repeated16：16 原子四轮 32 CZ | 8.79 / 10.81 | 1814.57 / 1658.67 | 两版均 [8,8,8,8]；物理快 8.6%，编译慢 23.0% |
| qec-ghz2：34 原子 480 槽 | 194.33 / 186.33 | 23472.44 / 83766.54 | CZ 17→81 批，物理约 3.57 倍，性能验收未通过 |

QEC 当前输入有 127 H、105 CZ、92 X、92 Z、32 MEASURE、32 RESET。条件门槽均正常完成，脉冲仅在条件成立时施加；当前无故障输入为 480 槽，不能混用历史带故障版本的 483 槽。两版量子态均验证逻辑 XX=ZZ=+1、16 稳定子为 +1、prepare/final syndrome 与测量协议完整。测量顺序不同可产生不同报告位和纠正分支，最终合同一致。新版独立重放 145.73 s，旧版 56.25 s。证据 `final/qec-ghz2-bounded-readout/{zoned_ids,ordered_greedy}`；新版后验量子验证另存 `protocol-verification.json`。

```powershell
python examples/compare_zoned_compiler.py configs/workbench/zoned_sparse20.json --output artifacts/zoned-compiler/reproduce/sparse20
python examples/compare_zoned_compiler.py configs/workbench/random20_depth4.json --output artifacts/zoned-compiler/reproduce/random20
python examples/compare_zoned_compiler.py configs/workbench/zoned_repeated16.json --output artifacts/zoned-compiler/reproduce/repeated16
python examples/compare_zoned_compiler.py configs/studio/demos/ordered-qec-ghz2.json --output artifacts/zoned-compiler/reproduce/qec-ghz2 --timeout 300
```

## 交付与下一步

- 原编辑器新版默认算法为 `zoned_ids`；旧有序贪心/SMT 及锁定 QEC demo 保留原策略；初态优化显式可选，非自动触发。
- 可编辑 16 原子入口：`http://127.0.0.1:58133/?job=02d30b83d0bc40edb00564d2c28cdc62`；20 原子按需搬运入口：`http://127.0.0.1:58133/?job=1682ac5e14194285beefc47db573b8f2`。
- 服务 PID37204，启动目录 `artifacts/zoned-compiler/delivery`；`python demo/launch.py` 可重启新的端口。只清理本轮临时调试服务 PID26824，先前用户服务保留。
- ZONED-003 OPEN：便宜落点评分未计准空轴重配/转弯/后继层几何破坏，兼容组失败拆分使 syndrome 碎片化。下一项应在新模块中加入多层驻留代价、结构保持候选与更强兼容分组，用同一 480 槽输入验证物理时间不退化；不要再叠加电路 ID 特判。该项未在本轮冒充完成。
- 千比特性能、作者完整 relaxed routing、跨捕获/卸载宏观重排、全局驻留匹配、任意初始混合 holder 及物理操作时间窗重叠均未宣称实现。

## 边界

没有改动本轮物理模型、关闭安全校验或宣称作者千比特性能。新算法独立适配，不等于 QMAP 所有搜索与 relaxed routing 功能的逐行复刻。暂未提交或推送 GitHub。
