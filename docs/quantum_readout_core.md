# 理想量子读出与复位底座

2026-09-12，按用户授权扩展真实辅助原子测量与纠错；本文件描述执行底座，不代表所有 QEC 协议或噪声模型已经验收。

## 接口与物理边界

`SimulationState` 默认保持几何模式。通过
`replace(state, quantum_state=StabilizerState.zero(tuple(sorted(state.atoms))))`
显式启用理想纯稳定子跟踪；量子态覆盖全部物理原子。H/X/Y/Z/CZ 由实际物理操作完成事件应用到量子态；T 在此模式明确拒绝，不能近似替代。普通几何模式仍保留 T。

线路门 `MEASURE`（核心兼容别名 `MZ`）和 `RESET` 都是单原子门。
`ProgramBuilder.add(OperationType.MEASUREMENT, label, gate_ids=(...))`
或 `OperationType.RESET` 接收不共享原子的同类门批次；单个门也可用 `gate_id`。
一个读出批次是一段 500 μs 物理设备区间，一个复位批次是一段 100 μs 区间；这两个默认值是项目明确的模拟假设，**不是实验设备标定值**。

所有目标必须存活、位于 measurement zone、由已启用 SLM 或静止 AOD 支撑；交接必须完成，整个 AOD 在读出/复位期间保持静止。操作占用 READOUT_0/RESET_0、AOD_0 以及目标原子/支撑资源。测量不删除原子、不移动 holder；它执行 Z 投影，将结果保存到 `measurement_results[gate_id]`，并设 `Atom.measured=True`。RESET 将实际量子态投影并恢复到 |0⟩，清除 measured 标记。再次打单比特光或 CZ 前必须完成 RESET；测量后再次测量是允许的。

本实现不推导读出保真度、光串扰、原子损失、加热或冷却模型，也不把理想量子投影等同于实验读出波形。

## 条件控制和依赖

`PhysicalGate.condition=((measurement_gate_id, bit), ...)` 是测量结果相等的 AND；仅允许 X/Z。每个引用必须指向线路中更早的 MEASURE/MZ。`depends_on=(gate_id,...)` 可显式添加更早门的依赖，DAG 合并这些依赖、条件依赖和逐原子依赖并去重。

条件门开始时，所有相关结果必须已经提交。条件成立则执行实际 Raman X/Z；条件不成立仍占用 1 μs 控制时隙并完成对应 DAG 门，但不改变量子态、不打 Raman 光、不累计 Raman busy time，资源记为 `CONTROL:<qubit>`。观察记录包含 `applied=false`，前端不能绘制虚假的光照。

## 确定性执行与恢复

纯预测、独立计划审计、实际 Executor 都使用同一不可变量子效应 reducer。每个 MEASURE/RESET 目标按操作中 gate_ids 的明确顺序消耗一个状态 RNG bit；确定性投影仍消耗该 bit，量子引擎仅在随机投影时使用它。因此每个给定种子、给定操作顺序都可逐字恢复，不在候选试算时修改实时 RNG。

checkpoint 升为 **schema 19**，保存量子态、结果、RNG，以及每个 scheduled program 的原始 atoms/量子态/结果/RNG。旧 checkpoint 必须从输入重新编译。带量子态的 ProgramBuilder 自动采用 scheduled program；手工提供的 legacy serial plan 会明确拒绝，避免漏掉量子效应。

恢复重新执行独立的物理与量子预测，并对比量子态、原子状态、结果、RNG、DAG、资源与时间；测量 trace 中的结果和条件门 applied 标记也会核对。VisualRecorder 的 operation 含最终测量结果及 applied，frame 含截至该时刻的累计 measurement_results；早期 frame 不会回填未来结果。

## 专项证据

`tests/test_quantum_readout.py` 包括 H→测量→复位→再次测量、纠缠 Bell 对批量读出的关联、真实 batch CZ 的独立稳定子预期、条件成立/不成立、MZ 外与运动期间拒绝、跨每个事件 checkpoint 续跑、结果篡改拒绝、控制资源及无光记录、程序后 RNG 恢复。运行记录由本轮交接日志汇总。

性能调整只复用不变依赖结构：DAG transition 不重复构建整张静态依赖图，restore 一次构建反向邻接；运行态 DAG 使用冻结 domain 对象直接比较。它们不跳过物理审计或依赖计数校验。
