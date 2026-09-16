# 通用工作台接入有序 AOD 策略 · 2026-09-16

本轮不是重定向到固定 34 原子实验页。`demo/workbench/` 继续使用 Atom Studio 的原子数、布局、AOD 配置、随机载入、门编辑、配置保存和手动编译流程；生产调用新增 `ordered_controller.run_ordered(env)`，复用已有有序贪心/SMT、axis-hold、占据格预筛选及测量目标策略。

## 使用

```sh
python -m pip install -e ".[smt]"
python demo/launch.py
```

首页“可编辑线路工作台”仍是原入口。新建自定义草稿默认选择 `ordered_greedy`、`row_column_orthogonal`、4 原子网格与 2×2 AOD；这些是可修改的初始值，不是固定协议。旧文件保留显式算法/硬件，不自动升级或改写历史结果。此前启动的服务须重新启动才能载入新 Python 内核；只刷新旧 8797 页面不能升级其后端。

- **初态**：1–128 原子；row/grid/shuffled、seed 沿用原工作台。门集 H/X/Y/Z/T/CZ。
- **平台**：1–128 AOD 交点，行数×列数派生容量；x/y 偏移仍相对于首轴，允许非均匀间隔。新增 row_column / row_column_orthogonal 下拉框，rigid 继续保留。
- **算法**：新增有序轴贪心与 SMT 当前批次；旧 greedy/basic/critical_path/lookahead 和单原子 returning/resident 仍在目录。切换算法不修改电路、原子数、布局、相对偏移或后端。
- **能力不匹配**：有序策略需有序行列后端；旧策略仍需 rigid，旧 M4 多交点仍限单行 10 μm。预览显示原因、编译禁用，直接提交也拒绝；不会静默回落成旧内核。
- **配置往返**：backend 属于平台；beam/实际候选/路线/SMT 模型预算、motion_router 和读出选项属于编译配置。两类独立保存和导出。
- **QEC**：顶部新增“当前有序轴与测量策略”完整 demo，保留原来几种协议 demo。新版 demo 在原工作台执行，配套线路/平台锁定；返回自定义恢复自己的草稿。普通自定义不隐式获得 Clifford 测量态或 GHZ 协议。

## 控制与分层

```text
原工作台输入 / 配置
  → validate_input + 用户布局生成（无固定实验工厂替换）
  → configured_strategy → 通用 Ordered Controller
  → 同类型 READY 1Q / OrderedAxisGreedy 或 SMTOrderedAxisPlanner / ReadoutPlacementPolicy
  → OrderedTransfer / axis-hold / 完整物理计划校验
  → NeutralAtomEnv.submit / run → 原有 recorder、逐原子统计与回放
```

`src/neutral_atom_strategies/scheduling/ordered_controller.py` 只接收已有 env，无 experiments 导入、GHZ 门编号或固定原子数。需要 CZ 时，将实际输入布局平移到现有 EZ 空 SLM，再按真实捕获闭包/行列容量分批运输；容不下整组时尝试更小组及单原子。这里只是候选策略，仍逐段检查实际物理规则。仅单比特或空线路无需先搬进 EZ。

有序硬件对应的平台生成器预留实际布局的 EZ 高度及空闲容量轴边界；几何只由平台/初态输入决定，不因选贪心或 SMT 而改变。rigid 旧输入保留既有几何。两种新版策略共用目标、路线、测量和终态逻辑，并分别构造 CZ 批次。

所有操作经环境执行；失败保留已执行前缀和 `DECISION_LIMIT` / 搜索耗尽 / 超时等结构化诊断。结果 `input.compilation_backend.kernel=ordered-axis-readout-v1`、run_options 和每条 decision 的 strategy/backend/motion_router 明确实际实现。旧策略不会带此新内核标识。

## 边界

- 任意原子数/布局在工作台既有输入范围内可编辑配置，不承诺有限候选能完成任意电路。EZ 容量、共享轴闭包、实际扫掠及预算仍可能拒绝。
- 当前有序控制器每批 CZ 归还、测量后归还，完整服务串行；不等于旧驻留型贪心的严格超集，不能保证总时间更短。
- 新版普通线路可用 T，但不跟踪完整量子态；QEC demo 使用原 Clifford 量子核，不能加入 T 冒充 QEC 验证。
- 原环境物理代码未改，不放宽距离、序关系、捕获、SLM 开关或光作用条件；未接入新增 RL 算法。
- 本轮浏览器工具仍报告 `nodeRepl.fetch request failed`；HTTP 与实际 JS 事件的 DOM/Canvas 替身检查不代表真实 GUI 检查。完整本轮结果见 [日志](../instruction/logs/2026-09-16-current-workbench.md)。

## 完整 demo 核验

当前 demo 沿用原单轮 QEC 的 480 槽电路（无额外故障注入），并改用新控制器；不是上一轮 483 槽 Y(Q013) 对照。完整执行 24335.380746 μs、64 计划、17 批 CZ（最大 9 对），27 次 LOAD / 27 次 OFFLOAD。逻辑 XX/ZZ、16 码稳定子、测量协议均通过，64 计划独立重放 checkpoint 逐字一致。编译 184.524 s、独立重放 57.480 s；不是隔离性能基准。

```sh
python examples/verify_ordered_workbench.py --output artifacts/ordered-workbench-qec
```

## 检查入口

```sh
python -m pytest tests/test_ordered_workbench.py tests/test_studio_config.py tests/test_studio_config_files.py tests/test_workbench_compilation_config.py tests/test_environment_boundary.py -q
python tools/check_architecture.py
python tools/build_demo_bundle.py
python tools/check_demo_bundle.py
python tools/check_demo_http.py
# 把端口替换为 demo/launch.py 输出的 workbench 地址
node tests/ordered_workbench_controls.cjs http://127.0.0.1:PORT/
```
