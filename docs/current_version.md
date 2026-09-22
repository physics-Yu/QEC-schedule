# 当前版本说明（2026-09-22）

本文依据当前源码、[工作台配置](../configs/studio/workbench.json)和各专题保存证据整理。2026-09-15 的非 RL 发布是历史快照；本版同时收录后续 placement、Parking、外部编译器、Interaction IR 与隔离 RL 研究代码。收录代码不代表实验策略已成为默认策略，也不代表此前每项实验都在本轮重新运行。

最新发布检查以 [handoff](../instruction/handoff.md) 及其发布日志为准；程序职责与演进见 [框架总览](general_framework_summary.md)。`QEC-scheduler-next` 是仓库外的另一项目，此处只保存迁移记录，不包含其实现或验收成果。

## 入口和验证范围

| 入口 | 用途 | 执行与验证范围 |
| --- | --- | --- |
| `python demo/launch.py` → 可编辑线路工作台 | 编辑 H/X/Y/Z/T/CZ，配置平台，手动编译、失败诊断、原子回放与统计 | Python 编译后由 Env 执行；默认 `qmap_native`，需单独安装作者运行环境 |
| Demo 首页 → 有序 AOD · QEC | 两逻辑 GHZ 的测量、reset、条件槽及贪心/SMT 对照 | 固定配套平台与协议，不能当作任意布局的通用 QEC 编译器 |
| Demo 首页 → SMT 对比 | 小规模单步、多阶段 SMT 与贪心比较 | 历史刚性 AOD 实验，与当前 `smt_ordered` 分开统计 |
| `demo/qec/replays.html`、`demo/ghz4/animation.html` | 直接查看保存的完整物理记录 | 离线播放，不重新编译；历史输入与当前模板可能不同 |
| `demo/parking/index.html` | 无需安装、可编辑且可分享的 Parking 演示 | 浏览器内模板运动学，不替代 Python Env 完整审计 |
| `python examples/parking_workbench.py --port 0` | Parking 真实计划、执行和独立重放 | 规则源 patch、显式增量抓取能力、共享轴与连续扫掠检查 |
| `python examples/zac_reuse_workbench.py --port 0` | ZAC 固定/SA 初态 × reuse 开/关实验 | 专用 CZ 线路及本地物理适配，需获取作者源码和研究依赖 |
| 大规模 QMAP、Enola、RL 的专题工具 | 原生算法研究或快速离散训练 | 各有独立合同；原生指令、端点审计、模型时间不等于本地连续物理验收 |

离线 HTML 下载后打开；GitHub 文件预览不执行页面脚本。工作台只由电路区域按钮启动编译，修改草稿不会自动运行。回放最高 32×，倍率不改变物理时间。

### 安装与依赖

在完整仓库根目录运行，基础要求 Python 3.11+。主要实机记录来自 Windows/Python 3.12；不代表所有研究入口已经跨平台验证。

```sh
python -m pip install -e ".[smt,test]"
python tools/setup_qmap_native.py
python demo/launch.py --port 0
```

`demo/launch.py` 启动工作台、SMT、QEC 服务和首页，因此启动时检查 Z3。不使用原生 QMAP 时可省略 setup，在工作台选择与平台兼容的有序贪心/SMT。

| 功能 | 额外依赖与边界 |
| --- | --- |
| 基础环境/有序贪心 | 主包标准库实现；test extra 包含 pytest、Matplotlib |
| SMT | smt extra 安装 `z3-solver` |
| QMAP | setup 创建 `artifacts/qmap-native/venv`，固定 QMAP 3.5.0、Bench 2.1.0；可用 `QEC_QMAP_PYTHON` 指定兼容解释器；[来源和锁文件](../third_party/qmap/README.md) |
| ZAC | `python tools/fetch_zac_sources.py` 获取固定来源；需要 NumPy、SciPy、Matplotlib、Qiskit、rustworkx。基础 extras 未统一包含，尚无全新机器安装验收；[说明](zac_reuse.md) |
| Enola scaling | 外部 Enola checkout、其 `.venv-research`、QMAP 隔离环境及 psutil；runner 仍使用 Windows `Scripts/python.exe`。源码位置用 `--source` 指定，仓库不捆绑 checkout；[说明](enola_scaling_benchmark.md) |
| 隔离 RL | 训练需要 PyTorch，依赖见 `configs/rl/`；`placement_rl` 模型、编译和离散审计只用标准库，网络和训练另需 PyTorch |
| JS 回归 | 部分 `tests/*.cjs` 需要 Node.js；DOM/Canvas 替身检查和真实浏览器验收分开记录 |

## 当前工作台算法

公开目录为四项。旧 M3/M4 基线保留给历史输入、API 和回归，旧算法的平台限制不等于当前后端的能力上限。

