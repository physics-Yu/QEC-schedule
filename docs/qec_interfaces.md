# 步骤 1–2：接口与电路约定

## 当前边界

实现 LogicalIR、可替换 QECCode、默认 d=3 rotated surface code 和完整 syndrome 门序列。
尚未实现 LogicalIR 到容错逻辑门的编译、PhysicalCircuitDAG ready-set、硬件模型或调度器。
LogicalH / LogicalCNOT 出现在 IR 中只表示可表达，不表示已实现其容错编译。
本阶段输出是 physical circuit JSON，不是带起止时间的实验 trace。

## 替换 code

`QECCode` 是基类，接口只涉及抽象 qubit ID、Pauli product 和 syndrome circuit：

- `data_qubits()`、`ancilla_qubits()` 返回抽象 ID。
- `stabilizers()` 返回 stabilizer、对应 ancilla 及有序 interaction。
- `logical_x()`、`logical_z()` 返回逻辑算符元组，支持多对逻辑算符。
- `syndrome_round(rounds=1, primitive="CZ")` 返回 `PhysicalCircuit`。
- `validate()` 检查引用、ID 唯一性、stabilizer 对易和 logical operator 对易关系。

CSS code 继承 `CSSCode`，提供拓扑即可复用 syndrome generator。
混合 X/Y/Z stabilizer 的 code 可继承 `QECCode`，自行提供 extraction；
不会强行套用 surface-code 电路。当前公共 stabilizer 数据模型约定正号生成元，
每个 check 使用独立 ancilla；需要负号生成元、共享 ancilla、flag 或 subsystem
gauge 测量时，需要扩展这个模型及其校验。

```python
from qec_schedule.qec import default_registry

registry = default_registry()
registry.register("my_code", MyCode)  # MyCode 实现 QECCode / CSSCode
code = registry.create("my_code", **my_parameters)
circuit = code.syndrome_round()
```

也可直接构造 MyCode 并注入后续编译器。注册表按实例隔离，不修改全局状态；
重名注册会报错。默认 `create_code()` 选择 `rotated_surface`。
不同编码块使用不同 `block_id`，例如 L0、L1，生成互不冲突的 qubit ID。
测试中用独立 repetition code 验证注册与 extraction，不依赖 surface-code 类型判断。
该 repetition code 仅验证接口，不宣称能够纠正任意单 qubit Pauli 错误。

## 默认拓扑

data qubit 的 dimensionless lattice coordinates：x 向右，y 向下。
这些坐标不是实验 atom 坐标，不包含长度单位、AOD 或 zone。

```text
d0  d1  d2
d3  d4  d5
d6  d7  d8
```

| Check | Support（也是 interaction 顺序） | Ordering slots |
|---|---|---|
| X0 | d0,d1,d3,d4 | 0,1,2,3 |
| X1 | d4,d5,d7,d8 | 0,1,2,3 |
| X2 | d1,d2 | 2,3 |
| X3 | d6,d7 | 0,1 |
| Z0 | d1,d4,d2,d5 | 0,1,2,3 |
| Z1 | d3,d6,d4,d7 | 0,1,2,3 |
| Z2 | d0,d3 | 2,3 |
| Z3 | d5,d8 | 0,1 |

Logical X = X(d0)X(d3)X(d6)；Logical Z = Z(d0)Z(d1)Z(d2)。
只有 distance=3 是当前支持的实现，其他 distance 明确报错。
测试穷举 stabilizer group 和 weight≤3 的 Pauli operators，验证 rank=8、distance=3。

## Syndrome 语义

输入 data qubits 被视作已存在；不会偷偷执行 data preparation 或声称已编码 |0_L>。
每轮显式生成：

- X check：PREPARE ancilla |0> → H(ancilla) → CNOT(ancilla,data)... → H(ancilla) → MEASURE_Z → RESET |0>。
- Z check：PREPARE ancilla |0> → CNOT(data,ancilla)... → MEASURE_Z → RESET |0>。
- 默认 CZ primitive：每个 CNOT(c,t) 展开为 H(t) → CZ(c,t) → H(t)。

当前不消除相邻 H；因此单轮为 104 个门：24 CZ、56 H、8 PREPARE、8 MEASURE_Z、8 RESET。
CNOT 模式是 56 个门：24 CNOT、8 H 和相同的 24 个 ancilla 生命周期操作。
measurement_key 包含 round 与 check ID；不生成测量结果、不运行 decoder。
重复 rounds 时，下一轮 PREPARE 依赖上一轮所有 RESET。该显式轮次边界保守且便于验收；
以后允许跨轮流水时需要单独设计。PREPARE 表示准备请求，RESET 表示测量后的重置请求，
后续硬件层需要定义其耗时及是否可融合，当前不为它们附加任何时间。

## Ordering 与依赖

Ordering slots 确定合法参考电路顺序，不是预先固定的硬件执行层。
X 使用 NW→NE→SW→SE；Z 使用 NW→SW→NE→SE，边界继承对应位置的 slots。
CSS validator 检查同 slot 的 data 冲突，以及相反基 checks 的共享 data 先后关系，
避免 extraction 意外产生 ancilla 间耦合。

每个 physical gate 的 predecessors 记录涉及 qubit 的上一操作，加上显式轮次边界。
因此独立 gate 不加全局 slot barrier，硬件调度可以延迟操作，但必须遵守依赖。
第三步将在这些记录之上实现 DAG、successors 和 ready_set，不在本步引入 scheduler。

测试使用含相位符号的 Clifford Pauli 传播，验证每个 measurement 实际对应目标 stabilizer，
验证 CNOT 与 CZ 电路对完整 Pauli 生成集合的作用一致，并检查随机合法重排。
这里验证的是理想门电路和编码代数，不是带噪声的 circuit-level fault distance。
interaction ordering 的重要性也见 [Katsuda 等，PRR 6, 013024 (2024)](https://doi.org/10.1103/PhysRevResearch.6.013024)。
