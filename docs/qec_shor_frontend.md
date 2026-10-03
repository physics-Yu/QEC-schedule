# Shor 算术到 logical Pauli 前端

`qec_pbc/shor_frontend.py` 接受显式 logical wire 上的 X/H/CX/CCX 算术，使用精确 7-T Toffoli 分解（4 T、3 Tdg、6 CX、2 H）后调用 `logical_pauli`。Tdg 保留为逆相位，不用多个物理 T 冒充资源态消耗。单个 Toffoli 的全部基态列、任意复数叠加和纠缠 spectator 已独立验证。

输入算术 provenance 与 Clifford+T 消耗报告分开保存；T consumption 不是峰值 magic buffer，也不是同时需要的原子数。没有建立 CCZ factory、T injection 或 QFT 综合模型。

`import_gidney_modexp(path)` 读取此前已经审计的 [作者 N=21 QASM](https://algassert.com/assets/2025-08-30-why-no-factor-21/factor21.qasm)，强制验证 SHA256 `1349167dc4e60e4df6f4687b1e4e09550dfc2ba140076400e05a847f69739068`。仅保留准备与模幂，删除首个 Fourier-readout H，不读取后续条件旋转或测量；不是通用 QASM parser，也不是完整 Shor。

已有原件可运行：

```powershell
$env:PYTHONPATH='artifacts/qec-pbc-test-deps;src'
& 'C:\Users\yuyqp\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' examples/run_shor_pauli_frontend.py --qasm artifacts/shor-greedy-2026-09-15/circuits/gidney-factor21.qasm --output artifacts/qec-parallel-2026-10-02/shor-prefix
```

跨机器先下载上述固定来源，再用相同入口；指纹变化会拒绝。入口独立验证全部 1024 个指数的 `pow(2,e,21)` 与控制寄存器恢复，再导出 logical Pauli JSON 与资源报告。无需输入已知周期或因子。

现有 `shor_arithmetic.Arithmetic` 的增量梯可通过相同接口作为算术正确性测试输入，但不能据此作为主要 Shor scaling 性能基准。
