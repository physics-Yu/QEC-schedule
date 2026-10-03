# mixed/Y 编码 Pauli 测量与条件 Clifford：下一实现设计

2026-10-04，**设计与独立公式校核，尚未实现后端**。下一可执行模块是保留既有 d=3 编码输入的多 patch Pauli-product measurement（PPM）：先做当前门集可表达的 mixed X/Z，再在独立 Clifford reference 中验收含 Y 的协议；native S 的能力决策通过后才接物理 lowering。条件 `S_P` 同时给出可执行 Clifford-frame 合同和显式测量式纠正候选。本文件不改变 ENV、门集、物理参数或量子态表示，不将完整 Shor 的 `encoded` / `physical_executed` 改为 true。

当前 [实际完整 PBC inventory](qec_shor15_encoding_requirements.md) 的每 shot 3500 项 joint measurement 中，2325 含 Y、3138 混合 basis、最大 logical weight 9。固定本文代表展开后，**这份实际导出的 physical Pauli support 最大为37**；它不是执行原子数或容错证明。3500 是消耗次数，12 个算法 patch 的基础角色数为204；factory、测量辅助和真实 atom peak 仍待调度确定。

## 1. 一手依据与采用范围

| 一手资料 | 核对位置与文献事实 | 本项目采用范围 |
| --- | --- | --- |
| [Shor, Fault-tolerant quantum computation, quant-ph/9605011v2](https://arxiv.org/pdf/quant-ph/9605011v2) | §4，PDF pp.5–7（cat核验重点p.6、重复读出p.7）：先核验 cat，再与数据逐点耦合；phase/readout 错误仍需重复处理 | 分布式辅助测量的出发点；本文“两次链式核验、三次 PPM”是待审计的 d=3 项目候选，并非照搬其容错定理 |
| [Litinski & von Oppen, Lattice Surgery with a Twist, 1709.02318v2](https://arxiv.org/html/1709.02318v2) | §3.3–3.4、§5/Fig.12、Appendix A.2/Figs.14–16：Y/多体测量与 twist；原生两比特展开需检查 hook 和门序 | 后续 surgery 替换后端的依据，不能直接套为当前17-role patch |
| [Litinski, A Game of Surface Codes, 1808.02892v3](https://arxiv.org/html/1808.02892v3) | §1、Appendix A/Figs.39–41：Clifford 共轭修改测量标签；Y surgery 含宽化和新的 checks | frame 标签与 twist 数据结构的依据，不把 tile 时间当作本项目物理时间 |
| [Bravyi–Smith–Smolin, Trading classical and quantum computational resources, 1506.01396v1](https://arxiv.org/pdf/1506.01396v1) | §I、§V：PBC 使用自适应非破坏 Pauli 测量和 magic 输入 | 保留现有任意输入/量子输出合同；本设计不执行 stabilizer-register 消去 |
| [Stim 1.15.0 官方 gate reference](https://github.com/quantumlib/Stim/blob/v1.15.0/doc/gates.md) | `S`、`S_DAG`、`MPP`：signed Hermitian product 和 Clifford reference | 独立 oracle；Stim 支持的门不自动成为本项目 native 门 |

下文协议、公式和资源界分别标明“数学推导”或“项目设计”。现有能力以源码而非文献推定：[IR](../src/neutral_atom_experiments/qec_pbc/ir.py)、[gate contract](../src/neutral_atom_env/hardware/gate_contract.py)、[tracked effects](../src/neutral_atom_env/simulation/quantum_effects.py)。

## 2. 固定 patch、朝向与输入合同

**现有实现快照**：每个 standard rotated `[[9,1,3]]` patch 为9 data＋8 syndrome，data 编号按行 `0,1,2 / 3,4,5 / 6,7,8`。

| 对象 | 固定代表 |
| --- | --- |
| X checks | `(0,1,3,4)`、`(4,5,7,8)`、`(1,2)`、`(6,7)` |
| Z checks | `(1,2,4,5)`、`(3,4,6,7)`、`(0,3)`、`(5,8)` |
| `X_L` | `X0 X3 X6` |
| `Z_L` | `Z0 Z1 Z2` |
| `Y_L=i X_L Z_L` | **`Y0 Z1 Z2 X3 X6`，正号** |

最后一行来自 `X0 Z0=-iY0` 的相位；不能把逻辑 Y 换成某一个 data 上的 Y 门或读出。代表乘以 stabilizer 时，若 incoming sector 为负，要同时修正 product 的符号；首版固定这些代表，不做这种优化。

**项目设计**：`MixedPPMSpec` 输入为已有 prefix、signed logical product、参与 patch 的8项 incoming `BitExpr`、orientation、辅助角色和 epoch。要求：

- prefix 的所有角色、操作、measurement IDs、detectors、observables 和依赖完整保留；数据不 RESET，不假定输入逻辑 basis/sign。
- incoming sector 引用 prefix 已存在的真实 semantic measurement IDs，不能以虚构外部位或全0常数替代。首轮 detector 比较 incoming sector 与真实新读出。
- 首版只接 `standard`；`dual` 或 code deformation 必须给出已验证的 checks、logical representatives、角色置换和 signed sector transfer，未提供则拒绝。
- 各参与 patch 的8个 syndrome auxiliaries 已 RESET/released；其后仍执行真实 syndrome rounds。未参与的算法 patch 不被重制备。
- cat/verifier 为另外的测量辅助，**不是现有 C 的17-role 编码 patch，也不是 magic resource**。新角色必须避开数据、magic 与旧测量 ID；回收要求完整破坏性读出并真实 RESET/reprepare。

本文受控门中的 data `H–CZ–H` 是完整 `CX` 的展开，不是独立 logical H；整个 gadget 输出仍使用原 standard code。耦合中途不要插入 canonical checks：尚未完成的受控 physical product 一般不与所有 checks 对易。

## 3. 第一后端：分布式 cat PPM 的理想 instrument

**项目设计**：将逻辑 product 展开为 `Q=⊗_{i=0}^{L-1} p_i`，目标为 `P=σQ`，`σ=±1`。每一个物理因子分配不同 cat 原子 `c_i`，每个 `c_i` 只耦合一个 data 原子。cat 为 `(|0^L>+|1^L>)/sqrt(2)`，在辅助制备阶段完成后才接触数据。

| 阶段 | 明确操作与记录 |
| --- | --- |
| 输入边界 | 读取 incoming history，参与 patch 执行3轮 canonical checks；首轮符号从 history 来 |
| cat 制备 | cat 全部 RESET，`H(c0)`，沿固定链执行 `CX(c_i,c_{i+1})`；逐门记录，不以 GHZ 标签代替线路 |
| 核验候选 | 用独立 verifier 逐项测 `Z(c_i)Z(c_{i+1})`，完整链做两遍，每项含 RESET、两次 CX、Z readout、release；非零核验位只允许在**数据耦合前**丢弃 cat 并重试 |
| 联合耦合 | 逐因子执行 `controlled-p_i(c_i,data_i)`；不测 data、不逐 patch 测量 P 的因子 |
| cat 读出 | 每个 cat 真实 X readout（H＋MEASURE），保留全部 raw/reported 位；semantic parity 为其 XOR 再加目标符号 |
| 关闭边界 | 参与 patch 真实 closing checks、输出各8项 sector history；cat/verifier 全部释放，数据保留 |

“两遍核验”是待故障验收的具体候选，不预称 FT。理想单次 gadget 可以先实现而保持 `fault_tolerant=false`；三次 parity 重复和中间 syndrome 的 decoder 合同见第6节。

**数学推导**：记 cat X 读出字符串为 `t`，`q=⊕_i t_i`，则其非归一化 data Kraus 为

```text
K_t = 2^(-(L+1)/2) [I + (-1)^q Q]
    = 2^(-(L-1)/2) Π_q(Q),       Π_b(P)=[I+(-1)^b P]/2.
semantic bit b = q XOR [σ=-1].
```

同 parity 的其余 cat 位不泄露额外 data 信息。把所有具有同一 b 的 raw branches 合并，得到精确 `Π_b(P) ρ Π_b(P)`；这个恒等式在 data 与外部 reference 纠缠时也成立。验收必须检查这个 retained-data instrument，不只检查 XOR 分布。

## 4. Y 的明确能力缺口与可先做的子集

**现有实现快照**：实际 native unitary menu 是 `H/X/Y/Z/T/CZ`，另有 MEASURE/RESET；`GateTask` 更窄，只有 `H/X/Z/CZ/MEASURE/RESET` 且只有 X/Z 接 measurement-bit 条件。`PhysicalGate` 字面接受 S/Sdg，但实际 gate contract、`StabilizerState.apply_gate`、tracked validation 和 QEC verification 没有端到端 S 支持。tracked T 明确拒绝，不做近似。

**数学推导**：不使用 T/复数资源时，H/X/Z/CZ、Z 测量和0/+制备都是实矩阵；Y unitary 也仅差一个 global phase 为实矩阵。因此当前这个操作集合不能对任意输入实现奇数个 Y 因子的 projective instrument。`T;T=S` 不能作 tracked shortcut：中间 T 态已超出现有稳定子表示。

精确 controlled-Y（control 为 cat，target 为 data）可按时间顺序写为

```text
CZ(c,d) → CX(c,d) → S(c),
CY = S_c CX_cd CZ_cd,
CX(c,d) = H(d) → CZ(c,d) → H(d).
```

S 只作用于 cat，整个受控门不会把 data patch 留在新的朝向。每个 physical Y 因子需要2个 CZ、2个 H、1个 S；controlled-X 需要1个 CZ、2个 H；controlled-Z 需要1个 CZ。这里的 S 尚是 reference capability，不能导出为已可执行门。

还有一个可独立验收的**偶数 Y 子集**：不加上述 cat S 时，每个 Y 因子实现 `XZ=-iY`。当 Y 因子数 `n_Y` 为偶数，完整 GHZ 分支测的是 `(-1)^(n_Y/2)Q`，semantic parity 再 XOR `(n_Y/2 mod 2)` 即可；这依赖 GHZ 子空间合同，并需自己的故障审计。奇数 Y 时分支是 `I±iQ`，不再是 projector，不能靠翻 bit 修好。

对实际默认 ε=1e-3/seed7 导出只读复算，Y 因子数0..5的计数是 `1175,1550,584,113,58,20`：**1683 项 odd-Y，642 项非零 even-Y**。这仅细分原始 eager-correction 标签；1175项无Y与642项偶Y具有当前 real-Clifford 菜单下的理想门代数候选，仍缺后端实现、encoded magic 输入、FT和真实物理执行，不能计为1817项已执行。

## 5. 条件 `S_P`：两条明确可验收的实现路线

### 5.1 先实现完整 signed Clifford frame

**项目设计**：frame 定义必须固定为 `ρ_sem = F ρ_phys F†`，其中 F 是未物理执行的纠正。下一项 logical product P 真正要测的是 `Q=F†PF`，包括符号；magic resource 的 Z 因子保持独立。原有两测量注入给出 m、r 后，更新

```text
C = P^r S_P(s)^m,              S_P(s)=Π+ + i s Π-,   s=±1
F_new = C F.
```

F 使用12个数据 wire 上的 signed symplectic tableau，记录全部24个 generator images；多体 `S_P` 可产生跨 patch correlations，不能用12个独立单比特 frame 代替。保存 branch/整体相位 ledger 以供完整复振幅审计。

对任意 Pauli A，设 `a=1` 表示 A 与 P 反对易，pullback 的精确公式是

```text
C† A C = (-1)^(r a) A                         if m=0 or a=0
       = (-1)^r i s P A                       if m=1 and a=1.
```

`i s P A` 的 Hermitian 相位需按 Pauli 乘法计算。每次纠正都要真实影响下一 measurement 标签、符号和 classical dependency；只更新一个“frame已处理”的状态字不满足合同。

最终 residual Clifford C_res 不能丢弃。若输出为 Shor 的8个 Z 测量，则实际测量 `F† C_res† Z_j C_res F` 并保留其 measurement order/result mapping；它们仍两两对易。若保留量子输出，则必须物理兑现 `C_res F`，或明确返回 frame-labelled output，不能声称实际 quantum state 已相同。

**新资源界**：frame 会改变原始标签，data support 可达12，joint 可达13；当前 inventory 的最大9/37不能移用于所有 adaptive branches。固定本文代表的保守 cat 长度上界为 `12*5+3=63`。实际 framed inventory 必须从真实 branch 逐项导出，未经运行不能声称仍为2325项Y或3138项mixed。

### 5.2 需要 eager 量子输出时，使用 Clifford `|Y_s>` 资源

**数学推导与项目候选**：令 `|Y_s>=(|0>+i s|1>)/sqrt(2)`。测 signed `P⊗Z_B` 得到 u，再在 X 基破坏性读出 B 得到 v。四个未纠正 Kraus 依次为

```text
K00=S_P(s)/2,         K01=P S_P(s)/2,
K10=i s S_P(s)†/2,   K11=-i s P S_P(s)†/2.
P^(u XOR v) K_uv = (i s)^u (-1)^(u v) S_P(s)/2.
```

因此原注入 m=1 时可真正执行这一 gadget，额外纠正仅为 Pauli。它避免直接请求 native **多体条件 S_P**；资源为 stabilizer `|±Y_L>`，不称为 T-state distillation。B 可从真实 canonical `|0_L>` 出发，经本后端 nondestructive `Y_L` 测量及 decoded-result 控制的 `Z_L` 制备；native/track S 的底层能力缺口仍需解决。

原注入的 r 纠正与本 gadget 的纠正合并为 `P^(r XOR u XOR v)`，所有 measurement IDs/decoded histories必须保留。B 的9 data 破坏性 X readout、8 syndrome release、再 RESET/preparation 后才能下一 epoch 复用。已经消耗的 magic A 若用同17原子变为 B，也要先满足这个完整回收合同；不能把 logical 状态名称直接替换。

**现有条件接口的具体限制**：`PhysicalGate.condition` 只能引用真正 native MEASURE gate 的报告位，条件是 conjunction；不能直接填入“37个cat reports的XOR结果 u”，也不能向 `measurement_results` 插入未投影的 computed key。若理想 Pauli 纠正指数是现有 `BitExpr` 的线性 XOR，可以保持原接口展开：

```text
e = c XOR b1 XOR ... XOR bk
P^e = P^c P^b1 ... P^bk,        P^2=I.
```

每项 `P^bi` 再展开为各 data 上 conditional X/Z，条件引用原始native measurement gate ID，已存在的report/sign映射只计算一次。逻辑/物理Y用X/Z实现时另记branch整体相位；所有控制位必须已committed。该方法增加真实physical Pauli门数，但无需伪造parity measurement。FT decoder的非线性recovery决定不能自动这样展开。

Clifford纠正不同：`S_P^e` 不能换成 `∏ S_P^bi`，因为两次S_P为P而非I。它要求真正的parity/decoded controller选择分支，或第5.1节完整deferred frame；不能用原conjunction接口直接塞一个semantic XOR。eager路线的额外 `|Y_s>` gadget应由原m的真实semantic值选择，controller须保存此选择的原始bit依赖。

在理想注入中原 m=1 的概率为1/2，所以每shot额外 Clifford 资源消耗期望1750、最坏3500；这是该候选的代数期望，不是已测 factory 产率或物理时间。它新增 Y-resource 制备与反馈测量，成本不能记为0。

## 6. syndrome、hook、distance 与 decoder 的验收合同

**项目设计，尚未证明 FT**：native-fault audit 必须覆盖 cat 制备、两遍核验、controlled product、readout、所有前后/中间 canonical rounds 与 classical-result 故障。一个 cat 只接触一个 data 限制了耦合阶段传播范围，**不解决 cat 制备的相关 X fault、phase/readout fault 或原8个 syndrome 的 hook**。

候选正式测量做3次 PPM，每次新制备/核验 cat，之间执行完整 canonical syndrome round。cat phase fault 可以翻 parity；data fault 可以使后续真实 parity 改变，所以不能把三次结果机械 majority 后宣称保留量子输出容错。decoder 同时读取 parity、所有 sector/detector 历史、核验接受位和时序，输出 logical bit、Pauli recovery/frame、是否拒绝及其原因。

验收按以下固定顺序进行：

1. **代数与距离**：checks 的 commutation/rank、目标 P 与所有 active checks 的 commutation、signed sector transfer；原patch空间distance3重新核对。candidate 动态协议的 circuit distance 另计算。
2. **理想 instrument**：单/双/多patch、±X/±Y/±Z、XY/XZ/YZ/XYZ、任意 signed incoming sectors、外部 reference；比较整个 retained Choi/channel 和每个 logical result，不测额外 logical 信息。小cat枚举全部raw branches；大cat以符号化 Kraus/affine instrument证明全部branches，抽样不能替代该证明。
3. **组合与反馈**：连续两个非对易 PPM、真实 prefix 态保留、辅助回收、全部四注入分支、三次非对易注入的64 branches、frame/eager oracle/residual 对照；不存在位提前使用、重复纠正、namespace碰撞或旧sector假定0。
4. **有界故障合同**：按独立 native location 模型枚举每个单故障和必要双故障，核验失败仅在未接数据前允许重试；对 accepted 单故障，证明 decoded parity 与 retained logical/reference channel 经实际恢复后正确。寻找 undetected parity/quantum-output failure 的最少fault witness，至少3才声称此模型的distance3；单纯 parity-distance证据不外推为quantum-output FT。
5. **物理验收**：声明全部角色和初始 holders/SLM/MZ sites，进行普通 compiler、validator、Executor、真实读出与严格完整重放/checkpoint。运输、idle、loss、fidelity和decoder latency 未建模的部分继续单列，不能由 native故障结论代替。

原来标准4层 syndrome 门序保持；任何跨patch模板都要检查真正的传播与同原子冲突。cat重试次数须有上限、每次保留失败证据；达到上限则失败，不选择性删除不喜欢的logical measurement结果。

## 7. 为什么先做 cat，twist 怎样作为第二后端

**项目取舍**：现有可重构原子耦合与canonical输入history使 cat 路线可先保留全部9+8 patch结构，逐因子线路、辅助和签名能直接审查。它增加辅助和耦合开销，不声称优于 surgery，也不继承现51原子 ZZ/XX runner 的物理验收。

twist 路线以同一 `MixedPPMSpec` 的 signed input/output instrument 为接口，但额外提供每阶段实际 data coordinates、active/removed/new checks、split/merge measurement IDs、logical representatives、boundary类型、code distance、hook门序和输出 sectors。现论文宽化/twist 模板不能放进原17-role预算后仍宣称原checks不变。新增data/辅助及五体check的native序列都先在独立理想reference中验收，再做故障与物理；不能从论文图凭外观指定 XX/ZZ 或沿用原4层hook ordering。

## 8. 资源账本与架构决策点

| 项目 | 首版账本/能力决策 |
| --- | --- |
| algorithm patches | 固定12×17=204角色；其他patch在某次PPM中闲置不代表可以RESET |
| magic A | 17-role候选编码patch，provenance/quality/error contract显式；目前仍没有真实制备/蒸馏 |
| cat长度 | `L=3w_joint+2n_Y`；实际原始3500项最大37；weight≤9的一般保守界43；framed12data＋resource的界63 |
| verifier | 候选1原子串行复用，每个check真实RESET/readout；重试要计时、计消耗 |
| 角色数示意 | 全12算法＋1resource＋实际37cat＋1verifier=259；framed保守63cat版本=285。这些是模板角色账本，排除factory/备用/reference，**不是已可行物理peak**；若eagerB另占fresh17则还要加17 |
| D1：S capability | 现gate合同/精确tracker尚不支持端到端native S/Sdg。需要先声明可执行模型、计时、GateTask/verification/lowering与相位验证接口；本轮未实现、未修改相关源码，实际duration保持未定 |
| D2：encoded non-Clifford状态 | 单个pure stabilizer不能保存 `|A_L>`。需要先声明精确表示及验证接口，如logical amplitude＋经过验证的Clifford编码等距映射及真实测量更新；204原子dense向量不作为方案。checkpoint、RNG/概率、branch和重放一致性须共同设计，本轮未实现 |
| D3：经典反馈 | 现AND条件不能直接表达长XOR/decoded Clifford标签。候选experiments controller在真实committed measurement后计算`BitExpr`、选择下一具体fragment并绑定状态指纹，保存决定及其依赖；若需修改ENV控制IR则另作接口决策。没有虚构native measurement结果，未知decoder/control latency保持unknown |

native S 的时长不能借用论文的code-cycle数，也不能把两个tracked T当作一个隐藏S。物理扩展平台须独立声明并验证：AOD容量、全部活动交点、实际CZ pairs、碰撞/支撑、光照与MZ运输条件继续不变。

## 9. 下一批文件与停止条件

建议按依赖新增，尚无实现承诺：

| 新模块 | 输入→输出与验收停止点 |
| --- | --- |
| `mixed_pauli_spec.py` | 已有prefix＋patch/sector/epoch＋signed product→不可变spec、代表展开、能力缺口；actual3500 inventory逐项覆盖、alias/坏history拒绝 |
| `mixed_pauli_reference.py` | spec→显式cat门/真实投影；current-menu mixed X/Z与even-Y候选用既有原语；full-Y采用明确reference S，不伪装可lower的PBCProgram。独立Stim `MPP`/NumPy Choi验收后停止 |
| `conditional_clifford_frame.py` | 真实decoded m/r→signed symplectic pullback＋下一标签＋phase/依赖ledger；完整逻辑3500resource、一般纠缠输入与eager oracle验收，报告真实framed support统计 |
| `encoded_clifford_resource.py` | explicit `|Y_s>` preparation＋signedPZ/X读出＋Pauli反馈＋full lifecycle；四分支、noncommuting组合和sector合同独立通过后停止 |
| `mixed_pauli_fault_audit.py` | 候选native序列→独立fault propagation、decoder、retained-channel与distance witness；验证失败保留失败，不改物理条件 |
| 后续platform adapter | 仅在所需gate/状态能力决策成立后接全部roles、动态feedback、Executor与strict replay；之前lowering应明确拒绝缺失能力 |

前两项可以先在独立协议/理想reference实现；mixed X/Z现门集路径可另外生成真实native circuit。native S或non-Clifford量子表示的架构决策未完成时，后续依赖必须保持blocked capability输出，而不是扩大当前`require_fault_tolerant`的成功范围。

## 10. 本轮校核与可重建数据

本轮新增本文和可发布的独立NumPy校核工具 [`audit_mixed_pauli_design.py`](../tools/audit_mixed_pauli_design.py)，不导入ENV、不安装依赖、默认不读取任何本地实验文件。只需要已声明的NumPy依赖（见 [`requirements-shor15.txt`](../requirements-shor15.txt)）。公式校核不是新的backend testids，不增加阶段测试总数：精确CY误差0；H/CZ展开最大误差2.22e-16；±signed二体Pauli、Tdg方向的`|Y_s>`纠正144分支最大1.16e-16；pullback误差0；三项注入保持原序（第三项与前两项反对易），复杂data-reference输入、residual Clifford/外部相位的64完整branches本机复建最大约5.98e-16（验收阈值1e-12）。这些只验证设计公式，不代表encoded circuit/FT/Executor。

从仓库目录运行，不需PYTHONPATH或任何hardcoded本地绝对路径：

```sh
# Formula-only audit; --output is optional. An existing output file is rejected.
python tools/audit_mixed_pauli_design.py --output artifacts/mixed-design/formula-audit.json

# Optionally audit an actual export already generated by the complete-PBC CLI.
python tools/audit_mixed_pauli_design.py --input artifacts/shor15/full-pbc/complete_adaptive_pbc.json --output artifacts/mixed-design/with-inventory-audit.json
```

工具实际收缩两次projectors/resource bras，对所有144纠正分支和64完整注入分支比较独立目标；`status=reference_math_passed` 与 encoded/FT/physical false 显式分开。给出 `--input` 才增加只读eager-source统计和源SHA256，不假定某个ignored artifact已经存在。输出按调用者路径创建新JSON，保留已有结果。

actual源为 `stage-complete-pbc-shots/complete_adaptive_pbc.json`，SHA256 `9b7f462782cba14f66f594fad29eee771d0b8ca287460f20cc6a37811fe47aaf`。可用现有完整CLI重新导出，再按每项factors计算 `n_Y` 与 `3*(len(data_factors)+1)+2*n_Y`，分别聚合计数；3500总数、1683odd-Y、642非零even-Y和最大37是该固定源的只读结果。它们不是framed全分支统计。

文档沿用RAG K04/K07/K09/K10/K18/K19/K23/K33/K39/K40的合同；K23/K33旧缺口快照的最新逻辑/组合能力由K38/K39和[阶段入口](qec_shor15_stage.md)覆盖。尚需实现的门、encoded magic与完整物理链路仍按各自验收状态报告。
