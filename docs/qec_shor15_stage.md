# d=3 surface-code Shor：阶段实现与验收

目标是把完整 N=15、a=2 Shor 通过 Pauli-based computation 和 d=3 rotated surface code 接到中性原子的 PhysicalCircuit、真实调度与 Executor。每个算法逻辑比特使用 9 个 data 与 8 个 syndrome 原子。2026-10-03 至10-04已验收完整逻辑参考、全部 QFT 的 Clifford+T 综合、实际完整 PBC 测量与因子恢复，以及可连续组合的编码 ZZ/XX；整体编码 Shor 仍是后续目标。共 **741 个不同相关测试通过**：740在远端main独立发布副本，另1项真实中断→恢复→无中断快照比较在原workspace；旧缓存/readout/恢复回归另有125通过、3项缺历史artifact跳过。RAG最新检索、新鲜度及252模块架构零违规的证据见[本轮日志](../instruction/logs/2026-10-03-shor15-autonomous-stage.md)。ZZ/XX完整三轮物理续跑仍在验收，不预报通过。

| 层 | 本阶段行为 | 限制 |
| --- | --- | --- |
| Shor 算法 | 12 wires、72 酉门、8 测量；模幂、完整逆 QFT、周期验证、gcd、失败重试 | 精确理想逻辑参考；原始72门源保持 |
| 完整 Clifford+T | 全部28 CP保留并综合；默认8993门、3500次T/Tdg消耗 | ε=1e-3预算，独立完整QFT算子误差6.78e-5 |
| 算术 PPR | 5 个 CCX 精确分解为 35 个 T/Tdg，带 signed Pauli 与 residual Clifford | 不包括逆 QFT |
| 资源测量桥 | 显式 magic resource、联合 Pauli 测量、资源 X 读出和条件 Clifford/Pauli 反馈；完整Shor已执行3500资源/7000测量 | 理想逻辑 instrument；尚未 encoded magic preparation/feedback |
| 完整 Clifford frame | 24个signed generator、真实m/r改变后续测量标签、保留完整纠正ledger与residual；终端在未兑现frame的向量上实际投影 | 理想逻辑controller；已完整恢复3/5，尚未接committed native measurements与encoded资源 |
| 编码 ZZ/XX | 完整辅助 d=3 patch；前后各三轮 checks、18 个 transversal CZ、保留两个输出 patch | 51 原子协议；理想完整 instrument，native-fault parity audit 范围另列 |
| 编码连续组合 | 接收既有 A/B 编码态与 syndrome 历史，显式消耗并重新制备 C；同 C 连续 ZZ→XX | 53 roles 含两个外部 reference、4081 native；理想 native-channel 验证，尚未物理组合执行 |
| 编码 mixed X/Z | 已准备的两patch signed product，cat制备与两遍核验、完整耦合、真实读出/RESET，同辅助原子连续非对易测量 | 41 roles（Choi另2ref），默认新增1295native/106detectors；核验边界仅参考审计拒绝，尚无生产abort/retry、Y/FT或物理执行 |
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

完整QFT综合使用独立、固定的纯Python核心，详见[依赖与误差合同](qec_qft_synthesis.md)：

```sh
python -m pip install --no-deps --target artifacts/qft-synthesis-deps -r requirements-qft-synthesis.txt
# Set PYTHONPATH=artifacts/qft-synthesis-deps;src on Windows (colon on Unix).
python examples/run_shor15_stage.py --complete-pbc --epsilon 1e-3 --seed 7 --output artifacts/shor15/complete-pbc
```

完整测量执行分别检查算法零输入和一般data-reference纠缠输入，每次全部3500资源consumed；instrument复振幅误差约1.05e-13，整体算法对原精确Shor的L2误差分别3.57e-5/2.53e-5，均在预算内。来源bit order、residual Clifford、整数相位和外部整体相位明确保存且实际执行。14新增综合测试通过，发布副本复验另记。

完整PBC的输出继续执行8项phase Z投影与经典后处理：seed7实测128失败，下一shot实测192恢复周期4并分解成3和5；两shot共7000资源、14000资源测量和16终端测量。它使用实际PBC态的分布，各shot fresh资源与测量生命周期明确，3新增投影/retry测试通过。

执行证据保存在新的输出目录。已有目录会自动追加 attempt 编号，失败前缀也保留。`animation.html` 来自真实 `VisualRecorder`；`plans.json`、`trace.jsonl`、`schedule.json`、初态和终态 checkpoint 可核对效果、物理时间及独立重放。离线生成动画不等于真实浏览器交互验收。

发生 wall-budget 超时后，用相同协议和 seed 续接已经导出的前缀：

```sh
python examples/run_encoded_parity.py --basis Z --rounds 3 --seed 0 --resume-from artifacts/shor15/zz --wall-budget 2400 --output artifacts/shor15/zz-resumed
```

恢复入口在创建新输出前核对协议、编译结果、平台、初始 placement、seed 与 original initial；accepted plan 的完整内容须与 checkpoint trace 或未开始的 pending plan 相同。它先完成已接受的尾计划，再编译新计划，保留原量子态、RNG、测量历史和绝对物理时间。新的 wall budget 只覆盖续跑；最终独立重放与完整动画仍从最初 initial 开始。部分计划无法导出完整 schedule 时保持原失败与 `null` 统计，不伪报已完成。

历史事件解码默认使用32768条/3GiB的稳定前缀缓存，每次仍审核所有历史与最新状态；超出任一预算的后缀仍解析。旧 LRU 越过16384条会循环淘汰，最初稳定前缀版保留16384条后又在真实16422-event续跑中暴露后缀解析成本，所以仅将entry上限调到32768，3GiB字节界保持。20k条独立回归验证完整热扫描0次JSON重新解析，不把小记录测试外推为任意大trace都拟合预算。已运行的16k进程保留原行为，新进程加载32k；缓存命中只复用不可变字符串的解码，不构成验收通过。snapshot/schema及物理条件不变。

