# 完整 Shor 的 QFT 综合与资源测量执行

2026-10-03：第二逻辑阶段新增 [`qft_synthesis.py`](../src/neutral_atom_experiments/qec_pbc/qft_synthesis.py)。完整 N=15 Shor 的全部 28 个 CP 已按原角度综合为 Clifford+T；整条线路可接既有 signed-Pauli 前端和 [adaptive resource bridge](qec_adaptive_pbc.md)，实际执行理想资源测量和反馈。

这是**完整未编码理想算法**的近似编译与 measurement instrument 验证，encoded magic、一般 encoded mixed-PPM/Clifford feedback 和原子执行仍需连接。encoded ZZ/XX 的独立物理证据以本轮协议文档与 handoff 为准。

## 一手实现与隔离依赖

已核对 [pygridsynth 官方仓库/API](https://github.com/quantum-programming/pygridsynth)、[固定 1.2.0 发布](https://pypi.org/project/pygridsynth/1.2.0/) 和 [MIT 许可](https://github.com/quantum-programming/pygridsynth/blob/main/LICENSE)。采用纯 Python 的 `pygridsynth==1.2.0` 与 `mpmath==1.3.0` 核心，固定 wheel SHA256 为 `96114f32eff2e26e2531dcdf38f8ba8e66510b52998ca75745cf183f2a345da8`。没有安装当前 2.0 的 cvxpy/numba 等额外多比特综合依赖，也未改宿主 Python 环境。

理论依据为 [Ross–Selinger 原论文](https://arxiv.org/abs/1403.2975)：不使用辅助量子比特的单比特 Rz 近似综合。当前不宣称本次输出达到全线路最优 T 数；实现是保留原 QFT 门序列的明确基线。

官方 `gridsynth_circuit(..., up_to_phase=False)` API 返回矩阵右乘顺序的 gates，必须反转后写入项目的 chronological IR。W 是整体相位，另有 `circuit.phase`；两者都保留，未把 W 当作单比特门。每个返回序列的 phase-sensitive 2×2 operator 误差另由 NumPy 独立核验。

## CP 分解与误差预算

定义 `CP(θ)=diag(1,1,1,exp(iθ))`，逐门使用：

```text
CP(θ) = exp(iθ/4) · [ Rz_c(θ/2), Rz_t(θ/2), CX(c,t), Rz_t(-θ/2), CX(c,t) ]
```

方括号按时间从左至右。这个公式独立验证全部四个 basis 列和整体相位。没有根据已知周期删除 CP。

默认总 operator ε 预算为 `1e-3`。28 个 CP 共 84 项 Rz；每项请求 `δ=ε/(2×84)`，预留另一半给数值余量。局部门嵌入任意更大寄存器不增加 operator 误差，乘积的 telescoping 上界为各局部误差之和。报告同时保存请求上界、各项实际数值误差及完整 QFT 的独立 operator SVD 误差；没有只验特殊 N=15 输出分布。

`Rz(kπ/4)=exp(-ikπ/8)T^k` 的情况走解析精确分解，其余使用固定 gridsynth。CCX 延用既有精确 7-T 分解。默认 seed=7、ε=1e-3 的完整门数如下：

| X | H | CX | Tdg | T | S | 总门 | T/Tdg 消耗 |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 32 | 3500 | 108 | 29 | 3471 | 1853 | 8993 | 3500 |

该资源数是总消耗，不是同时存在的 magic patches。精度改变会改变门数，factory/cache/物理原子峰值保持未知。

CP 分解累计的 θ/4 一般不是整数个 π/8。因此 wrapper 明确保留 `global_phase_radians`；`compile_pauli()` 只归一化 CT 门列，其整数 global phase 按既有前端合同处理。资源测量输出最后**实际乘上** external global phase，再与原 Shor 复振幅比较。不能把外部相位塞成整数、重复计入或静默丢弃。

## 已完成的独立验收

新增 **14 项测试通过**：

- Rz 的独立 2×2 operator 与 global phase；CP 全 basis 分解。
- 8-bit QFT 的全部 256 个 operator 列、SVD 误差 `6.78e-5 < 1e-3`。
- 一般复数且与 work 纠缠的 QFT probe，L2 误差 `2.54e-5`；完整 Shor 任意输入 probe `2.55e-5`。
- 全部 28 个原 CP angle 与 source gate ID 来源、84 份 Rz 证据和 72 项源 gate spans。
- 完整 CT → 3500 PPR rotations → 3500 magic resources 的理想执行：每次 7000 个实际投影测量和条件纠正，分别核验算法零输入与一般 data-reference 纠缠输入，全部资源 consumed。
- 全局相位、bit order 转换、完整 Shor phase 分布及总预算。

完整资源执行不建立 3500 magic wires 的联合指数态空间，而是逐个追加、测量、消耗。测量 branch 的概率是 `2**(-7000)`，用 `log2_branch_probability=-7000` 记录，避免 double 下溢误写为数学上的零概率。

## 复现与输出

```powershell
& 'C:\Users\yuyqp\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pip install --no-deps --target artifacts/qft-synthesis-deps -r requirements-qft-synthesis.txt
$env:PYTHONPATH='artifacts/qft-synthesis-deps;artifacts/qec-pbc-test-deps;src'
& 'C:\Users\yuyqp\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_qec_qft_synthesis.py -q -p no:cacheprovider --basetemp artifacts/pytest-qft-synthesis
& 'C:\Users\yuyqp\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m neutral_atom_experiments.qec_pbc.qft_synthesis --epsilon 1e-3 --seed 7 --output artifacts/qec-shor15-2026-10-03/complete-logical-pbc
```

其他机器使用 Python ≥3.11、已有 NumPy；测试还需 pytest。`--no-deps` 只安装本任务使用的纯 Python 综合核心；此入口不使用上游绘图功能。

输出 `clifford_t.json`、`logical_pauli.json`、`adaptive_pbc.json`、`audit.json`；后者保留两次完整执行的测量记录、概率、分支相位和 resource 生命周期。`complete_shor_clifford_t=true` 只描述逻辑近似编译；`encoded=false`、`physical_executed=false` 保持。

## PBC输出驱动终端测量与分解

[`shor15_pbc_run.py`](../src/neutral_atom_experiments/qec_pbc/shor15_pbc_run.py) 继续执行完整输出的8次Z投影，再以实际所得phase整数做连分数、周期验证、gcd和失败重试。每次尝试重新输入logical零态和fresh理想资源，资源实例以shot编号区分。seed7从实际PBC输出测得128（失败）和192（r4、因子3/5）；两次尝试共7000资源、14000资源测量、16终端测量。3新增tests验证投影归一化、条件Born概率乘积、重试、不可能/非法读出和耗尽失败。结果不是从精确Shor参考重新取样代替PBC输出。

完整可复现入口（先按上文隔离安装固定依赖，并设置PYTHONPATH）：

```sh
python examples/run_shor15_stage.py --complete-pbc --epsilon 1e-3 --seed 7 --output artifacts/shor15/full-pbc
```
