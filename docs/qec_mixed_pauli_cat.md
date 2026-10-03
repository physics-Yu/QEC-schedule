# 含 Y 的 signed cat PPM 原生线路与精确参考

本模块生成含 X/Y/Z 的真实 `PhysicalCircuit`，并在独立理想参考中验证其保留编码数据的测量通道。它补上此前 [mixed X/Z cat](qec_mixed_xz_cat.md) 的 Y 线路缺口。**没有扩展生产 PBC IR、tracked ENV 量子表示、物理模型或控制器；FT、physical execution、magic consumption、完整 encoded Shor 均为 false。**

源码：[`mixed_pauli_cat.py`](../src/neutral_atom_experiments/qec_pbc/mixed_pauli_cat.py)；独立验收：[`test_qec_mixed_pauli_cat.py`](../tests/test_qec_mixed_pauli_cat.py)。设计来源和文献/工程边界沿用 [`qec_mixed_pauli_backend_design.md`](qec_mixed_pauli_backend_design.md) §§2–6。当前标准朝向保持每 patch 9 data＋8 syndrome；未使用 code deformation 或 twist。

## 原生 CY 的顺序与相位

控制为 cat，目标为 data，时间顺序为：

```text
CZ(c,d); H(d); CZ(c,d); H(d); T(c); T(c).
```

前四门为 `CX·CZ`，control=1 时 data 接收 `XZ=-iY`。cat 上的 `T²=diag(1,i)` 正好补齐相位，因此完整矩阵是 `diag(I,Y)`，没有遗漏 branch 或整体相位。测试独立构造全部 4×4 复矩阵，同时证明调换 CZ/CX 会产生不同结果。逻辑代表仍为 `Y_L=iX_LZ_L=Y0 Z1 Z2 X3 X6`，不能换成一个裸物理 Y 测量。

每个 physical Y 实际输出 2 CZ＋2 H＋2 T。固定代表中的一个 logical Y 含一个 physical Y，其余四个因子为 X/Z，因此需要五个 cat atom、两个 T。所有 native gates 保留在导出中，不导出隐藏 S，不删除中间 T，不虚构耗时。

## 实验封装与组合合同

`append_mixed_pauli_cat(prefix, incoming_sectors, logical_product, ...)` 接已有 `PBCProgram` 或前一次 `MixedPauliCat`，返回独立实验封装。现有 `GateTask` 不接受 T，因此 `NativeCatProgram` 保存真实 role-based `PhysicalGate`，**不是新增 PBC IR primitive**。`item.compile(bindings)` 返回实际 `PhysicalCircuit`、完整 bindings 与 semantic/raw measurement sidecar。

从 PBCProgram 进入时，先使用现有 lowering，保留每一个原生 prefix gate 的 ID、依赖、条件、readout flip 和 semantic 测量映射，保留 roles、detectors、observables、memory contract。新增角色只追加在后面，默认绑定下原有 Q IDs 不变。连续测量直接保留前一 envelope；不能把这个 envelope 传给现有生产 `lower_to_physical` 当作 PBCProgram。

声明任意数量的标准 canonical patches，目标支持只能来自声明的 patches；所有参与 patch 的 8 项 incoming `BitExpr` 必须引用 prefix 中真实的 semantic 测量。首轮检测比较这些带符号的历史与实际新读出，不假定全零；所有 syndrome atom 要已真实 RESET，data 不能已消耗。完整耦合过程中不插入 checks。最后执行真实 closing rounds，并输出新的各 patch sector history。

cat、verifier 必须避开数据和旧角色。显式 `resource_reuse=True` 只允许完整角色集、每个角色最近一次非 RESET 操作为真实 destructive MEASURE、最终操作为 RESET。下一 epoch 仍逐个真实 RESET/reprepare；namespace 自动避开既有门、测量和输出 IDs。复用对象是测量辅助，**不代表 magic factory 复用**。

模块结构支持 13-patch joint product。12 个 logical Y 加一个资源 Z 的固定代表需要 `12×5+3=63` cat、一个 verifier；13×17＋64=285 是此模板角色数，**不是物理 peak**。测试只验此例的全依赖编译、bindings 无 alias 和 24 个真实 T，不将其写成完整 13-patch channel/FT/physical 验收。实际 framed inventory 的最大候选 cat 长度 45 仍来自已发布的每项具体 label，不能被这个保守示例替代。

