# PBC 与 T 注入实现边界审计

**用户要求的完整 logical circuit → 自适应 PBC → surface-code T 注入 → physical circuit，目前未实现。** 当前已有的 PPR 规范化、理想注入分支验证和组件物理门片段，不能合起来宣称该端到端功能已完成。

本次为 2026-10-03 独立只读代码审计。除本说明外没有修改功能；没有运行新的物理测试，不将历史 memory 验收推广到 T 注入或算法执行。

| 路径 | 已实现内容 | 实际输出／证据边界 | 代码 |
| --- | --- | --- | --- |
| Logical Clifford+T → PPR | 精确 signed Pauli rotations、剩余 Clifford 与全局相位 | `LogicalPauliProgram`；任意输入酉语义。没有标准 BSS 稳定子寄存器消去，也没有生成自适应测量电路 | [logical_pauli.py](../src/neutral_atom_experiments/qec_pbc/logical_pauli.py)，`compile_logical_pauli` |
| 模幂 → PPR | 算术门展开成 Clifford+T，再调用上述规范化 | 逻辑算术结果、PPR 与资源需求；没有 QFT、完整 Shor、资源工厂或原子调度 | [shor_frontend.py](../src/neutral_atom_experiments/qec_pbc/shor_frontend.py)，`compile_arithmetic`；[visual_report.py](../src/neutral_atom_experiments/qec_pbc/visual_report.py)，`shor_experiment_data` |
| Logical T/Tdg injection | 输入资源态请求、data→resource CX、资源 Z 测量、分支 S/Sdg 校正 | `MagicInjection` 逻辑 instrument 合同；没有 `PBCProgram` 或 `PhysicalCircuit` lowering | [magic_injection.py](../src/neutral_atom_experiments/qec_pbc/magic_injection.py)，`make_magic_injection` |
| 注入理想验证 | 直接输入理想 T/Tdg 复振幅，检查两个测量分支与校正后状态 | NumPy 小规模参考、`ideal_reference` 资源质量。没有资源态物理制备、编码 injection、蒸馏或 Executor 执行 | [visual_quantum_experiments.py](../src/neutral_atom_experiments/qec_pbc/visual_quantum_experiments.py)，`_injection_experiment` |
| 协议 `PBCProgram` → 物理门 | X/Z Pauli product 的裸辅助原子测量，以及已支持的 primitive | 返回 `CompiledPBC.circuit: PhysicalCircuit`；Y 测量拒绝，`require_fault_tolerant=True` 拒绝。这里的协议 IR 不等于通用标准 PBC 编译器 | [ir.py](../src/neutral_atom_experiments/qec_pbc/ir.py)；[lowering.py](../src/neutral_atom_experiments/qec_pbc/lowering.py)，`lower_to_physical` |
| Canonical coupling → backend | 保留有向 CNOT、H target 与层依赖，能力／静态配对检查 | `LayerRequest`；预检查不是实际 placement、运输、pulse 或 Executor 验收 | [backend_contract.py](../src/neutral_atom_experiments/qec_pbc/backend_contract.py)，`layer_requests`、`canonical_layer_requests` |
| Transversal CNOT／逻辑 H 片段 | 同朝向双块 9 对 CNOT 展开成 27 门 H–CZ–H；单块 9 H 并更新码朝向 | 可以返回 `PhysicalCircuit` 片段；无配套 QEC rounds/detectors、无实际原子执行，未证明带噪容错 | [logical_gadgets.py](../src/neutral_atom_experiments/qec_pbc/logical_gadgets.py)，`physical_coupling`、`physical_circuit` |
| 阶段 A canonical memory | 完整 canonical memory 协议接既有物理后端执行 | 独立 memory 的原生门、实际 accepted plans、Executor trace 与重放证据；不包含逻辑 T 或完整算法 | [baseline.py](../src/neutral_atom_experiments/qec_pbc/baseline.py)，`canonical_native_inputs`、`execute_canonical_memory`；[阶段 A 说明](qec_stage_a_baseline.md) |

## 条件校正与连接缺口

`MagicInjection` 的 outcome=1 分支要求 T 注入执行 S、Tdg 注入执行 Sdg。当前 [协议 IR](../src/neutral_atom_experiments/qec_pbc/ir.py) 的 `GateTask` 只接受 H/X/Z/CZ/RESET/MEASURE，条件操作只允许 X/Z。[原生 PhysicalGate](../src/neutral_atom_env/domain/models.py) 的 measurement-bit 条件同样只支持 X/Z。因此不能把上述 S/Sdg 分支当作已经可以由当前物理后端执行。

当前不存在从 `LogicalPauliProgram` 到 `MagicInjection` 序列，再到编码联合测量、资源消耗、条件校正及完整 `PhysicalCircuit` 的转换连接。已有 X/Z 裸辅助测量 lowering 没有提供容错 logical PPM，无法替代这部分工作。

## 图示应表达的真实含义

E1/E6 的 PPR 表及 residual Clifford 电路只能说明逻辑规范化。它们没有展示自适应 PBC 测量电路或 surface-code T 注入的 physical graph；“完整编译结果”应被理解为当前逻辑表示的完整结果，不能理解为用户要求的完整物理编译。

注入参考中的理想 `|T⟩`／`|Tdg⟩` 是**实验输入边界**：资源从外部作为既知复振幅进入。图上应标明 `ideal_reference resource input`，不能画一个暗示已实现制备操作的 `PREP` 门。CX、Z 测量及 S/Sdg 分支也是逻辑 instrument 的图示，不代表已运行原子脉冲、编码测量或工厂。

本说明仅记录实现事实与缺口，不新增物理能力或执行声明。
