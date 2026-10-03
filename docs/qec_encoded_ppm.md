# 三块 d=3 patch 的 encoded ZZ / XX 测量

本阶段把两块 surface-code 的联合 Pauli 测量展开为完整的原生电路。第三块 **完整 encoded ancilla patch** C 负责 parity；A、B 在测量后保留。实现：[encoded_ppm.py](../src/neutral_atom_experiments/qec_pbc/encoded_ppm.py)，专项检查：[test_qec_encoded_ppm.py](../tests/test_qec_encoded_ppm.py)。这条路线使用同朝向 transversal CNOT，不是 lattice surgery。

## 协议与资源

每块采用既有 `[[9,1,3]]` 编号、8 checks 和 logical representatives；不改变 canonical 四层 CSS extraction 顺序。[基线](qec_stage_a_baseline.md)、[逻辑 Clifford 合同](qec_logical_gadgets.md)

| 项目 | ZZ | XX |
| --- | --- | --- |
| encoded ancilla C | `|0_L⟩` | `|+_L⟩` |
| 第一组 transversal CNOT | A → C | C → A |
| 第二组 transversal CNOT | B → C | C → B |
| C 的 destructive readout | logical Z | logical X |
| 默认 A、B 输入 | `|+_L,+_L⟩` | `|0_L,0_L⟩` |
| 保留的默认输出 coherence | `X_A X_B=+1` | `Z_A Z_B=+1` |

共 **27 data + 24 syndrome = 51 个原子**，其中 C 的 17 个原子是 encoded parity 资源。Spectator、备份和 factory 不在此数目中。默认在 CNOT 前、后各执行三轮完整 canonical syndrome；每组 transversal CNOT 的九个有向 coupling 都展开为 `H(target) → CZ → H(target)`。每条 wire 的顺序、每个 phase 的依赖和所有 measurement IDs 保存在 sidecar，不将九对协议 coupling 当作一次可用硬件 pulse。

生产协议在 C 读出后结束，保留 A/B。参数 `close_data_basis` 只用于额外的、显式 destructive A/B diagnostic extension；开启后不能宣称输出保留量子态。

## 随机 syndrome sector 的处理

Canonical product preparation 的异基 checks 是随机的 signed sector。程序保留这些真实测量结果，不将它们当作错误或私自纠正。CNOT 后首轮 detector 必须按 stabilizer 的 Heisenberg pullback 计算：

| 协议 | 首个 closing round 中变化的 sector |
| --- | --- |
| ZZ | `sX(A)'=sX(A) XOR sX(C)`；`sX(B)'=sX(B) XOR sX(C)`；`sZ(C)'=sZ(C) XOR sZ(A) XOR sZ(B)` |
| XX | `sZ(A)'=sZ(A) XOR sZ(C)`；`sZ(B)'=sZ(B) XOR sZ(C)`；`sX(C)'=sX(C) XOR sX(A) XOR sX(B)` |

其他 sector 不变；公式对同编号的四个 X/Z checks 分别使用。后续 rounds 使用常规相邻轮 XOR。C 最终九个物理测量给出四个 closing detectors 和一个 logical parity observable。默认总计 **136 detectors**。

此处理由同朝向 transversal CNOT 对相同 CSS check support 的精确共轭推导，并由独立 Stim 检查。它没有假定所有 patch 初始 stabilizer 都为 +1。

## 理想 instrument 的验收

未签名测量的两个分支是

\[
K_b=\frac{I+(-1)^bP_AP_B}{2},\qquad P=X\text{ 或 }Z.
\]

`parity_sign=-1` 将语义输出 bit 翻转，对应测量 `-P_A P_B`。它不改变真实量子投影。程序允许 signed X/Z logical input eigenstates。

`verify_encoded_parity_instrument` 独立使用 Stim 对完整 native circuit 做 Choi 检查：在 encoded-input boundary，将 A/B 分别与两个未参与运算的外部 reference entangle；每个 parity branch 的真实概率必须是 1/2，再检查输出/reference 的全部四个稳定子。两种 basis、两个 parity sign 的每个分支都与理想 logical MPP 一致。这固定了任意输入、包括与外部系统纠缠输入的理想 branch channel。

