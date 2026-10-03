# 完整 N=15 Shor 逻辑参考

2026-10-03：新增 [`qec_pbc/shor15.py`](../src/neutral_atom_experiments/qec_pbc/shor15.py) 和 [`run_shor15.py`](../examples/run_shor15.py)。现在可运行 **N=15、a=2 的完整理想 Shor**：准备指数叠加、受控模幂、逆 QFT、采样、连分数恢复与验证周期、gcd 分解、失败重试。

这是一条完整的**未编码逻辑参考线路**。surface-code / PBC / 原子物理执行仍需继续连接，不能将本结果当作 d=3 编码 Shor 已执行。与[阶段 A memory](qec_stage_a_baseline.md)的既有物理证据分开记账；后续协议沿用 [RAG 路线与验收合同](qec_pbc_rag.md)。

## 电路与输入

默认 8 个 phase 比特、4 个 work 比特，共 12 个逻辑比特。每个寄存器使用 little-endian：

```text
basis_index = phase_integer + (work_integer << 8)
phase_integer = sum(phase[i] * 2**i)

|phase=0, work=0>
  → X(work[0])
  → H(phase[0..7])
  → controlled multiply by pow(2, 2**i, 15), for i=0..7
  → exact inverse QFT on phase
  → eight phase Z measurements
  → continued fractions → verified order → gcd → retry if needed
```

构造只接收 phase 宽度，不接收已知周期或因子。常数由 `pow(2, 1 << i, 15)` 计算，得到 `[2,4,1,1,1,1,1,1]`；恒等模乘来自计算结果。没有把验收中的周期 4 预先注入模幂构造。

因为 `15=2**4-1`，四位循环左移 k 位在有效状态 0…14 上等于乘 `2**k mod 15`。受控循环由 Fredkin 展开为 `CX → CCX → CX`；无效四位状态 15 显式固定。没有 opaque permutation gate。全部 16 个 work 输入、两种 control 输入及逆映射均验证，另验证与 spectator 纠缠的复振幅输入。

| 门 | 数量 | 当前合同 |
| --- | ---: | --- |
| X | 1 | work=1 制备 |
| H | 16 | 指数叠加和逆 QFT |
| CX | 22 | Fredkin 与 QFT SWAP 展开 |
| CCX | 5 | 受控模乘 |
| CP | 28 | 精确逆 QFT，角度为 `-π/2` 到 `-π/128` |
| phase Z 测量 | 8 | 全部量子门之后的终端读出 |

72 个酉门和 8 项测量全部导出到 `logical_circuit.json`，保留阶段、gate ID、wire 与 CP 角度。CP 约定为 `diag(1,1,1,exp(iθ))`。

## 可复现结果与失败

理想输出 phase 分布为 `0、64、128、192` 各 1/4。该分布来自完整门级复振幅计算，验收预期单独写在测试中。种子 7 的结果为：

1. 测得 128，`128/256=1/2`，候选周期 2 的 `pow(2,2,15)=4`，拒绝并重试。
2. 测得 192，连分数给 `3/4`，验证最小周期 4；`2**(4/2) mod 15=4`，gcd 给 3 与 5。

测得 0、无法恢复周期、奇数周期、平凡半周期或平凡因子均保留失败原因。达到 `max_attempts` 仍失败就返回失败；不会用已知答案补齐。后处理先检查 `a**r mod N=1`，再通过候选 r 的质因子约简/验证最小阶。当前不使用“搜索候选分母的倍数”挽救失败样本。

量子测量在这里通过理想态向量的 phase 边缘分布独立采样；它没有产生原子 `MEASURE` trace、控制延迟或带噪测量记录。

## 验证与复现

默认 12 比特的全部 4096 个最终复振幅，对比独立的 `np.fft.fft`，最大误差 `3.06e-16`；全部 256 个指数的 `pow(2,e,15)` 对照通过。逆 QFT 另在一般复数、work-entangled 输入上核验，避免这组小型算法的特殊输入让错误 CP 角度无效而漏检。新增与已有 Shor 前端专项合计 **37 项通过**。

```powershell
$env:PYTHONPATH='artifacts/qec-pbc-test-deps;src'
& 'C:\Users\yuyqp\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m pytest tests/test_qec_shor15.py tests/test_qec_shor_frontend.py -q -p no:cacheprovider --basetemp artifacts/pytest-shor15-reference
& 'C:\Users\yuyqp\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' examples/run_shor15.py --seed 7 --output artifacts/qec-shor15-2026-10-03/logical-reference
```

其他机器使用 Python ≥3.11 与 NumPy；测试还需 pytest。产物：

- `logical_circuit.json`：完整酉门、终端测量与经典后处理合同。
- `report.json`：采样、每次失败/成功、周期、因子、资源与独立验证。
- `phase_distribution.csv`：全部 256 个输出概率。
- `logical_pauli_prefix.json`：制备/模幂前缀接入既有精确 Clifford+T → signed-Pauli 前端的结果；**不含逆 QFT**。

首轮专项为 36 通过、1 失败：用于检验“翻转 CP 符号”的负测试未被特殊 Shor 输入激活。随后把一般纠缠输入的独立 QFT 检查纳入正式 audit，最终 37 通过；不是放宽断言或改变物理约束。

## 接入 d=3 surface code 的下一步

`arithmetic_prefix()` 已可复用[既有 Shor 前端](qec_shor_frontend.md)：5 个 CCX 对应精确 35 次 T/Tdg 消耗。消耗量不是同时需要的 magic patch 数量，资源制备/蒸馏、缓存和物理时间尚未核定。

按每逻辑比特一个 d=3 patch 直接映射，12 个算法 patch 的基础数量为 **108 data + 96 syndrome = 204 个原子**。联合测量区域、magic resources、资源工厂、备用或 spectator 另算，`physical_atom_peak` 保持 null。该数字是编码目标资源下界，尚未建立 204 原子的合法平台/原子执行。

后续需要逐项实现：

1. 两块 encoded ZZ/XX 的完整 checks、rounds、detectors、decoded observable 与物理执行。
2. Y/mixed-Pauli 测量、Clifford feedback 和 magic 注入链路。
3. CP 的 Clifford+T 综合及明确误差预算，或经过独立分布合同验证的算法线路优化。
4. 完整 Shor 的 PBC/encoded/native 编译、原子调度、Executor 和独立重放。

导出的完整电路和报告保持 `clifford_t_compiled=false`、`pbc_compiled=false`、`encoded=false`、`physical_executed=false`；只有 arithmetic prefix 已通过已有精确前端。
