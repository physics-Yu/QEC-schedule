# signed Pauli rotations → 自适应资源测量程序

2026-10-03：[`adaptive_pbc.py`](../src/neutral_atom_experiments/qec_pbc/adaptive_pbc.py) 新增真正执行理想 measurement instrument 的资源桥。它接收既有 `LogicalPauliProgram`，将每个正/负 π/8 指数 Pauli rotation 转成外供 T/Tdg resource、两次 Pauli 测量、测量条件 Clifford/Pauli 纠正，再执行 residual Clifford。

它保留 data 逻辑寄存器及任意输入/量子输出合同，没有执行 BSS 的 stabilizer-register 消去。输出为**logical resource-aware measurement program**；encoded PPM、encoded magic 制备、原生门、原子运输和 Executor 是后续接口。既有 surface memory 的物理证据与此理想 instrument 证据分别记账。

## 每个 rotation 的可执行合同

源约定与 [RAG §5](qec_pbc_rag.md) 一致：

```text
R_P(s) = exp(-i sπ P/8),       s ∈ {+1,-1}, P†=P, P²=I
|A_s>  = (|0> + exp(i sπ/4)|1>)/sqrt(2)
T_P(s) = Π+ + exp(i sπ/4)Π- = exp(i sπ/8) R_P(s)
S_P(s) = Π+ + exp(i sπ/2)Π-
```

每个 resource 有唯一 wire、T/Tdg state、provenance、quality 和生命周期。执行顺序：

1. 声明外供逻辑 `|A_s>`。制备尚未实现，成本不记为 0。
2. 非破坏性测 signed `P ⊗ Z_resource`，得到 m。
3. 在 X 基破坏性读出 resource，得到 r。
4. m=1 时执行 `S_P` 或 `Sdg_P`；r=1 时执行 signed P。
5. resource 标为 consumed，禁止与 data alias 或再次使用。
6. 下一 rotation 完成后，按原顺序执行 residual Clifford。

测量采用 `+1 → 0、-1 → 1`。P 的负号和 Y 保留到实际投影中；资源 T/Tdg 的选择只由 s 决定。多体 `S_P` 是一般 Clifford，不能冒称只在某一个 data 上执行 S。

| m | r | 未纠正 Kraus | 左乘纠正 | 纠正后的分支 |
| ---: | ---: | --- | --- | --- |
| 0 | 0 | `T_P(s)/2` | I | `T_P(s)/2` |
| 0 | 1 | `P T_P(s)/2` | P | `T_P(s)/2` |
| 1 | 0 | `w_s T_P(s)†/2` | `S_P(s)` | `w_s T_P(s)/2` |
| 1 | 1 | `-w_s P T_P(s)†/2` | `P S_P(s)` | `-w_s T_P(s)/2` |

其中 `w_s=exp(i sπ/4)`。每个 joint branch 概率 1/4；纠正之后均得到目标 channel，分支 global phase 显式记录。

## 不重复计入 global phase

源前端的目标为：

```text
U_source = exp(i φπ/8) C R_last ... R_first
```

注入实际实现 `T_P(s)`，每次自带 `exp(i sπ/8)`，所以资源程序最后只施加：

```text
global_phase_eighth_turns = (φ - sum(s)) mod 16
```

普通 Clifford+T 前端本来就保存 `φ=sum(s) mod 16`，因此其资源程序的补偿相位恰为 0。这个 0 来自相位推导，不能在任意手写 `LogicalPauliProgram` 上直接假设。每条 measurement branch 的额外相位另外记录，不重复算进源 global phase。

目前只支持 `quarter_turns=+1/-1`；0、±2、3、4 等明确拒绝，并报告未实现的角度。没有把任意角度静默替换为一份 magic resource。

## API 与理想执行