Bell boundary projection 和强制分支仅在 audit 中使用；未把 MPP 写成硬件操作，也未对生产 shots 做 postselection。`retained_output_expectations` 为真实执行的 clean 输入提供 signed A/B closing checks、measured parity 与 retained coherence 的可检验期望。

## 原生门故障与 decoder 的边界

`audit_encoded_parity` 采用独立 Stim detector-error propagation，并逐项对照另一份 binary Pauli-frame propagation。Fault calibration 的 A/B 在所测 parity eigenbasis 中，保证 DEM observable 是确定量；默认的 entangling inputs 用于独立 instrument 检查，不把随机结果错当作 DEM 错误。

声明故障模型是：每个 H/X/Z 后的 X/Y/Z；每个 CZ 后全部 15 个非平凡两比特 Pauli products（每个 CZ 只计一个 fault）；每个 RESET 后的错误 `|1⟩`；每个 MEASURE 的 reported-bit flip（真实投影保持）。没有 transport、idle、loss、leakage 或硬件概率模型。

本轮 calibration 结果：

| 指标 | ZZ | XX |
| --- | ---: | ---: |
| 完整 native gates | 1842 | 1878 |
| H / CZ / RESET / MEASURE | 1044 / 450 / 195 / 153 | 1080 / 450 / 195 / 153 |
| 枚举 native fault mechanisms | 10230 | 10338 |
| detectors | 136 | 136 |
| 无 detector 的单 fault parity 错误 | 0 | 0 |
| 相同 detector、不同 parity frame 的 fault pair | 0 | 0 |
| terminal report 三 fault witness | 有 | 有 |

Detector-only dictionary 为零或一个声明 fault 解码 classical parity；未知 history 拒绝。不同 fault 的同 detector/不同 observable conflict 会使构造失败。删除 C closing detectors 的真实反例、改变 native transversal gate 的 channel 反例均须拒绝。

这里的 distance-three witness 与 single-fault correction **仅针对所枚举模型的 decoded classical parity**。它不是 retained quantum output 的全噪声容错证明，不给出任意多 fault 的成功率。理想 nondestructive channel、native parity fault model、物理运输/Executor 是三项分开的验收。既有 `lower_to_physical(..., require_fault_tolerant=True)` 继续拒绝全局 FT 承诺。

## 入口与下一步

```python
from neutral_atom_experiments.qec_pbc.encoded_ppm import (
    encoded_parity_program, compile_encoded_parity,
    verify_encoded_parity_instrument, audit_encoded_parity)

protocol = encoded_parity_program(basis='Z', rounds=3)
compiled = compile_encoded_parity(protocol)
instrument = verify_encoded_parity_instrument(protocol, compiled)

calibration = encoded_parity_program(basis='Z', input_bases=('Z', 'Z'))
fault_report = audit_encoded_parity(calibration)
```

可传入一一对应且完整的 role→atom bindings；默认 A/B/C 共51个 `Q000...Q050`。`protocol.phases` 和 `protocol.couplings` 供物理调度使用，`compiled.measurements` 与 classical sidecar 供真实 readout、decoder 和后续 bit-use 使用。

默认 entangling-input ZZ/XX 都是 **1860 native gates**（1062 H、450 CZ、195 RESET、153 MEASURE）；上表的 1842/1878 是 parity-eigenbasis fault calibration，输入 H 数量不同。Signed input 为每个负 eigenstate 另外执行三个 logical-string X/Z。

2026-10-03 本轮专项复验：`tests/test_qec_encoded_ppm.py` **29 passed / 43.12 s**。包括全部 native fault signatures、decoder/witness、ZZ/XX 正负签名 Choi、reversed bindings、signed retained-state constraints，以及损坏原语、phase barrier、coupling sidecar 和 missing closing-check 的拒绝。`tools/check_architecture.py` 本轮180模块、0 violations。复现使用隔离 Python≥3.10，并使 `src`、`artifacts/qec-baseline-deps`（Stim 1.15.0）在导入路径中；普通系统 Python 3.7 不适用。

下一步是 root 集成的三块实验平台及全部 Executor/independent replay 验收。它必须使用真实合法布局、路径、光照、全 EZ actual-pairs 和原生 reset/measure；本模块没有添加位置或放宽 validator。之后再接 encoded Clifford feedback、Y 与 magic resource；该模块自身不宣称完整 PBC/Shor 或资源工厂已实现。