## TT 精确参考边界

`clifford_reference_steps(circuit)` 是独立参考适配器。只有严格相邻、同 atom、无参数/条件、第二 T 仅依赖第一 T，且第一 T 没有其他 successor 的 pair 才接受。后续所有涉及该 atom 的操作也必须确实依赖已完成的第二 T，防止依赖图从中间非 Clifford 态穿过去。输出参考 step 保留两个实际 native gate IDs。

单 T、Tdg、原生 S、分隔的 TT、不同 atom、竞争 successor 或绕开第二门的 wire dependency 均明确拒绝。适配器在 reference 层使用精确矩阵恒等式 `TT=S` 后调用 Stim；它不把单个 T 近似为 Clifford、不让 ENV 接受 T，也不支持两 T 之间插入的 fault/noise/measurement。**tracked `StabilizerState.apply_gate('T', ...)` 仍拒绝**。因此这种 grouping 不能用于宣称 native-location fault tolerance 或物理量子态重放。

`verify_mixed_pauli_instruments(...)` 真实执行 prefix 与全部制备/核验/耦合/readout/reset 的合格参考 fragments，入口独立检查 actual quantum sector，oracle 复制该实际输入后只实施目标 signed projectors。输出比较全部 logical/reference Pauli 期望和所有 retained stabilizers。外部 references 必须为真正 data-kind 角色，位于参与 patch 之外；cat/verifier/syndrome 不能假作 reference。

为避免指数计算被误当通用后端，完整 channel 枚举最多六个 logical＋reference qubits；结构编译没有此限制。`forced_cat_bits` 仅在独立参考中作真实 Born projector 的非零概率 postselection，不加入输出线路、控制位或 `measurement_results`。正常 seeds 路径真实采样。

## 核验与尚缺的生产控制

cat 链使用真实 H/CZ 制备；独立 verifier 对每个相邻 ZZ 做两遍真实 reset/coupling/readout/release。`verification_status(actual_semantic_reports)` 对未知位、非整数位拒绝，只有完整实际报告全零才接受。独立参考在第一 data coupling 前读取该状态，真实 cat X fault 的例子被拒绝。

静态 `PhysicalCircuit` **没有生产 abort/retry**。生产控制器仍需分别提交 resource fragment、等待 committed reports、验证/选择后续 data fragment，并保留失败证据。当前函数判断结果不能冒称已经停止 ENV 的执行。hook、重复 PPM decoder、accepted fault channel、运输/idle/loss 和 factory quality 尚未验收；标准空间 d=3 的来源不证明本 gadget 的 circuit distance。

## 当前可重建证据

35 个不同测试本轮通过。测试数量不把枚举内循环增加为 testids：

- ±Y：全部 32 raw records，真实编码 Bell/reference 输入；各 branch 的完整 logical/reference density operator 与 signed projector 一致。
- ±XYZ：全部 2048 raw Kraus 分支因子化证明；实际原生合格参考执行包括带符号 incoming sectors、三组编码/reference Bell pairs、两种显式 parity 和真实采样 probes；每个实际分支比较 4096 Pauli 期望。
- ±YY：全部 1024 raw Kraus 分支，两份 cat 相位和 4 个真实 T；实际 probes 检查 256 Pauli 期望。
- 非对易 `−Y_A X_B`→`Y_A Z_B`：全部四 logical branches，复用同八个 cat＋一个 verifier，保留两份外部纠缠与带符号 sectors；45 roles，不新增第二份辅助，不 RESET AB data。
- prefix history、完整 uninterrupted coupling、TT isolation、13-patch 编译、真实核验失败、错误 incoming sector、辅助生命周期及 reference alias 边界。
- public all-raw audit 对实际 H→Z、缺失 H、读出前 RESET、额外 coupling gate、改动 verification CZ 和 semantic sign sidecar 的六种突变明确拒绝，避免对修改的线路沿用原公式。

