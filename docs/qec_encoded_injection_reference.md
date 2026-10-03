# 编码 T/Tdg 的原生参考消费与报告桥

2026-10-04。`encoded_injection_reference.py` 接通了真正的17-qubit资源制备、编码联合测量、资源破坏性读出与完整 signed Clifford frame。输出包含完整 `PhysicalCircuit`、全部原生门成本、真实参考投影记录和单次消费 receipt。**这是独立的 native-factorized 编码 instrument reference；没有运行 ENV/Executor，没有全寄存器逐门 dense 模拟，没有完整编码 Shor、工厂或容错结论。**

## 1. 输入与实际门链

首版限一个算法 patch `A` 和零或一个外部 reference；A 与资源均保持 standard rotated `[[9,1,3]]` 的9 data＋8 syndrome。输入是调用方提供的归一化任意复数逻辑态，或 A 与 reference 的任意纠缠态。它在原生输入边界占据 `A.d0` 与 reference，其余16个 A data/aux 角色明确从零开始、执行真实 RESET；`A.d0` 与 reference 不 RESET。随后实际执行 [CSS encoder](qec_encoded_resource_reference.md) 的92 H、44 CZ，并执行默认三轮 canonical syndrome。**这个声明的未知输入边界不是 Executor 的全零初态制备验收。**

每次注入依次输出：

1. 用现有真实原生 producer 在新17角色上 RESET、H、T，再通过 H/CZ CSS encoder 制备 `|A_s,L>=(|0_L>+exp(i s π/4)|1_L>)/√2`。s=+1保留单个原生 T；s=−1保留连续七个原生 T，精确 `T^7=Tdg`。producer 的一轮实际 syndrome/readout/release 也保留。
2. controller 从当前完整 inverse frame 求真正要测的 signed `Q=F†PF`。保留所有 prefix 门、角色、测量映射和 sector history，追加 [qualified mixed/Y cat](qec_mixed_pauli_cat.md) 的真实 `Q_A Z_R` gadget：各 patch 默认三轮 before checks、cat RESET/GHZ/two-pass verifier、完整 product coupling、每 cat H/MEASURE/RESET、三轮 after checks。physical Y 因子的 CY 顺序和原生 T;T 相位成本照实保留。
3. 资源9 data 全部执行 H，随后9次真实 MEASURE，随后9次 RESET。逻辑读出固定为 **`r=b0 XOR b3 XOR b6`**，来自 `X_L=X0 X3 X6`；其余六位也保留。八个 resource syndrome 已真实 released。
4. `m=cat raw parity XOR physical-product sign` 与 r 经 reference receipt 接入 `FrameController`，记录 `F_new=P^r S_P(s)^m F` 的完整 signed generator table 和 chronological ledger。live encoded data 不执行 S_P/P 纠正；下一次真实测量标签使用这个更新后的 frame。
5. 资源生命周期记录 prepared → joint_measured → destructively_read_out → consumed → reset_released。逻辑 resource ID 永不重复。`physical_resource_reuse=True` 仅在同一 R 的9 data 已全部 MEASURE/RESET、8 aux released 后允许真实17 RESET 与下一 producer 重制备；两个 producer 的 gates 和 syndrome semantic IDs 使用不同 epoch。

cat 的 static native circuit 没有生产运行时 abort/retry controller。参考执行确实读出 verifier 并在 data coupling 前拒绝非零核验；这不能扩大为当前 ENV 已有 abort/retry。后续纠正兑现 `realize()` 只在逻辑数学参考中进行；native circuit 输出是 frame-labelled encoded quantum output。

## 2. native-factorized 的精确边界

实现不会用预计算 `|A_L>` 替换原生 producer 输出，也不会用原生 Z 门代替单个 T。它将实际 primitive sequence 分成可独立审查的边界：

| 部分 | 实际参考执行与资格校验 |
| --- | --- |
| A 输入 encoder | 未知 A/reference 输入上实际 RESET 和 H/CZ；与独立 CSS projector codewords 对照 |
| 资源 producer | 全部17 qubit 上逐原生门 dense，包括真正 T、MEASURE/RESET；输出实际9data资源向量，aux投影/release验证 |
| canonical before/after | 实际17+1-reference native Choi kernel 在完整两维 signed code sector 上检查 identity channel、复相位、确定性真实 syndrome 与 aux release；该精确边界用于每个 retained canonical bank，缓存仅保存不可变证书记录 |
| cat | 检查实际完整 ordered native tail、prefix边界、sign/measurement maps、readout H/M/release；小 native cat+verifier 执行真实准备/核验；实际完整 CY unitary 和实际 cat readout bras 的已 qualified Kraus 收缩作用于编码 data/resource/reference 向量 |
| 资源9X读出 | 在真正联合投影后的18data+reference向量上逐原生9H/9M/9RESET；先计算完整512 raw Born distribution，再真实投影、读出和复位 |

最大 retained dense 向量是 `2^19=524288` 个复振幅，单向量8 MiB；另有17q producer、18q canonical Choi 与至多9q cat+verifier 小 kernel。**不是44/51/68角色的整条线路逐门 dense 模拟，也不是生产 committed-report 证据。** 表中资格校验和独立数学 identity 保证了 factorized 边界的理想 retained instrument；transport、idle/loss、噪声、错误 decoder 和 circuit-distance 未实现。

