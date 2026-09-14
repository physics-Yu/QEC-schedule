# 4C 四 patch 时域协议预审

2026-09-12；**只读设计，尚未实现或验收**。本文在4B完整物理代表执行、全源码冻结期间编写。只读取现有实现与合同，没有运行协议生成、量子模拟、pytest、物理编译或浏览器实验。必须等待4B编译、独立重放及UI全部通过，才开始4C实施。本文的计数是按电路结构推导的预期，不是执行成绩。

## 最小扩展与冻结边界

推荐新增 `experiments/surface_qec_temporal_four.py`，提供与4B对应的 `protocol(fault=None)`、`experiment_input(fault=None, compiler='qec_temporal_four')`、`simulate_ideal(...)`、`decode(reported_bits)`、`validate_history(reported_bits)`、`summarize(state)`。独立导出128项 `HISTORY_IDS`、160项 `MEASUREMENT_IDS`、`CORRECTION_PREFIX='TEMP4_CORR_'` 与四patch角色表。

冻结 `surface_qec.py`、`surface_qec_temporal.py` 及两patch输入，不把本轮当作通用框架重构。可直接只读复用与patch数无关的 `X_CHECKS/Z_CHECKS`、`X_ORDER/Z_ORDER`、`LOGICAL_X/LOGICAL_Z`、`correction_table(kind)`、`_Builder`、`optimize_h_pairs` 与 `reduce_dependencies`。现有 `_syndrome`、`_corrections`、`data/ancilla`、`_protocol_complete`、历史表、summary均硬编码两patch，不能直接调用或临时修改其模块全局变量。

新模块局部采用固定 `PATCH_COUNT=4`，将抽取、制备纠正、角色映射、历史和观测量的小循环显式依赖这一常量；不新增全局可变配置，不抽取后反向改写旧模块。身份推荐数据 `Q000…Q035`，辅助 `Q036…Q067`，映射 `data(b,q)=Q[9b+q]`，`ancilla(b,k,i)=Q[36+8b+(0 if k=='X' else 4)+i]`。两patch辅助从Q018开始，不能混用旧角色或布局函数。

新增薄层 `simulation/qec_temporal_four.py::run_qec_temporal_four`，调用既有 `run_qec_joint(..., frontier_validator=...)`。采用新128位集合和前缀，在完整历史提交后及任一最终纠正READY前检查；不复制整个调度器，不修改core、RNG、支撑、CZ实际作用对或MZ约束。工作台必须按新profile选择对应布局和summary；旧 `run_qec_temporal` 检查64位，不足以保护四patch反馈。

## 电路与全局时序

1. 68个比特初始化为零。仅A的9个数据施加H，B/C/D保持零。四patch各做与旧协议同序的prepare抽取、真实MEASURE、真实RESET和条件Pauli纠正，得到A的逻辑加态及B/C/D的逻辑零态。
2. 第一层逻辑CNOT为A→B，9对对应数据用H–CZ–H实现。第二层为A→C与B→D，合并为18对不共享数据的逻辑CNOT层。两个层之间使用真实DAG依赖/阶段barrier。第二层数学上可并行，不等于具体AOD布局一定能在一个物理pulse完成18CZ，后者仍由全作用对和捕获闭包决定。
3. GHZ树全部完成后，依次执行round1、round2、round3、closing。每轮入口保留全局前一阶段完成barrier，单数据测试Pauli若存在必须在该轮全部抽取之前、前轮全部RESET之后。各轮内部沿用相同X/Z check顺序与真实辅助读出/RESET。前三轮不做数据反馈；最后一轮完全理想但必须真实执行、计入时间和运输。
4. 全128位reported历史通过固定全局支持表后，执行静态AND条件X/Z反馈，再验证并完成显式原始SLM终态。prepare的32位不属于时域历史。

结构预期：36数据+32辅助=68原子；每patch每轮24CZ，五轮共480CZ；GHZ树27CZ；**合计507CZ、160目标MEASURE和160目标RESET**。统计的是逻辑目标/效果数，物理批次数另报。H优化与条件控制槽总数应在实施后从生成结果实测，不能简单翻倍916；prepare、树层和相邻H消去会改变计数。

## 固定421事件模型与128位译码

保留4B的严格范围：无事件1项；3轮入口×36数据×X/Y/Z共324项；3轮×4patch×8check共96个reported readout flip；合计**421项**。事件只发生在逻辑GHZ完成后，不覆盖树内传播故障、制备/抽取门故障、hook错误、损失、加热、RESET错误或任意多个事件。

故障输入保持 `{kind:'data', round:1..3, pauli:'X'|'Y'|'Z', qubit_id}` 或 `{kind:'readout', round:1..3, patch:0..3, check_type:'X'|'Z', check_index:0..3}`。仍只允许一个事件，closing禁止注入。元数据不是行为来源：数据事件是实际Pauli门，readout事件是对应MEASURE的 `readout_flip:true`。读取真实投影与报告翻转的core保持原有实现；RESET作用真实量子态，decoder只看reported。