`audit_cat_factorized_kraus(item)` 首先对**完整实际 tail**作严格资格核对：ordered phase ledger 必须逐门覆盖实际线路；before/after 必须为声明的 canonical 模板；cat 准备、两遍 verification、coupling、H/MEASURE/RESET 的顺序、roles、IDs、依赖和 semantic/raw/sign sidecar 必须全部符合合同，任何额外或缺失 gate 均拒绝。其后用原生逐门复振幅模拟真实 GHZ 准备，独立检查每个完整 controlled factor 的全部 4×4 复矩阵，**从实际读出 unitary 构造每个 bra**，最后收缩两个 GHZ arms 与全部原始读出 bras。对于 L≤16，枚举所有 raw strings，核对

```text
K_t = 2^(-(L+1)/2) [I + (-1)^xor(t) Q],
b = xor(t) XOR [physical sign = -1].
```

因各 cat 只控制一个不同 physical data，该 factorization 是完整 noiseless Kraus 恒等式，包含 signed phase，适用于外部纠缠；不是对大 cat 的抽样结论。函数返回每项实际误差/计数；L>16 明确拒绝全部枚举，避免把 63-cat 示例伪称 all-raw proof。

在仓库目录、已声明 NumPy/Stim/pytest 依赖的 Python3.12 环境中复验：

```sh
python -m pytest tests/test_qec_mixed_pauli_cat.py -q -p no:cacheprovider
```

导出某个已有真实 prefix 的 native circuit 和参考报告时可直接使用以下接口；输出路径由调用者选择，不需要装依赖或 ENV 执行：

```python
from dataclasses import asdict
from neutral_atom_experiments.qec_pbc.mixed_pauli_cat import (
    append_mixed_pauli_cat, audit_cat_factorized_kraus,
    verify_mixed_pauli_instruments,
)

item = append_mixed_pauli_cat(prefix, incoming_sectors, signed_product,
                              data_patches=declared_patches, rounds=1)
compiled = item.compile()
export = {"instrument": item.to_dict(), "bindings": dict(compiled.bindings),
          "native_gates": [asdict(g) for g in compiled.circuit.gates],
          "all_raw_math": audit_cat_factorized_kraus(item),
          "actual_reference": verify_mixed_pauli_instruments(
              (item,), reference_roles=external_reference_roles, seeds=(0, 7))}
```

一轮 before＋一轮 after 的新增 native gate 数：单 Y 为 312，XYZ 为 858，YY 为 643；包括实际 syndrome rounds、完整 cat 核验与 release，排除调用者已有 prefix。默认 rounds=3 会真实增加前后 rounds，不能沿用这些计数作为默认成本。

本轮另执行六个 ±Y/±XYZ/±YY 原生导出和真实 seed 0/7 reference probes，完整实际 fragment 资格核对与真实 bra 收缩后的产物为 `artifacts/qec-shor15-2026-10-03/mixed-pauli-cat/native-reference-qualified.json`。最大 controlled-factor 矩阵误差 2.23e-16，GHZ 准备误差 1.58e-15，Kraus coefficient 误差 2.39e-16。之前 `native-reference.json` 保留为修复前证据，不作为当前 public all-raw 资格验收。该 ignored 产物不是运行依赖；调用者可使用上面的 export API，并从已提交测试里的 `prefix` 构造完全相同的真正线路输入：

```python
from runpy import run_path
from neutral_atom_experiments.qec_pbc.pauli import PauliProduct

make_prefix = run_path("tests/test_qec_mixed_pauli_cat.py")["prefix"]
declared_patches = ("A", "B", "C")
prefix, incoming_sectors = make_prefix(declared_patches, references=True,
                                       signed_sector=True)
signed_product = PauliProduct((("A", "X"), ("B", "Y"), ("C", "Z")), -1)
external_reference_roles = ("ref.A", "ref.B", "ref.C")
# Run the export block above; write JSON to a new caller-selected path.
```

这一重建入口依赖已声明的测试依赖，实际制备/纠正/编码 Bell 耦合来自 canonical/native gates；没有把期望向量注入量子输入。35 项新测试＋41 项既有 X/Z 测试联合本轮 76 PASS；原 workspace 架构扫描零违规。clean publication checkout 的模块计数由其独立验收记录，不沿用原 workspace 数字。
