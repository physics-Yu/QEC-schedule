# Surface-code GHZ 的初态放置验收

2026-09-21。两组完整物理执行、独立重放和量子核验均通过；该初态候选比基线慢0.1919%，物理复评保留原布局。本轮没有加速收益，也没有修改界面。

## 完整结果

| 布局 | 总物理时间 μs | LOAD批数 | 原子总路程 μm | GHZ/测量协议/独立重放 |
| --- | ---: | ---: | ---: | --- |
| 原布局 | 24337.380746 | 27 | 13252 | 全部通过 |
| 向EZ平移5 μm的候选 | 24384.075363 | 27 | 13082 | 全部通过 |

两组各66个实际计划、483个门/控制槽完成，16个码稳定子、逻辑XX和ZZ均为+1。共同终态的holder、SLM masks和AOD配置相同。物理复评最终选择基线，收益为0；不是把更慢候选当成优化结果。

代理评分36726.451→35532.791，耗时约0.27秒；实际编译/执行约171–201秒，独立重放约64–66秒。两者不是同一个计时指标，运行中还有独立回归测试，不能以这两个wall-clock时间比较策略编译效率。

机器回归：58项初态/边界/patch几何测试通过；77项既有QEC物理服务/量子协议测试通过；178模块架构检查通过。证据在 `artifacts/initial-placement/surface-ghz2/comparison.json`、`surface-tests.xml`、`surface-protocol-tests.xml`和`surface-architecture.json`。

## 电路与比较合同

- 采用现有两逻辑位 rotated distance-3 surface-code GHZ：34 原子，18 data＋16专用ancilla。
- 完整483门/控制槽：129 H、105 CZ、32 MEASURE、32 RESET、92条件候选X、92条件候选Z、1个实际Y故障。条件控制槽不成立时不能伪称发生Pauli光脉冲。
- 制备稳定子测量及反馈 → 9对transversal CNOT（H–CZ–H物理分解）→ Q013的单数据Y错误 → final稳定子测量/复位及反馈恢复。
- 使用既有 ordered_greedy、axis_hold 和读出落点策略，7×14 AOD；物理硬规则、原来的EZ四邻guard配置不变。
- 固定原 SZ/EZ/MZ 边界、移动视场和MZ/EZ trap。在SZ内建立96个两组共同可用的离散初态候选位置；两组共享同一world。新增SLM初态默认关闭，只有各组初始占据点开启。
- 原布局与候选布局不同，但最终必须恢复同一原布局的holder、SLM开关和AOD配置。使用相同随机种子和完整门表，跟踪真实stabilizer量子态。

## 为什么先限制候选形状

初态代价当前尚未计入测量、RESET和反馈运输。直接自由交换34个atom会打散既有patch几何，也难以解释收益。因此本轮复用 `optimize_initial` 的整体平移种子，`iterations=0` 禁用逐原子/行列退火；保留完整两patch相对结构，只搜索 y=-5/0/+5/+10 μm 平移。位置由固定SZ内的源点集合决定，并非在执行记录里修改原子坐标。

`lookahead_layers=64`覆盖本线路全部17个CZ预测层，`top_k=1`后另保留原布局，完整物理复评两份。约束的是此次实验候选族，不改变通用初态算法的能力。动态placement没有在本轮新增。

当前控制器首先把完整源阵列平移到EZ，再执行门，因此不同初态可能在第一步之后就汇合到同一个EZ状态。即使GHZ正确性通过，也不能据此宣称已实现整个QEC程序的显著优化。

## 必须同时通过的检查

1. 完整电路与门依赖保持，9对横向逻辑CNOT配对、data/ancilla身份不变。
2. 每个门/控制槽效果恰好提交一次，完整物理Executor校验通过。
3. 32次真实测量、32次RESET及classical feedback完成，`measurement_protocol_complete=true`。
4. 16个码稳定子期望值均为+1，逻辑XX和ZZ均为+1，`verified_logical_ghz2=true`。
5. 从初始checkpoint重新提交所有实际plans，最终完整snapshot逐字一致。
6. 两组最终holder、SLM masks、AOD configuration、输入电路和硬件相同。

这是理想读出下单数据Pauli恢复的既有模型，不是完整电路噪声容错、时域多轮测量噪声、四逻辑GHZ或真实设备实验。初态视为已准备好，不计随机装载到初态的组装。

## 复现

```powershell
python examples/check_surface_initial_placement.py --output artifacts/initial-placement/surface-ghz2
python -m pytest tests/test_surface_initial_placement.py tests/test_initial_placement.py tests/test_environment_boundary.py tests/test_qec_layout_origins.py -q
python -m pytest tests/test_qec_ordered_comparison.py tests/test_surface_qec_protocol.py -q
```

`src/neutral_atom_experiments/surface_initial_placement.py`负责共同平台、候选与汇总；既有QEC runner仅增加显式初态/共同终态和`render=False`可选参数，旧调用默认行为保持。

输出 `input.json`、`problem.json`、`config.json`、`search.json`、每组真实plans/trace/checkpoints/逐原子统计与`comparison.json`。不生成新HTML，不改工作台。运行过程可读每组 `progress.json`、`verification-progress.json`。

## 入区阶段诊断

额外对四个平移候选单独生成真实 staging plan，经过Executor执行与独立重放，确认入区后几何、AOD配置、SLM开关、量子态、DAG和RNG完全一致（不要求已经花费的时间、version和trace相同）。

| 初态 y 平移 μm | 空AOD对位 μs | 载原子移动 μs | LOAD/OFFLOAD μs | 入区总时间 μs |
| ---: | ---: | ---: | ---: | ---: |
| -5 | 54.772256 | 181.659021 | 200 | 436.431277 |
| 0 | 0 | 189.736660 | 200 | 389.736660 |
| +5 | 54.772256 | 197.484177 | 200 | 452.256432 |
| +10 | 77.459667 | 210.000000 | 200 | 487.459667 |

靠近EZ的候选少载原子移动5 μm，但还需先调整空AOD行坐标。考虑当前cubic加速度/jerk约束，增加54.772256 μs，远大于载原子段节省的8.077638 μs，净增46.694617 μs。

当前代理有两处偏差：没有空AOD对位项；后续17个CZ预测层仍使用初始SZ坐标，而当前控制器只在开头搬一次整个阵列到EZ。这不是量子纠错或碰撞规则的问题，是代理与下游编译流程不匹配。最终物理复评保留原布局，不能将代理评分下降冒充实际提升。

完整 `cost-analysis.json` 已核对两组入区之后的全部物理操作一致；总时间差46.694617 μs完全来自入区。不能把这次的原子总路程减少170 μm换算为时间收益。

后续改进应优先给该控制器接入“真实入区代价＋入区后共同状态”的评分；本受限候选族入区后状态相同，可以复用共同后缀的成本。只有扩展为不同patch间距、相对错位或动态落点后，才需要重新评价transversal、稳定子抽取和MZ往返；本轮没有私自切换这些方案。

诊断复现：`python tools/analyze_surface_initial_placement.py`。`--stage-only`只运行四份入区计划；完整模式另外读取两份全电路执行，检查后续物理操作及耗时差的来源。
