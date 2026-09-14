# 四个 surface-code logical qubit 的 GHZ：实验定义与独立核验

核验日期：2026-09-11。量子定义已实现于 `src/neutral_atom_experiments/surface_ghz.py`，物理执行由工作台及实验调度器负责。这里给出包含完整编码的 36 个数据原子线路：四块旋转 `[[9,1,3]]` surface code，制备 `( |0000>_L + |1111>_L ) / sqrt(2)`。这是理想无噪声编码和编译实验，不含 syndrome 测量、纠错轮次、decoder、测量后选择或保真度模拟；不称完整容错 QEC。

## 一手依据与适用边界

- [Bluvstein 等，Logical quantum processor based on reconfigurable atom arrays](https://arxiv.org/html/2312.03982v1)，Nature 626 (2024)，主文 Fig. 2 与 Methods “Transversal gates”：同构 CSS 码可通过对应数据比特之间的 transversal CNOT 实现逻辑 CNOT，作者在 surface code 上演示该操作。其具体 surface-code 制备使用 stabilizer 测量；其四 logical GHZ 演示使用 color code。我们的无测量 surface-code GHZ 是下文明确推导的实验线路，不能称该文 GHZ 实验的逐项复现。
- [Chen 等，Transversal Logical Clifford gates on rotated surface codes with reconfigurable neutral atom arrays](https://arxiv.org/html/2412.01391v1)，作者预印本 v1 (2024-12-02)，Fig. 1 与第 II 节：所有数据比特施加 H 会交换 X/Z 稳定子和边界，需配合 patch 旋转或等价置换才回到原编码约定。因此本实验直接编码 `|+>_L`，没有把九份物理 H 误当作固定 patch 的逻辑 H。
- [Horsman 等，Surface code quantum computing by lattice surgery](https://arxiv.org/html/1111.4022v2)，New Journal of Physics 14, 123011 (2012)，旋转 surface-code 讨论：提供平面旋转码的局域稳定子构造背景。本实验将码的连接图和原子的即时物理排布分开；row 布局通过原子运输实现非邻接门，不声称始终保持二维最近邻硬件连接。

## 码定义

每个 patch 的局部数据编号如下。全局编号为 `Q(9*b+q)`，其中块号 `b=0..3`、局部号 `q=0..8`；Q ID 补足三位。此 3×3 图定义量子码，当前公平比较的物理初态是 36 原子单行、相邻 10 μm，而非四个物理 3×3 方阵。

```text
0 1 2
3 4 5
6 7 8
```

下表每行表示正号稳定子；未列出的数据比特作用 I。

| 类型 | 四个 support |
| --- | --- |
| X checks | 0134；4578；12；67 |
| Z checks | 1245；3467；03；58 |
| logical X | 036 |
| logical Z | 012 |

八个 checks 独立、两两对易，logical X/Z 与它们对易且相互反对易。独立穷举所有权重 1、2 的 X/Y/Z Pauli，未发现非平凡逻辑算符；权重 3 首次发现，故距离为 3。

## 确定的完整编码线路

全部数据原子初始量子态假设为 `|0>`。令 `C_X` 为四个 X checks 的二进制 support 张成空间：

```text
|0>_L = (1/4) sum_{c in C_X} |c>
|+>_L = (1/sqrt(32)) sum_{c in span(C_X, logical_X)} |c>
```

下列两个系统形式生成矩阵分别张成这些空间。括号左侧为独占 pivot，右侧是该 row 的其余 1；先在所有 pivot 做 H，再按给定次序执行每个 pivot 到右侧各数据比特的 CNOT。因为任何 pivot 不出现在其他 row 中，此电路恰好生成指定均匀正幅叠加。

| 制备 | H targets | CNOT control → targets |
| --- | --- | --- |
| `|0>_L` | 0,1,5,6 | 0→2,3,4；1→2；5→4,7,8；6→7 |
| `|+>_L` | 0,1,4,5,6 | 0→3,7；1→2；4→2,7；5→2,8；6→7 |

每块使用 8 个 CNOT。该数是本构造的成本，不声称所有量子编码线路中的全局最优，也不声称此编码具有单故障容错性。block 0 制备 `|+>_L`，其余三块制备 `|0>_L`。

之后顺次执行逻辑 CNOT `0→1`、`0→2`、`1→3`。每个逻辑 CNOT 是对应局部号 `q=0..8` 间九个物理 CNOT。CSS 的 X/Z checks 分别传播为对应 checks 的乘积，仍处于码空间；logical X/Z 按标准 CNOT 共轭传播，最终为四块 GHZ。最后两个逻辑 CNOT 作用于不同块，可由依赖调度重叠；当前物理平台逐个 CZ 执行，没有用批量 CZ 规避 M5 边界。

所有物理 CNOT 展开为时间顺序 `H(target), CZ(control,target), H(target)`。线路最终 **194 门 = 135 H + 59 CZ**，其中编码 32 个 CNOT、逻辑互连 27 个 CNOT，额外 17 个初始 H。未做跨门 H 抵消。原生门只用当前许可门集中的 H/CZ。

编辑器用同一比特的先后依赖计算 ASAP column，共 17 列（0–16）。column 不是物理时刻，也不是强制全局阶段 barrier；不共享比特的后续阶段门可以提前出现。导入后按 column 排序再次独立验证，证明这种重排保留目标态。

## 独立核验与接口

`verify()` 不调用 compiler、Executor、物理 validator 或第三方量子库。它用带符号 Pauli tableau，表示 `i^p X^x Z^z`，精确跟踪 H/CZ/CNOT 的相位，验证：

1. 局部八 checks 的独立性、对易性，logical ops 的正确关系，Pauli 权重穷举得到距离 3。
2. 两种编码分别属于完整码空间且对应 logical Z 或 X 正本征态。
3. 完整 abstract CNOT 线路与原生 H/CZ 线路的最终有符号稳定子群相同。
4. 最终 32 个码稳定子以及 `Z_L0 Z_L1`、`Z_L0 Z_L2`、`Z_L0 Z_L3`、`X_L0 X_L1 X_L2 X_L3` 均为正本征值，36 个生成元独立，因此唯一确定目标 GHZ 态。
5. 删除最后的逻辑 CNOT 层会被拒绝。测试还删除单个 CZ，检查验证器不会沿用正确样例的标签。

测试另用 512 维稠密实振幅直接演化每个 9 数据比特编码器，与上述 CSS 均匀叠加定义比较，作为与 signed tableau 不同实现的检查。`tests/test_surface_ghz.py` 本轮 **6 passed**。

```python
from neutral_atom_experiments.surface_ghz import (
    experiment_input, experiment_stages, phase_columns, verify_gate_sequence, verify,
)
raw = experiment_input(compiler='row_greedy')  # 或 row_symmetric
report = verify()
assert verify_gate_sequence(sorted(raw['gates'], key=lambda g: (g['column'], g['id'])))
```

两策略输入只在 `compiler` 字段不同：36 data qubits、row、seed 0、adaptive EZ、单台 AOD 的 36 个可控列，线路完全相同。每次调用返回新对象，编辑草稿不会污染模板。工作台字段使用已有 `gate_type`，不添加其他门种；阶段注释由单独的 `experiment_stages()` 返回。模板显式携带本实验高预算：ready/site 各 128、lookahead depth 8、beam 32、rollout 4096、row candidate 4096、route expansions 100000、编译时限 3600 秒。预算放开不能视为编译完备性证明。

`verify_gate_sequence(gates)` 可验证实际门完成顺序，但原子轨迹、光照资格、资源冲突、终态归还仍需独立物理 replay 检查。理想编码通过不能替代这些检查，反过来，物理 trace 合法也不能自动证明逻辑 GHZ 正确。用户编辑线路后仍可正常编译，但只有再次通过量子目标验证，才可以显示此 GHZ 已实现。

复现量子产物：`python examples/research_surface_ghz.py --output artifacts/surface-ghz-research`。这里的门数仅对应理想量子定义；最终物理调度对比和浏览器验收由本轮实验报告记录。
