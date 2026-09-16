# QEC Schedule

**把量子线路编译成可执行、可检查、可回放的中性原子操作序列。**

QEC Schedule 是一个面向中性原子量子计算的调度研究平台。输入物理量子线路、原子布局、硬件配置和终态要求，编译器安排 AOD 捕获与运输、SLM 开关、量子门和测量；环境检查约束并执行，浏览器展示完整过程和统计结果。

项目要解决的是：**在相同物理约束下，如何让更多门并行、减少运输和等待，缩短整条电路的完成时间？** 实验环境与编译策略分离，便于在同一平台比较简单基线、贪心、有限前瞻和 SMT 等方法。

**当前通用工作台更新：2026-09-16（非 RL）**。原工作台已接入有序轴贪心/SMT，保留自定义原子数、布局和 AOD 配置；[接入说明](docs/ordered_workbench.md)。

**前次整理版：2026-09-15**。新增有序 AOD 贪心/SMT、分轴到位与离散避障、测量支撑/落点策略和可编辑 QEC 对照。见 [版本说明、配置归属与限制](docs/current_version.md)；[最新两份完整动画](demo/qec/replays.html) 已随仓库保存。

## 先体验

主要演示集中在 **[demo/](demo/README.md)**，无需从大量开发产物中寻找入口。

| 演示 | 可以了解什么 | 使用方式 |
| --- | --- | --- |
| **可编辑线路工作台** | 设置原子与 AOD、放置门、手动编译、回放、逐原子统计 | 启动下方服务，从首页进入 |
| **贪心 / SMT 对照实验** | 相同输入下，候选组合与多阶段决策如何影响并行和总时间；支持编辑重编译 | 启动服务，或[直接看已编译结果](demo/smt/replays.html) |
| **有序 AOD · 两逻辑 QEC 对照** | 编辑含测量/条件门的线路，比较贪心与 SMT；自动选择 AOD/SLM 测量支撑与落点 | 启动首页，或[直接播放两份完整动画](demo/qec/replays.html) |
| **四逻辑 GHZ 完整 QEC 回放** | 数据与辅助原子、稳定子测量、条件恢复和完整运输过程 | [下载后直接打开动画](demo/ghz4/animation.html)，约 41 MB，无需重编译 |

GitHub 文件预览不会执行 HTML。请下载完整仓库或克隆后在本地运行；离线动画可直接用浏览器打开。

## 快速开始

需要 **Python 3.11+** 和现代浏览器。启动脚本使用 Windows、macOS、Linux 通用的路径与进程接口；当前实机验收环境为 Windows / Python 3.12 / Edge，其他系统尚未实机验收。

```sh
git clone https://github.com/physics-Yu/QEC-schedule.git
cd QEC-schedule
python -m venv .venv
```

激活环境：

- Windows PowerShell：`.venv\Scripts\Activate.ps1`
- macOS / Linux：`source .venv/bin/activate`（创建环境时可使用 `python3`）

```sh
python -m pip install -e ".[smt]"
python demo/launch.py
```

浏览器会打开 Demo 首页。建议先试工作台中的“四原子 H 并行”，再看 SMT 的“矩形闭包”案例。保持终端打开，Ctrl+C 退出；端口冲突时用 `python demo/launch.py --port 0`。

**HTML 负责编辑与回放，Python 负责真实编译。** 保存动画无需 Python；编辑后重编译需要本地服务。页面不会自动编译，只有电路区域按钮会提交任务。新结果写入 `artifacts/demo-runs/`，不会覆盖参考数据。详见 [Demo 使用说明](demo/README.md)。

## 目前已经实现什么

| 层次 | 已实现能力 | 当前边界 |
| --- | --- | --- |
| 物理环境 | SLM/AOD 支撑、行列交点与开关、装卸、连续运动碰撞检查、门作用对检查、事件执行、终态验证 | 离散几何与事件模型，不模拟光场、波包或设备保真度 |
| 线路与控制 | DAG、H/X/Y/Z/T/CZ、同类型单比特门并行、持久状态、操作资源与计划提交 | 逻辑就绪不等于物理可执行，策略支持的平台族不同 |
| 编译与规划 | 单原子基线、驻留复用、贪心/关键路径/有限前瞻、正交通道 A*、专用二维批运输 | 尚未统一为任意布局、任意 AOD 形状的通用高效规划器 |
| SMT 实验 | 联合选择门、移动侧、位移和矩形捕获组合；单步及小规模多阶段比较 | 2–16 原子、最多 16 个无条件门；固定 EZ/10 μm、刚性 AOD、每批归还；未证明物理总时间最优 |
| 有序 AOD 研究 | 有序行列合批、独立 SMT、2.5 μm 离散路线、分轴到位、测量目标策略 | 有限候选和固定平台；仍每批归还，完整服务串行 |
| QEC 实验 | 两/四逻辑 surface-code GHZ，辅助原子、测量/reset、重复稳定子读出、声明故障下条件恢复 | 专用布局/协议，Clifford 量子态，QEC 不支持 T；不是全电路噪声容错证明 |
| 可视化与审计 | 编辑线路、失败诊断、最高 32× 回放、checkpoint、独立重放；逐原子路程/装卸/门/等待统计 | 普通模式不追踪完整量子态；动画显示已执行记录，不能单凭画面证明正确 |

