# d=3 surface-code Shor：阶段实现与验收

目标是把完整 N=15、a=2 Shor 通过 Pauli-based computation 和 d=3 rotated surface code 接到中性原子的 PhysicalCircuit、真实调度与 Executor。每个算法逻辑比特使用 9 个 data 与 8 个 syndrome 原子。2026-10-03 本阶段已验收完整逻辑参考、资源测量桥和编码联合测量协议；整体编码 Shor 仍是后续目标。发布副本最终联合回归 **589 项通过**，RAG 37知识块/29来源、18/18检索通过，247模块架构零违规。ZZ/XX完整物理执行与重放结果按[本轮日志](../instruction/logs/2026-10-03-shor15-autonomous-stage.md)更新。

| 层 | 本阶段行为 | 限制 |
| --- | --- | --- |
| Shor 算法 | 12 wires、72 酉门、8 测量；模幂、完整逆 QFT、周期验证、gcd、失败重试 | 理想逻辑参考；28 个 CP 尚未 Clifford+T 综合 |
| 算术 PPR | 5 个 CCX 精确分解为 35 个 T/Tdg，带 signed Pauli 与 residual Clifford | 不包括逆 QFT |
| 资源测量桥 | 显式 magic resource、联合 Pauli 测量、资源 X 读出和条件 Clifford/Pauli 反馈 | 理想逻辑 instrument；尚未 encoded magic preparation/feedback |
| 编码 ZZ/XX | 完整辅助 d=3 patch；前后各三轮 checks、18 个 transversal CZ、保留两个输出 patch | 51 原子协议；理想完整 instrument，native-fault parity audit 范围另列 |
| 物理执行 | 独立声明有限 51 原子场景，所有 RESET、MEASURE、CZ、运输经过普通 Executor 与重放 | 不含初态布局准备时间、transport/idle/loss 噪声或整体 Shor |

## 核心入口

```sh
python -m pip install -r requirements-shor15.txt
python examples/run_shor15.py --seed 7 --output artifacts/shor15/logical
python examples/run_shor15_stage.py --seed 7 --fault-audit --output artifacts/shor15/stage
python examples/run_encoded_parity.py --basis Z --rounds 3 --seed 0 --output artifacts/shor15/zz
python examples/run_encoded_parity.py --basis X --rounds 3 --seed 7 --output artifacts/shor15/xx
python tools/query_qec_pbc_rag.py --check
python tools/query_qec_pbc_rag.py --self-test
```

执行证据保存在新的输出目录。已有目录会自动追加 attempt 编号，失败前缀也保留。`animation.html` 来自真实 `VisualRecorder`；`plans.json`、`trace.jsonl`、`schedule.json`、初态和终态 checkpoint 可核对效果、物理时间及独立重放。离线生成动画不等于真实浏览器交互验收。

物理场景在执行前声明全部 EZ/MZ sites，三块以 70 μm 横向偏移放置，data 间距 20 μm。AOD 为同一台 7×14、98 交点，沿用原硬件默认、容量、碰撞、空阱扫掠、光照和全 EZ CZ pair 校验。场景的有限区域更宽以容纳三块；没有在策略内部新增 trap 或放宽 validator。两块原平台保持原样。初态是已排好的 EZ holder，量子态仍从物理零态开始，所有编码制备在真实 circuit 内完成。

远端 main 与本地未发布的 Enola 默认参数不同。本阶段发布验证从远端 main 的独立工作树进行，其实际硬件记录在 `platform.json`，不能混用本地历史计时。

## 验收边界与下一步

完整 Shor 的理想态向量对照独立 FFT；一般复数且与 work 纠缠的 QFT 输入也单独测试。编码 ZZ/XX 通过两个分支的 Choi 对照确认保留外部纠缠；零/单 native fault 的 classical parity decoder、独立传播及三报告位距离 witness 另验。它们不构成完整噪声条件下保留量子输出的容错证明。

当前编码协议 API 包含输入 patch 的制备/RESET，是完整独立实验示例。接入连续 Shor 时必须保留前序编码数据和 syndrome/frame 历史，新增消耗既有编码输入的组合接口；不能反复追加这个含 RESET 的完整示例。Choi 审计确定的中间 instrument 支持任意逻辑输入，但没有替代该生产组合接口。

12 个算法 patch 基础为 204 原子；magic、联合测量辅助 patch、缓存和备用另计，实际峰值保持未定。接下来依赖顺序是：CP 的 Clifford+T 综合及误差预算 → mixed/Y Pauli 与可执行 Clifford feedback → encoded magic preparation/injection → 全算法 patch/资源生命周期与合法原子平台 → 完整 Executor、测量反馈、解码和独立重放。每一项按自身合同提交阶段成果。

详细协议见 [完整 Shor 参考](qec_shor15.md)、[编码联合测量](qec_encoded_ppm.md)、[资源测量桥](qec_adaptive_pbc.md)；事实与实现快照见 [RAG](qec_pbc_rag.md)。
