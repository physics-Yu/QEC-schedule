# 四 patch 的三轮噪声时域恢复

2026-09-12。独立实现位于 `experiments/surface_qec_temporal_four.py`，不修改已通过的两patch协议。本文记录协议及量子专项；完整物理编译、独立重放与可编辑UI由主任务另行验收。

## 电路和模型

四块旋转[[9,1,3]]码，共36数据 `Q000…Q035` 和32辅助 `Q036…Q067`。prepare对四块做真实稳定子抽取、MEASURE、RESET与reported条件反馈，A制备逻辑加态，其他三块制备逻辑零态。逻辑GHZ使用A→B，再同层A→C/B→D，每条逻辑CNOT由九对数据的H–CZ–H组成。

之后是round1、round2、round3与closing；每轮有完整入口依赖，closing真实执行并计费。前三轮允许整个实验至多一个轮入口数据X/Y/Z或一个读出报告位翻转。prepare、GHZ树、抽取门、运输、RESET及closing保持理想；不是全门噪声容错或阈值实验。

输入事件为 `{kind:'data', round:1..3, pauli:'X'|'Y'|'Z', qubit_id}` 或 `{kind:'readout', round:1..3, patch:0..3, check_type:'X'|'Z', check_index:0..3}`。数据事件生成实际Pauli门；报告翻转附在对应MEASURE的 `readout_flip:true`，不改变真实量子投影或RESET。故障元数据只用于显示。

实际门表生成检查得到：**1868槽，689H、507CZ、160MEASURE、160RESET、176X、176Z**；X/Z包含未触发的条件槽，不能将槽数当作实际打光次数。单数据事件另外增加一个真实Pauli门，报告翻转不增加槽。最长gate ID为20个ASCII字符。物理批次数、运输、总耗时须从真实执行另外统计。

## 固定历史与反馈

无事件1项、3×36×3数据事件324项、3×4×8读出事件96项，共421个声明案例。由固定反对易关系生成并实际去重为 **373个128位全局历史**；所有输入共享该集合。prepare的32位不参加时域译码，四轮×四patch×八check共128位，按round→X/Z→patch→check排列。

先检查全128位历史属于固定支持集合，然后执行每patch/CSS四轮×四check的16位条件反馈。最终门前缀 `TEMP4_CORR_`，不复用两patch guard的64位集合。八张局部表分别受支持不能代替全局单事件检查。无事件和纯报告位翻转不会施加数据纠错。完整但不支持的历史报 `UNSUPPORTED_SYNDROME_HISTORY`，缺失或非法bit分别报 `INCOMPLETE_SYNDROME_HISTORY` / `INVALID_SYNDROME_HISTORY`。

closing在此模型中完全正确，Pauli代表可由它的四个CSS符号决定，前三轮用于受支持历史检查。多个事件若与支持历史别名，无法仅靠历史鉴别；此实现不保证拒绝所有多事件，也不声称通用MWPM。译码接口不接收fault元数据或真实投影结果。

## API和编辑输入

- `protocol(fault=None, optimize=True, reduce_edges=True)` 返回实际门表及只供显示的元数据；复用旧通用builder、H优化和精确依赖约简，使用新四patch局部映射/抽取循环。
- `experiment_input(fault=None, compiler='qec_temporal_four')` 返回 `layout='surface_qec_ghz4'`、68原子、四原点 `[[0,0],[40,0],[0,40],[40,40]]`、同7×14=98 AOD参数和可编辑门表，不使用旧 `qec_fault` 字段。实际物理布局由独立四patch布局模块提供。
- `HISTORY_IDS`有128项，`MEASUREMENT_IDS`有160项，`CORRECTION_PREFIX='TEMP4_CORR_'`。`decode(reported_bits)` 与 `validate_history(reported_bits)` 仅接收reported值。
- `simulate_ideal(gates=None, seed=0, fault=None)` 执行实际静态Clifford、测量、RESET和条件；`summarize(state)` 读取实际trace与state。真实/报告测量分开，`corrections`是已执行条件门，`decoded_corrections`仅是建议。

元数据显式含patch_count/logical_count=4、data_count=36、ancilla_count=32、logical_tree_layers、每轮入口、完整readouts及noise_event。summary含32个 `stabilizer_expectations`，`logical_xxxx`，`logical_zz_pairs={'AB','BC','CD'}`，`verified_logical_ghz4`，以及history/protocol完整性、各轮完整性、true/reported结果。三个ZZ是逻辑标签的链式相邻，不要求物理原子相邻。

## 验证与限制

`tests/test_surface_qec_temporal_four.py` 逐一模拟421事件，独立symplectic公式核对全部128位true/reported预期，检查实际反馈、32码稳定子、XXXX、AB/BC/CD三条ZZ和32辅助最终零态。附加检查固定373集合、16位局部反馈、双事件全局拒绝、完整轮入口祖先、全128历史依赖、原始/优化协议等价、映射/GHZ树/门ID/输入、多个制备seed及范围负例。

首次完整专项命令 `C:/python312/python.exe -m pytest tests/test_surface_qec_temporal_four.py -q --disable-warnings --maxfail=1`：**437 passed in 1438.13s (0:23:58)**，exit0，421事件全部通过；无意外失败、无重试、运行期间无源码修改。完整状态构造校验保留。结果与源码SHA256记于 `artifacts/qec-roadmap/step4C-quantum-tests/result.json`。这是量子协议专项结果，不是物理总耗时或完整编译/浏览器成绩。

68原子不等于68格点整体捕获。四patch完整行列覆盖196交点，超过工作台128容量，因此输入保持98格点并要求真实分组运输；模块不放宽捕获闭包、空trap sweep、CZ作用对、单比特距离、MZ或终态。量子恢复通过不能替代物理计划和浏览器的独立验收。
