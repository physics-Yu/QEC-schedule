# 2026-09-16 · 原通用 Demo 工作台接入新版策略

- 状态：COMPLETED
- 用户目标：新版策略接入原通用工作台，保留任意原子数、布局和原有配置；不是切换到固定 QEC 入口。
- 根因：上轮 `demo/launch.py` 的 workbench 仍指向 rigid M3/M4 调度，新版为独立 QEC 实验入口；实查旧 8797 catalog 无 readout_policy，8798 有 adaptive 配置。
- 相关规范：agent.md、instruction/compiler_contract.md、docs/studio_configuration_layers.md。

## 实现

- 新增 `neutral_atom_strategies/scheduling/ordered_controller.py`，直接接收用户平台的 env，无 experiments/GHZ 工厂或固定原子编号。实际选择 OrderedAxisGreedy / SMTOrderedAxisPlanner，复用 OrderedTransfer、axis-hold、占据格避障及 ReadoutPlacementPolicy。
- 泛化初始 EZ 平移与分组运输：按捕获闭包、行列容量、实际路径校验拆组，支持 AOD 小于原子数量；只含单比特或空电路不先运输。
- 原 Studio 的 1–128 原子、row/grid/shuffled、seed、非均匀相对偏移、HXYZTCZ、随机载入、独立平台/编译配置、手动编译均保留。新草稿默认 ordered_greedy + row_column_orthogonal + 2×2 AOD；旧导入不隐式迁移。
- 硬件后端与算法分别选择；旧算法仍保留 rigid/原几何限制，组合不兼容时在前端和服务端报告，不能偷偷回退。旧 M4 beam 上限 32 与新版上限 512 分开，保留旧 SEARCH_LIMITS 合同。
- 新增当前有序策略 QEC demo，沿用原单轮 480 槽无附加故障电路，完整配方锁定；原协议 demo 保留。普通自定义不暗中进入 Clifford QEC 模式。
- 刷新 demo 导出、manifest、配置和版本说明。结果含实际 compiler、aod_backend、`ordered-axis-readout-v1` 标识及决策日志。
- 物理环境源文件没有修改；本轮不涉及 RL 文件。

## 验证与失败记录

1. 145 项相关 Python 回归：合并轮 144 通过/1 失败；问题是旧全预算 fixture 使用共享 SEARCH_LIMITS，暴露旧/新 beam 上限常量混用。分离常量后，37 项涉及旧大输入/预算/目录的补验全通过；其余项目此前通过。最初两项配置失败（demo 重复 compiler 镜像、测试切换单 trap 算法时仍使用新 2×2 平台）已在源配置和 fixture 修复并通过。
2. `tests/ordered_workbench_controls.cjs` 使用实际维护 JS 事件 + HTTP worker：6 原子 shuffled、1×3 AOD、列偏移 [0,15,35]，放入 CZ 后分别真实编译贪心/SMT，门/布局/偏移保持；无自动编译；旧硬件组合拒绝；新版 QEC demo 锁定与自定义草稿恢复通过。首次测试宿主缺 location，补齐浏览器全局后通过。它使用 DOM/viewer 替身，不是浏览器渲染验收。
3. 完整两逻辑 demo 480 槽、64 计划、24335.380746 μs；105 CZ、32 MEASURE、32 RESET；逻辑 XX/ZZ、16 稳定子、测量协议通过，全部计划独立重放 checkpoint 逐字一致。编译 184.524 s，重放 57.480 s。不是上一轮 483 槽故障案例，也不是隔离性能对比。
4. 架构检查 0 违规；包含另一个任务未提交 RL 的工作区共 161 模块。本轮非 RL 新增通用策略模块，环境保持纯模拟职责。
5. Demo 导出 132 文件，完整性、哈希、链接、HTTP 10 项入口检查通过。Node 语法检查与 git diff --check 通过。
6. 中间测试服务发生新旧 Python 模块混载 ImportError（服务启动后仍改了预算常量）；重启本轮独立服务后最终 HTTP/实际 JS 验收通过。没有修改用户原 8797/8798 服务。
7. CUA 浏览器连接仍为 `nodeRepl.fetch request failed`，真实 GUI 验收未完成；没有用 HTTP 或替身冒充。

## 交付与复现

当前服务 PID 36940：工作台 `http://127.0.0.1:63791/`，Demo 首页 `http://127.0.0.1:63794/`。端口为本次自动分配，其他电脑运行 `python demo/launch.py` 获取自己的地址。

已编译新内核实例：`?job=8b98c4f10f154241ae11c6b32ca6cf06`（贪心）、`?job=82f9d869427b41d8ac060f870eebade1`（SMT），各5门，2660.80505 μs；两者 input 中实际标识 `ordered-axis-readout-v1`。新结果在 `artifacts/ordered-workbench-delivery/verified-runs/workbench/`。

完整 QEC 证据 `artifacts/ordered-workbench-delivery/full-qec/`，重新生成运行 `python examples/verify_ordered_workbench.py`。其余命令、配置归属与边界见 [接入说明](../../docs/ordered_workbench.md)。不依赖本机旧 artifacts 即可启动/重新编译。

## 未完成与边界

不是完备路径搜索：所有目标和路线仍有界，原子/交点最多128不等于每种输入必定编译成功。新版仍整组准备 EZ、每批归还、完整服务串行；旧驻留型算法保持独立价值。下一步优化跨批复用和规划开销，不放宽物理约束。真实浏览器验收待连接恢复后补做。