receipt 要求明确的 `MixedPauliCat` qualification 对象、完整原生 native hash、完全相同的 joint prefix/roles/sidecars、全部真实 measurement IDs 与整数报告、接受的 verifier 和一致的 syndrome/detector history，以及完整有序27门 H/MEASURE/RESET suffix。它严格检查 X0/X3/X6代表、signed cat parity、resource/measurement ID、依赖顺序，以及两个条件概率均为该理想合同的1/2（数值容差2e-11），在所有这些检查后才更新 frame。它不向 ENV `measurement_results` 插入一个虚构的 XOR bit，原生条件仍是现有真实报告位 conjunction 合同。

prepared resource 的+X-stabilizer sector中，X_all9与固定X0/X3/X6相差X checks，因此其32条非零理想 raw strings上 xor9 恰好等价。receipt拒绝xor9是**固定接口代表合同**，不是声称这两种理想统计不同。一般报告字符串/非标准sector不能据此默认xor9；参考始终从三个明确 native gate IDs生成 r。

## 3. 全分支与独立预期

测试的独立2×2矩阵不调用编码 producer、native emulator、frame realize 来生成预期。真实未纠正 logical instrument 为

```text
K_mr = [(I+(-1)^m Q) + (-1)^r exp(i s π/4)(I-(-1)^m Q)]/4.
C_mr = P^r [Π+(P)+i s Π-(P)]^m.
```

每个 m/r 的 Born probability是1/4。校正后包含 branch整体相位：m=0为1；m=1为 `exp(i s π/4)(-1)^r`。再乘编译器 `exp(i π/8 * (source_phase-sum(s)))`，才得到 source `exp(-i s π P/8)` 的复振幅。测试逐振幅比较这个相位和一般纠缠 reference 的 coherence。

覆盖 ±X/±Y/±Z×正/负资源全部48个单资源 m/r 分支；两个不对易 signed 注入的16组合分支、非零 measured input sector与真实 R patch 回收重制备；真正 Born采样的三轮 Choi 输入样例；未知/缺失/非整数 raw报告、xor9代表、错误符号/resource/semantic IDs、提前使用、非法概率、原生 H→Z/缺RESET、dirty incoming history、重复消费和不完整释放均拒绝。

独立 raw oracle 通过四个X generators的二进制 orbit 枚举 codewords，然后直接计算 `⟨b|H^⊗9|x⟩=(-1)^(b·x)/√512`。它核验全部512 raw概率、32条非零支持、归一化和按固定logicalX parity分组；不只验证最终r分布。每条 emitted MEASURE/RESET恰有一个实际 execution/kernel 记录并按 native order 导出。

本轮36个不同新测试、35个既有mixed/Y回归通过：首次联合68项通过后，新增的无外部reference/真正单T消费API测试另行1项通过；独立peer发现public receipt可接受不可能概率0.75，补1/2 guard与该负例、两项概率的容差内/外边界原子性测试后定向20项通过。未将重复执行计入新增数。架构扫描0违规；干净发布副本的独立验收另由发布记录提供。

## 4. 接口与复建

```python
result = execute_encoded_injections(adaptive_program, logical_reference_vector,
    reference_qubits=1, rounds=3, seed=7, physical_resource_reuse=True)
circuit = result.compile().circuit  # 真正 PhysicalCircuit；含真实全部T/7T/TT
encoded_output = result.encoded_data
frame = result.frame               # native live output 的完整逻辑frame
semantic_reference_output = result.realize()
audit = audit_encoded_reference_result(result, logical_reference_vector)
```

`commit_encoded_receipt(controller, receipt, native_program, raw_reports, qualified_joint=item)` 只消费实验 reference 实际投影结果；不是 ENV transaction/生产 controller。final circuit 绑定为 Q000…，无平台、时长或初始holder假定。现有 tracked ENV 仍明确拒绝单T；原 mixed/Y Clifford adapter 同样拒绝消费者的真实单T/7T prefix，不静默抹掉它们。本次仅给 `append_mixed_pauli_cat` 增加第三种**已经通过 NativeCatProgram constructor 校验**的 experiment native prefix输入，保留原来 PBCProgram/MixedPauliCat 行为；没有改 GateTaskIR/core门集。

在已具备 NumPy/pytest 的隔离 Python 3.12 中：

```powershell
$env:PYTHONPATH='src'
python -m pytest -p no:cacheprovider tests/test_qec_encoded_injection_reference.py tests/test_qec_mixed_pauli_cat.py -q
python -m neutral_atom_experiments.qec_pbc.encoded_injection_reference --rounds 3 --seed 7 --reuse-resource-patch --output artifacts/encoded-injection/native-factorized-audit.json
```

CLI只写新的 caller output路径（拒绝覆盖），输出完整 native gates/sidecars、projection记录、512概率、两个资格证书、frame/lifecycle及独立source matrix audit。seed7默认一般复数reference输入的3轮 `−Y(+T)` → `X(Tdg)` 实际 m/r为 `(1,1),(0,1)`：**3641门，2062 H、903 CZ、10 T、288 MEASURE、378 RESET；51 declared roles；666 projection记录。** 10 T包括两个 producer的1+7 T和Y coupling的2 T。这是所导出线路的真实门成本，不是时间/atom peak；旧cat roles保留在declared role集合，已released但本轮没有回收cat角色的优化。

独立source复振幅 L2误差 `1.7714e-15`，最大semantic conditional probability误差 `1.1102e-16`，两份raw512概率归一化误差0。完整编码 Shor仍为false。下一依赖是把这个有界消费合同扩到多算法patch并在完整framed标签上组合，同时保持一般参考输入和真实source门成本；生产物理T表示、decoded parity/controller、magic resource质量及FT/物理执行需要各自独立验收。
