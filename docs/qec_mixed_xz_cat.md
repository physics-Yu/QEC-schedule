# Mixed X/Z cat logical measurement：理想 native 参考实现

`mixed_xz_cat.py` 将已制备的两块 rotated [[9,1,3]] 数据 patch 上的非平凡、带符号 X/Z 逻辑 Pauli product 转成真实 H、CZ、MEASURE、RESET 操作。阶段目标是补齐 `X_A Z_B` 这样的混合基测量，并保持输入数据与外部参考比特的相干性。本模块没有调用物理平台执行器。

入口：

```python
from neutral_atom_experiments.qec_pbc.mixed_xz_cat import (
    append_mixed_xz_cat, verify_mixed_xz_instruments,
)
from neutral_atom_experiments.qec_pbc.pauli import PauliProduct

one = append_mixed_xz_cat(
    prepared_prefix, incoming_sectors,
    PauliProduct((('A', 'X'), ('B', 'Z')), sign=-1),
    rounds=3,
)
native = one.compile()
two = append_mixed_xz_cat(
    one.program, one.output_sectors,
    PauliProduct((('A', 'Z'), ('B', 'Z'))),
    rounds=3, cat_roles=one.cat_roles,
    verifier_role=one.verifier_role, resource_reuse=True,
)
```

`prepared_prefix` 必须实际包含两块 canonical patch 的所有 34 个角色、已完成的测量历史，以及已释放的 syndrome 辅助原子。`incoming_sectors[(patch, kind, check)]` 是非空 `BitExpr`，引用真实 prefix 测量位；常数项保存已知符号运输。前缀操作、角色、detector 和 observable 原样保留，输入 data 不重新 RESET 或制备。显式非空 `pending_operations` 被拒绝；它是调用者给出的执行前沿声明，本模块不读取物理 checkpoint。独立 native 审计还在第一条新操作前检查实际数据态是否位于声明的 16 个带符号稳定子扇区。

协议依次执行：

1. 两块输入各执行 `rounds` 轮完整 canonical syndrome extraction，第一轮与真实 incoming-sector 历史构成 detector。
2. 为每个物理 Pauli factor 分配一个 cat 原子，另配一个 verifier。全部真实 RESET，H 第一个 cat，再用 H(target)–CZ–H(target) 的 CNOT 链制备 GHZ。
3. 两遍测量全部相邻 cat `Z_i Z_(i+1)`。每次 verifier 真实 RESET、两次 CNOT、Z 测量、RESET；各报告位及其依赖完整保存。
4. 完整耦合整个 product。Z factor 使用 CZ(cat,data)，X factor 使用 H(data)–CZ(cat,data)–H(data)。整个耦合期间没有插入 data syndrome check。
5. 每个 cat 真实 H、Z 测量、RESET。全部报告位的 XOR 为 unsigned physical product 的结果；负号仅作为最终 `BitExpr` 常数翻转。
6. 两块输入再各执行 `rounds` 轮完整 canonical extraction，留下全部 16 个实际 closing-sector 表达式。完整 logical product 与每个 code stabilizer 对易，所以这些 detector 比较同一个扇区。

标准代表为 `X_L=X_0 X_3 X_6`、`Z_L=Z_0 Z_1 Z_2`。`X_A Z_B` 因此需要 6 个 cat 加 1 个 verifier；两块 data/syndrome 为 34 个角色，共 41 个，带两个外部 Choi reference 时共 43 个。默认 3+3 syndrome rounds 的新增部分是 **1295 个 native gates：735 H、319 CZ、129 RESET、112 MEASURE；106 detectors：96 syndrome、10 cat verification；1 个新的 signed logical observable**。这些是协议数量，不是脉冲、时长或物理性能。

`verification_status(committed_semantic_bits)` 只在全部真实核验报告可用时返回 accepted/rejected；缺位视为 pending，非整数位拒绝。非零报告的声明策略是在 `coupling_entry_id` 之前拒绝该 resource。**静态 `PBCProgram` 不包含 abort/retry controller；调用 `compile()` 后直接执行整个 circuit 不会自动中止。** 独立理想 native 审计在这个边界检查报告并拒绝异常。未来物理适配需要分段提交、先等待核验报告，再决定是否提交数据耦合。核验 detector 本身不能替代这一控制步骤。

资源默认必须新建。`resource_reuse=True` 必须显式提供全部已有 cat/verifier 角色；每个角色的最后操作必须是 RESET，最后一个非 RESET 操作必须是真实 MEASURE。旧 epoch 的测量不能为后来未经读出的资源制备提供释放证明。新的 epoch 再次执行完整 RESET/GHZ/核验，namespace 自动避让，历史报告不删除。此版本支持相同权重的资源复用；不同权重需要匹配新的明确资源集合。

理想仪器的数学目标为带符号 `P` 的投影测量 `Π_b=(I+(-1)^b P)/2`。长度 L 的 cat 逐位 X 读出产生 raw string t；令 q 为其 XOR、s 为 product 负号位，则 semantic result `b=q XOR s`。对应 Kraus operator 为 `K_t=2^(-(L-1)/2) Π_b`，相同 semantic parity 的所有 raw strings 不额外泄露 logical 信息。

测试实际执行 encoded prefix 并制备两对 logical/reference Bell pair，不将预期量子态安装到 native simulator。oracle 只复制已实际执行的初态，然后施加 signed logical projector。±`X_A Z_B` 的全部 64 个 raw strings 均核验：Choi 输入下各概率 1/64、两个 semantic branches 各 1/2；每个分支比较全部 256 个 logical/reference Pauli expectations 和全部 16 个 closing stabilizers。这验证任意两逻辑比特输入及其外部纠缠的理想 retained channel。

连续非对易样例是 `X_A Z_B → Z_A Z_B`，仅 A 上的因子反对易。四个 logical branch combinations 均通过，复用同一组 7 个资源原子、保存全部 prefix 和再 RESET；所选两条 raw strings 的联合概率各为 1/4096。测试中的强制读出通过独立 Stim postselection 完成，只用于审计，不进入 IR、native circuit 或生产 controller。另有实际 cat X 扰动产生非零 verifier 报告的 pre-data rejection 测试，以及 Y、无效/未来 history、非 codespace 输入、角色冲突、未释放资源和 pending 前沿的拒绝测试。

复现：

```powershell
$env:PYTHONPATH='src;artifacts/qec-baseline-deps'
& '.venv-qec-noise-modern/Scripts/python.exe' -m pytest tests/test_qec_mixed_xz_cat.py -q -p no:cacheprovider
```

已实现范围是无故障、声明 code-space 输入上的理想 native measurement instrument。两遍 cat 核验以及前后重复 syndrome 不能推出 circuit-noise 容错。此版本没有 single-fault/distance audit、noisy decoder、retained-channel FT、运输/idle/loss 噪声、Y/S/Sdg、magic-state 制备、三次 PPM 重复读出、完整 encoded Shor 或物理平台执行。后续验证重复 PPM 与 syndrome 的联合 noisy contract，才能讨论对应容错性质。
