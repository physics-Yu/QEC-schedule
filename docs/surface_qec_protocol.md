# 两个 d=3 surface logical qubit 的测量制备、GHZ与纠错协议

日期：2026-09-12。实现：`quantum/stabilizer.py`、`experiments/surface_qec.py`。本文件定义量子和经典协议；物理布局、AOD路径、读出区、时间、光照及独立物理重放由对应runner负责。本协议不是把软件计算出的稳定子期望值当作一次测量。

## 范围与一手依据

本实验含 **18数据原子＋16专用辅助原子＝34原子**。每个rotated `[[9,1,3]]` patch配置9个data和8个check ancilla，测量四个X稳定子及四个Z稳定子。此资源口径对应常规独立辅助方案；[Krinner等原文](https://arxiv.org/pdf/2112.03708) 第1–3页、Fig.1/2以及Appendix C2明确给出9+8结构、测量电路及错误传播门序。该实验为超导平台，本文引用其码与测量电路，不套用其硬件时长。

[Bluvstein等中性原子论文](https://arxiv.org/html/2312.03982v1) Methods “Surface code and its implementation”以初态 `|+>` 或 `|0>` 配合另一类稳定子投影测量制备逻辑态，随后做transversal CNOT。本项目进一步显式测量两类全部checks，保留真实随机测量结果并根据结果执行物理Pauli纠正。没有声称复制该论文的全部标定、读出保真度或容错实现。

保证的故障范围是：**理想Clifford门、理想投影读出和reset，最终syndrome提取前任意一个数据原子的X/Y/Z故障**。测量随机性来自量子态本身。暂不包括辅助原子故障、错误读出、泄漏、噪声运输、多数据故障和重复时域解码；不能将本轮54单数据故障恢复称为完整电路噪声下的容错QEC。

## 编号、稳定子与完整静态线路

- data A：Q000–Q008；data B：Q009–Q017；局部编号为3×3行优先。
- ancilla A：Q018–Q021对应X0..X3，Q022–Q025对应Z0..Z3。
- ancilla B：Q026–Q029对应X0..X3，Q030–Q033对应Z0..Z3。
- X support：0134、4578、12、67；Z support：1245、3467、03、58。
- logical X为036，logical Z为012；与既有distance-3独立验证采用相同约定。

全线路依次包含：A块9数据H、prepare轮全部X/Z syndrome、prepare条件Pauli修正、对应数据间9个CNOT、可编辑单数据故障门、final轮全部X/Z syndrome、final条件Pauli修正。全部原子起始为 `|0>`，因此prepare纠正后为 `|+>_LA |0>_LB`，横向CNOT后为两逻辑GHZ，也就是逻辑Bell态。

每个MEASURE后立即安排同一辅助原子的RESET。测量在量子引擎中使该辅助原子与条件态坍缩，并保存测量bit；reset再次测量并按需施加X使辅助恢复 `|0>`，不是仅清除一个显示标志。物理runner需在MZ执行实际读出/reset后再运输，不得隐藏这些操作的时间与支撑。

线路包含`condition`和`depends_on`：前者是若干 `(measurement_gate_id, bit)` 的AND；后者是显式阶段依赖。普通同qubit依赖仍由DAG建立。编辑器排序按column/id，与所有依赖一致。condition为false的预留纠正slot不改变量子态、不打单比特光；若runner计控制slot时长，须单列，不计作实际Pauli脉冲。

## 稳定子提取及门序

X check：ancilla初态0，先H到 `|+>`，按下列顺序做 `CX(ancilla,data)`，最后H并Z测量ancilla。Z check：按顺序做 `CX(data,ancilla)`，随后Z测量。所有CX原生展开为 `H(target), CZ, H(target)`。

| 类型 | check 0 | check 1 | check 2 | check 3 |
| --- | --- | --- | --- | --- |
| X的data次序 | 0,1,3,4 | 4,5,7,8 | 1,2 | 6,7 |
| Z的data次序 | 1,4,2,5 | 3,6,4,7 | 0,3 | 5,8 |

先完整X的四个CNOT层，再完整Z的四层。每个层中的目标data互不重复，两个patch可以并行；weight-2 checks只在前两层参与。不是把所有24条data-ancilla边同时打光。X的weight-4 check最后两个data水平方向，Z的最后两个data垂直方向，分别避免二数据hook错误沿本协议logical X/Z string方向排列。此安排符合保守的错误传播方向原则；本轮恢复声明仍仅覆盖syndrome前单data故障，不声称仅靠这一局部门序已完成全电路容错证明。

## 只根据测量bit的decoder

每种check类型都有16个可能四bit模式。枚举9-bit纯Pauli support，按最小weight和确定的整数次序选代表：X-check结果决定Z纠正，Z-check结果决定X纠正。所有模式均有定义，因而prepare轮产生的随机syndrome也能修正。

量子证明：A的初始全部X checks与logical X已是+1，测Z checks后以X修正，不改变这些X本征值；B对偶。因此prepare轮结束确定进入所需码态。final轮单data错误的syndrome由其与checks的反对易关系决定；最小weight纠正与该错误至多相差稳定子，保留逻辑GHZ。

`decode(readout_bits, round_name)`只接受测量结果映射，没有fault参数，也不读量子expectation或注入位置。静态线路对每个非零syndrome预留对应X/Z纠正门，并用完整四bit条件选择实际执行者。184个纠正slot不是184次光照；不满足条件的slot必须明确标为未施光。

## 电路优化及真实量子核验

原始无故障604个slot。保守的wire相邻HH消去移除62对H，变为 **480个slot：127H＋105CZ＋184条件X/Z＋32MEASURE＋32RESET**。一个可选fault pulse再加1slot。H消去不会跨同wire的任何其他门、measurement、reset或conditional门；依赖指向被消除H时，将其依赖传递到保留祖先，保证没有悬空依赖。优化前后使用相同随机测量输入得到相同读出结果与最终态。

阶段barrier由上一阶段各wire最后一个门组成EXIT frontier。随后进行独立的依赖传递约简：先计入每wire前驱和条件读出依赖，再删除已被它们或其他显式祖先覆盖的边。无故障模板显式边10261→1001；含单fault模板8130→881。每个gate的完整祖先集合通过独立set算法逐一比较相等，门ID、位置、类型、目标与condition均不改变；这不是通过删除必要barrier换速度。

105个CZ包含两轮各48个data-ancilla CZ，加9个横向逻辑CNOT对应CZ。光学批次可以合并多个合法READY CZ，门数与实际pulse批次数须分别统计。协议定义批次的量子相容性，物理runner仍需核验AOD Cartesian闭包、支撑、扫掠、EZ真实作用对和Raman邻距。

`StabilizerState`是不可变完整纯态stabilizer tableau，精确跟踪 `i^phase X^x Z^z`。Z测量若可预测则返回真实确定结果并忽略提供的随机bit；若不可预测，按提供bit选择等概率分支并更新全部相关生成元。random_bit由core的可恢复RNG提供，引擎内部不偷偷抽样。H/X/Y/Z/CZ及内部CX精确支持；T或其他不支持门明确拒绝，不作Clifford近似。

测试包含：随机三qubit Clifford与独立稠密复振幅比较；Bell测量相关性、负YY符号和reset；序列化/不可变分支；12个随机初始化seed；18data×3Pauli的54个真实故障；每次最终读出bit与独立Pauli反对易预期逐一相等，纠正后16checks和logical XX/ZZ全为+1；删除final恢复步骤时验证失败。软件期望值是最终独立检查，不能取代线路里的32次MEASURE。

## 对接API

```python
from neutral_atom_env.quantum.stabilizer import StabilizerState
from neutral_atom_env.experiments.surface_qec import (
    experiment_input, protocol, decode, simulate_ideal, summarize, quantum_summary,
)
raw = experiment_input(fault={'pauli': 'Y', 'qubit_id': 'Q013'})
definition = protocol()
quantum, report = simulate_ideal(seed=7, fault={'pauli': 'Y', 'qubit_id': 'Q013'})
```

`qec_protocol`含readouts、stages、atom_roles、fault_targets、fault_column和优化统计。fault ID固定`QEC_FAULT`，column应读metadata；编辑该门只改线路，不得根据故障参数重新生成覆盖用户草稿。`summarize(state)`读取真实quantum_state、measurement_results及trace中effect_completed的applied_gate_ids，报告syndrome_bits、实际条件纠正、16checks、logical_xx/logical_zz，以及两个syndrome轮是否都有完整读出。实际纠正数不由decoder建议数推定。`measurement_protocol_complete`另外检查命名读出、对应ancilla、每check的实际CZ邻接及H前后作用、紧随其后的reset；删去check边/读出/reset会使它为false。该结构检查仍不能代替完整量子结果核验或全噪声容错证明。用户编辑后按修改后的门表执行，逻辑目标与测量协议完整性分别报告。