快照摘要另有至多1项、1536MiB保守引用预算的复用。每次重新canonicalize全部非trace字段，完整比较immutable trace值；只有完整序列化前像相等才复用SHA。同version嵌套编辑、history首尾分叉、自定义encoder、非exact字符串/keys及超预算均由独立canonical JSON/SHA预期验收，21项新增检查在干净发布副本通过。小型实际候选编译的三次同摘要成本由124.79ms降至80.79ms，仅是该只读profile；不能推断整段物理运行倍率。缓存不省略任何物理或历史校验。

物理场景在执行前声明全部 EZ/MZ sites，三块以 70 μm 横向偏移放置，data 间距 20 μm。AOD 为同一台 7×14、98 交点，沿用原硬件默认、容量、碰撞、空阱扫掠、光照和全 EZ CZ pair 校验。场景的有限区域更宽以容纳三块；没有在策略内部新增 trap 或放宽 validator。两块原平台保持原样。初态是已排好的 EZ holder，量子态仍从物理零态开始，所有编码制备在真实 circuit 内完成。

远端 main 与本地未发布的 Enola 默认参数不同。本阶段发布验证从远端 main 的独立工作树进行，其实际硬件记录在 `platform.json`，不能混用本地历史计时。

## 验收边界与下一步

完整 Shor 的理想态向量对照独立 FFT；一般复数且与 work 纠缠的 QFT 输入也单独测试。编码 ZZ/XX 通过两个分支的 Choi 对照确认保留外部纠缠；零/单 native fault 的 classical parity decoder、独立传播及三报告位距离 witness 另验。它们不构成完整噪声条件下保留量子输出的容错证明。

独立 `encoded_parity_program` 包含输入 patch 的制备/RESET。连续线路使用新的 [`append_encoded_parity`](qec_encoded_composition.md)，保留 prefix、A/B data、全部测量记录与 syndrome sector 历史。默认分配 fresh C；`resource_reuse=True` 只在完整 C 的 9 data 明确 MEASURE/RESET、8 syndrome RESET/released 后允许使用同一组原子，下一 epoch 仍真实执行 C RESET/reprepare。ZZ→XX 同 C 实跑 53 roles/4081 native，两个外部 reference 保留；逐阶段全部 256 个逻辑/reference Pauli 期望、144 detectors、16 closing sectors 验证通过，25 项组合测试通过。这里的复用是联合测量辅助 patch 生命周期，不代表 magic factory 已实现。

12 个算法 patch 基础为 204 原子；magic、联合测量辅助 patch、缓存和备用另计，实际峰值保持未定。CP综合、完整理想PBC、完整signed Clifford frame与 X/Z 编码组合接口已完成，接下来依赖顺序是：mixed/Y encoded Pauli → 将frame controller接到committed native measurements和真实资源生命周期 → encoded magic representation/preparation/injection → 全算法patch与合法原子平台 → 完整 Executor、解码和独立重放。每一项按自身合同提交阶段成果。

[实际后端需求审计](qec_shor15_encoding_requirements.md) 从完整导出逐项统计：3500 项 joint measurements 中2325含Y、3138混合basis，最大weight9。这给下一阶段的协议范围提供具体输入，避免以双patch ZZ/XX覆盖整个算法的假设。

[mixed/Y 后端设计](qec_mixed_pauli_backend_design.md) 给出保留9+8 patch结构的分布式cat测量、signed Clifford frame、显式 Clifford-resource 纠正和原生报告位的控制接口。可发布公式审计工具复建144纠正分支与64非对易注入分支，误差小于6e-16；这是数学/reference验算，没有把后端、FT或physical能力改成已实现。

[完整frame实现](qec_conditional_clifford_frame.md)每次只投影真实`F†PF`，纠正留在24-generator frame与完整复相位ledger中；最终测量`F†C_res†Z_jC_resF`而不重采样eager结果。完整3500-resource零输入与纠缠reference对照通过，兑现frame后对eager L2误差约1.26e-14，对原CT约1.05e-13。fresh framed Shor seed7/8/9实际读出128/0/192，失败保留，第三次验证周期4与因子3/5；共10500资源、21000注入测量与24终端投影。该seed7实际标签含Y2168项、mixed2437项，data最大12/joint13；固定3/5代表的cat模板最大45（18项），仅为template shape，资源峰值未定。分批终端读出仍保存完整namespace/history/dependencies。27项新增独立检查已在干净发布副本验收，native S/encoded/FT/physical均保持false。

[mixed X/Z native参考](qec_mixed_xz_cat.md)已实现signed `X_A Z_B`的完整cat线路，保留原prefix/data/sectors与外部纠缠。全部64个raw cat-X报告组合逐分支Choi验证，正/负号和两semantic分支正确；连续非对易`X_A Z_B→Z_A Z_B`同7cat/verifier原子真实再RESET，两个边界均核对256个logical/reference Pauli与16 stabilizers。默认3+3轮新增1295native（735H/319CZ/129RESET/112M），106detectors；41项新增检查与54项旧PPM/组合回归在clean联合95通过。它将核验结果/边界显式导出，静态compile不会主动abort/retry，未来物理controller须在数据耦合前等待真实核验并拒绝异常。没有Y、magic factory、噪声FT或完整Executor声明。

详细协议见 [完整 Shor 参考](qec_shor15.md)、[编码联合测量](qec_encoded_ppm.md)、[资源测量桥](qec_adaptive_pbc.md)；事实与实现快照见 [RAG](qec_pbc_rag.md)。