```python
from neutral_atom_experiments.qec_pbc.adaptive_pbc import (
    compile_adaptive_pbc, execute_reference, audit_adaptive_pbc)

program = compile_adaptive_pbc(logical_pauli_program,
                              resource_quality='ideal_reference',
                              resource_provenance='explicit ideal vectors for this reference')
payload = program.to_dict()
result = execute_reference(program, normalized_state,
                           reference_qubits=1, seed=7)
report = audit_adaptive_pbc(logical_pauli_program,
                            reference_qubits=1, seed=7)
```

态向量采用 **big-endian data wire 顺序，后接 reference wires**。这与 `shor15.py` 的 little-endian 算术索引不同，调用独立算术 oracle 时必须显式转换；测试覆盖了这个接口。

`execute_reference` 实际追加 resource 态，投影 signed PZ，按投影概率选择 m，投影 resource X，选择 r，归一化并实际施加两项条件纠正。它不是直接把结果赋为目标 rotation。可传 `outcomes=((m,r),...)` 重放指定分支，数量必须与 injections 一致。

资源默认 quality 为 `unknown`。此时理想 executor 必须收到显式 `assume_ideal_resources=True` 才运行，结果记录这项假设，资源合同本身仍保持 unknown。声明 `ideal_reference` 仅说明验证向量，不代表物理资源质量。

`audit_adaptive_pbc` 返回 JSON 验证报告；可传 `expected_state` 对照调用者的原线路 oracle。默认按源 Pauli rotation、residual Clifford 和源相位独立计算目标，不使用测量过程来构造目标。资源顺序消耗，临时态只需 data/reference 维度的两倍，不建立全部 magic wires 的指数维度态向量。

## 已完成验收

[`test_qec_adaptive_pbc.py`](../tests/test_qec_adaptive_pbc.py) 新增 **37 项通过**；与完整 Shor、既有算术前端、Pauli 前端及 magic contract 合计 **89 项通过**：

- T/Tdg、X/Y/Z、负 Y、负 mixed Pauli、±I 的全部四分支，独立 tensor/projector Kraus、概率及 data-reference channel。
- 三个非对易 rotation 的全部 64 条分支、任意源 global phase、residual Clifford 与纠缠 reference；倒序结果确实不同。
- 源 Clifford+T 原门序列对照，含由 inverse Clifford frame 产生的负 Y，验证相位未重复。
- [N=15 Shor](qec_shor15.md) 制备/模幂前缀的 **35 份 magic resources、70 次测量**，任意 4096 维复数输入，与原 X/H/CX/CCX 线路独立对照。
- consumed-resource reuse、data alias、measurement ID 冲突、重复 global phase、坏分支输入和未知质量拒绝。

35-resource 前缀带 1 个 reference 比特的独立实跑：8192 amplitudes，最大临时维度 16384，全部资源 consumed；与源 unitary 最大误差 `4.05e-17`，单次条件概率最大误差 `4.44e-16`。源相位为 5 个 π/8，资源程序补偿相位为 0。

```powershell
$env:PYTHONPATH='artifacts/qec-pbc-test-deps;src'
& 'C:\Users\yuyqp\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_qec_adaptive_pbc.py tests/test_qec_shor15.py tests/test_qec_shor_frontend.py tests/test_qec_logical_pauli.py tests/test_qec_magic_injection.py -q -p no:cacheprovider --basetemp artifacts/pytest-adaptive-pbc-reference
```

## 尚需连接的边界

这一桥使既有 Shor 算术前缀从酉 PPR 变成了可执行的理想资源测量程序。完整 Shor 的逆 QFT 仍有一般角度 CP，尚未通过 Clifford+T 综合/误差预算，不能宣称整个 Shor 已转为此程序。

后续把每项 logical PPM、mixed/Y 支持、一般条件 Clifford、资源生命周期与质量合同映射到 encoded protocol，再连接原子调度及 Executor。encoded ZZ/XX 是否已获得完整物理证据，以本轮独立协议交付和 handoff 为准；本说明不把逻辑 instrument audit 当作物理验收。
