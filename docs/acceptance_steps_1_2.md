# 步骤 1、2 验收

状态：已实现并通过自动测试；现已继续完成 [步骤 3](dag.md)。本文保留步骤 1、2 验收方法。

## 运行条件

Python 3.10+。步骤 1、2 本身无第三方依赖；项目使用 src layout。
运行当前完整测试集请安装：`python -m pip install -e ".[visualization]"`。
仅运行步骤 1、2 时，也可在 PowerShell 设置 `$env:PYTHONPATH = 'src'`。

## 步骤 1

运行 `python examples/demo_code_topology.py`。

核对：9 data、8 ancilla、4 X checks、4 Z checks；4 个 weight-2 和4 个 weight-4 checks。
拓扑、顺序和 logical operators 见 [接口文档](qec_interfaces.md)。

自动验证：stabilizer group 大小 256（rank=8）、无 weight-1/2 logical Pauli，
存在 weight-3 logical Pauli；替代 code factory、生效的输入校验和多个 block ID。

## 步骤 2

运行 `python examples/demo_syndrome_circuit.py`。

核对：控制台列出每个 ancilla 的 data interaction sequence；
`results/syndrome_circuit.json` 含 17 个 qubit、104 个 gate，
每个 gate 包含 ID、类型、qubits、predecessors、round/check metadata。

运行 `python examples/demo_syndrome_circuit.py --primitive CNOT --output results/syndrome_cnot.json`。
预期：56 个 gate，其中 24 CNOT；X check 的 ancilla 是 control，Z check 的 ancilla 是 target。

运行 `python examples/demo_syndrome_circuit.py --rounds 3 --output results/syndrome_three_rounds.json`。
预期：312 个 gate，24 个唯一 measurement keys，下一轮准备依赖上一轮 reset。

运行 `$env:PYTHONPATH = 'src'; python -m unittest discover -s tests -v`。
检查 gate counts、实际测量算符及符号、CZ/CNOT 等价、依赖允许的重排、非法顺序拒绝。

## 本次验收重点

1. qubit/check 命名及表中的 stabilizer 支撑集是否符合预期。
2. 默认实例与 QECCode/CSSCode 可替换方式是否合适。
3. syndrome 序列、CZ 分解和 round 边界是否接受。

验收通过后再实现步骤 3：PhysicalCircuitDAG 的 successors、ready_set 和状态推进。