`HISTORY_IDS`仍按round→X/Z→patch→check排列，现为4×2×4×4=128位；例如 `round2_X3_0`。所有421输入共享由反对易关系推导的同一全局支持集合，不读取当前fault参数来定制表。按4B每两patch187个非重叠单事件历史推导，四patch预计去重为 **1+2×(187−1)=373**；这是静态推导，实施时须独立构造集合核验。

CSS局部表有4patch×2类型=8张，每张仍只读取本patch四轮×四check的16位，使用closing四位选择既有最小重量Pauli代表。局部表是固定全局集合的投影。不能将八个分别受支持的局部历史当成全局单事件有效性；必须先检查全部128位。缺失、非法bit、完整但不支持分别沿用 `INCOMPLETE_SYNDROME_HISTORY`、`INVALID_SYNDROME_HISTORY`、`UNSUPPORTED_SYNDROME_HISTORY`。

在单事件且closing完全正确的模型中，历史用于验证受支持的事件类型/时序，最终Pauli代表仍可由closing符号确定；不将此称为通用时域MWPM或阈值结果。多事件可与单事件历史发生别名，只保证拒绝支持集合之外的历史。

## 独立量子验收

新增 `tests/test_surface_qec_temporal_four.py`，421个参数案例逐一运行真实68比特stabilizer引擎的静态Clifford线路、投影、RESET及reported条件。每案例至少检查：

- 独立symplectic/反对易公式给出全部128位true与reported预期；readout事件只翻一个报告位且不改真实投影，数据事件从目标轮持续到closing。
- 160个MEASURE及160个RESET真实执行，五轮32check完整；每个辅助最终Z期望+1。抽取完整性验证必须读取实际执行门序及正确辅助/数据伙伴，不只认ID或元数据。
- **32个码稳定子全部+1**。
- **逻辑XXXX=+1**，即四patch各取旧逻辑X代表的联合Pauli算符。
- **相邻逻辑ZZ三条均+1：Z_A Z_B、Z_B Z_C、Z_C Z_D**。这是逻辑标签的链式相邻，不是要求原子物理相邻。三条独立ZZ与XXXX稳定四比特GHZ；可额外报GHZ树边AB/AC/BD，但不能用额外指标替代这三条合同项。
- 实际执行的最终条件纠正集合与decoder建议一致；建议和实际trace在summary/UI分开。仅无事件或报告翻转时不应生成实际数据纠错光。

至少补多个无故障随机制备seed，原始/优化线路量子等价，全局轮入口祖先完整，以及每个最终条件门受全部128位guard约束。对比不同fault输入的最终纠正门表/条件必须一致，避免选择性生成纠错门成为oracle。预声明负例选两个不同patch的独立readout flip：局部各合法但全局不受支持；还要测试删历史、改依赖提前纠正、非法bit、closing注入、错误辅助映射。完整历史若不支持，不能在先应用纠正之后才报错。

建议summary新增 `logical_xxxx`、`logical_zz_pairs={'AB':...,'BC':...,'CD':...}`、`verified_logical_ghz4`，保留actual `corrections`、`decoded_corrections`、true/reported、history/protocol完整性和scope。不以XX/ZZ两个旧字段冒充四逻辑验收。

## 物理整合前置检查

旧 `qec_layout.py` 只接受两个原点、34个原子和固定SZ y≤35，不能复用为四patch布局。建议另建有界 `qec_four_layout.py`，使用四patch真实数据及辅助坐标、显式SZ/EZ/MZ/world边界和有限trap集合；所有角色、MZ目标、原始SLM终态从68原子产生。区域尺寸是新输入平台的声明，不能静默扩大旧平台或作用/碰撞距离。

例如四原点(0,0)/(40,0)/(0,40)/(40,40)的完整数据+辅助坐标需要14种行与14种列，整体Cartesian捕获会涉及 **196交点，超过当前128容量**。68是占据原子数，不是阵列容量。最小方向为在既有≤128的单rigid AOD上分组运输、分组读出与合法CZ批次；可静态检查7×14阵列是否能分别覆盖两个水平band，但不能未经实际编译就宣称此布局或完整阶段预置已支持。空活动交点、附带捕获、整个axes世界边界和路线都要验证。若现有分组运输无法构造，应报告具体能力缺口，不改容量上限或物理约束换取通过。

现有 `run_qec_joint` 的策略主体按state/READY门工作，可优先复用；但其 `patch_assignment`、cohort绑定及readout候选涉及全布局，因此量子421项通过并不证明68原子的物理编译可行。物理首次尝试之前应静态审查这些边界，固定输入、终态、预算和代表事件，再分级做最小真实服务、完整编译、compiler-free replay、checkpoint及可编辑UI验收。性能只报四patch自身实测，不要求比两patch更快，也不将更大规模完成视为容错阈值证明。

## 后续实施顺序

4B全验收通过并解除冻结 → 独立四patch协议/接口与421项量子测试 → 有界布局和现有策略的最小物理构造 → 明确预算的完整代表 → 独立量子/物理重放与原始归还终态 → 真实可编辑线路、重新编译和双模式32×动画验收。四patch源码目前不存在本轮实现，本文不将任何待验收项标为PASS。
