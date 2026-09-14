# 可运行门集与并行规范

2026-09-12 扩展：普通编辑模式继续 H/X/Y/Z/T/CZ；用户新增的 QEC 模式支持 H/X/Y/Z/CZ/MEASURE/RESET，使用精确 Clifford 态并明确拒绝 T。MEASURE/RESET 必须在 MZ，当前时长 500/100 μs 为模拟假设。条件 X/Z 可读取前序测量位；false 时是无光控制时隙。CZ 现已有单脉冲多个互不共享 qubit 的真实批量效果，实际 EZ pairs 必须与整批 intended 完全相同。schema19。下文未更新的“逐门 CZ/schema17”是历史基线，参见[批量合同](batch_cz_contract.md)与[读出合同](quantum_readout_core.md)。

生效：2026-09-11，按用户最新要求。此规范覆盖此前允许 U3/旋转门及不同门类型同时执行的约定。

## 门集合

| 门 | 操作数 | 输入参数 | 物理作用时长 |
| --- | --- | --- | --- |
| H、X、Y、Z、T | 一个 qubit | 无，parameters 为 [] | 各固定 1 μs |
| CZ | 两个不同 qubit | 无，parameters 为 [] | 按现有 hardware.pulse_duration_us 配置，默认 0.3 μs |

界面门工具、随机生成、维护的示例、输入导入、HTTP 编译和真实物理执行均遵守此门集。U、U3、RX/RY/RZ、S/Sdg、Tdg、I 等不可执行。旧输入明确报错，由用户修改；不静默分解、删除或替换。内部保留标准 U 矩阵参数表示，用来记录 H/X/Y/Z/T 的确切效果，不开放参数编辑。

## 同类型并行

只有 gate_type 相同的门作用区间才允许重叠。例如 H/H、T/T 可并行；H/X、T/Z、CZ/H 均不可重叠。门 ID 不需要相同；这里的“同一个门”指同一种门类型。

同类型只是必要条件，还必须满足：

- 操作数互不重叠，DAG 前驱已经完成；同一 qubit 上的门始终遵循依赖顺序。
- H/X/Y/Z/T 的原子由开启的 SLM 或静止 AOD 支撑，已完成相关交接，并满足寻址区域条件。与任意其他存活原子距离 ≥5 μm（含 5），不区分目标/邻居 holder；<5 μm 先分离再打光。
- 原子、trap、激光、AOD、作用区域与完整几何约束均合法。

CZ/CZ 虽满足类型兼容，当前单 AOD/单作用槽后端仍逐门执行；此规范不代表已实现批量 CZ。运输、装卸、trap 开关不属于门类型，可与不相关原子的门操作重叠，相关原子与支撑仍受资源互斥约束。取出原子和 2.5+5k μm 正交通道约束保持。

区间使用半开形式 [start, end)：H 在 1 μs 结束后，X 可在同一 1 μs 时刻开始。执行器按先完成再开始处理该边界。不同类型的部分重叠也必须拒绝。

## 编译与独立验证

M4 从实际原子可用窗口中寻找最早开始时间；如果完整 1 μs 区间与异类门冲突，则推迟到冲突结束后，再检查后续窗口。已就绪、同类型且不同 qubit 的门可加入同一时间段。执行器独立检查实际在途门类型，手工计划和 checkpoint 不能绕过该规则。

门集合的唯一 Python 常量入口为 `hardware/gate_contract.py`；物理单比特资格在 `hardware/raman.py`；同类型并行的最终校验在 `simulation/operation_program.py`；M4 窗口安排在 `simulation/m4.py`。AOD 目标占用 AOD_0，保证脉冲期间运输与支撑不改变；移动邻居的间距按脉冲实际时间区间校验。checkpoint **schema 17**，旧 1–16 必须从满足新门集的输入重新编译。历史 HTML 保留原记录，不用改动画伪造新规范结果。文献依据、数值假设与新验收见 [AOD Raman](aod_raman.md)。

## 可复现验收

`python examples/validate_gate_contract.py` 生成 `artifacts/gate-contract`，各案例均调用不运行 compiler 的独立 verifier：

- 四个 H：四门均 0–1 μs，总 1 μs。
- H/X/H/X 分别在四个 qubit 上：H 组 0–1 μs，X 组 1–2 μs，总 2 μs。
- 四 H 后接四 T：两层共 2 μs。
- 混合 CZ 与单比特：检查全部门区间，异类型不重叠，运输允许合法重叠。
- 决策预算失败：保留真实部分执行、失败原因和下载报告。

专项 `tests/test_gate_contract.py` 还覆盖不支持门的双层拒绝、异类型计划原子性拒绝、全部事件边界恢复。最终结果见 [本轮日志](../instruction/logs/2026-09-11-gate-contract.md)。