AOD trap 来自**活动行坐标 × 活动列坐标**，空交点也参与校验。配置 offsets 为相对首行/首列偏移，再叠加阵列整体位置。环境可表达非均匀轴与行列重构，但不代表所有规划器支持动态变距；工作台区分硬件表达能力与策略支持范围。

距离和耗时是本项目的明确假设，例如单比特操作固定 1 μs，并非真实硬件的普适常量。约束与来源见 [物理模型](instruction/physics.md)、[AOD 后端](instruction/aod_backends.md)。

## 怎样理解策略与结果

自定义线路使用通用策略；GHZ/QEC 专用算法只随完整 demo 提供。电路示例只替换线路，平台与编译配置分别管理，避免把特定电路预编排当通用能力。见 [配置分层](docs/studio_configuration_layers.md)、[配置文件](configs/studio/workbench.json)。

早期刚性 AOD / 小电路 SMT 对照保持相同初态、AOD、物理校验和终态（与当前有序 QEC 实验分别统计）：

| 总物理时间 / μs | 二维分组贪心 | 单步 SMT | 多阶段 SMT |
| --- | ---: | ---: | ---: |
| 简单并行 | 333.3 | 333.3 | 333.3 |
| 矩形捕获闭包 | 1366.9 | 984.6 | 874.6 |
| 交叉配对与依赖 | 1521.5 | 1521.5 | 1279.2 |
| 混合门与依赖 | 337.3 | 337.3 | 337.3 |

联合搜索能找到现有启发式遗漏的合法组合，多阶段能保留后续合批机会；**SMT 并非对所有电路都更好或编译更快**。这是保存的正式实验，不是普遍性能保证。合同、编译耗时、复测差异及失败反馈见 [实验报告](docs/smt_batch_experiment.md)。

完整 GHZ 回放与当前模板各自保留输入：模板后来做过等价 HH 化简，历史动画不会被标为新编译结果。横向逻辑 CNOT 与条件槽语义见 [电路核验](docs/demo_circuit_audit.md)，QEC 成果与限制见 [四逻辑验收](docs/qec_temporal_four_acceptance.md)。

## 程序如何组织

```text
物理线路 + 平台/初态 + 终态要求
            ↓
外部策略：依赖分析 → 候选/路由 → 调度决策
            ↓
NeutralAtomEnv：检查计划 → 提交操作 → 推进事件
            ↓
状态 / trace / checkpoint / 指标 → 共用可视化回放
```

| 目录 | 职责 |
| --- | --- |
| `src/neutral_atom_env/` | 实验环境、硬件规则、执行、恢复、只读观测；不导入外部策略 |
| `src/neutral_atom_strategies/` | 可替换规划、路由、调度、SMT |
| `src/neutral_atom_app/` | 配置、控制程序、HTTP 服务、编辑器 |
| `src/neutral_atom_experiments/` | GHZ/QEC 协议、对照实验、验收工具 |
| `configs/` | 平台、显示、策略预设、demo 电路 |
| `demo/` | 精选入口、可移植 HTML/JS、已编译参考结果 |
| `tests/`、`tools/` | 测试、架构检查、电路审计、演示导出 |
| `docs/` | 接口、实验合同、结果分析 |
| `artifacts/` | 本地运行与开发证据，不随 Git 提交，不作为新用户入口 |

开发接口见 [环境/策略边界](docs/environment_strategy_boundary.md)、[源码导航](src/README.md)。只有环境执行器提交实时状态，策略与渲染器不直接修改实验状态。

## 开发与复现

```sh
python -m pip install -e ".[smt,test]"
python tools/check_architecture.py
python -m pytest tests/test_environment_boundary.py tests/test_smt_batch.py
python examples/run_smt_experiment.py --output artifacts/smt-reproduce
```

运行 `python tools/build_demo_bundle.py` 刷新对外 UI 与文件哈希，`python tools/check_demo_bundle.py` 检查导出完整性。新克隆包含参考结果，无需旧 artifacts；详见 [维护说明](demo/README.md) 和 [本轮交付核验](docs/demo_delivery_validation.md)。完整测试与大型 QEC 编译可能耗时较长，各报告区分逻辑验证、物理执行、独立重放、浏览器验收。

后续重点是减少候选遗漏、复用 SMT 模型、引入有预算的多阶段决策，并扩大通用二维/AOD 规划范围。本次发布聚焦非 RL 编译与物理平台，新增 RL 算法和训练工作未纳入本次交付。
