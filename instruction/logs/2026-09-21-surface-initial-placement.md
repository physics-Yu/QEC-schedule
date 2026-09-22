# Surface-code GHZ初态优化非可视化实验

## 用户目标与实现

验证新初态优化是否仍能正确运行surface-code GHZ。选用既有完整两逻辑位d=3协议：34原子、18data/16ancilla、9对transversal CNOT、制备/最终稳定子测量反馈和Q013单数据Y错误恢复；483槽、105CZ、32MEASURE、32RESET。

新增 `neutral_atom_experiments/surface_initial_placement.py` 和 `examples/check_surface_initial_placement.py`。复用原 placement 整体平移种子，iterations=0防止逐原子交换打散patch，候选y=-5/0/+5/+10 μm，top_k=1＋原布局。双方采用SZ中共同96候选SLM、相同world边界/MZ/EZ/硬件/门表及同一基线终态；未放宽物理限制。

现有QEC comparison runner新增显式 `initial_state`、`terminal_target`、`render=False`参数，默认调用不变；本轮不生成动画。新增分析工具独立执行四个入区计划、检查共同后继状态并解释成本。

## 本轮证据

- `python examples/check_surface_initial_placement.py --output artifacts/initial-placement/surface-ghz2`：两组完整执行及全snapshot独立重放通过；每组66plans，效果恰好一次，测量反馈协议完整，16稳定子及逻辑XX/ZZ均+1。
- 原布局24337.380746 μs；候选24384.075363 μs，慢46.694617 μs / 0.1919%。LOAD均27批，原子路程13252→13082 μm。物理复评保留基线，0收益。
- `python tools/analyze_surface_initial_placement.py --stage-only`：四份真实入区计划及独立重放通过；入区后holder、AOD、SLM开关、量子态、DAG与RNG相同。
- `python tools/analyze_surface_initial_placement.py`：完整trace/plan对照通过，初始入区之后全部物理操作一致；总时间差精确等于入区时间差，证据 `cost-analysis.json`。
- `python -m pytest tests/test_surface_initial_placement.py tests/test_initial_placement.py tests/test_environment_boundary.py tests/test_qec_layout_origins.py -q --junitxml=artifacts/initial-placement/surface-tests.xml`：58 passed / 5.87s。
- `python -m pytest tests/test_qec_ordered_comparison.py tests/test_surface_qec_protocol.py -q --junitxml=artifacts/initial-placement/surface-protocol-tests.xml`：77 passed / 49.12s。
- 178模块架构依赖检查通过。新参数没有破坏既有QEC runner调用。

## 为什么没有收益

候选载原子移动少5 μm，节省8.077638 μs；但空AOD需要新对位，增加54.772256 μs。代理漏算空载对位，还把初始SZ坐标用于全部17个CZ层；实际控制器仅一次整体入区，后续都在同一EZ几何中执行。这是评分与控制器不匹配，不是量子门或稳定子错误。

本次成功指量子/物理/重放正确性，以及按真实时间排除负收益候选；不代表初态优化在surface code上已经提速。后续应增加controller-aware的入区评分/共同后缀复用，再考虑patch相对错位、动态落点和测量运输。未自行扩展为新物理模型、时域多轮纠错或四逻辑GHZ。

合同与结果：`docs/surface_initial_placement.md`；`artifacts/initial-placement/surface-ghz2/comparison.json`。未改UI、未新增RL、未提交推送。
