# 从已有编码输入续接 ZZ / XX

2026-10-03：[`encoded_composition.py`](../src/neutral_atom_experiments/qec_pbc/encoded_composition.py) 新增可组合接口，解决原 `encoded_parity_program()` 同时制备 A/B/C、不能直接接到已有算法态上的问题。

`append_encoded_parity()` 保留已有 `PBCProgram` prefix 的所有角色、操作、测量 ID、detectors、observables 和条件。**新增部分只初始化 C patch；A/B data 不 RESET、不重新制备，不接受输入逻辑 basis/sign。** 默认 C 是新 patch；显式回收条件满足时可复用已消耗的 C。canonical syndrome 辅助原子仍按真实测量后 RESET 的协议复用。

这是已有 encoded input → encoded parity native circuit 的组合能力与理想 channel 验证。完整 Shor 的 encoded 执行仍未接通；没有调用当前“从零初始化 51 个原子”的物理 runner，也没有把该 runner 直接当成组合后的平台 adapter。

## 接口与输入条件

```python
from neutral_atom_experiments.qec_pbc.encoded_composition import append_encoded_parity

first = append_encoded_parity(prefix,
    incoming_sectors=sector_history,
    basis='Z', rounds=3, data_patches=('A', 'B'), ancilla_patch='C')

second = append_encoded_parity(first.program,
    incoming_sectors=first.output_sectors,
    basis='X', rounds=3, data_patches=('A', 'B'), ancilla_patch='C2')

native = second.compile()  # native circuit + classical sidecar; no physical execution
```

`sector_history` 的 16 个 key 是 `(patch, 'X'/'Z', check_index)`，value 是 `BitExpr`。表达式必须引用 prefix 内真实已发生的 semantic measurement IDs，不能是虚构的 external result，也不能只给一个假定的 0/1 常数。

例如前一轮 `A.Z2` 的测量后执行了会翻转该 check 的物理 Pauli，则当前历史可以是：

```python
sector_history['A', 'Z', 2] = BitExpr(('A.r2.Z2',), constant=1)
```

这项 constant 是明确的 signed sector 传递，依赖前序电路；没有替用户猜测、设置或纠正量子态。调用者必须声明其前序逻辑/物理操作怎样传递这些 check sectors。

A/B 必须各具有现有 canonical 9 data + 8 syndrome roles；syndrome 辅助必须由 prefix 明确 RESET/release。否则接口拒绝，不隐式补 A/B 的初始化。高层 `PauliMeasurement` 的既有 lowering 包含真实 ancilla release RESET，因此该合同也支持此类 prefix。

C 默认必须是 prefix 中不存在的新 patch；第二次测量可用 C2。也可明确请求回收：

```python
second = append_encoded_parity(first.program,
    incoming_sectors=first.output_sectors,
    basis='X', ancilla_patch='C', resource_reuse=True)
```

只有既有 C 的完整 canonical 角色一致、9 个 data 最近操作均为显式破坏性 `MEASURE` 或 `RESET`、8 个 syndrome 最近操作均已 RESET/release 时，才允许 `resource_reuse=True`。未消耗的 C、部分 readout、脏辅助或残缺角色都会拒绝。未显式请求 reuse 时，既有 C 仍拒绝。

每次 reuse **真实执行全部 17 个 C 原子的 RESET 和所需 H 制备**，再运行完整 before/after checks；没有静默消去旧纠缠或 postselect 资源态。前序测量 bits 和 observables 保持；新 namespace 是新的 resource epoch，避免新 readout 覆盖旧结果。这是联合测量辅助 patch 的回收，不能宣称 T-state 制备/蒸馏工厂复用。

两块 A/B 与两个 reference 的连续 ZZ→XX，fresh C2 使用 70 roles；复用同 C 使用 **53 roles = A/B 34 + C 17 + refs 2**。这是声明 native 角色数，不是包括额外 spectator 与平台设施的物理峰值测量。

## 时间、IDs 与 detector 历史

新增首 phase 等待整个 prefix 的 terminal frontier。operation/phase/detector/observable IDs 自动使用独立 namespace；冲突时生成 `.next1` 等后缀。角色和所有 prefix IDs 原样保存。

沿用[编码 PPM](qec_encoded_ppm.md)的完整 before/after canonical rounds、两次 transversal CNOT、sector transfer 和 C 的逻辑读出：

- 第一轮 A/B 的全部 16 个 detectors 为 `incoming_sector XOR new_measurement`，包括历史 constant。
- 第一轮 C 只有已知制备 basis 的 detectors；异基随机 sector 不假定为 0。
- CNOT 后第一轮按真实 Heisenberg sector transfer 比较前序 check bits。
- 其余 rounds 比较相邻时刻 syndrome，C 数据读出闭合检查保持。
- A/B 保留全部 data；`output_sectors` 返回最后实测的 16 项 sector expressions，供下一段续接。

新模块的 phases/couplings 描述新增区段；完整 prefix 的已有 sidecars 仍属于调用者的前序协议。`compile()` 能导出整段 native circuit，但组合后的物理布局、绑定、已执行 placement 与资源区域仍需另适配。

## 独立 native instrument 验收

[`test_qec_encoded_composition.py`](../tests/test_qec_encoded_composition.py) **25 项通过**：

- A/B 多种实际前序制备 basis/sign；所有制备与 syndrome 都真实执行。
- 已实测 sector 后的物理 Pauli 翻转，正确 constant 时 detectors 全零；错误历史 constant 触发独立 native replay 失败。
- ZZ→XX、XX→ZZ、ZZ→ZZ、XX→XX 两次连续测量，保留前序操作与全部数据。
- 前序原生操作实际把 A/B 分别与两个 reference 原子纠缠；每个输出分支对照 **全部 256 个 logical/reference Pauli 期望值**，证明完整约化 density operator 一致，包括相干和 reference 纠缠。
- Prefix 操作对象、依赖、semantic measurement 引用、incoming/outgoing histories、native CZ sidecar IDs 合法。
- 同 C 的 ZZ→XX、XX→ZZ、ZZ→ZZ、XX→XX 真实 RESET/reprepare，前序量子态与 signed histories 保持，53 roles，全部 logical/reference Pauli 对照通过。
- 虚构 measurement、缺失 history、常数假输入、脏 syndrome 辅助、默认 consumed C reuse、部分 C readout 与未消耗/残缺 C 明确拒绝。

`verify_composed_instruments()` 先执行真实 prefix，理想 oracle 在新增 instrument 边界复制**已执行得到的 prefix state**，之后只施加独立的 ideal logical parity projector；native simulator 的输入没有被期望态覆盖。Native C 读出的实际结果决定 oracle branch，同时检查它在理想输入上的条件概率非零。没有向生产电路加入 audit-only MPP、postselection 或外部 measurement 结果。

每次还检查所有新增 detectors、16 个真实 closing-sector 期望。验证说明的是 ideal instrument；组合后的 native fault audit、decoder 与原子 Executor 仍须另外验收。

```powershell
$env:PYTHONPATH='artifacts/qec-baseline-deps;artifacts/qec-pbc-test-deps;src'
& 'C:\Users\yuyqp\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_qec_encoded_composition.py -q -p no:cacheprovider --basetemp artifacts/pytest-encoded-composition
```

使用既有隔离 `stim==1.15.0` 参考依赖；缺依赖的 skip 不算通过。输出保持 `physical_executed=false`、`complete_algorithm_encoded=false`。
