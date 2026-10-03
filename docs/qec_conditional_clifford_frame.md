# 条件 Clifford frame 的理想测量执行

本模块实现 [mixed/Y 后端设计 §5.1](qec_mixed_pauli_backend_design.md#51-先实现完整-signed-clifford-frame) 的完整 signed Clifford frame 控制器。它在每次真实资源测量后推迟纠正，用新的 signed Pauli 标签执行下一次投影，并能把保留的量子输出兑现为正确复振幅。`encoded=false`、`fault_tolerant=false`、`physical_executed=false`、`native_s_implemented=false` 始终明确；现有 ENV、硬件与已发布 eager `adaptive_pbc.py` 均未修改。

## 状态、相位和依赖合同

约定 `psi_sem = F psi_unrealized`。`SignedCliffordFrame` 保存全部 `2n` 个 `F† X_j F` / `F† Z_j F` signed generator images；12个 data wire 是24个像。每次更新检查整个 symplectic commutation form。多体纠正可把单比特 generator 变成跨 wire 的 Pauli product，不能用逐 wire 的 frame 代替。

下一项源 observable P 实际使用 `Q=F†PF`，其符号也进入联合投影。理想 executor 附加真实 `(|0>+exp(i*s*pi/4)|1>)/sqrt(2)` resource vector，实际计算、归一化 `Q⊗Z` projector 的 m 分支，再实际计算、归一化 resource X 的 r 分支。随机路径从这些 Born 概率采样；确定性 `outcomes` 仅选择真实存在的分支，不填写期望量子态。每次只保留一份 resource 临时态，允许 data 与外部 reference 纠缠。

`FrameController` 按 `begin → commit_joint → commit_resource_x → update` 推进；joint/resource IDs 必须属于当前 resource，m/r 必须是已知整数0/1。缺少 joint 投影、提前更新、提前开始下一 resource、重复 ID、重复 update 或消耗后重用 resource 均拒绝。测量记录以线性真实结果依赖链连接，下一 joint 通过上一次 resource-X 的依赖间接依赖整个先前 frame。报告副本不能修改已 committed 的控制历史。controller 接收 executor 的结果，本身不执行或伪造量子投影，也不向 native `measurement_results` 写入 computed key。

结果形成 `C=P^r S_P(s)^m`，再更新 `F_new=C F`。inverse-frame 的 Hermitian 相位按完整 Pauli 乘法处理：反对易且m=1时 `C† A C=(-1)^r i s P A`。每条纠正的 P、s、m、r、resource 和真实 measurement IDs 保存在 chronological ledger 中。symplectic tableau 不保存 global phase，最终兑现必须使用该 ledger 的精确 `S_P(s)=Pi_plus+i*s*Pi_minus` 和 signed P，不能仅重建一个相差任意 global phase 的 Clifford。

公开构造 frame 时，合法 symplectic tableau 仍必须与其完整 ledger 一致；空 ledger 只允许 identity frame。独立 ledger replay 在公开构造/审计时执行一次。内部 `corrected()` 在不可变的已验证 frame 上验证新记录并更新全部 generator，不在每一步重新演算3500条历史。

## 可调用接口与最终输出

- `SignedCliffordFrame.identity(wires)`、`pullback(P)`、`corrected(record)`、`validate_ledger()`：完整 signed frame 的生成、更新和独立 ledger 审核。
- `execute_deferred_reference(program, state, reference_qubits=..., outcomes=..., seed=...)`：输入已有 `AdaptivePBCProgram`，执行真实 pulled-back projections，返回 `DeferredReferenceResult`。unknown resource quality 要有显式 `assume_ideal_resources=True` 才可按理想态执行。
- `result.unrealized_state` 是只读的 frame-labelled vector；它尚未执行 F、residual Clifford 或 program phase。`result.realize(external_global_phase_radians=...)` 按时间顺序兑现 ledger、执行 residual，并实际乘 program 与 external phase，返回兑现后的理想量子输出。
- `result.terminal_z_labels(wires)` 导出按调用方顺序排列的 `F† C_res† Z_j C_res F`；`execute_terminal_z` 在 unrealized vector 上真正投影这些 signed labels，返回保留量子态与真实结果记录。标签两两对易，measurement IDs 避免历史冲突，位与原 semantic wire 的映射保留。分批调用时，结果的独立 `terminal_measurement_records` 继续保存完整 terminal 历史、namespace 和依赖，不混入 resource records 或改变其 inventory。
- `audit_deferred_program(source, input_state=..., expected_state=...)` 比较兑现结果、现有 eager executor 与直接源酉/调用方原始线路预期，核验复振幅、global phase、全部结果依赖、resource 消耗及实际分支 inventory。`expected_state` 应已包含调用方的 external global phase。

`tools/audit_conditional_clifford_frame.py` 接受现有完整 Shor CT 导出，保留全部72个源门的 spans 与28个 CP 出处，读出 external phase 后真正作用于输出。CLI 不安装依赖、不导入 ENV，也不修改输入；`--output` 必须是新文件。

## 本轮验收

27个独立测试通过。矩阵预期直接构造 Pauli、纠正酉和 resource embedding/projector；覆盖 signed Y/identity、两种 s 与全部m/r、任意 complex input、外部 reference、非对易三注入的全部64分支、24 generator 的独立 binary symplectic form，以及包括 residual/phase 的 terminal retained-data instrument和分批8Z读出的连续历史。失败边界涵盖未知位、顺序依赖、重复资源与不一致的 tableau/ledger。另一个完整源 Shor gate-level output 测试执行真实终端投影，再分别验证128的 order-recovery失败和192的CF/order/GCD成功；不依靠预知周期构造电路。

完整默认 ε=1e-3/seed7 CT 导出已在零输入4096维与 generic entangled reference 8192维上执行，每个 case 都真实消耗3500个资源、执行7000次投影。兑现后与 eager 的 L2 差分别为 `1.22e-14` / `1.26e-14`，与原 CT circuit 为 `1.046e-13` / `1.048e-13`；与 exact Shor 的差为 `3.56877e-5` / `2.53070e-5`，在原 `1e-3` 总预算内。external global phase `3.5281558121369727` 实际作用，完整8个 terminal Z 投影也与 semantic-output 独立 projector 比较通过。

seed7 的实际 framed inventory 是3500 joint measurements、2168项含Y、2437项 mixed data basis；data support最大12，含resource的joint support最大13，后者出现56次。signed joint 负1732项、正1768项。同seed的两种输入产生相同m/r路径，故该两case的统计相同；这些数字只描述实际分支，不能替代其他 seed 的 inventory。设计用固定 d=3 X/Z长度3、Y长度5代表展开 `3*joint_weight+2*nY`，这一分支的最大候选 cat length为45；它只是 `template_shape_only`，不是 physical atom peak、已实现 encoded coupling 或 FT 证明，通用保守上界63仍保留。

CLI 还执行了 fresh controller/vector/resource namespace 的独立完整算法 shots：seed7/8/9 的真实 terminal projector 依次读到128、0、192。前两次失败原样保留；第三次通过 continued fractions 得到并验证order4，再由GCD得到3和5。共实际消耗10500个资源，执行21000次注入投影和24次 terminal投影。用于验算的 CT/源线路态只作 oracle，不用于重新采样或选择成功结果。默认最大16次，耗尽时保留 `success=false`。

复建使用项目 Python3.12 和现有 NumPy：

```powershell
$env:PYTHONPATH = 'src'
python tools/audit_conditional_clifford_frame.py `
  --input artifacts/shor15/full-pbc/complete_clifford_t.json `
  --output artifacts/shor15/deferred-frame/audit.json `
  --seed 7 --max-attempts 16 --include-measurement-records
```

输入可由已发布 [QFT synthesis CLI](qec_qft_synthesis.md) 生成；路径由调用方选择。本轮本机输入是 `artifacts/qec-shor15-2026-10-03/stage-complete-pbc/complete_clifford_t.json`，最终证据是同目录父级 `conditional-frame/full-audit-final.json`；ignored artifacts 不作为跨机器唯一交接。新27项与现有eager37项联合复验为64个不同nodeids通过；原工作树的source扫描范围为184模块、0违规；本PR远端main独立发布副本的统一架构检查为251模块、0违规。

下一依赖是让 encoded mixed/Y PPM 后端实际接受这里的 signed、branch-dependent labels 与真实反馈依赖。当前 native AND条件接口不等于这个理想 controller；decoded XOR、native/encoded S 能力、encoded magic input、resource factory、hook/distance/decoder验收和整体 physical Shor 均仍未实现。surface orientation 与物理约束维持现合同。
