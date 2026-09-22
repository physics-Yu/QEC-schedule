# QEC Schedule

**将量子线路编译为可检查、可执行、可回放的中性原子操作。**

输入电路、平台、初态和终态要求，策略选择门批次、原子落点、AOD 抓取与路径；环境检查支撑、连续运动、作用对及时间约束，Executor 推进状态，共用工作台展示完整过程和逐原子统计。研究目标是在明确的物理模型与相同实验合同下减少运输、等待和完成时间。

**当前整理：2026-09-22。** 覆盖可编辑工作台、Parking、初态优化、有序贪心/SMT、本地分层驻留、QMAP 原生接入、ZAC 对照、交互 IR，以及隔离的 RL/大规模原生实验。当前自定义默认是 `qmap_native`；研究模块的范围分别说明，不代表全部算法或 QEC 优化已完成。

- [当前版本、能力与限制](docs/current_version.md)
- [整体架构与可复用模块](docs/general_framework_summary.md)
- [当前交接及下一步](instruction/handoff.md) · [本次整理与验证记录](instruction/logs/2026-09-22-repository-release.md)

## 快速开始

本机验收环境为 Windows / Python 3.12。主体要求 Python 3.11+；跨平台完整复现尚未验收，部分研究工具有额外依赖。

```sh
git clone https://github.com/physics-Yu/QEC-schedule.git
cd QEC-schedule
python -m venv .venv
```

激活：Windows PowerShell 使用 `.venv\Scripts\Activate.ps1`；macOS/Linux 使用 `source .venv/bin/activate`。

```sh
python -m pip install -e ".[smt,test]"
# 当前默认 QMAP 编译器需要独立运行时（首次安装需要网络）：
python tools/setup_qmap_native.py
python demo/launch.py --port 0
```

安装器将作者依赖隔离到 `artifacts/qmap-native/venv`，也可通过 `QEC_QMAP_PYTHON` 指定已有兼容解释器。固定来源、许可证和 Windows/Python 3.12 依赖锁见 [third_party/qmap](third_party/qmap/README.md)。若只试有序贪心/SMT，可跳过原生安装，并在自定义工作台中显式选择对应算法。

浏览器自动打开 Demo 首页，保持终端运行；Ctrl+C 退出。无桌面环境加 `--no-browser`。**HTML 负责编辑与回放，实际编译由 Python 进行。** 修改线路不会自动编译，使用电路区域的编译按钮。新任务保存在 `artifacts/demo-runs/`，旧任务链接不会随仓库一起迁移。

## 演示入口

| 入口 | 内容 | 运行方式 |
|---|---|---|
| [可编辑工作台](demo/README.md) | 原子与平台配置、H/X/Y/Z/T/CZ 编辑、手动编译、失败诊断、32× 回放、逐原子统计 | 启动 Demo 后进入；默认原生编译器需上述 setup |
| [Parking Lab](demo/parking/index.html) | 10×10 格点编辑、红色目标/蓝色固定原子、逐行/列抓取、兼容批次、集体搬运 | 单 HTML 可离线编辑并分享；属于构造式模板演示 |
| [初态优化](docs/studio_initial_placement.md) | 顺序布局与优化布局比较、并行编译评估、自定义线路 | 原工作台选择支持的本地算法及优化初态；当前默认关闭 |
| [SMT 保存结果](demo/smt/replays.html) | 小规模贪心 / 单步 SMT / 多阶段 SMT 对照 | 可离线播放；编辑重编译从 Demo 首页进入 |
| [两逻辑 QEC 保存回放](demo/qec/replays.html) | 34 原子、稳定子测量/reset、条件恢复、有序贪心/SMT | 保存的是 2026-09-15 完整执行；可离线播放 |
| [四逻辑 GHZ 完整回放](demo/ghz4/animation.html) | 68 原子、1868 门/控制槽的历史 QEC 执行 | 单文件约 41 MB，离线播放 |

GitHub 文件预览不会执行 HTML；下载或克隆后用浏览器打开。除独立 Parking 文件和保存动画外，运行单位是完整源码仓库。

## 算法各自负责什么