| ID | 当前作用 | 主要边界 |
| --- | --- | --- |
| `qmap_native` | **自定义工作台默认**。作者 C++ 分层、复用、IDS 落点、分组和指令生成，本地适配 Env 操作 | 显式成对 SLM 平台及作者初态；普通 H/X/Y/Z/T/CZ，测量/反馈留在旧 QEC。原生求解与本地适配/审计耗时分开 |
| `zoned_ids` | 本地分层驻留实验：按需入 EZ、下一伙伴、有限 IDS、兼容合批、EZ SLM 落地 | 非作者源码移植；落点/路径有预算，完整服务仍串行，AOD 不任意跨服务带载续接；QEC 性能退化未解决 |
| `ordered_greedy` | 旧流程对照：移动侧、作用方向、有序轴 CZ 批次与完整路线的有限搜索 | 通用控制器仍有整片入 EZ、每批归还等预设组织规则 |
| `smt_ordered` | 当前批次的门、轴、次序、容量、捕获闭包和作用对约束求解，再验证完整路线 | 有限模型和预算，当前批次目标不等于全电路最短物理时间 |

详见 [QMAP](qmap_native.md)、[zoned](zoned_compiler.md)、[有序工作台](ordered_workbench.md)、[能力说明](workstation_compilers.md)。完整 QEC demo 锁定配套策略，不随普通默认值变化。

原生 QMAP 适配保持门/装卸服务边界，减少冗余折点；超出本地轴容量的运输组可拆批。部分 PARK 需显式 selective-transfer 能力；1Q 寻址分离、连续路径及空交点检查仍执行。原生程序成功不保证本地适配成功，失败保留指令和执行前缀。

## 分层、Interaction IR 与 constraint 现状

```text
电路 / 平台 / 已准备初态 / 终态合同
  → 策略：调度、驻留、placement、合批和运动编译
  → 完整且绑定状态的 CompiledPlan
  → Env 校验、submit、Executor 推进
  → 已提交状态、trace、逐原子统计、共用回放
```

环境在 `neutral_atom_env`；算法在 `neutral_atom_strategies`；协议/基准在 `neutral_atom_experiments`；配置、控制与界面在 `neutral_atom_app`。只有 Executor 提交真实下一状态。`env.run()` 执行已提交操作，不继续搜索剩余电路。

新 `strategies/ir/` 提供无具体坐标的 `MoveToInteraction` / `ApplyInteraction`。`run_zoned` 已接入“原子对与区域请求 → resolver 选择角色/落点并绑定状态 → lowerer 展开 AOD/路线/pulse/落地 → CompiledPlan”。准备不执行门，已有合法配对可零移动。当前仍构造完整私有事务，验证后提交；不是任意准备阶段可单独提交/恢复。旧 ordered/SMT、QEC、native 没有全部迁移；作者 NAViz 已有的坐标也不会丢弃后重新求解。详见 [Interaction IR](interaction_ir.md)。

**constraint 统一重构仍是待实施建议。** 检查目前分布在落点预筛、批次构造、硬件操作、完整计划审计和运行时绑定中。连续碰撞、支撑、共享轴、实际 CZ 作用对属于模型约束；EZ 四邻保护是显式配置合同；beam、路径族、整片搬运和站点窗口属于策略选择。搜索耗尽不能解释为物理无解。

统一意图/目标/运输/路径/整计划检查接口、拒绝原因分类和重复校验开销优化尚未完成。`env` 还包含从下一 CZ 推导 EZ 保留关系的耦合；改为上层显式预约合同需要独立设计与验证。新增 IR 本身没有解决这些缺口。

## placement 和 Parking

`strategies/placement/` 已包含问题/结果对象、成本代理、初态算法、自由选址、有界真实编译反馈和并行评估。自由选址是从**配置的合法 SLM 域**选择站点，包括空位与不规则占据形状，不是连续坐标任意生成新 trap。

- 初态优化在创建环境前准备 Q→SLM 映射，保持电路身份、门和依赖；不计初次实验装配时间。
- 工作台搜索支持 `ordered_greedy`、`smt_ordered`、`zoned_ids`，固定线路、平台、预算和终态；`qmap_native` 使用作者映射，不接此入口。
- 候选各自完整编译，相同映射去重；同一服务内相同成功请求可复用。动画是已接受计划的独立重放，无需再次规划。
- `stable` 不追加末尾统一归还，仍完成门服务必要落地；`fixed` 要求共同绝对终态，比较不能混用。
- `DynamicPlacementPolicy` / `LandingProposal` 已有接口和固定归还基线；zoned CZ 落地、测量落点和 ZAC 动态放置仍是各自实现，未统一成一个动态服务。

详见 [初态模块](initial_placement.md)、[自由选址](free_initial_placement.md)、[并行评估](parallel_initial_placement.md)、[工作台流程](unified_compilation_workflow.md)。专题中保存的早期默认值按历史理解，当前新草稿初态优化已改为**显式可选、默认关闭**。

Parking 朴素逐行/逐列保留已匹配轴，跳过无目标行列，只做必要对齐和新增抓取；不再每轮恢复全部轴。兼容优化把空位当不约束，固定原子禁止被抓，求整行/整列冲突图的最少兼容组数并比较方向。`pattern_optimal` **已实现**，最优仅指声明模板族中的抓取次数，不涵盖任意矩形拆分、混合方向或总物理时间。Python 生成真实计划；分享版构造浏览器模板动作。详见 [Parking v2](parking_compatibility.md)、[分享版范围](parking_portable.md)。

