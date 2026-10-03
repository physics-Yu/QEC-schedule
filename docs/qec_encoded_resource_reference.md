# Encoded T/Tdg 资源的 native 制备参考

`encoded_resource_reference.py` 从17个原子的显式 RESET 开始，生成真正的 `PhysicalCircuit`，在标准 rotated [[9,1,3]] patch 上制备

```text
|A_s,L> = (|0_L> + exp(i*s*pi/4)|1_L>)/sqrt(2),  s=+1/-1.
```

线路只使用现有 native RESET、H、T、CZ、MEASURE，不安装预计算 encoded state。它已由独立 dense reference 逐门执行验证；没有在 ENV 或物理平台执行。tracked `StabilizerState` 继续拒绝 T，这个模块没有修改 quantum representation、schema、硬件谓词或时间模型。`fault_tolerant=false`、`magic_factory=false`、`physical_execution=false`、`complete_algorithm_encoded=false` 明确保持。

## CSS encoder 与标准朝向

数据顺序为 d0..d8，syndrome 为 X0..X3、Z0..Z3。标准逻辑代表仍为 `X_L=X0 X3 X6`、`Z_L=Z0 Z1 Z2`，Y 按 `Y_L=i X_L Z_L` 的 Hermitian 符号计算。这里的 X0 逻辑代表记号表示 data0 上的X，与 syndrome role `A.X0` 区分；代码始终使用完整角色 ID。

取 `surface.stabilizers` 的4个正号 X generators 与 logical X，作为 GF(2) 矩阵的前5列：第一列是logical X，其后4列是X checks。按独立性逐个添加 standard basis vector，得到9×9可逆线性变换。当前 completion 对应 physical d0、d1、d3、d5；这4列是虚拟输入5..8，均初始化为0，不是额外原子。

虚拟输入0承载任意 logical state；输入1..4经H制成4个 `|+>`，输入5..8保持 `|0>`。变换使每个计算基串输出 `A v mod2`，因此产生 logical coset 与4个X-stabilizer轨道的均匀叠加，并保持4个Z stabilizers的+1 sector。行消元得到的44个CNOT按反序重建矩阵；每个都显式展开为 H(target)–CZ–H(target)，没有 native CX 捷径。仅 encoder 为92 H、44 CZ。

`build_css_isometry()` 同时提供完整可逆的 `linear_circuit` 和包括4个虚拟H的 `isometry_circuit`。公开 bit order 为 big-endian：9个data wire之后才是未操作的reference wire。完整线性变换的 logical Z pullback可以包含虚拟5..8的Z；这些输入固定为0，所以在编码等距子空间上，逻辑 X/Y/Z 与原 logical qubit 精确对应。

输入 magic 资源先在虚拟0执行 H，再执行1个 native T获得s=+1。s=-1使用7个native T：`T^7=diag(1,exp(-i*pi/4))=Tdg`，包含全部实际门成本，不请求未接通的 native Tdg/S。所有17个role均先RESET，输入data没有预装码字。

可选的最后一轮 syndrome 默认开启。它复用现有 canonical 四层 CSS extraction：只追加该轮的H、24个CZ、8次真实MEASURE与8次RESET，保留encoded data，未追加 memory 的产品态初始化、纠正表或破坏性data readout。检查位来自实际投影，理想制备中8位全0；aux最终真实归零。所有coupling之后才提取syndrome，最终标准code orientation由8个稳定子与逻辑代表验证。

| 资源 | 最后一轮 syndrome | native gate总数 | RESET | H | T | CZ | MEASURE |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| T | 无 | 155 | 17 | 93 | 1 | 44 | 0 |
| Tdg | 无 | 161 | 17 | 93 | 7 | 44 | 0 |
| T | 一轮 | 251 | 25 | 149 | 1 | 68 | 8 |
| Tdg | 一轮 | 257 | 25 | 149 | 7 | 68 | 8 |

这些是协议gate counts，不是CZ脉冲数或平台耗时。本轮不估计任何transport、staging、fidelity或physical atom peak；独立制备声明17个角色。将线路接到已有程序时，调用者必须提供新分配或已消耗释放的资源原子，因为本接口会RESET全部17个角色；它不是保留输入data的append gadget。

## 接口、执行与资源生命周期

- `build_encoded_resource(sign=..., patch=..., bindings=..., namespace=..., syndrome_round=True)`：返回完整 PhysicalCircuit、固定9+8 role bindings、encoder provenance和真实syndrome measurement IDs。bindings必须完整覆盖且无alias；sign只接受整数±1。
- `apply_native_unitaries(circuit, state, qubits, reference_qubits=...)`：独立9-qubit/带reference的原生门向量执行，拒绝把RESET、MEASURE或condition静默当unitary。
- `execute_resource_reference(preparation, initial_state=..., seed=...)`：独立17-qubit dense执行全部native gates。RESET先按真实Born概率投影，再对1分支施加X，不假定输入已经归零；MEASURE保留实际结果及条件概率。没有向ENV安装任何state或measurement结果。
- `audit_encoded_resource(preparation)`：从CSS stabilizer projectors独立构造0/1码字，仅用于oracle，对照真实native输出的复振幅、8个稳定子、aux归零和测量记录。
- `audit_code_distance()`：按Pauli centralizer/stabilizer群枚举静态码距；不代表制备线路的circuit-noise distance。

builder的 lifecycle 为 `preparation_circuit_defined`。逐门reference执行结果才记为 `prepared`，`consumed=false`；本模块不实现后续联合测量、破坏性resource读出、factory或复用接口。这个生命周期是reference事实，不能解释为已提供物理encoded magic resource。

## 本轮证据与复建

23个不同测试通过。全部512个计算基输入核验native线性变换，0/1码字与8个CSS projector组成的独立oracle比较复振幅；任意complex logical input与1个reference的纠缠通过等距映射，全部8个稳定子及X/Y/Z逻辑代表正确。静态码距为3：枚举排除全部weight1/2的非平凡centralizer，找到weight3 witness；这是编码空间性质。

正负资源、含/不含最后syndrome round全部真实执行；17原子全为1的初态也通过实际17次RESET归零后制备。负资源成本包含7个T，没有任何注入或Clifford factory捷径。默认17-qubit参考维度为131072。CLI独立制备审计的codeword L2差分别为 `1.11e-16` / `2.22e-16`，aux残差为0，8个stabilizer残差为0，正负各8个真实syndrome报告全0。ENV的tracked T拒绝也有明确回归测试。

使用项目Python3.12与现有NumPy，无需新安装依赖：

```powershell
$env:PYTHONPATH='src'
python -m neutral_atom_experiments.qec_pbc.encoded_resource_reference `
  --output artifacts/encoded-resource/native-reference.json --seed 7
```

`--output`必须是新文件；`--without-syndrome-round`可导出仅制备线路。JSON同时包含两个独立资源的native gates和实际执行审计，不把两种资源解释为同一组原子的并行制备。本机本轮证据为 `artifacts/qec-shor15-2026-10-03/encoded-resource/native-reference.json`；ignored artifact不作为跨机器唯一交接。

这一制备从裸T开始，44个encoder CNOT可传播相关故障；末尾一轮checks不能推出FT、noisy decoder或distillation。接下来需要把已验证的encoding isometry与资源测量retained instrument组合，并声明可表示非Clifford logical amplitude的reference/执行边界。现有PBCProgram GateTask没有T primitive，tracked ENV仍只有精确Clifford状态；本轮没有把PhysicalCircuit冒充已能接入这些生产接口。完整encoded Shor、mixed/Y联合测量、magic-state工厂及物理执行仍需后续实现和验收。