| 模块 | 能力 | 当前边界 |
|---|---|---|
| [QMAP 原生](docs/qmap_native.md) | 作者 C++ 调度、复用、IDS 落点与路由；本地适配 AOD 操作并执行 | 要求显式成对 SLM 平台；支持普通门，未迁移测量/反馈 QEC；原生耗时不含本地执行审核 |
| [有序贪心 / SMT](docs/ordered_axis_greedy.md) | 移动侧、四方向作用、有序共享轴合批、有限正交路径和读出目标 | 旧流程整片入区/批内归还；SMT 优化当前批次，非全电路最优 |
| [本地分层驻留](docs/zoned_compiler.md) | 按需入区、调度/驻留/落点/物理生成分离 | 本地研究实现，非作者代码；候选有限，QEC 性能退化未解决 |
| [初态 placement](docs/compiler_initial_placement.md) | 站点分配、空位与占据形状搜索、真实编译反馈及并行评估 | 自由选址限已配置合法 SLM 域；不连续生成 trap、不保证全局最优；不叠加到原生 QMAP 映射 |
| [Parking](docs/parking_compatibility.md) | 跳过无目标行/列、保留已匹配轴、空位通配、兼容分组、选择抓取更少的方向 | pattern_optimal 只对指定整行/列模板的抓取批数最优 |
| [ZAC](docs/zac_reuse.md) / [初态 SA](docs/zac_initial_placement.md) | 固定作者源码的分层、复用、动态落点和 SA 初态，接本地物理执行 | 专用 CZ 实验；需下载作者源码和额外科学计算依赖，非开箱即用的通用工作台选项 |
| [交互 IR](docs/interaction_ir.md) | 无坐标的 MoveToInteraction / ApplyInteraction → 落点解析 → 实际 AOD 计划 | 已接本地 zoned；完整服务事务提交，未统一迁移所有旧策略 |
| [RL 研究](docs/rl_initial_placement.md) | 候选调度与独立初态布局/对抗场景训练 | 隔离实验，非默认策略；未稳定胜过启发式，离散训练见证不等于连续物理验收 |

完整协议 demo 锁定配套配置；电路示例仅替换门列表。平台能力、编译策略和电路分开管理，当前默认值维护于 [workbench.json](configs/studio/workbench.json)。AOD 容量由行列数计算；初始偏移为相对坐标，不是整个编译期间固定的抓取位置。

## 架构与正确性边界

```text
电路 + 平台 + 初态/终态合同
  → 策略：初态、前沿、交互请求、落点、抓取分组、路径
  → 具体物理操作程序（包含坐标、支撑和时间）
  → Env 校验 → Executor 提交/推进
  → trace、checkpoint、逐原子统计、共用 viewer
```

| 目录 | 职责 |
|---|---|
| src/neutral_atom_env/ | 状态、硬件判据、操作审核、事件执行、恢复与观测，不导入算法包 |
| src/neutral_atom_strategies/ | 可替换调度、placement、运动、IR、外部编译器适配与研究策略 |
| src/neutral_atom_experiments/ | 电路与协议、受限 QEC、对照实验和验收 |
| src/neutral_atom_app/ | 配置、控制程序、HTTP 作业、编辑器和展示 |
| configs/、examples/ | 可保存输入和复现入口 |
| docs/、instruction/logs/ | 当前合同、研究结果、历史尝试与失败记录 |
| demo/、tests/、tools/ | 精选交付、回归、审计、导出与 benchmark 工具 |
| third_party/ | 小型固定来源材料、许可证和依赖锁；大源码/安装环境由工具获取 |
| artifacts/ | 本地生成的运行证据和模型，不提交 Git |

只有 Executor 提交实时状态；策略在私有状态中预测，viewer 只读执行记录。`env.run()` 执行已提交的工作，不会自行完成后续编译。见 [包边界](docs/environment_strategy_boundary.md)、[源码导航](src/README.md)。

AOD trap 来自**活动行 × 活动列的全部交点**。共享轴、顺序、附带捕获、活动空 trap 扫掠和连续碰撞均需检查，不能只检查目标原子或路径端点。同类型单比特门可并行，固定 1 μs；间距、门作用模型和 EZ 四邻保护均是本项目声明配置，不能视为所有设备的普适物理事实。

普通运行主要模拟几何与事件；QEC 通路可跟踪 Clifford 理想量子态、测量与声明故障，尚不是全电路噪声阈值或任意故障容错证明。QMAP/Enola 大规模原生指令审计、Parking 浏览器模板、RL 离散模型与完整 Env 物理重放的证据等级分开。见 [原生规模实验](docs/enola_scaling_benchmark.md)。

## 开发与复现

```sh
python tools/check_architecture.py
python -m pytest tests/test_environment_boundary.py tests/test_interaction_ir.py tests/test_interaction_lowering.py
python examples/interaction_ir_demo.py --output artifacts/interaction-ir-demo
python tools/build_demo_bundle.py
python tools/check_demo_bundle.py
python tools/check_demo_http.py
```

交互 IR 例子保存输入、无坐标意图、落点、物理计划、执行结果与共用回放；这里的独立重放不重新运行规划器。完整回归用 `python -m pytest`；外部原生环境、ZAC/Enola 作者源码和 RL 依赖按专题说明另行准备，不承诺默认安装覆盖全部研究实验。

本次发布的复验结果见 [发布日志](instruction/logs/2026-09-22-repository-release.md)。大型实验、训练与历史浏览器验收按各自日志记录，不把旧 PASS 当作本轮重新执行。维护 UI 应修改 src，再导出 Demo；保存回放不会因新代码自动变成新的编译结果。

接下来的重点是 [constraint/placement 边界重构](docs/constraint_placement_audit.md)：提前区分落点、批次和路线失败，减少重复审核，并统一动态落点合同。这项重构尚未实施。独立探索工程 QEC-scheduler-next 的实现也不包含在本仓库；这里只保留 [迁移记录](instruction/logs/2026-09-22-qec-next-bootstrap.md)。