## 配置归属

| 内容 | 用户选择/预设 | 编译或环境派生 |
| --- | --- | --- |
| 完整实验 demo | 选择协议、平台、策略的锁定组合 | 电路和量子验收合同随 demo；修改后不自动继承原协议正确性 |
| 自定义线路 | 原子数、门、布局、算法、预算、终态 | DAG 就绪集、批次、具体目标和路线 |
| AOD | 行列数、后端、初始非均匀相对 offsets | 容量=行×列；trap=活动行×活动列；绝对位置=阵列位置+offset；支持的策略继续规划运行中轴坐标 |
| 初态优化 | 开关、候选域、候选池/评估数/进程数、终态 | 新草稿默认 pool=256、evaluations=16、workers=4、stable、允许 SZ 空位、enabled=false；最终选择由真实评估决定 |
| 物理参数/保护合同 | 显式平台配置，策略不得为成功而放宽 | 固定 1Q 1 μs、运动时间、作用对、clearance、支撑按当前模型检查，不是普适硬件常数 |
| 显示/统计 | 播放模式、速度和可见项 | 逐原子路程、装卸/门次数、活动与等待来自执行记录，显示不改变状态 |

电路示例只替换门，不自动切换算法。相对 AOD offsets 是初始构型，不是固定可抓取地址白名单；运行中变距能力取决于后端与策略。

## 保存证据与未完成边界

以下均为各专题**已保存的历史验收**，不是本次整理重新测出的性能。本轮回归另见最新发布日志。

| 模块 | 保存证据 | 不能据此宣称 |
| --- | --- | --- |
| 有序 QEC | 34 原子、483 槽旧版本，两策略物理/量子/重放通过；各 17 批 CZ、最多 9 对，24337.381 / 24975.219 μs | SMT 普遍更优，或当前所有模板均为 483 槽 |
| zoned | 普通例有正负收益；480 槽 QEC 通过声明理想协议检查，但 CZ 批数 17→81，物理时间约 3.57 倍 | QEC 性能验收完成；此项仍 OPEN |
| QMAP 本地适配 | 五组普通电路逐门效果、独立重放和终态通过 | 原几何上的加速；本轮采用显式成对 SLM 平台 |
| QMAP 5000 原子 | GHZ 链 14998 门原生约 9.28 s，离散审计通过；graph-state 在 900 s 内未完成 | 5000 原子本地连续物理验收，或高并行图负载成功 |
| Enola / QMAP scaling | 30–5000 原子共 12 尝试，8 完成/4 超时，完整配对到 1000 | 同硬件排名；平台/曝光/终态不同，无本地 Env 连续验收 |
| 初态搜索 | 有小例物理收益，也有 20 原子随机四层电路零收益；失败候选保留 | 代理更低必然更快、任意电路或 surface QEC 都加速 |
| ZAC | 固定初态 reuse 消融完整执行；SA 四组 16 份中 14 完成、2 失败 | 少装载必然更快；失败终态不能参与完整成绩比较 |
| Interaction IR | 57 项分组测试；6 原子/2CZ 同批，2 旁观原子全程不动，序列化独立重放一致 | 所有策略已迁移、constraint 已统一，或本轮 GUI 已验收 |
| RL | `learning/` 候选调度与 `placement_rl/` 离散初态训练分开，有训练/测试/失败记录 | 稳定超过启发式、已替换生产默认；CZ-only 不等于完整 syndrome extraction |

RL 代码与配置在本版可查，权重与大型产物仍在被忽略的 `artifacts/` 中，可按 [候选调度实验](rl_cz_experiment.md)、[初态 RL](rl_initial_placement.md) 重建。它们不属于工作台稳定算法菜单。

后续优先：统一约束判定/拒绝原因，减少物理适配与重复审计成本，修复 zoned QEC 合批退化，在固定平台/完整电路/共同终态下比较算法。连续安全、量子协议、搜索性能和界面交互分别验收。

## 维护检查和复现

```sh
python tools/check_architecture.py
python tools/check_demo_bundle.py
python tools/check_demo_http.py
python -m pytest -q tests/test_interaction_ir.py tests/test_interaction_lowering.py tests/test_zoned_compiler.py tests/test_environment_boundary.py
python examples/interaction_ir_demo.py
```

上列是检查入口，不是预先声明通过。UI 源码修改后用 `python tools/build_demo_bundle.py` 刷新导出与 manifest，再做 bundle/HTTP 检查。完整 QEC、初始化搜索、作者 benchmark 可能较慢，按专题固定输入、预算与终态。产物通常不随 Git 提交，运行不应依赖开发机旧端口。

历史数据入口：[2026-09-15 发布](../instruction/logs/2026-09-15-stable-release.md)、[QEC 保存对照](../demo/qec/reference/comparison.json)、[QMAP 大例](qmap_large_benchmark.md)、[Enola scaling](enola_scaling_benchmark.md)、[ZAC 初始化](zac_initial_placement.md)。
